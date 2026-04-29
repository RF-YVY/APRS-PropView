"""Weather data provider using Open-Meteo (current conditions) and NWS (alerts).

All APIs used are free and require no API key:
  - Open-Meteo: https://open-meteo.com/
  - NWS:        https://api.weather.gov/
  - Zippopotam: http://api.zippopotam.us/  (zip → lat/lon)
"""

import asyncio
import json
import logging
import math
import re
import time
import urllib.request
import urllib.error
from typing import Optional, Dict, Any, List, Tuple

from server.config import Config

logger = logging.getLogger("propview.weather")

# ── WMO Weather Code descriptions ────────────────────────────────────

WMO_CODES: Dict[int, Tuple[str, str]] = {
    0:  ("Clear sky", "☀️"),
    1:  ("Mainly clear", "🌤️"),
    2:  ("Partly cloudy", "⛅"),
    3:  ("Overcast", "☁️"),
    45: ("Fog", "🌫️"),
    48: ("Rime fog", "🌫️"),
    51: ("Light drizzle", "🌦️"),
    53: ("Moderate drizzle", "🌦️"),
    55: ("Dense drizzle", "🌧️"),
    56: ("Light freezing drizzle", "🌧️"),
    57: ("Dense freezing drizzle", "🌧️"),
    61: ("Slight rain", "🌦️"),
    63: ("Moderate rain", "🌧️"),
    65: ("Heavy rain", "🌧️"),
    66: ("Light freezing rain", "🌧️"),
    67: ("Heavy freezing rain", "🌧️"),
    71: ("Slight snow", "🌨️"),
    73: ("Moderate snow", "🌨️"),
    75: ("Heavy snow", "❄️"),
    77: ("Snow grains", "❄️"),
    80: ("Slight rain showers", "🌦️"),
    81: ("Moderate rain showers", "🌧️"),
    82: ("Violent rain showers", "🌧️"),
    85: ("Slight snow showers", "🌨️"),
    86: ("Heavy snow showers", "❄️"),
    95: ("Thunderstorm", "⛈️"),
    96: ("Thunderstorm w/ slight hail", "⛈️"),
    99: ("Thunderstorm w/ heavy hail", "⛈️"),
}

# NWS severity mapping
NWS_SEVERITY = {
    "Extreme":  "warning",
    "Severe":   "warning",
    "Moderate": "watch",
    "Minor":    "watch",
    "Unknown":  "watch",
}

# US Zip code regex
_ZIP_RE = re.compile(r"^\d{5}$")
# ICAO code regex (4 uppercase letters)
_ICAO_RE = re.compile(r"^[A-Z]{4}$")


def _classify_alert_categories(event: str, alert_type: str) -> List[str]:
    """Return coarse map overlay categories for a weather alert."""
    categories: List[str] = []
    event_lower = (event or "").lower()

    if alert_type == "warning":
        categories.append("warnings")
    elif alert_type == "watch":
        categories.append("watches")

    if any(term in event_lower for term in ("flood", "flash flood", "coastal flood")):
        categories.append("flood")
    if any(term in event_lower for term in ("winter", "snow", "blizzard", "ice", "freeze", "freezing", "sleet")):
        categories.append("winter")
    if "marine" in event_lower:
        categories.append("marine")
    if any(term in event_lower for term in ("fire", "red flag", "heat")):
        categories.append("fire_heat")

    if not categories:
        categories.append("other")

    return list(dict.fromkeys(categories))


def _sync_http_get(url: str, timeout: int = 10, retries: int = 1) -> Optional[Dict]:
    """Synchronous HTTP GET returning parsed JSON, or None on failure.

    Retries on timeout/connection errors with exponential backoff.
    """
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "APRSPropView/1.0 (amateur-radio-weather-app)",
            "Accept": "application/geo+json, application/json",
        },
    )
    last_err = None
    for attempt in range(1 + retries):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError,
                OSError, TimeoutError) as e:
            last_err = e
            if attempt < retries:
                import time as _time
                _time.sleep(2 ** attempt)  # 1s, 2s backoff
                logger.debug(f"Retrying ({attempt + 1}/{retries}) {url}")
    logger.warning(f"HTTP GET failed for {url}: {last_err}")
    return None


