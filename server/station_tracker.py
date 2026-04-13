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

    def set_alert_manager(self, alert_manager):
        """Inject the AlertManager instance for band-opening detection."""
        self._alert_manager = alert_manager

    async def track_packet(self, packet: APRSPacket):
        """Process a parsed packet and update station tracking."""
        source = packet.source  # 'rf' or 'aprs_is'
        callsign = packet.from_call

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
        )

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

    async def get_propagation_data(self) -> Dict[str, Any]:
        """Calculate current propagation metrics."""
        now = time.time()
        stats = await self.db.get_stats()

        # Get RF stations with distances for the last hour
        rf_1h = await self.db.get_stations(source="rf", since=now - 3600)
        distances = [s["distance_km"] for s in rf_1h if s.get("distance_km")]

        max_dist = max(distances) if distances else 0
        avg_dist = sum(distances) / len(distances) if distances else 0
        station_count = len(rf_1h)

        # Propagation score: weighted combination of station count and distance
        # Score 0-100 where higher = better propagation
        count_score = min(station_count * 5, 50)  # Up to 50 points for 10+ stations
        dist_score = min(max_dist / 4, 50)  # Up to 50 points for 200+ km
        prop_score = min(count_score + dist_score, 100)

        # Determine propagation level
        if prop_score >= 75:
            prop_level = "excellent"
        elif prop_score >= 50:
            prop_level = "good"
        elif prop_score >= 25:
            prop_level = "fair"
        elif prop_score > 0:
            prop_level = "poor"
        else:
            prop_level = "none"

        result = {
            "score": round(prop_score, 1),
            "level": prop_level,
            "rf_stations_1h": stats.get("rf_stations_1h", 0),
            "rf_stations_6h": stats.get("rf_stations_6h", 0),
            "rf_stations_24h": stats.get("rf_stations_24h", 0),
            "is_stations_1h": stats.get("is_stations_1h", 0),
            "max_distance_km": round(max_dist, 1),
            "avg_distance_km": round(avg_dist, 1),
            "distances": sorted(distances),
            "timestamp": now,
        }

        # Log propagation data periodically
        await self.db.log_propagation(
            rf_count=station_count,
            max_dist=max_dist if max_dist else None,
            avg_dist=avg_dist if avg_dist else None,
            unique_1h=stats.get("rf_stations_1h", 0),
            unique_6h=stats.get("rf_stations_6h", 0),
            unique_24h=stats.get("rf_stations_24h", 0),
        )

        return result

    async def cleanup_loop(self):
        """Periodically clean up old station data."""
        while True:
            try:
                await asyncio.sleep(self.config.tracking.cleanup_interval)
                max_age = self.config.tracking.max_station_age
                await self.db.delete_old_stations(max_age)
                await self.db.delete_old_packets(max_age * 2)

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
                prop_data = await self.get_propagation_data()
                await self.ws.broadcast({"type": "propagation", "data": prop_data})

                # Check for band opening alerts
                if self._alert_manager:
                    alert = self._alert_manager.check_and_alert(prop_data)
                    if alert:
                        logger.info(f"Band opening alert triggered! Score: {alert['score']}")
                        await self._alert_manager.send_alert(alert)
                        # Notify web clients of alert
                        await self.ws.broadcast({"type": "alert", "data": alert})

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Propagation broadcast error: {e}")
