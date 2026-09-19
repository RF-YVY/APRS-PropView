"""Live NOAA GOES GLM lightning ingestion with bounded in-memory retention."""

import asyncio
import logging
import math
import re
import time
import urllib.request
import xml.etree.ElementTree as ET
from collections import deque
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Deque, Dict, Iterable, List, Optional

from server.config import Config

logger = logging.getLogger("propview.lightning")

SATELLITES = {
    "goes19": {"bucket": "noaa-goes19", "label": "GOES-19 (East)", "longitude": -75.2},
    "goes18": {"bucket": "noaa-goes18", "label": "GOES-18 (West)", "longitude": -137.0},
}
_GRANULE_END_RE = re.compile(r"_e(\d{13})\d(?:_|\.)")
MAX_RETAINED_FLASHES = 50_000
MAX_API_FLASHES = 5_000


def _longitude_distance(a: float, b: float) -> float:
    return abs((a - b + 180.0) % 360.0 - 180.0)


def select_satellite(selection: str, latitude: float, longitude: float) -> str:
    """Resolve an explicit selection or choose the closest GOES orbital slot."""
    requested = (selection or "auto").strip().lower().replace("-", "")
    if requested in SATELLITES:
        return requested
    return min(
        SATELLITES,
        key=lambda name: _longitude_distance(longitude, SATELLITES[name]["longitude"]),
    )


def distance_and_bearing_miles(lat1: float, lon1: float, lat2: float, lon2: float):
    """Return great-circle distance in miles and initial bearing in degrees."""
    radius = 3958.7613
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    dp = p2 - p1
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    distance = radius * 2 * math.atan2(math.sqrt(a), math.sqrt(max(0.0, 1 - a)))
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return distance, (math.degrees(math.atan2(y, x)) + 360.0) % 360.0