async def _async_http_get(url: str, timeout: int = 10, retries: int = 1) -> Optional[Dict]:
    """Run a synchronous HTTP GET on an executor to keep the event loop free."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None, _sync_http_get, url, timeout, retries
    )


# ── Geocoding helpers ─────────────────────────────────────────────────

async def _resolve_zip(zip_code: str) -> Optional[Tuple[float, float, str]]:
    """Resolve a US zip code → (lat, lon, place_name)."""
    data = await _async_http_get(f"http://api.zippopotam.us/us/{zip_code}")
    if not data or "places" not in data or len(data["places"]) == 0:
        return None
    p = data["places"][0]
    lat = float(p.get("latitude", 0))
    lon = float(p.get("longitude", 0))
    name = f"{p.get('place name', '')}, {p.get('state abbreviation', '')}"
    return lat, lon, name.strip(", ")


async def _resolve_icao(icao: str) -> Optional[Tuple[float, float, str]]:
    """Resolve an ICAO airport code → (lat, lon, station_name) via NWS."""
    data = await _async_http_get(
        f"https://api.weather.gov/stations/{icao.upper()}"
    )
    if not data or "geometry" not in data:
        return None
    coords = data["geometry"].get("coordinates", [])
    if len(coords) < 2:
        return None
    lon, lat = coords[0], coords[1]
    name = data.get("properties", {}).get("name", icao.upper())
    return lat, lon, name


async def resolve_location(code: str) -> Optional[Dict[str, Any]]:
    """Resolve a zip code or ICAO code to lat/lon/name.

    Returns: {"latitude": float, "longitude": float, "name": str} or None.
    """
    code = code.strip()
    if _ZIP_RE.match(code):
        result = await _resolve_zip(code)
    elif _ICAO_RE.match(code.upper()):
        result = await _resolve_icao(code.upper())
    else:
        return None

    if not result:
        return None

    lat, lon, name = result
    return {"latitude": lat, "longitude": lon, "name": name}


async def resolve_alert_scope_from_point(lat: float, lon: float) -> Optional[Dict[str, Any]]:
    """Resolve county and forecast zone identifiers for a point via the NWS points API."""
    data = await _async_http_get(f"https://api.weather.gov/points/{lat:.4f},{lon:.4f}", timeout=15, retries=1)
    if not data:
        return None

    props = data.get("properties", {})

    def _last_segment(url: str) -> str:
        return (url or "").rstrip("/").split("/")[-1]

    return {
        "county": _last_segment(props.get("county", "")),
        "forecast_zone": _last_segment(props.get("forecastZone", "")),
        "fire_zone": _last_segment(props.get("fireWeatherZone", "")),
        "grid_id": props.get("gridId", ""),
    }


# ── Current weather from Open-Meteo ──────────────────────────────────

async def fetch_current_weather(lat: float, lon: float) -> Optional[Dict[str, Any]]:
    """Fetch current weather conditions from Open-Meteo.

    Returns a dict with temperature, humidity, wind, conditions, etc.
    """
    url = (
        f"https://api.open-meteo.com/v1/forecast?"
        f"latitude={lat:.4f}&longitude={lon:.4f}"
        f"&current=temperature_2m,relative_humidity_2m,apparent_temperature,"
        f"precipitation,rain,showers,snowfall,weather_code,cloud_cover,"
        f"pressure_msl,surface_pressure,wind_speed_10m,wind_direction_10m,"
        f"wind_gusts_10m,is_day"
        f"&temperature_unit=fahrenheit"
        f"&wind_speed_unit=mph"
        f"&precipitation_unit=inch"
        f"&timezone=auto"
    )
    data = await _async_http_get(url)
    if not data or "current" not in data:
        return None

    c = data["current"]
    code = c.get("weather_code", 0)
    desc, icon = WMO_CODES.get(code, ("Unknown", "❓"))

    # Determine if thunderstorm conditions exist (codes 95-99)
    is_thunderstorm = code >= 95

    return {
        "temperature_f": c.get("temperature_2m"),
        "feels_like_f": c.get("apparent_temperature"),
        "humidity": c.get("relative_humidity_2m"),
        "wind_speed_mph": c.get("wind_speed_10m"),
        "wind_direction": c.get("wind_direction_10m"),
        "wind_gusts_mph": c.get("wind_gusts_10m"),
        "pressure_mb": c.get("pressure_msl"),
        "surface_pressure_mb": c.get("surface_pressure"),
        "cloud_cover": c.get("cloud_cover"),
        "precipitation_in": c.get("precipitation"),
        "weather_code": code,
        "description": desc,
        "icon": icon,
        "is_day": c.get("is_day", 1) == 1,
        "is_thunderstorm": is_thunderstorm,
        "timestamp": time.time(),
        "timezone": data.get("timezone", ""),
    }


# ── Tropospheric Ducting Index ───────────────────────────────────────

async def fetch_ducting_data(lat: float, lon: float) -> Optional[Dict[str, Any]]:
    """Fetch atmospheric data and compute a VHF ducting probability index.

    Uses Open-Meteo pressure-level API for temperature at 850 hPa and surface,
    plus surface humidity and pressure trends. The ducting index (0-100) estimates
    the likelihood of tropospheric ducting conditions.

    Key factors:
    - Temperature inversion (surface temp < 850 hPa temp, or small lapse rate)
    - High surface pressure (> 1020 mb) and rising trend
    - High relative humidity (moisture gradient aids ducting)
    - Low wind speed (stable atmosphere)
    """
    # Fetch current conditions + hourly pressure for trend + 850 hPa temp
    url = (
        f"https://api.open-meteo.com/v1/forecast?"
        f"latitude={lat:.4f}&longitude={lon:.4f}"
        f"&current=temperature_2m,relative_humidity_2m,pressure_msl,"
        f"surface_pressure,wind_speed_10m"
        f"&hourly=pressure_msl,temperature_850hPa"
        f"&past_hours=6&forecast_hours=1"
        f"&temperature_unit=fahrenheit"
        f"&wind_speed_unit=mph"
        f"&timezone=auto"
    )
    data = await _async_http_get(url, timeout=15)
    if not data or "current" not in data:
        return None

    c = data["current"]
    surface_temp_f = c.get("temperature_2m")
    humidity = c.get("relative_humidity_2m")
    pressure_msl = c.get("pressure_msl")
    wind_speed = c.get("wind_speed_10m", 0)

    # Extract 850 hPa temperature from hourly data (most recent value)
    temp_850 = None
    hourly = data.get("hourly", {})
    temps_850 = hourly.get("temperature_850hPa", [])
    if temps_850:
        # Get the last non-null value
        for t in reversed(temps_850):
            if t is not None:
                temp_850 = t
                break

    # Compute pressure trend from hourly MSL pressure (last 6 hours)
    pressure_trend = None
    pressures = hourly.get("pressure_msl", [])
    if len(pressures) >= 3:
        valid_pressures = [p for p in pressures if p is not None]
        if len(valid_pressures) >= 2:
            pressure_trend = valid_pressures[-1] - valid_pressures[0]

    # ── Ducting index calculation ──────────────────────────────
    score = 0.0
    factors = {}

    # 1. Temperature inversion check (0-35 points)
    # Normal lapse rate: surface should be warmer than 850 hPa
    # If the difference is small or inverted, ducting is more likely
    inversion_detected = False
    if surface_temp_f is not None and temp_850 is not None:
        # Convert both to same unit for comparison (both already Fahrenheit)
        lapse = surface_temp_f - temp_850
        # Normal lapse: surface 20-40°F warmer than 850 hPa (~5000ft)
        # Inversion: surface cooler than or close to 850 hPa
        if lapse < 0:
            # True inversion
            score += 35
            inversion_detected = True
            factors["inversion"] = f"Strong inversion (lapse={lapse:.1f}°F)"
        elif lapse < 10:
            score += 25
            inversion_detected = True
            factors["inversion"] = f"Weak inversion (lapse={lapse:.1f}°F)"
        elif lapse < 20:
            score += 10
            factors["inversion"] = f"Reduced lapse rate ({lapse:.1f}°F)"
        else:
            factors["inversion"] = f"Normal lapse rate ({lapse:.1f}°F)"

    # 2. Surface pressure (0-25 points)
    # High pressure systems favor ducting
    if pressure_msl is not None:
        if pressure_msl >= 1030:
            score += 25
            factors["pressure"] = f"Very high ({pressure_msl:.0f} mb)"
        elif pressure_msl >= 1025:
            score += 20
            factors["pressure"] = f"High ({pressure_msl:.0f} mb)"
        elif pressure_msl >= 1020:
            score += 12
            factors["pressure"] = f"Above average ({pressure_msl:.0f} mb)"
        elif pressure_msl >= 1013:
            score += 5
            factors["pressure"] = f"Normal ({pressure_msl:.0f} mb)"
        else:
            factors["pressure"] = f"Low ({pressure_msl:.0f} mb)"

    # 3. Pressure trend — rising is favorable (0-15 points)
    if pressure_trend is not None:
        if pressure_trend > 3:
            score += 15
            factors["trend"] = f"Rising fast (+{pressure_trend:.1f} mb/6h)"
        elif pressure_trend > 1:
            score += 10
            factors["trend"] = f"Rising (+{pressure_trend:.1f} mb/6h)"
        elif pressure_trend > 0:
            score += 5
            factors["trend"] = f"Slight rise (+{pressure_trend:.1f} mb/6h)"
        elif pressure_trend > -1:
            factors["trend"] = f"Steady ({pressure_trend:+.1f} mb/6h)"
        else:
            factors["trend"] = f"Falling ({pressure_trend:+.1f} mb/6h)"

    # 4. Humidity — moderate to high favors ducting (0-15 points)
    if humidity is not None:
        if humidity >= 80:
            score += 15
            factors["humidity"] = f"High ({humidity}%)"
        elif humidity >= 60:
            score += 10
            factors["humidity"] = f"Moderate ({humidity}%)"
        elif humidity >= 40:
            score += 5
            factors["humidity"] = f"Low-moderate ({humidity}%)"
        else:
            factors["humidity"] = f"Low ({humidity}%)"

    # 5. Wind speed — calm conditions favor stable layers (0-10 points)
    if wind_speed is not None:
        if wind_speed < 5:
            score += 10
            factors["wind"] = f"Calm ({wind_speed:.0f} mph)"
        elif wind_speed < 10:
            score += 7
            factors["wind"] = f"Light ({wind_speed:.0f} mph)"
        elif wind_speed < 15:
            score += 3
            factors["wind"] = f"Moderate ({wind_speed:.0f} mph)"
        else:
            factors["wind"] = f"Strong ({wind_speed:.0f} mph)"

    score = min(score, 100)

    # Classify level
    if score >= 70:
        level = "high"
    elif score >= 45:
        level = "moderate"
    elif score >= 20:
        level = "low"
    else:
        level = "minimal"

    return {
        "ducting_index": round(score, 1),
        "level": level,
        "inversion_detected": inversion_detected,
        "factors": factors,
        "surface_temp_f": surface_temp_f,
        "temp_850hPa_f": temp_850,
        "pressure_mb": pressure_msl,
        "pressure_trend": round(pressure_trend, 2) if pressure_trend is not None else None,
        "humidity": humidity,
        "wind_speed_mph": wind_speed,
        "timestamp": time.time(),
    }


# ── NWS Severe Weather Alerts ────────────────────────────────────────

def _wind_direction_label(degrees: float) -> str:
    """Convert wind direction degrees to compass label."""
    dirs = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
            "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]
    idx = round(degrees / 22.5) % 16
    return dirs[idx]


def _haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate distance between two points in miles."""
    R = 3958.8  # Earth radius in miles
    lat1_r, lat2_r = math.radians(lat1), math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(lat1_r) * math.cos(lat2_r) * math.sin(dlon / 2) ** 2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


