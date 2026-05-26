"""APRS status/DX report transmitter."""

import asyncio
import logging
import random
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


def build_mheard_status_text(prop_data: Dict[str, Any], window_minutes: int = 60, max_length: int = 67) -> str:
    """Build a compact MHeard report from direct-heard RF stations only."""
    window = max(1, int(window_minutes or 60))
    stations = prop_data.get("direct_heard_stations") or []
    if not stations:
        return trim_status_text(f"MHeard {window}m: no direct RF stations", max_length)

    calls = []
    for station in stations:
        call = (station.get("callsign") or "").strip().upper()
        if call and call not in calls:
            calls.append(call)
        if len(calls) >= 6:
            break

    suffix = "" if len(stations) <= len(calls) else f" +{len(stations) - len(calls)}"
    return trim_status_text(f"MHeard {window}m: {', '.join(calls)}{suffix}", max_length)


def build_weather_alert_status_text(alert: Dict[str, Any], max_length: int = 67) -> str:
    """Build a compact severe weather status beacon."""
    event = (alert.get("event") or alert.get("headline") or "Weather Alert").strip()
    severity = (alert.get("severity") or "").strip()
    prefix = "WX WARNING" if str(alert.get("alert_type", "")).lower() == "warning" else "WX ALERT"
    if severity and severity.lower() not in event.lower():
        text = f"{prefix}: {event} ({severity})"
    else:
        text = f"{prefix}: {event}"
    return trim_status_text(text, max_length)


