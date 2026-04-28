"""Station tracker — tracks heard stations, calculates propagation metrics."""

import asyncio
import logging
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

    def set_alert_manager(self, alert_manager):
        """Inject the AlertManager instance for band-opening detection."""
        self._alert_manager = alert_manager

    def set_analytics(self, analytics):
        """Inject the AnalyticsEngine for anomaly and Es checks."""
        self._analytics = analytics

    async def track_packet(self, packet: APRSPacket):
        """Process a parsed packet and update station tracking."""
        source = packet.source  # 'rf' or 'aprs_is'
        callsign = packet.from_call
        is_direct = source == "rf" and self._is_direct_path(packet.path)

        if not callsign:
            return

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
                hop_count=hop_count,
                is_direct=is_direct,
                commit=False,
            )

        # Log and alert on first-heard stations
        if is_first_heard:
            await self.db.log_first_heard(
                callsign=callsign,
                source=source,
                distance_km=distance_km,
                heading=heading,
                latitude=packet.latitude,
                longitude=packet.longitude,
                commit=False,
            )
            # Broadcast first-heard event to web clients
            await self.ws.broadcast({
                "type": "first_heard",
                "data": {
                    "callsign": callsign,
                    "distance_km": distance_km,
                    "heading": heading,
                    "timestamp": time.time(),
                },
            })
            # Trigger first-heard alert if alert manager is available
            if self._alert_manager and distance_km and (source != "rf" or is_direct):
                await self._alert_manager.check_first_heard(
                    callsign, distance_km, heading
                )

        await self.db.commit()

        # Update in-memory cache
        cache = self._rf_stations if source == "rf" else self._is_stations
        cache[callsign] = station

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
                    "distance_km": distance_km,
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

    async def get_propagation_data(self, log_sample: bool = False) -> Dict[str, Any]:
        """Calculate current propagation metrics for both meters."""
        now = time.time()
        stats = await self.db.get_stats()
        prop_cfg = self.config.propagation

        # Get RF stations with distances for the last hour
        rf_1h = await self.db.get_stations(source="rf", since=now - 3600)

        # Split RF stations into direct-heard local and relayed regional groups
        all_distances = [s["distance_km"] for s in rf_1h if s.get("distance_km")]
        direct_stations = [s for s in rf_1h if self._is_direct_path(s.get("last_path", ""))]
        direct_distances = [s["distance_km"] for s in direct_stations if s.get("distance_km")]
        regional_stations = [s for s in rf_1h if not self._is_direct_path(s.get("last_path", ""))]
        regional_distances = [s["distance_km"] for s in regional_stations if s.get("distance_km")]

        rf_6h = await self.db.get_stations(source="rf", since=now - 21600)
        rf_24h = await self.db.get_stations(source="rf", since=now - 86400)
        regional_count_6h = sum(1 for s in rf_6h if not self._is_direct_path(s.get("last_path", "")))
        regional_count_24h = sum(1 for s in rf_24h if not self._is_direct_path(s.get("last_path", "")))

        # ── My Station meter (direct-heard only) ────────────
        my_count = len(direct_stations)
        my_max_dist = max(direct_distances) if direct_distances else 0
        my_avg_dist = sum(direct_distances) / len(direct_distances) if direct_distances else 0
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
                await self.ws.broadcast({"type": "propagation", "data": prop_data})

                # Check for band opening alerts
                if self._alert_manager:
                    alerts = self._alert_manager.check_and_alert(prop_data)
                    for alert in alerts:
                        logger.info(f"Alert triggered: {alert['type']} — Score: {alert['score']}")
                        await self._alert_manager.send_alert(alert)
                        await self.ws.broadcast({"type": "alert", "data": alert})

                # Check for anomaly and sporadic-E (every 5th cycle = ~5 min)
                if self._analytics and self._alert_manager:
                    try:
                        anomaly = await self._analytics.get_anomaly_status()
                        await self._alert_manager.check_anomaly(anomaly)
                        # Broadcast anomaly status to frontend
                        await self.ws.broadcast({"type": "anomaly", "data": anomaly})

                        es_data = await self._analytics.detect_sporadic_e()
                        await self._alert_manager.check_sporadic_e(es_data)
                        if es_data.get("es_level") in ("likely", "possible"):
                            await self.ws.broadcast({"type": "sporadic_e", "data": es_data})
                    except Exception as e:
                        logger.error(f"Anomaly/Es check error: {e}")

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Propagation broadcast error: {e}")
