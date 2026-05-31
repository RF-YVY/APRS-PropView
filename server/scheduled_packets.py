"""Scheduled APRS bulletins and map-created object packets."""

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from server.aprs_parser import make_message_packet
from server.config import Config

logger = logging.getLogger("propview.scheduled_packets")


def _clean_ascii(text: str, max_len: int) -> str:
    return "".join(ch for ch in str(text or "") if 32 <= ord(ch) <= 126).strip()[:max_len]


def _coord_to_aprs(latitude: float, longitude: float) -> str:
    lat_dir = "N" if latitude >= 0 else "S"
    lon_dir = "E" if longitude >= 0 else "W"
    lat = abs(float(latitude))
    lon = abs(float(longitude))
    lat_deg = int(lat)
    lon_deg = int(lon)
    lat_min = (lat - lat_deg) * 60
    lon_min = (lon - lon_deg) * 60
    return f"{lat_deg:02d}{lat_min:05.2f}{lat_dir}", f"{lon_deg:03d}{lon_min:05.2f}{lon_dir}"


def _bool_item(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on", "enabled"}


def _int_item(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _float_item(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def build_bulletin_info(item: Dict[str, Any]) -> str:
    bulletin_id = _clean_ascii(item.get("id", "1"), 5).upper() or "1"
    text = _clean_ascii(item.get("text", ""), 67)
    return make_message_packet(f"BLN{bulletin_id}", text)


def build_object_info(item: Dict[str, Any]) -> str:
    name = _clean_ascii(item.get("name", ""), 9).upper().ljust(9)[:9]
    if not name.strip():
        raise ValueError("Object name is required.")
    lat, lon = _coord_to_aprs(float(item.get("latitude", 0)), float(item.get("longitude", 0)))
    overlay = _clean_ascii(item.get("overlay", ""), 1)
    symbol_table = overlay or (_clean_ascii(item.get("symbol_table", "/"), 1) or "/")[:1]
    symbol_code = (_clean_ascii(item.get("symbol_code", "\\"), 1) or "\\")[:1]
    active = _bool_item(item.get("active", item.get("live", True)), True)
    permanent = _bool_item(item.get("permanent", False), False)
    comment_parts: List[str] = []

    speed = _int_item(item.get("speed_mph"), 0)
    course = _int_item(item.get("course_deg"), 0) % 360
    if speed > 0:
        comment_parts.append(f"{course:03d}/{min(speed, 999):03d}")

    signpost = _clean_ascii(item.get("signpost", ""), 20)
    if signpost:
        comment_parts.append(signpost)

    frequency = _clean_ascii(item.get("frequency", ""), 12)
    if frequency:
        freq_text = frequency if "MHz" in frequency else f"{frequency}MHz"
        comment_parts.append(freq_text)

    duplex = _clean_ascii(item.get("duplex", ""), 3)
    tone = _clean_ascii(item.get("tone", ""), 8)
    if duplex:
        comment_parts.append(f"Dup {duplex}")
    if tone:
        comment_parts.append(f"T{tone}")

    qru = _clean_ascii(item.get("qru", ""), 12).upper()
    if qru:
        comment_parts.append(f"QRU {qru}")

    comment = _clean_ascii(item.get("comment", ""), 80)
    if comment:
        comment_parts.append(comment)
    body_comment = _clean_ascii(" ".join(part for part in comment_parts if part), 120)

    if permanent:
        live_flag = "!" if active else "_"
        return f"){name.rstrip()}{live_flag}{lat}{symbol_table}{lon}{symbol_code}{body_comment}"

    live_flag = "*" if active else "_"
    stamp = datetime.now(timezone.utc).strftime("%d%H%Mz")
    return f";{name}{live_flag}{stamp}{lat}{symbol_table}{lon}{symbol_code}{body_comment}"


def object_transmit_mode(item: Dict[str, Any], default_mode: str) -> Optional[str]:
    if not _bool_item(item.get("enabled", True), True):
        return None
    scope = _clean_ascii(item.get("scope", "global"), 12).lower()
    if scope == "private":
        return None
    if scope == "local":
        return "rf"
    mode = _clean_ascii(item.get("mode", ""), 12).lower()
    return mode if mode in {"both", "rf", "aprs_is"} else default_mode


def object_transmit_path(item: Dict[str, Any], default_path: str) -> str:
    return _clean_ascii(item.get("path", ""), 40) or default_path


class ScheduledPacketTransmitter:
    """Periodically transmits configured APRS bulletins and objects."""

    def __init__(self, config: Config, handler):
        self.config = config
        self.handler = handler
        self._last_bulletin_tx = 0.0
        self._last_object_tx = 0.0
        self._killed_object_counts: Dict[str, int] = {}

    def get_status(self) -> Dict[str, Any]:
        return {
            "bulletins": {
                "enabled": self.config.bulletins.enabled,
                "interval": self.config.bulletins.interval,
                "count": len(self._bulletin_items()),
                "last_transmit": self._last_bulletin_tx or None,
            },
            "objects": {
                "enabled": self.config.aprs_objects.enabled,
                "interval": self.config.aprs_objects.interval,
                "count": len(self._object_items()),
                "last_transmit": self._last_object_tx or None,
            },
        }

    def _bulletin_items(self) -> List[Dict[str, Any]]:
        return [item for item in self.config.bulletins.items if _clean_ascii(item.get("text", ""), 67)]

    def _object_items(self) -> List[Dict[str, Any]]:
        return [item for item in self.config.aprs_objects.items if _clean_ascii(item.get("name", ""), 9)]

    def _transmittable_object_items(self, force: bool = False) -> List[Dict[str, Any]]:
        items = []
        for item in self._object_items():
            if object_transmit_mode(item, self.config.aprs_objects.mode) is None:
                continue
            name = _clean_ascii(item.get("name", ""), 9).upper()
            active = _bool_item(item.get("active", item.get("live", True)), True)
            if not force and not active and self._killed_object_counts.get(name, 0) >= 3:
                continue
            items.append(item)
        return items

    def preview_bulletins(self) -> List[str]:
        return [build_bulletin_info(item) for item in self._bulletin_items()]

    def preview_objects(self) -> List[str]:
        previews = []
        for item in self._object_items():
            prefix = ""
            if not _bool_item(item.get("enabled", True), True):
                prefix = "[disabled] "
            elif _clean_ascii(item.get("scope", "global"), 12).lower() == "private":
                prefix = "[private] "
            previews.append(prefix + build_object_info(item))
        return previews

    async def transmit_bulletins_once(self, force: bool = True) -> Dict[str, Any]:
        if not force and not self.config.bulletins.enabled:
            return {"transmitted": False, "message": "Bulletins are disabled."}
        items = self._bulletin_items()
        if not items:
            return {"transmitted": False, "message": "No bulletins configured."}
        for item in items:
            info = build_bulletin_info(item)
            result = await self.handler.transmit_aprs_info(
                self.config.station.full_callsign,
                info,
                mode=self.config.bulletins.mode,
                path=self.config.bulletins.path,
                destination="APPRPV",
            )
            if result.get("can_transmit"):
                self.handler.record_transmit_history("bulletin", self.config.station.full_callsign, info, "Bulletin")
        self._last_bulletin_tx = time.time()
        return {"transmitted": True, "message": f"Transmitted {len(items)} bulletin(s)."}

    async def transmit_objects_once(self, force: bool = True) -> Dict[str, Any]:
        if not force and not self.config.aprs_objects.enabled:
            return {"transmitted": False, "message": "APRS objects are disabled."}
        items = self._transmittable_object_items(force=force)
        if not items:
            return {"transmitted": False, "message": "No APRS objects configured."}
        for item in items:
            info = build_object_info(item)
            tx_mode = object_transmit_mode(item, self.config.aprs_objects.mode)
            if not tx_mode:
                continue
            result = await self.handler.transmit_aprs_info(
                self.config.station.full_callsign,
                info,
                mode=tx_mode,
                path=object_transmit_path(item, self.config.aprs_objects.path),
                destination="APPRPV",
            )
            if result.get("can_transmit"):
                self.handler.record_transmit_history("object", self.config.station.full_callsign, info, "APRS object")
            if not _bool_item(item.get("active", item.get("live", True)), True):
                name = _clean_ascii(item.get("name", ""), 9).upper()
                self._killed_object_counts[name] = self._killed_object_counts.get(name, 0) + 1
        self._last_object_tx = time.time()
        return {"transmitted": True, "message": f"Transmitted {len(items)} APRS object(s)."}

    async def loop(self):
        await asyncio.sleep(15)
        while True:
            try:
                now = time.time()
                if self.config.bulletins.enabled and now - self._last_bulletin_tx >= max(600, int(self.config.bulletins.interval or 1800)):
                    await self.transmit_bulletins_once(force=False)
                if self.config.aprs_objects.enabled and now - self._last_object_tx >= max(600, int(self.config.aprs_objects.interval or 1800)):
                    await self.transmit_objects_once(force=False)
                await asyncio.sleep(30)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.warning("Scheduled packet transmit skipped: %s", exc)
                await asyncio.sleep(60)