class StatusReportTransmitter:
    """Periodically sends compact APRS status reports."""

    def __init__(self, config: Config, handler, tracker, weather_manager=None):
        self.config = config
        self.handler = handler
        self.tracker = tracker
        self.weather_manager = weather_manager
        self._last_tx = 0.0
        self._last_error = ""
        self._last_text = ""
        self._dynamic_index = 0
        self._last_weather_alert_key = ""
        self._last_weather_alert_tx = 0.0

    def get_status(self) -> Dict[str, Any]:
        cfg = self.config.status
        return {
            "enabled": cfg.enabled,
            "beacon_interval": cfg.beacon_interval,
            "mode": cfg.mode,
            "path": cfg.path,
            "report_window_minutes": cfg.report_window_minutes,
            "max_length": cfg.max_length,
            "source": cfg.source,
            "dynamic_order": cfg.dynamic_order,
            "dynamic_messages": cfg.dynamic_messages,
            "weather_alert_beacon_enabled": cfg.weather_alert_beacon_enabled,
            "weather_alert_cooldown_minutes": cfg.weather_alert_cooldown_minutes,
            "last_transmit": self._last_tx or None,
            "last_error": self._last_error,
            "last_text": self._last_text,
        }

    async def build_text(self, advance_dynamic: bool = True) -> str:
        cfg = self.config.status
        source = (cfg.source or "dx").strip().lower()
        if source == "dynamic":
            return self._dynamic_text(advance=advance_dynamic)

        prop_data = await self.tracker.get_propagation_data()
        if source == "mheard":
            return build_mheard_status_text(
                prop_data,
                window_minutes=cfg.report_window_minutes,
                max_length=cfg.max_length,
            )
        return build_dx_status_text(
            prop_data,
            window_minutes=cfg.report_window_minutes,
            max_length=cfg.max_length,
        )

    async def build_preview_text(self) -> str:
        return await self.build_text(advance_dynamic=False)

    def _dynamic_text(self, advance: bool = True) -> str:
        cfg = self.config.status
        messages = [
            trim_status_text(msg, cfg.max_length)
            for msg in (cfg.dynamic_messages or [])
            if trim_status_text(msg, cfg.max_length)
        ]
        if not messages:
            return trim_status_text(self.config.station.comment or "APRS PropView", cfg.max_length)
        if (cfg.dynamic_order or "sequential").strip().lower() == "random":
            return random.choice(messages)
        text = messages[self._dynamic_index % len(messages)]
        if advance:
            self._dynamic_index = (self._dynamic_index + 1) % len(messages)
        return text

    async def preview_weather_alert_text(self) -> Dict[str, Any]:
        cfg = self.config.status
        if not cfg.weather_alert_beacon_enabled:
            return {"enabled": False, "text": "", "message": "Weather alert beaconing is disabled."}
        if not self.weather_manager:
            return {"enabled": True, "text": "", "message": "Weather alerts are not available."}
        alerts = await self.weather_manager.get_alerts(force=False)
        if not alerts:
            return {"enabled": True, "text": "", "message": "No active severe weather alerts."}
        alert = alerts[0]
        return {
            "enabled": True,
            "text": build_weather_alert_status_text(alert, cfg.max_length),
            "alert": alert,
            "message": "Previewing the highest-priority active alert.",
        }

    async def maybe_transmit_weather_alert(self) -> Optional[Dict[str, Any]]:
        cfg = self.config.status
        if not cfg.weather_alert_beacon_enabled or not self.weather_manager:
            return None

        cooldown = max(1, int(cfg.weather_alert_cooldown_minutes or 30)) * 60
        if self._last_weather_alert_tx and time.time() - self._last_weather_alert_tx < cooldown:
            return None

        alerts = await self.weather_manager.get_alerts(force=False)
        if not alerts:
            return None

        alert = alerts[0]
        key = "|".join(str(alert.get(k) or "") for k in ("event", "headline", "effective", "expires"))
        if key and key == self._last_weather_alert_key:
            return None

        text = build_weather_alert_status_text(alert, cfg.max_length)
        result = await self._transmit_text(text, feature="weather_alert")
        self._last_weather_alert_key = key
        self._last_weather_alert_tx = time.time()
        return {"alert": alert, **result}

    async def _transmit_text(self, text: str, feature: str = "status") -> Dict[str, Any]:
        cfg = self.config.status
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
        if hasattr(self.handler, "record_transmit_history"):
            self.handler.record_transmit_history(
                feature,
                self.config.station.full_callsign,
                f">{text}",
                result["message"],
            )
        return {
            "transmitted": True,
            "message": result["message"],
            "text": text,
        }

    async def transmit_once(self, force: bool = False) -> Dict[str, Any]:
        cfg = self.config.status
        if not cfg.enabled and not force:
            return {"transmitted": False, "message": "Status/DX transmit is disabled."}

        text = await self.build_text()
        if not text:
            raise ValueError("Status/DX report is empty.")

        source = (cfg.source or "dx").strip().lower()
        feature = "mheard" if source == "mheard" else "status"
        return await self._transmit_text(text, feature=feature)

    async def loop(self):
        await asyncio.sleep(20)
        while True:
            try:
                interval = max(600, int(self.config.status.beacon_interval or 1800))
                if not self.config.status.enabled:
                    await self.maybe_transmit_weather_alert()
                    await asyncio.sleep(60)
                    continue
                try:
                    alert_result = await self.maybe_transmit_weather_alert()
                    if alert_result and alert_result.get("transmitted"):
                        logger.info("Weather alert status TX: %s", alert_result.get("text"))
                    result = await self.transmit_once(force=False)
                    if result.get("transmitted"):
                        logger.info("Status/DX TX: %s", result.get("text"))
                except Exception as exc:
                    self._last_error = str(exc)
                    logger.warning("Status/DX transmit skipped: %s", exc)
                slept = 0
                while slept < interval:
                    await asyncio.sleep(min(60, interval - slept))
                    slept += min(60, interval - slept)
                    try:
                        alert_result = await self.maybe_transmit_weather_alert()
                        if alert_result and alert_result.get("transmitted"):
                            logger.info("Weather alert status TX: %s", alert_result.get("text"))
                    except Exception as exc:
                        self._last_error = str(exc)
                        logger.warning("Weather alert status transmit skipped: %s", exc)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                self._last_error = str(exc)
                logger.error("Status/DX loop error: %s", exc, exc_info=True)
                await asyncio.sleep(60)
