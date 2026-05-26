"""WXnow.txt APRS weather transmitter."""

import asyncio
import logging
import re
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from server.config import Config

logger = logging.getLogger("propview.wxnow")
POSITIONLESS_WX_POSITION_INTERVAL = 30 * 60

WXNOW_TIMESTAMP_FORMATS = (
    "%b %d %Y %H:%M",
    "%B %d %Y %H:%M",
)
WEATHER_BODY_RE = re.compile(r"^[0-9. ]{3}/[0-9. ]{3}(?:[A-Za-z0-9.+\-/ ]*)$")
WEATHER_BODY_WITH_IMPLIED_TEMP_RE = re.compile(r"^([0-9. ]{3}/[0-9. ]{3}(?:g\d{3})?)(-?\d{3})(?=[A-Za-z]|$)")


@dataclass
class WxNowReading:
    timestamp: datetime
    weather_body: str
    file_mtime: float
    signature: str


def normalize_weather_body(weather_body: str) -> str:
    """Normalize common WXnow variants into APRS weather body syntax."""
    weather_body = WEATHER_BODY_WITH_IMPLIED_TEMP_RE.sub(r"\1t\2", weather_body, count=1)
    return re.sub(r"([rpP])\d{4,}(?=[A-Za-z]|$)", r"\1...", weather_body)


def format_positionless_weather_body(weather_body: str) -> str:
    """Return APRS101 positionless WX body syntax."""
    match = re.match(r"^([0-9. ]{3})/([0-9. ]{3})(.*)$", weather_body)
    if not match:
        return weather_body
    wind_dir, wind_speed, rest = match.groups()
    if not rest.startswith("g"):
        rest = f"g...{rest}"
    return f"c{wind_dir}s{wind_speed}{rest}"


def parse_wxnow_text(text: str, file_mtime: Optional[float] = None) -> WxNowReading:
    """Parse a two-line wxnow.txt file."""
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    if len(lines) < 2:
        raise ValueError("WXnow.txt must contain a timestamp line and a weather data line.")

    timestamp_text = lines[0]
    parsed_time = None
    for fmt in WXNOW_TIMESTAMP_FORMATS:
        try:
            parsed_time = datetime.strptime(timestamp_text, fmt)
            break
        except ValueError:
            continue
    if parsed_time is None:
        raise ValueError("WXnow.txt timestamp must look like 'Jul 07 2012 14:00'.")

    weather_body = normalize_weather_body(lines[1])
    if any(ord(ch) < 32 or ord(ch) > 126 for ch in weather_body):
        raise ValueError("WXnow.txt weather data must use printable ASCII characters.")
    if len(weather_body) > 100:
        raise ValueError("WXnow.txt weather data is too long for a single APRS packet.")
    if not WEATHER_BODY_RE.match(weather_body):
        raise ValueError("WXnow.txt weather data must start with wind direction/speed, like 292/004.")

    return WxNowReading(
        timestamp=parsed_time,
        weather_body=weather_body,
        file_mtime=float(file_mtime or time.time()),
        signature=f"{timestamp_text}\n{weather_body}",
    )


def format_aprs_lat_lon(lat: float, lon: float) -> tuple[str, str]:
    """Return APRS uncompressed latitude and longitude strings."""
    lat_dir = "N" if lat >= 0 else "S"
    lon_dir = "E" if lon >= 0 else "W"
    lat_abs = abs(lat)
    lon_abs = abs(lon)
    lat_deg = int(lat_abs)
    lon_deg = int(lon_abs)
    lat_min = (lat_abs - lat_deg) * 60
    lon_min = (lon_abs - lon_deg) * 60
    return f"{lat_deg:02d}{lat_min:05.2f}{lat_dir}", f"{lon_deg:03d}{lon_min:05.2f}{lon_dir}"


def build_wxnow_info(config: Config, reading: WxNowReading) -> str:
    """Build the APRS information field for a wxnow.txt reading."""
    wx = config.wxnow
    if wx.include_position:
        timestamp = reading.timestamp.strftime("%d%H%Mz")
        station = config.station
        if station.latitude == 0.0 and station.longitude == 0.0:
            raise ValueError("Set station latitude and longitude before sending positioned WX packets.")
        lat, lon = format_aprs_lat_lon(station.latitude, station.longitude)
        table = (wx.symbol_table or "/")[:1]
        code = (wx.symbol_code or "_")[:1]
        return f"@{timestamp}{lat}{table}{lon}{code}{reading.weather_body}"

    timestamp = reading.timestamp.strftime("%m%d%H%M")
    return f"_{timestamp}{format_positionless_weather_body(reading.weather_body)}"


