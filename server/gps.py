"""GPS ingestion and live station-location state."""

import asyncio
import logging
import time
from typing import Any, Dict, Optional

from server.config import Config
from server.aprs_parser import calculate_bearing, calculate_distance

logger = logging.getLogger("propview.gps")


def _valid_lat_lon(latitude: float, longitude: float) -> bool:
    return -90 <= latitude <= 90 and -180 <= longitude <= 180


def _nmea_coord(value: str, hemisphere: str) -> Optional[float]:
    if not value or not hemisphere:
        return None
    try:
        dot = value.find(".")
        deg_len = (dot - 2) if dot >= 0 else (len(value) - 2)
        degrees = int(value[:deg_len])
        minutes = float(value[deg_len:])
        result = degrees + minutes / 60.0
        if hemisphere.upper() in {"S", "W"}:
            result = -result
        return result
    except (ValueError, TypeError):
        return None


def parse_nmea_position(sentence: str) -> Optional[Dict[str, Any]]:
    """Parse common RMC/GGA NMEA sentences into decimal coordinates."""
    line = (sentence or "").strip()
    if not line.startswith("$"):
        return None

    body = line[1:].split("*", 1)[0]
    parts = body.split(",")
    if not parts:
        return None

    sentence_type = parts[0][-3:].upper()
    speed_mph = None
    course_deg = None
    if sentence_type == "RMC" and len(parts) >= 7:
        if parts[2].upper() != "A":
            return None
        lat = _nmea_coord(parts[3], parts[4])
        lon = _nmea_coord(parts[5], parts[6])
        try:
            speed_mph = float(parts[7] or 0) * 1.15078 if len(parts) > 7 else None
        except (TypeError, ValueError):
            speed_mph = None
        try:
            course_deg = float(parts[8]) if len(parts) > 8 and parts[8] else None
        except (TypeError, ValueError):
            course_deg = None
    elif sentence_type == "GGA" and len(parts) >= 6:
        if not parts[6] or parts[6] == "0":
            return None
        lat = _nmea_coord(parts[2], parts[3])
        lon = _nmea_coord(parts[4], parts[5])
    else:
        return None

    if lat is None or lon is None or not _valid_lat_lon(lat, lon):
        return None
    result = {"latitude": lat, "longitude": lon}
    if speed_mph is not None:
        result["speed_mph"] = speed_mph
    if course_deg is not None:
        result["course_deg"] = course_deg
    return result