async def fetch_nws_alerts(
    lat: float,
    lon: float,
    range_miles: int = 50,
    scope_mode: str = "point",
    scope_zone: str = "",
) -> List[Dict[str, Any]]:
    """Fetch active NWS weather alerts near a location.

    Returns a list of alert dicts with severity classification:
      - 'warning' (red) — Warnings, Extreme/Severe
      - 'watch'   (orange) — Watches, Advisories, Moderate/Minor
    """
    # NWS alerts by point — returns alerts whose zone/county covers the point
    if scope_mode == "county_zone" and scope_zone:
        url = f"https://api.weather.gov/alerts/active?zone={scope_zone}"
    else:
        url = f"https://api.weather.gov/alerts/active?point={lat:.4f},{lon:.4f}"
    data = await _async_http_get(url, timeout=30, retries=2)

    alerts = []

    if data and "features" in data:
        for feature in data["features"]:
            props = feature.get("properties", {})

            event = props.get("event", "Unknown Event")
            severity = props.get("severity", "Unknown")
            certainty = props.get("certainty", "Unknown")
            urgency = props.get("urgency", "Unknown")
            headline = props.get("headline", "")
            description = props.get("description", "")
            instruction = props.get("instruction", "")
            sender_name = props.get("senderName", "")
            effective = props.get("effective", "")
            expires = props.get("expires", "")
            status = props.get("status", "")

            # Skip test/exercise alerts
            if status in ("Test", "Exercise"):
                continue

            # Classify severity
            alert_type = "warning" if severity in ("Extreme", "Severe") else "watch"

            # Check if event name contains key terms
            event_lower = event.lower()
            if "warning" in event_lower:
                alert_type = "warning"
            elif "watch" in event_lower or "advisory" in event_lower:
                alert_type = "watch"

            alerts.append({
                "id": feature.get("id") or props.get("id") or "",
                "event": event,
                "severity": severity,
                "alert_type": alert_type,     # 'warning' or 'watch'
                "certainty": certainty,
                "urgency": urgency,
                "headline": headline,
                "description": description[:6000],
                "instruction": instruction[:3000] if instruction else "",
                "sender": sender_name,
                "effective": effective,
                "expires": expires,
                "area_desc": props.get("areaDesc", ""),
                "geometry": feature.get("geometry"),
                "overlay_categories": _classify_alert_categories(event, alert_type),
            })

    # Sort: warnings first, then watches
    alerts.sort(key=lambda a: (0 if a["alert_type"] == "warning" else 1))

    return alerts