def build_wxnow_position_info(config: Config) -> str:
    """Build a same-callsign weather-symbol position for positionless WX reports."""
    station = config.station
    if station.latitude == 0.0 and station.longitude == 0.0:
        raise ValueError("Set station latitude and longitude before sending positionless WX packets.")
    lat, lon = format_aprs_lat_lon(station.latitude, station.longitude)
    wx = config.wxnow
    table = (wx.symbol_table or "/")[:1]
    code = (wx.symbol_code or "_")[:1]
    return f"!{lat}{table}{lon}{code}WXnow"


def parse_weather_body_values(reading: WxNowReading) -> dict[str, Any]:
    """Parse common APRS WX body fields into dashboard current conditions."""
    body = reading.weather_body
    values: dict[str, Any] = {
        "time": reading.timestamp.isoformat(),
        "raw": body,
        "source": "wxnow",
    }

    wind = re.match(r"^(?P<dir>[0-9. ]{3})/(?P<speed>[0-9. ]{3})", body)
    if wind:
        try:
            values["wind_direction"] = int(wind.group("dir").strip().replace(".", "") or 0)
        except ValueError:
            pass
        try:
            values["wind_speed_mph"] = int(wind.group("speed").strip().replace(".", "") or 0)
        except ValueError:
            pass

    def field(pattern: str) -> Optional[int]:
        match = re.search(pattern, body)
        if not match:
            return None
        try:
            return int(match.group(1))
        except ValueError:
            return None

    temperature = field(r"t(-?\d{3})")
    if temperature is not None:
        values["temperature"] = temperature
        values["temperature_f"] = temperature
        values["feels_like"] = temperature
        values["feels_like_f"] = temperature

    gust = field(r"g(\d{3})")
    if gust is not None:
        values["wind_gusts_mph"] = gust

    humidity = field(r"h(\d{2})")
    if humidity is not None:
        values["humidity"] = 100 if humidity == 0 else humidity

    pressure = field(r"b(\d{5})")
    if pressure is not None:
        values["pressure"] = pressure / 10.0
        values["pressure_mb"] = pressure / 10.0

    rain_hour = field(r"r(\d{3})")
    if rain_hour is not None:
        values["precipitation_in"] = rain_hour / 100.0
        values["rain"] = rain_hour / 100.0

    return values