class LightningManager:
    """Poll public NODD S3 GLM granules and expose a small rolling flash window."""

    def __init__(
        self,
        config: Config,
        alert_manager=None,
        ws_manager=None,
        list_keys: Optional[Callable[[str, datetime], List[str]]] = None,
        download: Optional[Callable[[str, str], bytes]] = None,
        parse: Optional[Callable[[bytes, str], Iterable[Dict[str, Any]]]] = None,
    ):
        self.config = config
        self.alert_manager = alert_manager
        self.ws_manager = ws_manager
        self._flashes: Deque[Dict[str, Any]] = deque()
        self._seen: Dict[str, float] = {}
        self._last_poll = 0.0
        self._last_data = 0.0
        self._last_error = ""
        self._last_alert = 0.0
        self._watch_last_alert: Dict[str, float] = {}
        self._satellite = ""
        self._list_keys = list_keys or self._list_s3_keys
        self._download = download or self._download_s3_object
        self._parse = parse or self._parse_netcdf

    @property
    def enabled(self) -> bool:
        return bool(self.config.weather.lightning_enabled)

    def _resolved_satellite(self) -> str:
        return select_satellite(
            self.config.weather.lightning_satellite,
            float(self.config.station.latitude or 0),
            float(self.config.station.longitude or 0),
        )

    @staticmethod
    def _prefix(now: datetime) -> str:
        return f"GLM-L2-LCFA/{now.year}/{now.timetuple().tm_yday:03d}/{now.hour:02d}/"

    @classmethod
    def _list_s3_keys(cls, satellite: str, now: datetime) -> List[str]:
        bucket = SATELLITES[satellite]["bucket"]
        prefix = cls._prefix(now)
        url = f"https://{bucket}.s3.amazonaws.com/?list-type=2&prefix={prefix}"
        request = urllib.request.Request(url, headers={"User-Agent": "APRSPropView/1.0"})
        with urllib.request.urlopen(request, timeout=15) as response:
            root = ET.fromstring(response.read())
        return [node.text for node in root.findall(".//{*}Key") if node.text]

    @staticmethod
    def _download_s3_object(satellite: str, key: str) -> bytes:
        bucket = SATELLITES[satellite]["bucket"]
        request = urllib.request.Request(
            f"https://{bucket}.s3.amazonaws.com/{key}",
            headers={"User-Agent": "APRSPropView/1.0"},
        )
        with urllib.request.urlopen(request, timeout=20) as response:
            return response.read()

    @staticmethod
    def _granule_end_timestamp(key: str) -> Optional[float]:
        match = _GRANULE_END_RE.search(key)
        if not match:
            return None
        try:
            return datetime.strptime(match.group(1), "%Y%j%H%M%S").replace(tzinfo=timezone.utc).timestamp()
        except ValueError:
            return None

    @staticmethod
    def _parse_netcdf(payload: bytes, key: str) -> Iterable[Dict[str, Any]]:
        try:
            import netCDF4
        except ImportError as exc:  # pragma: no cover - packaging guard
            raise RuntimeError("The netCDF4 package is required for GOES lightning") from exc

        dataset = netCDF4.Dataset("glm-memory.nc", mode="r", memory=payload)
        try:
            base_text = str(getattr(dataset, "time_coverage_start", ""))
            base = datetime.fromisoformat(base_text.replace("Z", "+00:00")).timestamp()
            latitudes = dataset.variables["flash_lat"][:]
            longitudes = dataset.variables["flash_lon"][:]
            offsets = dataset.variables["flash_time_offset_of_first_event"][:]
            quality = dataset.variables.get("flash_quality_flag")
            qualities = quality[:] if quality is not None else [0] * len(latitudes)
            energies_var = dataset.variables.get("flash_energy")
            energies = energies_var[:] if energies_var is not None else [None] * len(latitudes)
            areas_var = dataset.variables.get("flash_area")
            areas = areas_var[:] if areas_var is not None else [None] * len(latitudes)
            for index in range(len(latitudes)):
                if int(qualities[index]) != 0:
                    continue
                yield {
                    "lat": round(float(latitudes[index]), 4),
                    "lon": round(float(longitudes[index]), 4),
                    "timestamp": base + float(offsets[index]),
                    "energy_j": float(energies[index]) if energies[index] is not None else None,
                    "area_m2": float(areas[index]) if areas[index] is not None else None,
                    "source": key.rsplit("/", 1)[-1],
                }
        finally:
            dataset.close()

    def _retention_seconds(self) -> int:
        minutes = max(1, min(60, int(self.config.weather.lightning_history_minutes or 10)))
        return minutes * 60

    def prune(self, now: Optional[float] = None):
        """Delete stale flashes and old dedupe keys; memory use stays bounded."""
        now = now or time.time()
        cutoff = now - self._retention_seconds()
        while self._flashes and self._flashes[0]["timestamp"] < cutoff:
            self._flashes.popleft()
        while len(self._flashes) > MAX_RETAINED_FLASHES:
            self._flashes.popleft()
        seen_cutoff = now - max(7200, self._retention_seconds() * 2)
        self._seen = {key: seen_at for key, seen_at in self._seen.items() if seen_at >= seen_cutoff}

    async def poll_once(self, now: Optional[datetime] = None):
        now = now or datetime.now(timezone.utc)
        satellite = self._resolved_satellite()
        if satellite != self._satellite:
            self._flashes.clear()
            self._seen.clear()
            self._satellite = satellite

        self._last_poll = time.time()
        try:
            keys = await asyncio.to_thread(self._list_keys, satellite, now)
            if now.minute * 60 + now.second < self._retention_seconds():
                keys += await asyncio.to_thread(self._list_keys, satellite, now - timedelta(hours=1))
            unseen = [key for key in sorted(set(keys)) if key not in self._seen]
            # On startup/catch-up, bound work to the configured rolling window.
            max_granules = max(3, min(180, self._retention_seconds() // 20 + 3))
            for key in unseen[-max_granules:]:
                payload = await asyncio.to_thread(self._download, satellite, key)
                points = list(self._parse(payload, key))
                self._flashes.extend(points)
                self._seen[key] = time.time()
                granule_end = self._granule_end_timestamp(key)
                timestamps = [p["timestamp"] for p in points]
                if granule_end is not None:
                    timestamps.append(granule_end)
                if timestamps:
                    self._last_data = max(self._last_data, max(timestamps))
                self.prune()
            if unseen:
                self._flashes = deque(sorted(self._flashes, key=lambda item: item["timestamp"]))
            self._last_error = ""
            self.prune()
            await self._maybe_alert()
        except Exception as exc:
            self._last_error = str(exc)
            logger.warning("GOES lightning update failed: %s", exc)
            self.prune()

    async def run(self):
        while True:
            if self.enabled:
                await self.poll_once()
                await asyncio.sleep(20)
            else:
                self._flashes.clear()
                self._seen.clear()
                await asyncio.sleep(5)

    def snapshot(self, now: Optional[float] = None) -> Dict[str, Any]:
        now = now or time.time()
        self.prune(now)
        station_lat = float(self.config.station.latitude or 0)
        station_lon = float(self.config.station.longitude or 0)
        recent_minute = [point for point in self._flashes if point["timestamp"] >= now - 60]
        nearby = []
        nearest = None
        for point in recent_minute:
            distance, bearing = distance_and_bearing_miles(
                station_lat, station_lon, point["lat"], point["lon"]
            )
            if nearest is None or distance < nearest["distance_miles"]:
                nearest = {
                    "distance_miles": round(distance, 1),
                    "bearing_degrees": round(bearing),
                    "timestamp": point["timestamp"],
                }
            if distance <= float(self.config.weather.lightning_alert_radius_miles or 0):
                nearby.append(point)
        satellite = self._satellite or self._resolved_satellite()
        stale_seconds = max(60, int(self.config.weather.lightning_stale_seconds or 120))
        data_age = (now - self._last_data) if self._last_data else None
        rendered_flashes = list(self._flashes)[-MAX_API_FLASHES:]
        return {
            "enabled": self.enabled,
            "satellite": satellite,
            "satellite_label": SATELLITES[satellite]["label"],
            "selection": self.config.weather.lightning_satellite,
            "history_minutes": self.config.weather.lightning_history_minutes,
            "opacity": self.config.weather.lightning_opacity,
            "flashes": rendered_flashes,
            "flashes_truncated": len(self._flashes) > len(rendered_flashes),
            "counts": {
                "last_minute": len(recent_minute),
                "retained": len(self._flashes),
                "within_alert_radius": len(nearby),
            },
            "nearest": nearest,
            "alert_radius_miles": self.config.weather.lightning_alert_radius_miles,
            "info_card_enabled": self.config.weather.lightning_info_card_enabled,
            "data_age_seconds": round(data_age, 1) if data_age is not None else None,
            "stale": data_age is None or data_age > stale_seconds,
            "last_error": self._last_error,
        }

    async def _maybe_alert(self):
        await self._maybe_local_alert()
        await self._maybe_watched_alerts()

    async def _maybe_local_alert(self):
        cfg = self.config.weather
        if not cfg.lightning_alert_enabled or not self.alert_manager:
            return
        now = time.time()
        cooldown = max(1, int(cfg.lightning_alert_cooldown_minutes or 1)) * 60
        if now - self._last_alert < cooldown or self.alert_manager._is_quiet_time():
            return
        snap = self.snapshot(now)
        count = snap["counts"]["within_alert_radius"]
        nearest = snap["nearest"]
        if not count or not nearest or nearest["distance_miles"] > cfg.lightning_alert_radius_miles:
            return
        alert = {
            "type": "lightning_proximity",
            "timestamp": now,
            "distance_miles": nearest["distance_miles"],
            "bearing_degrees": nearest["bearing_degrees"],
            "flash_count": count,
            "message": (
                f"Lightning nearby: {count} GOES GLM flash{'es' if count != 1 else ''} within "
                f"{cfg.lightning_alert_radius_miles:g} mi of {self.config.station.full_callsign}.\n"
                f"Nearest flash: {nearest['distance_miles']:.1f} mi at {nearest['bearing_degrees']}°.\n"
                "Satellite optical lightning data; not a ground-strike or safety-warning service."
            ),
        }
        self._last_alert = now
        self.alert_manager.record_alert(alert)
        channels = [
            channel
            for channel, enabled in (
                ("discord", cfg.lightning_alert_discord_enabled),
                ("email", cfg.lightning_alert_email_enabled),
                ("sms", cfg.lightning_alert_sms_enabled),
            )
            if enabled
        ]
        await self.alert_manager.send_alert(alert, channels=channels)
        if self.ws_manager:
            await self.ws_manager.broadcast({"type": "alert", "data": alert})

    @staticmethod
    def _target_coordinates(target) -> Optional[tuple[float, float]]:
        grid = str(getattr(target, "grid", "") or "").strip()
        if grid:
            from server.station_tracker import StationTracker
            return StationTracker.maidenhead_to_lat_lon(grid)
        try:
            lat = float(getattr(target, "latitude", 0))
            lon = float(getattr(target, "longitude", 0))
        except (TypeError, ValueError):
            return None
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            return None
        return lat, lon

    async def _maybe_watched_alerts(self):
        """Alert independently for opted-in repeater, event, and remote watch sites."""
        if not self.alert_manager or self.alert_manager._is_quiet_time():
            return
        now = time.time()
        recent = [point for point in self._flashes if point["timestamp"] >= now - 60]
        if not recent:
            return
        for target in (getattr(self.config, "watched_paths", []) or [])[:50]:
            if not getattr(target, "enabled", True) or not getattr(target, "watch_lightning_enabled", False):
                continue
            channels = [
                channel
                for channel, enabled in (
                    ("discord", getattr(target, "watch_discord_enabled", False)),
                    ("email", getattr(target, "watch_email_enabled", False)),
                    ("sms", getattr(target, "watch_sms_enabled", False)),
                )
                if enabled
            ]
            if not channels:
                continue
            coords = self._target_coordinates(target)
            if not coords:
                continue
            label = str(getattr(target, "callsign", "WATCH") or "WATCH").strip().upper()
            cooldown = max(1, int(getattr(target, "watch_alert_cooldown_minutes", 30) or 30)) * 60
            if now - self._watch_last_alert.get(label, 0) < cooldown:
                continue
            radius = max(1.0, min(500.0, float(getattr(target, "watch_alert_radius_miles", 25) or 25)))
            nearby = []
            nearest = None
            for point in recent:
                distance, bearing = distance_and_bearing_miles(coords[0], coords[1], point["lat"], point["lon"])
                if distance <= radius:
                    nearby.append(point)
                    if nearest is None or distance < nearest[0]:
                        nearest = (distance, bearing)
            if not nearby or nearest is None:
                continue
            alert = {
                "type": "lightning_proximity",
                "timestamp": now,
                "watch_location": label,
                "distance_miles": round(nearest[0], 1),
                "bearing_degrees": round(nearest[1]),
                "flash_count": len(nearby),
                "message": (
                    f"Lightning near watched site {label}: {len(nearby)} GOES GLM flash"
                    f"{'es' if len(nearby) != 1 else ''} within {radius:g} mi.\n"
                    f"Nearest flash: {nearest[0]:.1f} mi at {nearest[1]:.0f}°.\n"
                    "Satellite optical lightning data; not a ground-strike or safety-warning service."
                ),
            }
            self._watch_last_alert[label] = now
            self.alert_manager.record_alert(alert)
            await self.alert_manager.send_alert(alert, channels=channels)
            if self.ws_manager:
                await self.ws_manager.broadcast({"type": "alert", "data": alert})