class GPSManager:
    """Maintains live GPS state and optionally applies it to station config."""

    def __init__(self, config: Config, ws_manager=None, tracker=None):
        self.config = config
        self.ws = ws_manager
        self.tracker = tracker
        self.current: Optional[Dict[str, Any]] = None
        self.source_status: Dict[str, Dict[str, Any]] = {}

    def set_tracker(self, tracker):
        self.tracker = tracker

    @property
    def enabled(self) -> bool:
        return bool(getattr(self.config, "gps", None) and self.config.gps.enabled)

    def _should_accept_source(self, source: str) -> bool:
        if not self.enabled:
            return False
        selected = (self.config.gps.source or "browser").strip().lower()
        return selected in {"any", source}

    def _visible_current(self) -> Optional[Dict[str, Any]]:
        if not self.current:
            return None
        selected = (self.config.gps.source or "browser").strip().lower()
        if selected == "any":
            return self.current
        current_source = (self.current.get("source") or "").lower()
        if selected == "browser" and current_source in {"browser", "companion"}:
            return self.current
        if current_source == selected:
            return self.current
        return None

    async def _set_source_status(self, source: str, state: str, message: str):
        self.source_status[source] = {
            "state": state,
            "message": message,
            "timestamp": time.time(),
        }
        if self.ws:
            await self.ws.broadcast({"type": "gps_location", "data": self.get_status()})

    async def update_location(
        self,
        latitude: float,
        longitude: float,
        source: str,
        accuracy_m: Optional[float] = None,
        timestamp: Optional[float] = None,
        speed_mph: Optional[float] = None,
        course_deg: Optional[float] = None,
        update_station_position: Optional[bool] = None,
        station_position_locked: Optional[bool] = None,
    ) -> Dict[str, Any]:
        lat = float(latitude)
        lon = float(longitude)
        if not _valid_lat_lon(lat, lon):
            raise ValueError("GPS latitude/longitude out of range.")

        now = timestamp or time.time()
        self.current = {
            "latitude": lat,
            "longitude": lon,
            "source": source,
            "accuracy_m": accuracy_m,
            "timestamp": now,
            "applied_to_station": False,
        }
        if speed_mph is not None:
            self.current["speed_mph"] = float(speed_mph)
        if course_deg is not None:
            self.current["course_deg"] = float(course_deg)
        self.source_status[source] = {
            "state": "fix",
            "message": f"GPS fix received from {source}.",
            "timestamp": now,
        }

        should_update_station = (
            self.config.gps.update_station_position
            if update_station_position is None
            else bool(update_station_position)
        )
        is_locked = (
            self.config.gps.station_position_locked
            if station_position_locked is None
            else bool(station_position_locked)
        )

        if should_update_station and not is_locked:
            self.config.station.latitude = lat
            self.config.station.longitude = lon
            self.current["applied_to_station"] = True
            if self.tracker:
                self.tracker.set_my_position(lat, lon)

        if self.ws:
            await self.ws.broadcast({"type": "gps_location", "data": self.get_status()})

        return self.get_status()

    async def update_from_nmea(self, sentence: str, source: str = "nmea") -> Optional[Dict[str, Any]]:
        pos = parse_nmea_position(sentence)
        if not pos:
            return None
        return await self.update_location(
            pos["latitude"],
            pos["longitude"],
            source=source,
            speed_mph=pos.get("speed_mph"),
            course_deg=pos.get("course_deg"),
        )

    def get_status(self) -> Dict[str, Any]:
        cfg = self.config.gps
        selected = (cfg.source or "browser").strip().lower()
        source_status = self.source_status.get(selected)
        if not source_status:
            if not cfg.enabled:
                source_status = {"state": "disabled", "message": "GPS ingestion is disabled.", "timestamp": None}
            elif selected in {"self_packet", "any"}:
                source_status = {"state": "waiting", "message": "Waiting for a GPS fix from the selected source.", "timestamp": None}
            elif selected == "browser":
                source_status = {"state": "waiting", "message": "Start Device GPS to use this browser's location.", "timestamp": None}
        return {
            "enabled": cfg.enabled,
            "source": cfg.source,
            "update_station_position": cfg.update_station_position,
            "station_position_locked": cfg.station_position_locked,
            "map_update_enabled": cfg.map_update_enabled,
            "current": self._visible_current(),
            "source_status": source_status,
        }

    async def run_tcp_nmea(self):
        while True:
            if not self.enabled or self.config.gps.source != "nmea_tcp":
                await asyncio.sleep(2)
                continue
            try:
                await self._set_source_status(
                    "nmea_tcp",
                    "connecting",
                    f"Connecting to NMEA TCP {self.config.gps.tcp_host}:{self.config.gps.tcp_port}...",
                )
                reader, writer = await asyncio.open_connection(
                    self.config.gps.tcp_host,
                    int(self.config.gps.tcp_port),
                )
                logger.info("GPS NMEA TCP connected to %s:%s", self.config.gps.tcp_host, self.config.gps.tcp_port)
                await self._set_source_status("nmea_tcp", "connected", "NMEA TCP connected; waiting for GPS sentences.")
                try:
                    while self.enabled and self.config.gps.source == "nmea_tcp":
                        line = await reader.readline()
                        if not line:
                            break
                        await self.update_from_nmea(line.decode("ascii", errors="ignore"), "nmea_tcp")
                finally:
                    writer.close()
                    await writer.wait_closed()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.warning("GPS NMEA TCP error: %s", e)
                await self._set_source_status("nmea_tcp", "error", f"NMEA TCP connection failed: {e}")
                await asyncio.sleep(5)

    async def run_serial_nmea(self):
        while True:
            if not self.enabled or self.config.gps.source != "nmea_serial":
                await asyncio.sleep(2)
                continue
            try:
                import serial_asyncio

                await self._set_source_status(
                    "nmea_serial",
                    "connecting",
                    f"Opening NMEA serial GPS on {self.config.gps.serial_port}...",
                )
                reader, writer = await serial_asyncio.open_serial_connection(
                    url=self.config.gps.serial_port,
                    baudrate=int(self.config.gps.serial_baudrate),
                )
                logger.info("GPS NMEA serial connected to %s", self.config.gps.serial_port)
                await self._set_source_status("nmea_serial", "connected", "NMEA serial connected; waiting for GPS sentences.")
                try:
                    while self.enabled and self.config.gps.source == "nmea_serial":
                        line = await reader.readline()
                        if not line:
                            break
                        await self.update_from_nmea(line.decode("ascii", errors="ignore"), "nmea_serial")
                finally:
                    writer.close()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.warning("GPS NMEA serial error: %s", e)
                await self._set_source_status("nmea_serial", "error", f"NMEA serial connection failed: {e}")
                await asyncio.sleep(5)

    async def run_udp_nmea(self):
        class Protocol(asyncio.DatagramProtocol):
            def __init__(self, manager: "GPSManager"):
                self.manager = manager

            def datagram_received(self, data, addr):
                text = data.decode("ascii", errors="ignore")
                for line in text.splitlines():
                    asyncio.create_task(self.manager.update_from_nmea(line, "nmea_udp"))

        transport = None
        while True:
            if not self.enabled or self.config.gps.source != "nmea_udp":
                await asyncio.sleep(2)
                continue
            try:
                loop = asyncio.get_running_loop()
                await self._set_source_status(
                    "nmea_udp",
                    "connecting",
                    f"Starting NMEA UDP listener on {self.config.gps.udp_host}:{self.config.gps.udp_port}...",
                )
                transport, _ = await loop.create_datagram_endpoint(
                    lambda: Protocol(self),
                    local_addr=(self.config.gps.udp_host, int(self.config.gps.udp_port)),
                )
                logger.info("GPS NMEA UDP listening on %s:%s", self.config.gps.udp_host, self.config.gps.udp_port)
                await self._set_source_status("nmea_udp", "connected", "NMEA UDP listener active; waiting for GPS sentences.")
                while self.enabled and self.config.gps.source == "nmea_udp":
                    await asyncio.sleep(2)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.warning("GPS NMEA UDP error: %s", e)
                await self._set_source_status("nmea_udp", "error", f"NMEA UDP listener failed: {e}")
                await asyncio.sleep(5)
            finally:
                if transport:
                    transport.close()
                    transport = None


def distance_from_current(config: Config, gps_manager: Optional[GPSManager], latitude: float, longitude: float):
    if (
        gps_manager
        and gps_manager.current
        and config.gps.enabled
        and config.gps.update_station_position
    ):
        lat = gps_manager.current["latitude"]
        lon = gps_manager.current["longitude"]
    else:
        lat = config.station.latitude
        lon = config.station.longitude
    if lat == 0.0 and lon == 0.0:
        return None, None
    return (
        calculate_distance(lat, lon, latitude, longitude),
        calculate_bearing(lat, lon, latitude, longitude),
    )
