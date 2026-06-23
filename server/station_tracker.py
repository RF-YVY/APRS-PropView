"""Station tracker — tracks heard stations, calculates propagation metrics."""

import asyncio
import logging
import math
import re
import time
from typing import Optional, Dict, Any, List

from server.config import Config
from server.database import Database
from server.aprs_parser import APRSPacket, calculate_distance, calculate_bearing
from server.websocket_manager import WebSocketManager

logger = logging.getLogger("propview.tracker")


class StationTracker:
    """Tracks RF and APRS-IS stations with propagation analysis."""

    def __init__(self, db: Database, config: Config, ws_manager: WebSocketManager):
        self.db = db
        self.config = config
        self.ws = ws_manager
        self.my_lat = config.station.latitude
        self.my_lon = config.station.longitude

        # In-memory cache for quick access
        self._rf_stations: Dict[str, Dict[str, Any]] = {}
        self._is_stations: Dict[str, Dict[str, Any]] = {}

        # Propagation metrics
        self._prop_history: List[Dict[str, Any]] = []

        # Alert manager (set later via set_alert_manager)
        self._alert_manager = None

        # Analytics engine (set later via set_analytics)
        self._analytics = None
        self._gps_manager = None
        self._mqtt_publisher = None
        self._mqtt_max_distance_km: Optional[float] = None
        self._last_rf_packet_time: float = 0.0
        self._recent_first_heard_until: float = 0.0
        self._watched_path_last_alert: Dict[str, float] = {}

    def set_alert_manager(self, alert_manager):
        """Inject the AlertManager instance for band-opening detection."""
        self._alert_manager = alert_manager

    def set_analytics(self, analytics):
        """Inject the AnalyticsEngine for anomaly and Es checks."""
        self._analytics = analytics

    def set_gps_manager(self, gps_manager):
        """Inject live GPS updates for own-position tracking."""
        self._gps_manager = gps_manager

    def set_mqtt_publisher(self, mqtt_publisher):
        """Inject the optional MQTT publisher."""
        self._mqtt_publisher = mqtt_publisher

    def set_my_position(self, latitude: float, longitude: float):
        """Update the reference position used for distance and bearing."""
        self.my_lat = float(latitude)
        self.my_lon = float(longitude)

    @staticmethod
    def _angular_difference(a: float, b: float) -> float:
        """Return smallest absolute difference between two bearings."""
        return abs((a - b + 180) % 360 - 180)

    @staticmethod
    def _confidence_threshold(level: str) -> float:
        level = (level or "medium").strip().lower()
        if level == "low":
            return 45.0
        if level == "high":
            return 75.0
        return 60.0

    @staticmethod
    def maidenhead_to_lat_lon(grid: str) -> Optional[tuple[float, float]]:
        """Return approximate center lat/lon for a Maidenhead grid square."""
        value = (grid or "").strip().upper()
        if len(value) < 4 or len(value) % 2:
            return None
        if not re.fullmatch(r"[A-R]{2}[0-9]{2}(?:[A-X]{2})?(?:[0-9]{2})?", value):
            return None

        lon = -180.0 + (ord(value[0]) - ord("A")) * 20
        lat = -90.0 + (ord(value[1]) - ord("A")) * 10
        lon_width = 20.0
        lat_height = 10.0

        lon += int(value[2]) * 2
        lat += int(value[3]) * 1
        lon_width = 2.0
        lat_height = 1.0

        if len(value) >= 6:
            lon += (ord(value[4]) - ord("A")) * (2.0 / 24.0)
            lat += (ord(value[5]) - ord("A")) * (1.0 / 24.0)
            lon_width = 2.0 / 24.0
            lat_height = 1.0 / 24.0

        if len(value) >= 8:
            lon += int(value[6]) * (lon_width / 10.0)
            lat += int(value[7]) * (lat_height / 10.0)
            lon_width /= 10.0
            lat_height /= 10.0

        return lat + lat_height / 2.0, lon + lon_width / 2.0

    @staticmethod
    def _radio_horizon_km(my_height_m: float, target_height_m: float) -> float:
        """Approximate radio horizon using 4/3 earth-radius convention."""
        my_h = max(0.0, float(my_height_m or 0.0))
        target_h = max(0.0, float(target_height_m or 0.0))
        return 4.12 * (my_h ** 0.5 + target_h ** 0.5)

    @staticmethod
    def _eirp_w(power_w: float, gain_dbi: float) -> float:
        power = max(0.1, float(power_w or 0.0))
        gain = max(-20.0, min(30.0, float(gain_dbi or 0.0)))
        return power * (10 ** (gain / 10.0))

    @staticmethod
    def _capability_bonus(eirp_w: float, radio_horizon_km: float, target_distance_km: float) -> float:
        """Small bounded score adjustment from station capability, not a replacement for RF evidence."""
        eirp_bonus = max(-4.0, min(8.0, math.log10(max(eirp_w, 0.1) / 50.0) * 4.0))
        horizon_bonus = max(0.0, min(4.0, (radio_horizon_km / max(target_distance_km, 1.0)) * 8.0))
        return round(eirp_bonus + horizon_bonus, 1)

    async def evaluate_watched_paths(self, allow_alerts: bool = True) -> Dict[str, Any]:
        """Score configured target paths against recent RF propagation evidence."""
        targets = [
            target for target in getattr(self.config, "watched_paths", []) or []
            if getattr(target, "enabled", True) and getattr(target, "callsign", "").strip()
        ]
        now = time.time()
        result = {
            "enabled": bool(targets),
            "opportunities": [],
            "alerts": [],
            "timestamp": now,
        }
        if not targets or self.my_lat == 0.0 or self.my_lon == 0.0:
            return result

        station_rows = await self.db.get_stations(source="rf", since=now - 6 * 3600)
        for target in targets:
            try:
                if getattr(target, "grid", "").strip():
                    grid_pos = self.maidenhead_to_lat_lon(target.grid)
                    if not grid_pos:
                        continue
                    target_lat, target_lon = grid_pos
                else:
                    target_lat = float(target.latitude)
                    target_lon = float(target.longitude)
            except (TypeError, ValueError):
                continue
            if target_lat == 0.0 and target_lon == 0.0:
                continue

            target_call = (target.callsign or "").strip().upper()
            target_distance_km = calculate_distance(self.my_lat, self.my_lon, target_lat, target_lon)
            target_heading = calculate_bearing(self.my_lat, self.my_lon, target_lat, target_lon)
            radio_horizon_km = self._radio_horizon_km(
                getattr(target, "my_antenna_height_m", 10.0),
                getattr(target, "target_antenna_height_m", 10.0),
            )
            my_tx_power_w = max(0.1, float(getattr(target, "my_tx_power_w", 50.0) or 50.0))
            my_antenna_gain_dbi = max(-20.0, min(30.0, float(getattr(target, "my_antenna_gain_dbi", 0.0) or 0.0)))
            my_eirp_w = self._eirp_w(my_tx_power_w, my_antenna_gain_dbi)
            capability_bonus = self._capability_bonus(my_eirp_w, radio_horizon_km, target_distance_km)
            horizon_ratio = target_distance_km / max(radio_horizon_km, 1.0)
            if horizon_ratio <= 1.0:
                path_geometry = "line_of_sight_plausible"
            elif horizon_ratio <= 2.5:
                path_geometry = "modestly_beyond_horizon"
            else:
                path_geometry = "propagation_aided"
            max_age_minutes = max(5, int(getattr(target, "max_age_minutes", 60) or 60))
            cutoff = now - max_age_minutes * 60
            bearing_tolerance = max(5, min(90, int(getattr(target, "bearing_tolerance_deg", 30) or 30)))
            min_probe_count = max(1, int(getattr(target, "min_probe_count", 2) or 2))
            min_distance_km = target_distance_km * 0.85
            probes = []

            for station in station_rows:
                last_heard = float(station.get("last_heard") or 0)
                if last_heard < cutoff:
                    continue
                distance_km = station.get("distance_km")
                heading = station.get("heading")
                if distance_km is None or heading is None:
                    continue
                distance_km = float(distance_km)
                heading = float(heading)
                heading_diff = self._angular_difference(heading, target_heading)
                station_call = (station.get("callsign") or "").upper()
                same_target = station_call == target_call or station_call.split("-", 1)[0] == target_call.split("-", 1)[0]
                if not same_target and (heading_diff > bearing_tolerance or distance_km < min_distance_km):
                    continue

                age_ratio = max(0.0, min(1.0, 1.0 - ((now - last_heard) / (max_age_minutes * 60))))
                bearing_score = 30.0 if same_target else max(0.0, 30.0 * (1.0 - heading_diff / bearing_tolerance))
                distance_score = min(25.0, 25.0 * (distance_km / max(target_distance_km, 1.0)))
                freshness_score = 20.0 * age_ratio
                hop_count = self._count_hops(station.get("last_path", ""))
                direct = self._is_direct_path(station.get("last_path", ""))
                path_score = 20.0 if direct else 12.0 if hop_count <= 1 else 6.0
                proximity_score = 0.0
                proximity_km = None
                if station.get("latitude") is not None and station.get("longitude") is not None:
                    proximity_km = calculate_distance(
                        float(station["latitude"]),
                        float(station["longitude"]),
                        target_lat,
                        target_lon,
                    )
                    if proximity_km <= 50:
                        proximity_score = 15.0
                    elif proximity_km <= 100:
                        proximity_score = 8.0
                exact_score = 30.0 if same_target else 0.0
                score = min(
                    100.0,
                    bearing_score + distance_score + freshness_score + path_score + proximity_score + exact_score,
                )
                probes.append({
                    "callsign": station_call,
                    "distance_km": round(distance_km, 1),
                    "heading": round(heading, 1),
                    "heading_diff": round(heading_diff, 1),
                    "last_heard": last_heard,
                    "age_seconds": round(now - last_heard),
                    "path": station.get("last_path", ""),
                    "is_direct": direct,
                    "hop_count": hop_count,
                    "proximity_km": round(proximity_km, 1) if proximity_km is not None else None,
                    "score": round(score, 1),
                    "same_target": same_target,
                })

            probes.sort(key=lambda item: item["score"], reverse=True)
            qualifying = [probe for probe in probes if probe["score"] >= 35.0]
            if qualifying:
                top_scores = [probe["score"] for probe in qualifying[:5]]
                aggregate_score = min(100.0, (sum(top_scores) / len(top_scores)) + min(20.0, (len(qualifying) - 1) * 5.0))
                aggregate_score = max(0.0, min(100.0, aggregate_score + capability_bonus))
            else:
                aggregate_score = 0.0
            if len(qualifying) < min_probe_count and not any(probe["same_target"] for probe in qualifying):
                aggregate_score = min(aggregate_score, 44.0)

            if aggregate_score >= 75:
                confidence = "high"
            elif aggregate_score >= 60:
                confidence = "medium"
            elif aggregate_score >= 45:
                confidence = "low"
            else:
                confidence = "none"

            opportunity = {
                "callsign": target_call,
                "band": getattr(target, "band", "2m") or "2m",
                "mode": getattr(target, "mode", "") or "",
                "frequency_mhz": float(getattr(target, "frequency_mhz", 0.0) or 0.0),
                "grid": getattr(target, "grid", "") or "",
                "target_latitude": target_lat,
                "target_longitude": target_lon,
                "target_distance_km": round(target_distance_km, 1),
                "target_heading": round(target_heading, 1),
                "radio_horizon_km": round(radio_horizon_km, 1),
                "my_antenna_height_m": round(float(getattr(target, "my_antenna_height_m", 10.0) or 10.0), 1),
                "target_antenna_height_m": round(float(getattr(target, "target_antenna_height_m", 10.0) or 10.0), 1),
                "my_tx_power_w": round(my_tx_power_w, 1),
                "my_antenna_gain_dbi": round(my_antenna_gain_dbi, 1),
                "my_eirp_w": round(my_eirp_w, 1),
                "capability_bonus": capability_bonus,
                "path_geometry": path_geometry,
                "terrain_status": "terrain_profile_not_available",
                "bearing_tolerance_deg": bearing_tolerance,
                "min_probe_count": min_probe_count,
                "probe_count": len(qualifying),
                "score": round(aggregate_score, 1),
                "confidence": confidence,
                "threshold": self._confidence_threshold(getattr(target, "min_confidence", "medium")),
                "min_confidence": getattr(target, "min_confidence", "medium"),
                "probes": qualifying[:5],
            }
            result["opportunities"].append(opportunity)

            alert_key = target_call
            cooldown_seconds = max(5, int(getattr(target, "alert_cooldown_minutes", 30) or 30)) * 60
            if (
                allow_alerts
                and aggregate_score >= opportunity["threshold"]
                and now - self._watched_path_last_alert.get(alert_key, 0.0) >= cooldown_seconds
            ):
                self._watched_path_last_alert[alert_key] = now
                result["alerts"].append({
                    "type": "watched_path",
                    "timestamp": now,
                    **opportunity,
                    "message": (
                        f"VHF opportunity toward {target_call}\n"
                        f"Band: {opportunity['band']}\n"
                        f"Mode: {opportunity['mode'] or 'any'}\n"
                        f"Target: {opportunity['target_distance_km']:.1f} km "
                        f"({opportunity['target_distance_km'] * 0.621371:.1f} mi), "
                        f"bearing {opportunity['target_heading']:.0f} deg\n"
                        f"Geometry: {path_geometry.replace('_', ' ')}\n"
                        f"Confidence: {confidence.upper()} (score {aggregate_score:.0f})\n"
                        f"RF probes: {len(qualifying)}"
                    ),
                })

        result["opportunities"].sort(key=lambda item: item["score"], reverse=True)
        return result

    def _propview_transmit_callsigns(self) -> set[str]:
        base = (self.config.station.callsign or "").strip().upper()
        calls = {self.config.station.full_callsign.upper()}
        if base:
            wx_ssid = max(0, min(15, int(getattr(self.config.wxnow, "ssid", 13) or 0)))
            calls.add(f"{base}-{wx_ssid}" if wx_ssid else base)
        return {call for call in calls if call}

    def packet_digipeated_by_me(self, path: str) -> bool:
        my_call = self.config.station.full_callsign.upper()
        if not my_call or not path:
            return False
        for hop in path.split(","):
            hop = hop.strip().upper()
            if hop.endswith("*") and hop[:-1] == my_call:
                return True
        return False

    @staticmethod
    def normalize_blocked_callsigns(values) -> List[str]:
        """Normalize callsign blocklist entries, preserving base-call wildcards."""
        if isinstance(values, str):
            values = re.split(r"[\s,]+", values)
        if not isinstance(values, list):
            return []

        normalized = []
        seen = set()
        for value in values:
            call = str(value or "").strip().upper()
            if not call or call in seen:
                continue
            if not re.fullmatch(r"[A-Z0-9]{1,9}(?:-(?:[0-9]|1[0-5]))?", call):
                continue
            seen.add(call)
            normalized.append(call)
        return normalized

    def is_blocked_callsign(self, callsign: str) -> bool:
        """Return True when a packet source matches the configured blocklist."""
        call = (callsign or "").strip().upper()
        if not call:
            return False
        blocked = self.normalize_blocked_callsigns(
            getattr(self.config.tracking, "blocked_callsigns", [])
        )
        if call in blocked:
            return True
        base = call.split("-", 1)[0]
        return base in blocked

    async def _log_packet_only(
        self,
        packet: APRSPacket,
        port_name: str,
        distance_km: Optional[float] = None,
        commit: bool = True,
    ):
        await self.db.log_packet(
            source=packet.source,
            from_call=packet.from_call,
            to_call=packet.to_call,
            path=packet.path,
            raw=packet.raw,
            packet_type=packet.packet_type,
            latitude=packet.latitude,
            longitude=packet.longitude,
            port_name=port_name,
            digipeated_by_me=self.packet_digipeated_by_me(packet.path),
            commit=commit,
        )
        digipeated_by_me = self.packet_digipeated_by_me(packet.path)
        await self.ws.broadcast(
            {
                "type": "packet",
                "data": {
                    "timestamp": time.time(),
                    "source": packet.source,
                    "from_call": packet.from_call,
                    "to_call": packet.to_call,
                    "path": packet.path,
                    "raw": packet.raw,
                    "packet_type": packet.packet_type,
                    "latitude": packet.latitude,
                    "longitude": packet.longitude,
                    "port_name": port_name,
                    "distance_km": distance_km,
                    "digipeated_by_me": digipeated_by_me,
                },
            }
        )

    async def track_packet(self, packet: APRSPacket):
        """Process a parsed packet and update station tracking."""
        source = packet.source  # 'rf' or 'aprs_is'
        callsign = packet.from_call
        port_name = packet.port_name if source == "rf" else ""
        is_direct = source == "rf" and self._is_direct_path(packet.path)
        digipeated_by_me = self.packet_digipeated_by_me(packet.path)
        if source == "rf":
            self._last_rf_packet_time = time.time()

        if not callsign:
            return

        if self.is_blocked_callsign(callsign):
            logger.info("%s: %s ignored by station blocklist", "RF" if source == "rf" else "APRS-IS", callsign)
            return

        if source == "rf" and self._has_internet_path(packet.path):
            await self.db.log_packet(
                source=source,
                from_call=callsign,
                to_call=packet.to_call,
                path=packet.path,
                raw=packet.raw,
                packet_type=packet.packet_type,
                latitude=packet.latitude,
                longitude=packet.longitude,
                port_name=port_name,
                digipeated_by_me=digipeated_by_me,
            )
            await self.ws.broadcast(
                {
                    "type": "packet",
                    "data": {
                        "timestamp": time.time(),
                        "source": source,
                        "from_call": callsign,
                        "to_call": packet.to_call,
                        "path": packet.path,
                        "raw": packet.raw,
                        "packet_type": packet.packet_type,
                        "latitude": packet.latitude,
                        "longitude": packet.longitude,
                        "port_name": port_name,
                        "distance_km": None,
                        "digipeated_by_me": digipeated_by_me,
                    },
                }
            )
            logger.info("RF: %s [third-party internet path ignored for propagation]", callsign)
            return

        if (
            packet.has_position
            and self._gps_manager
            and self.config.gps.enabled
            and self.config.gps.source in {"self_packet", "any"}
            and callsign.upper() == self.config.station.full_callsign.upper()
        ):
            await self._gps_manager.update_location(
                packet.latitude,
                packet.longitude,
                source="self_packet",
            )

        is_own_packet = callsign.upper() in self._propview_transmit_callsigns()
        is_own_weather_packet = is_own_packet and packet.packet_type == "weather"
        if is_own_packet:
            if not is_own_weather_packet:
                await self._log_packet_only(packet, port_name)
                logger.info(
                    "%s: %s [%s] logged as own PropView packet; not added to station list",
                    "RF" if source == "rf" else "APRS-IS",
                    callsign,
                    packet.packet_type or "other",
                )
                return
            logger.info("%s: %s weather packet allowed into station list", "RF" if source == "rf" else "APRS-IS", callsign)

        # Calculate distance if we have both positions
        distance_km = None
        heading = None
        if (
            packet.has_position
            and self.my_lat != 0.0
            and self.my_lon != 0.0
        ):
            distance_km = calculate_distance(
                self.my_lat, self.my_lon, packet.latitude, packet.longitude
            )
            heading = calculate_bearing(
                self.my_lat, self.my_lon, packet.latitude, packet.longitude
            )

        # Detect first-heard station (before upsert creates the record)
        is_first_heard = False
        if source == "rf":
            is_first_heard = not await self.db.is_station_known(callsign, source)

        previous_max_distance_km = None
        if source == "rf" and distance_km is not None:
            if self._mqtt_max_distance_km is None:
                self._mqtt_max_distance_km = await self.db.get_max_rf_distance()
            previous_max_distance_km = self._mqtt_max_distance_km

        # Update database
        station = await self.db.upsert_station(
            callsign=callsign,
            source=source,
            latitude=packet.latitude,
            longitude=packet.longitude,
            symbol_table=packet.symbol_table,
            symbol_code=packet.symbol_code,
            comment=packet.comment,
            path=packet.path,
            port_name=port_name,
            raw=packet.raw,
            distance_km=distance_km,
            heading=heading,
            commit=False,
        )

        # Log packet
        await self.db.log_packet(
            source=source,
            from_call=callsign,
            to_call=packet.to_call,
            path=packet.path,
            raw=packet.raw,
            packet_type=packet.packet_type,
            latitude=packet.latitude,
            longitude=packet.longitude,
            port_name=port_name,
            digipeated_by_me=digipeated_by_me,
            commit=False,
        )

        # Track path quality for RF stations
        if source == "rf":
            hop_count = self._count_hops(packet.path)
            await self.db.log_path_event(
                callsign=callsign,
                distance_km=distance_km,
                heading=heading,
                path=packet.path,
                port_name=port_name,
                hop_count=hop_count,
                is_direct=is_direct,
                commit=False,
            )

        # Log and alert on first-heard stations
        if is_first_heard:
            first_heard_logged = await self.db.log_first_heard(
                callsign=callsign,
                source=source,
                distance_km=distance_km,
                heading=heading,
                latitude=packet.latitude,
                longitude=packet.longitude,
                path=packet.path,
                port_name=port_name,
                hop_count=self._count_hops(packet.path) if source == "rf" else 0,
                is_direct=is_direct,
                commit=False,
            )
            if not first_heard_logged:
                is_first_heard = False

        if is_first_heard:
            self._recent_first_heard_until = time.time() + 300
            # Broadcast first-heard event to web clients
            await self.ws.broadcast({
                "type": "first_heard",
                "data": {
                    "callsign": callsign,
                    "distance_km": distance_km,
                    "heading": heading,
                    "timestamp": time.time(),
                    "is_direct": is_direct,
                    "path": packet.path,
                    "port_name": port_name,
                },
            })
            await self._publish_mqtt_event(self._station_event_payload(
                event="first_heard",
                callsign=callsign,
                source=source,
                distance_km=distance_km,
                heading=heading,
                latitude=packet.latitude,
                longitude=packet.longitude,
                path=packet.path,
                port_name=port_name,
                is_direct=is_direct,
                hop_count=self._count_hops(packet.path) if source == "rf" else 0,
            ))
            # Trigger first-heard alert if alert manager is available
            if self._alert_manager and distance_km and (source != "rf" or is_direct):
                alert = await self._alert_manager.check_first_heard(
                    callsign, distance_km, heading
                )
                if alert:
                    await self._publish_mqtt_alert(alert)

        if (
            source == "rf"
            and distance_km is not None
            and previous_max_distance_km is not None
            and distance_km > previous_max_distance_km
        ):
            self._mqtt_max_distance_km = distance_km
            await self._publish_mqtt_event(self._station_event_payload(
                event="new_max_distance",
                callsign=callsign,
                source=source,
                distance_km=distance_km,
                heading=heading,
                latitude=packet.latitude,
                longitude=packet.longitude,
                path=packet.path,
                port_name=port_name,
                is_direct=is_direct,
                hop_count=self._count_hops(packet.path),
                extra={"previous_distance_km": round(previous_max_distance_km, 1)},
            ))

        await self.db.commit()

        # Update in-memory cache
        cache = self._rf_stations if source == "rf" else self._is_stations
        cache[callsign] = station
        await self._publish_mqtt_watched_station(callsign, station)

        # Push update to web clients
        await self.ws.broadcast(
            {
                "type": "station_update",
                "station": station,
                "source": source,
            }
        )

        # Push packet to web clients
        await self.ws.broadcast(
            {
                "type": "packet",
                "data": {
                    "timestamp": time.time(),
                    "source": source,
                    "from_call": callsign,
                    "to_call": packet.to_call,
                    "path": packet.path,
                    "raw": packet.raw,
                    "packet_type": packet.packet_type,
                    "latitude": packet.latitude,
                    "longitude": packet.longitude,
                    "port_name": port_name,
                    "distance_km": distance_km,
                    "digipeated_by_me": digipeated_by_me,
                },
            }
        )

        # Log for RF stations
        if source == "rf":
            dist_str = f" ({distance_km:.1f} km)" if distance_km else ""
            logger.info(f"RF: {callsign}{dist_str} [{packet.packet_type}]")

    async def get_rf_stations(
        self,
        since: Optional[float] = None,
        max_distance: Optional[float] = None,
    ) -> List[Dict[str, Any]]:
        """Get RF stations with optional filters."""
        return await self.db.get_stations(source="rf", since=since, max_distance=max_distance)

    async def get_is_stations(
        self, since: Optional[float] = None
    ) -> List[Dict[str, Any]]:
        """Get APRS-IS stations."""
        return await self.db.get_stations(source="aprs_is", since=since)

    async def get_all_stations(
        self, since: Optional[float] = None
    ) -> Dict[str, List[Dict[str, Any]]]:
        """Get all stations grouped by source."""
        rf = await self.get_rf_stations(since=since)
        aprs_is = await self.get_is_stations(since=since)
        return {"rf": rf, "aprs_is": aprs_is}

    async def delete_station(self, callsign: str, source: str) -> bool:
        """Delete one station from storage, cache, and connected clients."""
        deleted = await self.db.delete_station(callsign, source)
        cache = self._rf_stations if source == "rf" else self._is_stations
        cache.pop(callsign, None)
        if deleted:
            await self.ws.broadcast({
                "type": "station_removed",
                "data": {"callsign": callsign, "source": source},
            })
        return deleted

    @staticmethod
    def _is_direct_path(path: str) -> bool:
        """Return True if the APRS path indicates a direct (no digipeater) reception.

        A station is direct-heard if:
        - The path is empty, OR
        - None of the path hops have a '*' (used) suffix with a real callsign
          (i.e. WIDE1-1* alone doesn't count as relayed through another digi)
        """
        if not path:
            return True
        hops = [h.strip() for h in path.split(",") if h.strip()]
        for hop in hops:
            if hop.endswith("*"):
                base = hop[:-1]
                # WIDE/RELAY/TRACE aliases with * don't indicate a foreign digi
                if not any(base.upper().startswith(a) for a in ("WIDE", "RELAY", "TRACE")):
                    return False
        return True

    @staticmethod
    def _count_hops(path: str) -> int:
        """Count the number of digipeater hops in the path."""
        if not path:
            return 0
        hops = [h.strip() for h in path.split(",") if h.strip()]
        count = 0
        for hop in hops:
            if hop.endswith("*"):
                count += 1
        return count

    @staticmethod
    def _has_internet_path(path: str) -> bool:
        """Return True if a path shows APRS-IS/TCP-originated traffic."""
        if not path:
            return False
        internet_hops = {"TCPIP", "TCPXX"}
        for hop in path.split(","):
            base = hop.strip().rstrip("*").upper()
            if base in internet_hops or base.startswith("QA"):
                return True
        return False

    @staticmethod
    def _used_digipeaters(path: str) -> List[str]:
        """Return non-generic used digipeater callsigns from an APRS path."""
        if not path:
            return []
        generic_prefixes = ("WIDE", "RELAY", "TRACE", "TCPIP", "TCPXX", "QA")
        digis = []
        for hop in path.split(","):
            base = hop.strip().rstrip("*")
            if not hop.strip().endswith("*") or not base:
                continue
            if any(base.upper().startswith(prefix) for prefix in generic_prefixes):
                continue
            digis.append(base)
        return digis

    async def get_propagation_data(self, log_sample: bool = False) -> Dict[str, Any]:
        """Calculate current propagation metrics for both meters."""
        now = time.time()
        stats = await self.db.get_stats()
        prop_cfg = self.config.propagation

        # Get RF stations with distances for the last hour
        own_calls = self._propview_transmit_callsigns()
        rf_1h = [
            station for station in await self.db.get_stations(source="rf", since=now - 3600)
            if (station.get("callsign") or "").upper() not in own_calls
        ]

        # Split RF stations into direct-heard local and relayed regional groups
        all_distances = [s["distance_km"] for s in rf_1h if s.get("distance_km")]
        direct_stations = [s for s in rf_1h if self._is_direct_path(s.get("last_path", ""))]
        direct_distances = [s["distance_km"] for s in direct_stations if s.get("distance_km")]
        near_hop_stations = [
            s for s in rf_1h
            if s.get("distance_km")
            and not self._has_internet_path(s.get("last_path", ""))
            and self._count_hops(s.get("last_path", "")) <= 1
        ]
        regional_stations = [s for s in rf_1h if not self._is_direct_path(s.get("last_path", ""))]
        regional_distances = [s["distance_km"] for s in regional_stations if s.get("distance_km")]

        rf_6h = [
            station for station in await self.db.get_stations(source="rf", since=now - 21600)
            if (station.get("callsign") or "").upper() not in own_calls
        ]
        rf_24h = [
            station for station in await self.db.get_stations(source="rf", since=now - 86400)
            if (station.get("callsign") or "").upper() not in own_calls
        ]
        regional_count_6h = sum(1 for s in rf_6h if not self._is_direct_path(s.get("last_path", "")))
        regional_count_24h = sum(1 for s in rf_24h if not self._is_direct_path(s.get("last_path", "")))

        # ── My Station meter (direct-heard only) ────────────
        my_count = len(direct_stations)
        my_max_dist = max(direct_distances) if direct_distances else 0
        my_avg_dist = sum(direct_distances) / len(direct_distances) if direct_distances else 0
        my_top_station = None
        if direct_distances:
            top = max(
                (s for s in direct_stations if s.get("distance_km")),
                key=lambda s: s["distance_km"],
            )
            my_top_station = {
                "callsign": top.get("callsign"),
                "distance_km": round(top["distance_km"], 1),
                "heading": round(top["heading"], 1) if top.get("heading") is not None else None,
            }
        sorted_near_hop = sorted(near_hop_stations, key=lambda s: s["distance_km"], reverse=True)
        if my_top_station and my_top_station.get("callsign"):
            top_call = my_top_station["callsign"].upper()
            top_matches = [s for s in sorted_near_hop if (s.get("callsign") or "").upper() == top_call]
            other_matches = [s for s in sorted_near_hop if (s.get("callsign") or "").upper() != top_call]
            sorted_near_hop = top_matches[:1] + other_matches

        my_near_hop_stations = []
        for station in sorted_near_hop[:8]:
            used_digis = self._used_digipeaters(station.get("last_path", ""))
            my_near_hop_stations.append({
                "callsign": station.get("callsign"),
                "distance_km": round(station["distance_km"], 1),
                "heading": round(station["heading"], 1) if station.get("heading") is not None else None,
                "hop_count": self._count_hops(station.get("last_path", "")),
                "path": station.get("last_path", ""),
                "via_digipeater": used_digis[0] if used_digis else "",
                "is_digipeater": bool(
                    station.get("callsign")
                    and station.get("callsign", "").upper() in {d.upper() for d in used_digis}
                ),
            })
        direct_heard_stations = [
            {
                "callsign": station.get("callsign"),
                "distance_km": round(station["distance_km"], 1) if station.get("distance_km") else None,
                "heading": round(station["heading"], 1) if station.get("heading") is not None else None,
                "last_heard": station.get("last_heard"),
                "path": station.get("last_path", ""),
            }
            for station in sorted(
                direct_stations,
                key=lambda s: s.get("last_heard") or 0,
                reverse=True,
            )
        ]
        my_full_count = max(prop_cfg.my_station_full_count, 1)
        my_full_dist = max(prop_cfg.my_station_full_dist_km, 1)
        my_count_score = min(my_count / my_full_count * 50, 50)
        my_dist_score = min(my_max_dist / my_full_dist * 50, 50)
        my_score = min(my_count_score + my_dist_score, 100)
        my_level = self._score_to_level(my_score)

        # ── Regional meter (all RF stations) ─────────────────
        reg_count = len(regional_stations)
        reg_max_dist = max(regional_distances) if regional_distances else 0
        reg_avg_dist = sum(regional_distances) / len(regional_distances) if regional_distances else 0
        reg_full_count = max(prop_cfg.regional_full_count, 1)
        reg_full_dist = max(prop_cfg.regional_full_dist_km, 1)
        reg_count_score = min(reg_count / reg_full_count * 50, 50)
        reg_dist_score = min(reg_max_dist / reg_full_dist * 50, 50)
        reg_score = min(reg_count_score + reg_dist_score, 100)
        reg_level = self._score_to_level(reg_score)

        result = {
            # My Station meter
            "my_score": round(my_score, 1),
            "my_level": my_level,
            "my_stations_1h": my_count,
            "my_max_distance_km": round(my_max_dist, 1),
            "my_avg_distance_km": round(my_avg_dist, 1),
            "my_top_station": my_top_station,
            "my_near_hop_stations": my_near_hop_stations,
            "direct_heard_stations": direct_heard_stations,
            # Regional meter
            "score": round(reg_score, 1),
            "level": reg_level,
            "rf_stations_1h": stats.get("rf_stations_1h", 0),
            "rf_stations_6h": stats.get("rf_stations_6h", 0),
            "rf_stations_24h": stats.get("rf_stations_24h", 0),
            "regional_stations_1h": reg_count,
            "regional_stations_6h": regional_count_6h,
            "regional_stations_24h": regional_count_24h,
            "is_stations_1h": stats.get("is_stations_1h", 0),
            "max_distance_km": round(reg_max_dist, 1),
            "avg_distance_km": round(reg_avg_dist, 1),
            "distances": sorted(all_distances),
            "direct_distances": sorted(direct_distances),
            "regional_distances": sorted(regional_distances),
            "timestamp": now,
        }

        if log_sample:
            await self.db.log_propagation(
                rf_count=reg_count,
                max_dist=reg_max_dist if reg_max_dist else None,
                avg_dist=reg_avg_dist if reg_avg_dist else None,
                unique_1h=reg_count,
                unique_6h=regional_count_6h,
                unique_24h=regional_count_24h,
            )

        return result

    async def _publish_mqtt_propagation(self, prop_data: Dict[str, Any]):
        """Publish propagation metrics through the optional MQTT integration."""
        if not self._mqtt_publisher:
            return
        try:
            await self._mqtt_publisher.publish_propagation(prop_data)
            await self._mqtt_publisher.publish_prop_score(
                prop_data.get("score", 0),
                prop_data.get("level", "none"),
            )
            await self._mqtt_publisher.publish_status_snapshot(
                self._mqtt_status_snapshot(prop_data=prop_data)
            )
        except Exception as e:
            logger.error(f"MQTT propagation publish error: {e}")

    async def _publish_mqtt_alert(self, alert: Dict[str, Any]):
        """Publish an alert through the optional MQTT integration."""
        if not self._mqtt_publisher:
            return
        try:
            await self._mqtt_publisher.publish_alert(alert)
            await self._mqtt_publisher.publish_status_snapshot(
                self._mqtt_status_snapshot(active_alert=alert)
            )
        except Exception as e:
            logger.error(f"MQTT alert publish error: {e}")

    def _station_event_payload(
        self,
        event: str,
        callsign: str,
        source: str,
        distance_km: Optional[float],
        heading: Optional[float],
        latitude: Optional[float],
        longitude: Optional[float],
        path: str,
        port_name: str,
        is_direct: bool,
        hop_count: int,
        extra: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        payload = {
            "event": event,
            "timestamp": time.time(),
            "callsign": callsign,
            "source": source,
            "distance_km": round(distance_km, 1) if distance_km is not None else None,
            "heading": round(heading, 1) if heading is not None else None,
            "latitude": latitude,
            "longitude": longitude,
            "path": path,
            "port_name": port_name,
            "is_direct": is_direct,
            "hop_count": hop_count,
        }
        if extra:
            payload.update(extra)
        return payload

    async def _publish_mqtt_event(self, event: Dict[str, Any]):
        """Publish an automation event through the optional MQTT integration."""
        if not self._mqtt_publisher:
            return
        try:
            await self._mqtt_publisher.publish_event(event)
        except Exception as e:
            logger.error(f"MQTT event publish error: {e}")

    async def _publish_mqtt_watched_station(self, callsign: str, station: Dict[str, Any]):
        """Publish a watched-callsign presence snapshot when one is heard."""
        if not self._mqtt_publisher:
            return
        try:
            normalized = (callsign or "").strip().upper()
            if normalized in set(getattr(self._mqtt_publisher, "watched_callsigns", []) or []):
                await self._mqtt_publisher.publish_watched_station(normalized, station, True)
        except Exception as e:
            logger.error(f"MQTT watched station publish error: {e}")

    def _mqtt_status_snapshot(
        self,
        prop_data: Optional[Dict[str, Any]] = None,
        active_alert: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Build retained Home Assistant state for summary and binary sensors."""
        now = time.time()
        prop_data = prop_data or {}
        active_alert = active_alert or {}
        alert_type = str(active_alert.get("type") or active_alert.get("event") or "").lower()
        band_opening = alert_type in {"my_station_opening", "regional_watch"}
        weather_warning = "weather" in alert_type
        return {
            "rf_station_count": len(self._rf_stations),
            "aprs_is_station_count": len(self._is_stations),
            "last_rf_packet_time": self._last_rf_packet_time or None,
            "last_rf_packet_age_seconds": round(now - self._last_rf_packet_time) if self._last_rf_packet_time else None,
            "band_opening_active": "ON" if band_opening or float(prop_data.get("score", 0) or 0) >= 70 else "OFF",
            "sporadic_e_possible": "ON" if float(prop_data.get("sporadic_e_score", 0) or 0) >= 60 else "OFF",
            "new_station_heard": "ON" if now < self._recent_first_heard_until else "OFF",
            "weather_warning_active": "ON" if weather_warning else "OFF",
            "weather_alert_count": 1 if weather_warning else 0,
            "timestamp": now,
        }

    @staticmethod
    def _score_to_level(score: float) -> str:
        if score >= 75:
            return "excellent"
        elif score >= 50:
            return "good"
        elif score >= 25:
            return "fair"
        elif score > 0:
            return "poor"
        return "none"

    async def cleanup_loop(self):
        """Periodically clean up old station data."""
        while True:
            try:
                await asyncio.sleep(self.config.tracking.cleanup_interval)
                max_age = self.config.tracking.max_station_age
                await self.db.delete_old_stations(max_age)
                await self.db.delete_old_packets(max_age * 2)

                # Prune in-memory caches and notify frontend
                cutoff = time.time() - max_age
                for cache, source in [
                    (self._rf_stations, "rf"),
                    (self._is_stations, "aprs_is"),
                ]:
                    stale = [
                        cs for cs, info in cache.items()
                        if info.get("last_heard", 0) < cutoff
                    ]
                    for cs in stale:
                        del cache[cs]
                        await self.ws.broadcast({
                            "type": "station_removed",
                            "data": {"callsign": cs, "source": source},
                        })
                    if stale:
                        logger.info(f"Pruned {len(stale)} stale {source} stations from memory")

                # Calculate and broadcast propagation update
                prop_data = await self.get_propagation_data()
                await self.ws.broadcast({"type": "propagation", "data": prop_data})
                await self._publish_mqtt_propagation(prop_data)

                logger.info(
                    f"Cleanup: purged stations older than {max_age}s, "
                    f"propagation score: {prop_data['score']}"
                )
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Cleanup error: {e}")

    async def propagation_broadcast_loop(self):
        """Broadcast propagation data every 60 seconds."""
        while True:
            try:
                await asyncio.sleep(60)
                prop_data = await self.get_propagation_data(log_sample=True)
                watched_alerts_allowed = bool(
                    self._alert_manager
                    and self._alert_manager.config.enabled
                    and not self._alert_manager._is_quiet_time()
                )
                watched_paths = await self.evaluate_watched_paths(allow_alerts=watched_alerts_allowed)
                prop_data["watched_paths"] = watched_paths
                await self.ws.broadcast({"type": "propagation", "data": prop_data})
                await self._publish_mqtt_propagation(prop_data)

                # Check for band opening alerts
                if self._alert_manager:
                    alerts = self._alert_manager.check_and_alert(prop_data)
                    for alert in alerts:
                        logger.info(f"Alert triggered: {alert['type']} — Score: {alert['score']}")
                        await self._alert_manager.send_alert(alert)
                        await self.ws.broadcast({"type": "alert", "data": alert})
                        await self._publish_mqtt_alert(alert)
                    if watched_alerts_allowed:
                        for alert in watched_paths.get("alerts", []):
                            logger.info("Watched path alert triggered: %s score %.1f", alert.get("callsign"), alert.get("score", 0))
                            self._alert_manager.record_alert(alert)
                            await self._alert_manager.send_alert(alert)
                            await self.ws.broadcast({"type": "alert", "data": alert})
                            await self._publish_mqtt_alert(alert)

                # Check for anomaly and sporadic-E (every 5th cycle = ~5 min)
                if self._analytics and self._alert_manager:
                    try:
                        anomaly = await self._analytics.get_anomaly_status()
                        anomaly_alert = await self._alert_manager.check_anomaly(anomaly)
                        if anomaly_alert:
                            await self.ws.broadcast({"type": "alert", "data": anomaly_alert})
                            await self._publish_mqtt_alert(anomaly_alert)
                        # Broadcast anomaly status to frontend
                        await self.ws.broadcast({"type": "anomaly", "data": anomaly})

                        es_data = await self._analytics.detect_sporadic_e()
                        es_alert = await self._alert_manager.check_sporadic_e(es_data)
                        if es_alert:
                            await self.ws.broadcast({"type": "alert", "data": es_alert})
                            await self._publish_mqtt_alert(es_alert)
                        if es_data.get("es_level") in ("likely", "possible"):
                            await self.ws.broadcast({"type": "sporadic_e", "data": es_data})
                    except Exception as e:
                        logger.error(f"Anomaly/Es check error: {e}")

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Propagation broadcast error: {e}")