class WxNowTransmitter:
    """Polls wxnow.txt and transmits fresh, changed readings."""

    def __init__(self, config: Config, handler):
        self.config = config
        self.handler = handler
        self._last_signature = ""
        self._last_tx = 0.0
        self._last_position_tx = 0.0
        self._last_error = ""
        self._last_reading: Optional[WxNowReading] = None
        self._last_info = ""

    def _station_call(self) -> str:
        base = (self.config.station.callsign or "N0CALL").strip().upper()
        ssid = max(0, min(15, int(self.config.wxnow.ssid)))
        return f"{base}-{ssid}" if ssid else base

    def get_status(self) -> dict:
        wx = self.config.wxnow
        path = Path(wx.file_path).expanduser() if wx.file_path else None
        exists = bool(path and path.exists() and path.is_file())
        age_seconds = None
        stale = False
        if exists:
            age_seconds = max(0.0, time.time() - path.stat().st_mtime)
            stale = age_seconds > max(1, int(wx.max_age_minutes)) * 60

        return {
            "enabled": wx.enabled,
            "configured": bool(wx.file_path),
            "file_path": wx.file_path,
            "file_exists": exists,
            "station": self._station_call(),
            "mode": wx.mode,
            "include_position": wx.include_position,
            "beacon_interval": wx.beacon_interval,
            "max_age_minutes": wx.max_age_minutes,
            "last_transmit": self._last_tx or None,
            "last_position_transmit": self._last_position_tx or None,
            "last_error": self._last_error,
            "last_info": self._last_info,
            "age_seconds": age_seconds,
            "stale": stale,
        }

    def preview(self) -> dict:
        """Build the next WXnow packet(s) without transmitting."""
        wx = self.config.wxnow
        if not wx.file_path:
            raise ValueError("Choose a WXnow.txt file before enabling weather transmit.")

        path = Path(wx.file_path).expanduser()
        if not path.exists() or not path.is_file():
            raise ValueError("WXnow.txt file was not found.")

        stat = path.stat()
        max_age = max(1, int(wx.max_age_minutes)) * 60
        age = time.time() - stat.st_mtime
        if age > max_age:
            raise ValueError(f"WXnow.txt is stale ({int(age // 60)} minutes old).")

        reading = parse_wxnow_text(path.read_text(encoding="ascii", errors="strict"), stat.st_mtime)
        info = build_wxnow_info(self.config, reading)
        position_info = None
        if not wx.include_position:
            now = time.time()
            if not self._last_position_tx or now - self._last_position_tx >= POSITIONLESS_WX_POSITION_INTERVAL:
                position_info = build_wxnow_position_info(self.config)

        return {
            "dry_run": True,
            "info": info,
            "position_info": position_info,
            "station": self._station_call(),
            "mode": (wx.mode or "both").strip().lower(),
            "path": wx.path,
            "age_seconds": age,
            "unchanged": reading.signature == self._last_signature,
        }

    async def transmit_once(self, force: bool = False) -> dict:
        wx = self.config.wxnow
        if not wx.enabled and not force:
            return {"transmitted": False, "message": "WXnow transmit is disabled."}
        if not wx.file_path:
            raise ValueError("Choose a WXnow.txt file before enabling weather transmit.")

        path = Path(wx.file_path).expanduser()
        if not path.exists() or not path.is_file():
            raise ValueError("WXnow.txt file was not found.")

        stat = path.stat()
        max_age = max(1, int(wx.max_age_minutes)) * 60
        age = time.time() - stat.st_mtime
        if age > max_age:
            raise ValueError(f"WXnow.txt is stale ({int(age // 60)} minutes old).")

        reading = parse_wxnow_text(path.read_text(encoding="ascii", errors="strict"), stat.st_mtime)
        if not force and reading.signature == self._last_signature:
            return {"transmitted": False, "message": "WXnow.txt has not changed since the last transmit."}

        position_result = None
        if not wx.include_position:
            position_result = await self._transmit_position_if_needed()

        info = build_wxnow_info(self.config, reading)
        result = await self.handler.transmit_aprs_info(
            source_call=self._station_call(),
            info=info,
            mode=(wx.mode or "both").strip().lower(),
            path=wx.path,
        )

        if not result["can_transmit"]:
            raise ValueError(result["message"])

        self._last_signature = reading.signature
        self._last_reading = reading
        self._last_tx = time.time()
        self._last_info = info
        self._last_error = ""
        if hasattr(self.handler, "record_transmit_history"):
            self.handler.record_transmit_history(
                "wxnow",
                self._station_call(),
                info,
                result["message"],
            )
        return {
            "transmitted": True,
            "message": result["message"],
            "info": info,
            "position_info": position_result.get("info") if position_result else None,
            "station": self._station_call(),
        }

    async def _transmit_position_if_needed(self, force: bool = False) -> Optional[dict]:
        now = time.time()
        if not force and self._last_position_tx and now - self._last_position_tx < POSITIONLESS_WX_POSITION_INTERVAL:
            return None

        wx = self.config.wxnow
        info = build_wxnow_position_info(self.config)
        result = await self.handler.transmit_aprs_info(
            source_call=self._station_call(),
            info=info,
            mode=(wx.mode or "both").strip().lower(),
            path=wx.path,
        )
        if not result["can_transmit"]:
            raise ValueError(result["message"])

        self._last_position_tx = now
        logger.info("WXnow position TX: %s", result.get("message"))
        return {"info": info, "message": result.get("message")}

    async def loop(self):
        await asyncio.sleep(15)
        while True:
            try:
                interval = max(60, int(self.config.wxnow.beacon_interval or 600))
                if not self.config.wxnow.enabled:
                    await asyncio.sleep(60)
                    continue
                try:
                    result = await self.transmit_once(force=False)
                    if result.get("transmitted"):
                        logger.info("WXnow TX: %s", result.get("message"))
                    else:
                        logger.debug("WXnow skipped: %s", result.get("message"))
                except Exception as exc:
                    self._last_error = str(exc)
                    logger.warning("WXnow transmit skipped: %s", exc)
                await asyncio.sleep(interval)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                self._last_error = str(exc)
                logger.error("WXnow loop error: %s", exc, exc_info=True)
                await asyncio.sleep(60)
