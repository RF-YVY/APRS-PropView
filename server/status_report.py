"""APRS status/DX report transmitter."""

import asyncio
import logging
import time
from typing import Any, Dict, Optional

from server.config import Config

logger = logging.getLogger("propview.status")


def bearing_label(heading: Optional[float]) -> str:
    if heading is None:
        return ""
    sectors = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
    return sectors[int(((heading % 360) + 22.5) // 45) % 8]


def trim_status_text(text: str, max_length: int) -> str:
    """Return printable ASCII text that fits a conservative APRS status size."""
    clean = "".join(ch if 32 <= ord(ch) <= 126 else " " for ch in (text or ""))
    clean = " ".join(clean.split())
    limit = max(20, min(120, int(max_length or 67)))
    return clean[:limit].rstrip()


def build_dx_status_text(prop_data: Dict[str, Any], window_minutes: int = 60, max_length: int = 67) -> str:
    """Build a compact DX status report from propagation data."""
    window = max(1, int(window_minutes or 60))
    top = prop_data.get("my_top_station") or {}
    direct_count = int(prop_data.get("my_stations_1h") or 0)
    regional_count = int(prop_data.get("regional_stations_1h") or prop_data.get("rf_stations_1h") or 0)
    level = str(prop_data.get("my_level") or prop_data.get("level") or "none").upper()

    if top.get("callsign") and top.get("distance_km"):
        distance_mi = float(top["distance_km"]) * 0.621371
        bearing = bearing_label(top.get("heading"))
        parts = [
            f"DX {window}m:",
            f"{top['callsign']} {distance_mi:.0f}mi",
        ]
        if bearing:
            parts.append(bearing)
        parts.append(f"{direct_count}D/{regional_count}RF")
        if level and level != "NONE":
            parts.append(level)
        return trim_status_text(" ".join(parts), max_length)

    if regional_count:
        text = f"DX {window}m: no direct DX; {regional_count} RF heard"
    else:
        text = f"DX {window}m: no RF stations heard"
    return trim_status_text(text, max_length)


class StatusReportTransmitter:
    """Periodically sends compact APRS status reports."""

    def __init__(self, config: Config, handler, tracker):
        self.config = config
        self.handler = handler
        self.tracker = tracker
        self._last_tx = 0.0
        self._last_error = ""
        self._last_text = ""

    def get_status(self) -> Dict[str, Any]:
        cfg = self.config.status
        return {
            "enabled": cfg.enabled,
            "beacon_interval": cfg.beacon_interval,
            "mode": cfg.mode,
            "path": cfg.path,
            "report_window_minutes": cfg.report_window_minutes,
            "max_length": cfg.max_length,
            "last_transmit": self._last_tx or None,
            "last_error": self._last_error,
            "last_text": self._last_text,
        }

    async def build_text(self) -> str:
        cfg = self.config.status
        prop_data = await self.tracker.get_propagation_data()
        return build_dx_status_text(
            prop_data,
            window_minutes=cfg.report_window_minutes,
            max_length=cfg.max_length,
        )

    async def transmit_once(self, force: bool = False) -> Dict[str, Any]:
        cfg = self.config.status
        if not cfg.enabled and not force:
            return {"transmitted": False, "message": "Status/DX transmit is disabled."}

        text = await self.build_text()
        if not text:
            raise ValueError("Status/DX report is empty.")

        result = await self.handler.transmit_aprs_info(
            source_call=self.config.station.full_callsign,
            info=f">{text}",
            mode=(cfg.mode or "both").strip().lower(),
            path=cfg.path,
        )
        if not result["can_transmit"]:
            raise ValueError(result["message"])

        self._last_tx = time.time()
        self._last_error = ""
        self._last_text = text
        return {
            "transmitted": True,
            "message": result["message"],
            "text": text,
        }

    async def loop(self):
        await asyncio.sleep(20)
        while True:
            try:
                interval = max(600, int(self.config.status.beacon_interval or 1800))
                if not self.config.status.enabled:
                    await asyncio.sleep(60)
                    continue
                try:
                    result = await self.transmit_once(force=False)
                    if result.get("transmitted"):
                        logger.info("Status/DX TX: %s", result.get("text"))
                except Exception as exc:
                    self._last_error = str(exc)
                    logger.warning("Status/DX transmit skipped: %s", exc)
                await asyncio.sleep(interval)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                self._last_error = str(exc)
                logger.error("Status/DX loop error: %s", exc, exc_info=True)
                await asyncio.sleep(60)