# ── Weather Manager (caching + periodic refresh) ─────────────────────

class WeatherManager:
    """Manages weather data fetching with caching to avoid excessive API calls."""

    def __init__(self, config: Config):
        self.config = config
        self._location: Optional[Dict[str, Any]] = None  # resolved lat/lon/name
        self._current: Optional[Dict[str, Any]] = None
        self._alerts: List[Dict[str, Any]] = []
        self._ducting: Optional[Dict[str, Any]] = None
        self._last_fetch: float = 0
        self._last_alert_fetch: float = 0
        self._last_ducting_fetch: float = 0
        self._location_code_resolved: str = ""  # last code we resolved
        self._alert_scope_info: Optional[Dict[str, Any]] = None
        self._elevated_polling_until: float = 0

    @property
    def is_configured(self) -> bool:
        return bool(
            self.config.weather.enabled
            and self.config.weather.location_code
        )

    async def resolve_and_set_location(self, code: str) -> Optional[Dict[str, Any]]:
        """Resolve a location code and cache the result."""
        result = await resolve_location(code)
        if result:
            self._location = result
            self._location_code_resolved = code
            # Reset caches to force fresh fetch
            self._last_fetch = 0
            self._last_alert_fetch = 0
            self._alert_scope_info = None
            logger.info(f"Weather location resolved: {result['name']} "
                        f"({result['latitude']:.4f}, {result['longitude']:.4f})")
        return result

    async def get_alert_scope_info(self, force: bool = False) -> Optional[Dict[str, Any]]:
        """Resolve point-based NWS county/zone metadata for UI helpers."""
        if not self.is_configured:
            return None

        if self.config.weather.location_code != self._location_code_resolved:
            await self.resolve_and_set_location(self.config.weather.location_code)

        if not self._location:
            return None

        if self._alert_scope_info and not force:
            return self._alert_scope_info

        self._alert_scope_info = await resolve_alert_scope_from_point(
            self._location["latitude"],
            self._location["longitude"],
        )
        return self._alert_scope_info

    def _get_alert_poll_interval_seconds(self) -> int:
        normal = 300
        if (
            self.config.weather.elevated_alert_polling_enabled
            and self._elevated_polling_until > time.time()
        ):
            return max(30, int(self.config.weather.elevated_alert_polling_seconds))
        return normal

    def _alerts_trigger_elevated_mode(self, alerts: List[Dict[str, Any]]) -> bool:
        if not self.config.weather.elevated_alert_polling_enabled:
            return False

        trigger_events = {
            (event or "").strip().lower()
            for event in self.config.weather.elevated_trigger_events
            if (event or "").strip()
        }
        if not trigger_events:
            return False

        for alert in alerts or []:
            event = (alert.get("event", "") or "").strip().lower()
            if event in trigger_events:
                return True
        return False

    async def get_current_weather(self, force: bool = False) -> Optional[Dict[str, Any]]:
        """Get current weather, fetching from API if cache is stale."""
        if not self.is_configured:
            return None

        # Re-resolve location if code changed
        if self.config.weather.location_code != self._location_code_resolved:
            await self.resolve_and_set_location(self.config.weather.location_code)

        if not self._location:
            return None

        refresh = self.config.weather.refresh_minutes * 60
        if not force and self._current and (time.time() - self._last_fetch < refresh):
            return self._current

        weather = await fetch_current_weather(
            self._location["latitude"],
            self._location["longitude"],
        )
        if weather:
            weather["location_name"] = self._location.get("name", "")
            weather["location_code"] = self.config.weather.location_code
            weather["wind_direction_label"] = _wind_direction_label(
                weather.get("wind_direction", 0) or 0
            )
            self._current = weather
            self._last_fetch = time.time()

        return self._current

    async def get_alerts(self, force: bool = False) -> List[Dict[str, Any]]:
        """Get NWS alerts, fetching from API if cache is stale."""
        if not self.is_configured or not self._location:
            return []

        cache_seconds = self._get_alert_poll_interval_seconds()
        if not force and self._alerts is not None and (time.time() - self._last_alert_fetch < cache_seconds):
            return self._alerts

        alerts = await fetch_nws_alerts(
            self._location["latitude"],
            self._location["longitude"],
            self.config.weather.alert_range_miles,
            self.config.weather.alert_scope_mode,
            (self.config.weather.alert_scope_zone or "").strip().upper(),
        )
        self._alerts = alerts
        self._last_alert_fetch = time.time()
        if self._alerts_trigger_elevated_mode(alerts):
            self._elevated_polling_until = time.time() + max(1, int(self.config.weather.elevated_alert_cooldown_minutes)) * 60
        return self._alerts

    async def get_ducting(self, force: bool = False) -> Optional[Dict[str, Any]]:
        """Get ducting index data, fetching from API if cache is stale."""
        if not self.is_configured or not self._location:
            return None

        # Refresh ducting data every 15 minutes
        if not force and self._ducting and (time.time() - self._last_ducting_fetch < 900):
            return self._ducting

        ducting = await fetch_ducting_data(
            self._location["latitude"],
            self._location["longitude"],
        )
        if ducting:
            self._ducting = ducting
            self._last_ducting_fetch = time.time()

        return self._ducting

    async def get_all(self, force: bool = False) -> Dict[str, Any]:
        """Get combined weather + alerts + ducting payload."""
        current = await self.get_current_weather(force=force)
        alerts = await self.get_alerts(force=force)
        ducting = await self.get_ducting(force=force)

        return {
            "enabled": self.config.weather.enabled,
            "configured": self.is_configured,
            "refresh_minutes": self.config.weather.refresh_minutes,
            "location": self._location,
            "current": current,
            "alerts": alerts,
            "ducting": ducting,
            "alert_count": len(alerts),
            "warning_count": sum(1 for a in alerts if a["alert_type"] == "warning"),
            "watch_count": sum(1 for a in alerts if a["alert_type"] == "watch"),
            "alert_polling": {
                "current_interval_seconds": self._get_alert_poll_interval_seconds(),
                "elevated_active": self._elevated_polling_until > time.time(),
                "elevated_until": self._elevated_polling_until or None,
                "scope_mode": self.config.weather.alert_scope_mode,
                "scope_zone": self.config.weather.alert_scope_zone,
            },
            "map_overlays": {
                "radar_enabled": self.config.weather.radar_enabled,
                "radar_provider": self.config.weather.radar_provider,
                "radar_opacity": self.config.weather.radar_opacity,
                "radar_animate": self.config.weather.radar_animate,
                "alert_overlay_enabled": self.config.weather.alert_overlay_enabled,
                "alert_overlay_groups": self.config.weather.alert_overlay_groups,
            },
        }
