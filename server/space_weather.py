"""Cached NOAA SWPC context for radio operators."""

import asyncio
import json
import logging
import time
import urllib.request
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger("propview.space_weather")

KP_URL = "https://services.swpc.noaa.gov/products/noaa-planetary-k-index.json"
SCALES_URL = "https://services.swpc.noaa.gov/products/noaa-scales.json"


class SpaceWeatherManager:
    def __init__(self, config, alert_manager=None, ws_manager=None, fetch_json: Optional[Callable[[str], Any]] = None):
        self.config = config
        self.alert_manager = alert_manager
        self.ws_manager = ws_manager
        self._fetch_json = fetch_json or self._download_json
        self._snapshot: Dict[str, Any] = {}
        self._last_fetch = 0.0
        self._last_success = 0.0
        self._last_error = ""
        self._last_alert = 0.0

    @property
    def enabled(self) -> bool:
        return bool(getattr(self.config.weather, "space_weather_enabled", True))

    @staticmethod
    def _download_json(url: str):
        request = urllib.request.Request(url, headers={"User-Agent": "APRSPropView/1.0"})
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))

    @staticmethod
    def _timestamp(value: str) -> Optional[float]:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            parsed = parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)
            return parsed.timestamp()
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _context(kp: float, g_scale: int) -> Dict[str, str]:
        if kp >= 7 or g_scale >= 3:
            return {"level": "high", "text": "Strong geomagnetic activity. Treat unusual northern or polar VHF paths as possible auroral context, not confirmation."}
        if kp >= 5 or g_scale >= 1:
            return {"level": "elevated", "text": "Elevated geomagnetic activity. Compare northern-path RF evidence with normal station behavior."}
        return {"level": "quiet", "text": "Geomagnetic activity is currently quiet; no auroral VHF inference is being made."}

    async def poll_once(self):
        if not self.enabled:
            self._snapshot = {}
            return
        self._last_fetch = time.time()
        try:
            kp_rows, scales = await asyncio.gather(
                asyncio.to_thread(self._fetch_json, KP_URL),
                asyncio.to_thread(self._fetch_json, SCALES_URL),
            )
            latest = kp_rows[-1] if isinstance(kp_rows, list) and kp_rows else {}
            current = scales.get("0", {}) if isinstance(scales, dict) else {}
            forecast = scales.get("1", {}) if isinstance(scales, dict) else {}
            kp = float(latest.get("Kp", 0) or 0)
            g_scale = int((current.get("G", {}) or {}).get("Scale") or 0)
            r_scale = int((current.get("R", {}) or {}).get("Scale") or 0)
            s_scale = int((current.get("S", {}) or {}).get("Scale") or 0)
            observed_at = self._timestamp(latest.get("time_tag"))
            self._snapshot = {
                "enabled": True,
                "kp": round(kp, 2),
                "a_running": latest.get("a_running"),
                "station_count": latest.get("station_count"),
                "g_scale": g_scale,
                "r_scale": r_scale,
                "s_scale": s_scale,
                "forecast_g_scale": int((forecast.get("G", {}) or {}).get("Scale") or 0),
                "observed_at": observed_at,
                "context": self._context(kp, g_scale),
                "source": "NOAA SWPC",
            }
            self._last_success = time.time()
            self._last_error = ""
            await self._maybe_alert()
            if self.ws_manager:
                await self.ws_manager.broadcast({"type": "space_weather", "data": self.snapshot()})
        except Exception as exc:
            self._last_error = str(exc)
            logger.warning("NOAA SWPC update failed: %s", exc)

    def snapshot(self) -> Dict[str, Any]:
        now = time.time()
        age = now - self._last_success if self._last_success else None
        return {
            "enabled": self.enabled,
            **self._snapshot,
            "updated_at": self._last_success or None,
            "age_seconds": round(age) if age is not None else None,
            "stale": age is None or age > 3600,
            "last_error": self._last_error,
        }

    async def _maybe_alert(self):
        cfg = self.config.weather
        if not getattr(cfg, "space_weather_alert_enabled", False) or not self.alert_manager:
            return
        now = time.time()
        cooldown = max(5, int(getattr(cfg, "space_weather_alert_cooldown_minutes", 60) or 60)) * 60
        kp = float(self._snapshot.get("kp", 0) or 0)
        threshold = max(0.0, min(9.0, float(getattr(cfg, "space_weather_alert_min_kp", 5.0) or 5.0)))
        if kp < threshold or now - self._last_alert < cooldown or self.alert_manager._is_quiet_time():
            return
        channels = [
            channel for channel, enabled in (
                ("discord", getattr(cfg, "space_weather_alert_discord_enabled", False)),
                ("email", getattr(cfg, "space_weather_alert_email_enabled", False)),
                ("sms", getattr(cfg, "space_weather_alert_sms_enabled", False)),
            ) if enabled
        ]
        if not channels:
            return
        alert = {
            "type": "space_weather",
            "timestamp": now,
            "kp": kp,
            "g_scale": self._snapshot.get("g_scale", 0),
            "message": f"NOAA SWPC geomagnetic context: Kp {kp:g}, G{self._snapshot.get('g_scale', 0)}.\n{self._snapshot.get('context', {}).get('text', '')}",
        }
        self._last_alert = now
        self.alert_manager.record_alert(alert)
        await self.alert_manager.send_alert(alert, channels=channels)
        if self.ws_manager:
            await self.ws_manager.broadcast({"type": "alert", "data": alert})

    async def run(self):
        while True:
            try:
                if self.enabled:
                    await self.poll_once()
                    await asyncio.sleep(900)
                else:
                    await asyncio.sleep(30)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("Space weather loop failed: %s", exc)
                await asyncio.sleep(60)
