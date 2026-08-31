"""FastAPI web application — serves UI and WebSocket endpoints."""

import asyncio
import base64
import binascii
import hashlib
import mimetypes
import os
import re
import shutil
import subprocess
import time
import logging
import tempfile
import urllib.parse
import urllib.request
import math
from pathlib import Path
from typing import Optional, Dict, Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query, Request, BackgroundTasks
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from server.config import (
    Config, StationConfig, DigiConfig, IGateConfig, APRSISConfig,
    KISSSerialConfig, KISSTCPConfig, RFPortConfig, WatchedPathConfig, WebConfig, DatabaseConfig, TrackingConfig,
    MessagingConfig, AlertsConfig, PropagationConfig, WeatherConfig, GPSConfig, MQTTConfig,
)
from server.callbook import CallbookCredentials, lookup_callsign
from server.browser_launch import available_browsers, browser_ids
from server.database import Database
from server.station_tracker import StationTracker
from server.websocket_manager import WebSocketManager
from server.packet_handler import PacketHandler
from server.analytics import AnalyticsEngine
from server.alerts import AlertConfig, AlertManager
from server.aprs_is import APRSISClient
from server.aprs_parser import parse_packet
from server.weather import WeatherManager
from server.update_checker import UpdateChecker, _github_ssl_context

logger = logging.getLogger("propview.app")

# Support PyInstaller frozen builds
import sys as _sys
if getattr(_sys, 'frozen', False):
    STATIC_DIR = Path(_sys._MEIPASS) / "static"
else:
    STATIC_DIR = Path(__file__).parent.parent / "static"
RUNTIME_DATA_DIR = Path(os.environ.get("PROPVIEW_DATA_DIR") or Path.cwd()).expanduser()
USER_AUDIO_DIR = Path(os.environ.get("PROPVIEW_USER_AUDIO_DIR") or (RUNTIME_DATA_DIR / "user_audio")).expanduser()
ALERT_AUDIO_KEYS = {
    "my_station_opening": "audio_my_station_opening_file",
    "regional_watch": "audio_regional_watch_file",
    "first_heard": "audio_first_heard_file",
    "anomaly": "audio_anomaly_file",
    "sporadic_e": "audio_sporadic_e_file",
    "message_received": "audio_message_received_file",
    "weather_warning": "audio_weather_warning_file",
    "weather_watch": "audio_weather_watch_file",
}
ALERT_AUDIO_EXTS = {".wav", ".mp3"}
MAX_ALERT_AUDIO_BYTES = 15 * 1024 * 1024
MAP_TILE_CACHE_DIR = Path(os.environ.get("PROPVIEW_MAP_TILE_CACHE_DIR") or (RUNTIME_DATA_DIR / "map_tile_cache")).expanduser()
MAX_TILE_CACHE_REQUEST = 800

# ── Validation helpers ──────────────────────────────────────────────

# APRS station identifier base. Keep this deliberately country-neutral;
# APRS-IS validates account/passcode authority, while the app only guards
# against characters that cannot be represented safely in APRS packets.
_STATION_CALLSIGN_RE = re.compile(r'^[A-Z0-9]{1,9}$')
_MESSAGE_ADDRESSEE_RE = re.compile(r'^[A-Z0-9][A-Z0-9-]{0,8}$')
_HOSTNAME_RE = re.compile(r'^[A-Za-z0-9._-]{1,253}$')
_SAFE_PATH_RE = re.compile(r'^[A-Za-z0-9._-]{1,100}$')
_FILTER_TOKEN_RE = re.compile(r'^-?[a-z]{1,2}/[!-~]+$', re.IGNORECASE)
_GPS_SOURCE_VALUES = {"browser", "self_packet", "nmea_serial", "nmea_tcp", "nmea_udp", "gpsd", "any"}
_TILE_URL_TOKENS = ("{z}", "{x}", "{y}")
# Disallowed callsigns (common placeholders)
_BLOCKED_CALLSIGNS = {'N0CALL', 'NOCALL', 'MYCALL', 'TEST'}
_INVALID_CALLSIGN_MESSAGE = "Invalid callsign format. Use 1-9 letters/numbers; APRS-IS will validate your account when connecting."
_IGATE_CALLSIGN_MESSAGE = "IGate requires your assigned callsign. Change your callsign from the default."
_IGATE_PASSCODE_MESSAGE = "RF\u2192APRS-IS gating requires a valid APRS-IS passcode. Read-only (passcode -1) cannot inject packets."


def _rf_ports_signature(ports) -> tuple:
    """Return the restart-relevant RF port configuration."""
    return tuple(
        (
            port.name,
            bool(port.enabled),
            port.type,
            port.port,
            int(port.baudrate),
            port.host,
            int(port.tcp_port),
            port.protocol,
            port.mode,
            port.flow_control,
            port.init_profile,
            port.init_commands,
            bool(port.rx_only_rf),
            bool(port.rx_only_is),
        )
        for port in ports
    )


def _container_env_override_warnings(body: Dict[str, Any]) -> list[str]:
    """Describe saved settings that will be replaced by container env on restart."""
    if not isinstance(body, dict):
        return []

    checks = [
        ("station", "station identity/location", ("PROPVIEW_CALLSIGN", "PROPVIEW_SSID", "PROPVIEW_LATITUDE", "PROPVIEW_LONGITUDE")),
        ("web", "web host/port/browser/update checks", ("PROPVIEW_HOST", "PROPVIEW_PORT", "PROPVIEW_LAUNCH_BROWSER", "PROPVIEW_UPDATE_CHECKS")),
        ("database", "database path", ("PROPVIEW_DB",)),
        ("aprs_is", "APRS-IS enabled state", ("PROPVIEW_APRS_IS_ENABLED",)),
        ("kiss_tcp", "legacy KISS TCP input", ("PROPVIEW_KISS_TCP_ENABLED", "PROPVIEW_KISS_TCP_HOST", "PROPVIEW_KISS_TCP_PORT")),
        ("rf_ports", "RF ports", ("PROPVIEW_KISS_TCP_ENABLED", "PROPVIEW_KISS_TCP_HOST", "PROPVIEW_KISS_TCP_PORT")),
    ]
    warnings = []
    for section, label, env_names in checks:
        if section not in body:
            continue
        active = [name for name in env_names if os.environ.get(name) is not None]
        if active:
            warnings.append(f"{label} is controlled at startup by {', '.join(active)}")
    return warnings


def _is_valid_message_addressee(value: str) -> bool:
    """Validate the APRS message addressee field.

    APRS message addressees are a 9-character padded field. They are often
    callsigns, but can also be tactical or gateway addressees, so this is
    intentionally broader than the station callsign validator.
    """
    addressee = (value or "").strip().upper()
    if not _MESSAGE_ADDRESSEE_RE.fullmatch(addressee):
        return False
    if addressee.startswith("-") or addressee.endswith("-"):
        return False
    return True


def _is_valid_station_callsign(value: str) -> bool:
    """Validate only APRS-safe station identifier shape, not license format."""
    call = (value or "").strip().upper()
    return bool(_STATION_CALLSIGN_RE.fullmatch(call))


def _mask_passcode(passcode: str) -> str:
    """Mask passcode for API responses — show only last char."""
    if not passcode or passcode == "-1":
        return passcode
    return "*" * (len(passcode) - 1) + passcode[-1]


def _merge_secret_value(current: str, submitted: Any, *, submitted_present: bool) -> str:
    """Merge password-like settings from the UI."""
    if not submitted_present:
        return current
    value = "" if submitted is None else str(submitted)
    if "*" in value:
        return current
    return value


def _clean_aprs_object_item(item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Normalize a user-created APRS object/item config entry."""
    def as_bool(value: Any, default: bool = False) -> bool:
        if isinstance(value, bool):
            return value
        if value is None:
            return default
        return str(value).strip().lower() in {"1", "true", "yes", "on", "enabled"}

    try:
        name = str(item.get("name", "")).strip().upper()[:9]
        if not name:
            return None
        scope = str(item.get("scope", "global")).strip().lower()
        if scope not in {"private", "local", "global"}:
            scope = "global"
        mode = str(item.get("mode", "")).strip().lower()
        if mode not in {"", "both", "rf", "aprs_is"}:
            mode = ""
        return {
            "name": name,
            "enabled": as_bool(item.get("enabled"), True),
            "active": as_bool(item.get("active", item.get("live")), True),
            "permanent": as_bool(item.get("permanent"), False),
            "scope": scope,
            "latitude": float(item.get("latitude", 0)),
            "longitude": float(item.get("longitude", 0)),
            "symbol_table": (str(item.get("symbol_table", "/")) or "/")[:1],
            "symbol_code": (str(item.get("symbol_code", "\\")) or "\\")[:1],
            "overlay": (str(item.get("overlay", "")) or "")[:1],
            "speed_mph": max(0, int(float(item.get("speed_mph", 0) or 0))),
            "course_deg": int(float(item.get("course_deg", 0) or 0)) % 360,
            "signpost": str(item.get("signpost", "")).strip()[:20],
            "frequency": str(item.get("frequency", "")).strip()[:12],
            "duplex": str(item.get("duplex", "")).strip()[:3],
            "tone": str(item.get("tone", "")).strip()[:8],
            "qru": str(item.get("qru", "")).strip().upper()[:12],
            "path": str(item.get("path", "")).strip()[:40],
            "mode": mode,
            "comment": str(item.get("comment", "")).strip()[:80],
        }
    except (TypeError, ValueError):
        return None


def _safe_alert_audio_filename(name: str) -> str:
    stem = Path(name or "alert").stem
    ext = Path(name or "").suffix.lower()
    safe_stem = re.sub(r"[^A-Za-z0-9._-]+", "_", stem).strip("._-")[:60] or "alert"
    return f"{safe_stem}{ext}"


def _alert_audio_url(filename: str) -> str:
    if not filename:
        return ""
    return f"/api/alert-audio/file/{urllib.parse.quote(filename)}"


def _default_tile_url() -> str:
    return "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"


def _tile_source_config(config: Config) -> Dict[str, Any]:
    source = (config.web.map_tile_source or "osm").strip().lower()
    if source == "custom" and config.web.map_tile_url:
        return {
            "url": config.web.map_tile_url,
            "attribution": config.web.map_tile_attribution or "",
            "max_zoom": int(config.web.map_tile_max_zoom or 19),
        }
    return {
        "url": _default_tile_url(),
        "attribution": "&copy; OpenStreetMap contributors",
        "max_zoom": 19,
    }


def _tile_cache_key(tile_url: str) -> str:
    return hashlib.sha256(tile_url.encode("utf-8")).hexdigest()[:16]


def _tile_cache_path(tile_url: str, z: int, x: int, y: int) -> Path:
    suffix = ".png"
    parsed_suffix = Path(urllib.parse.urlparse(tile_url).path).suffix.lower()
    if parsed_suffix in {".png", ".jpg", ".jpeg", ".webp"}:
        suffix = parsed_suffix
    return MAP_TILE_CACHE_DIR / _tile_cache_key(tile_url) / str(z) / str(x) / f"{y}{suffix}"


def _tile_url_for(tile_url: str, z: int, x: int, y: int) -> str:
    subdomains = "abc"
    subdomain = subdomains[(x + y) % len(subdomains)]
    return (
        tile_url
        .replace("{s}", subdomain)
        .replace("{z}", str(z))
        .replace("{x}", str(x))
        .replace("{y}", str(y))
    )


def _download_tile(tile_url: str, z: int, x: int, y: int) -> Optional[Path]:
    path = _tile_cache_path(tile_url, z, x, y)
    if path.exists() and path.stat().st_size > 0:
        return path

    url = _tile_url_for(tile_url, z, x, y)
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "APRSPropView tile-cache",
            "Referer": "http://localhost/",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            status = getattr(resp, "status", 200)
            if status >= 400:
                return None
            data = resp.read(1024 * 1024)
    except Exception:
        return None

    if not data:
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(data)
    tmp.replace(path)
    return path


def _lon_to_tile_x(lon: float, z: int) -> int:
    return int((lon + 180.0) / 360.0 * (1 << z))


def _lat_to_tile_y(lat: float, z: int) -> int:
    lat = max(-85.05112878, min(85.05112878, lat))
    lat_rad = math.radians(lat)
    return int((1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * (1 << z))


def _tile_coords_for_bounds(bounds: Dict[str, Any], min_zoom: int, max_zoom: int) -> list[tuple[int, int, int]]:
    north = float(bounds.get("north"))
    south = float(bounds.get("south"))
    east = float(bounds.get("east"))
    west = float(bounds.get("west"))
    north = max(-85.05112878, min(85.05112878, north))
    south = max(-85.05112878, min(85.05112878, south))
    if south > north:
        south, north = north, south

    coords = []
    for z in range(min_zoom, max_zoom + 1):
        limit = (1 << z) - 1
        y_min = max(0, min(limit, _lat_to_tile_y(north, z)))
        y_max = max(0, min(limit, _lat_to_tile_y(south, z)))
        if west <= east:
            x_ranges = [(max(0, min(limit, _lon_to_tile_x(west, z))), max(0, min(limit, _lon_to_tile_x(east, z))))]
        else:
            x_ranges = [
                (max(0, min(limit, _lon_to_tile_x(west, z))), limit),
                (0, max(0, min(limit, _lon_to_tile_x(east, z)))),
            ]
        for x_min, x_max in x_ranges:
            if x_min > x_max:
                x_min, x_max = x_max, x_min
            for x in range(x_min, x_max + 1):
                for y in range(y_min, y_max + 1):
                    coords.append((z, x, y))
    return coords


def _validate_config(body: Dict[str, Any]) -> Optional[str]:
    """Validate config values per APRS-IS usage policies.
    Returns an error message or None if valid."""

    warnings = []  # Non-blocking policy warnings

    if "station" in body:
        s = body["station"]
        call = (s.get("callsign", "") or "").strip().upper()
        if call:
            if not _is_valid_station_callsign(call):
                return _INVALID_CALLSIGN_MESSAGE
        ssid = s.get("ssid", 0)
        try:
            ssid = int(ssid)
            if ssid < 0 or ssid > 15:
                return "SSID must be 0-15."
        except (ValueError, TypeError):
            return "SSID must be a number 0-15."
        try:
            lat = float(s.get("latitude", 0))
            lon = float(s.get("longitude", 0))
            if not (-90 <= lat <= 90):
                return "Latitude must be between -90 and 90."
            if not (-180 <= lon <= 180):
                return "Longitude must be between -180 and 180."
        except (ValueError, TypeError):
            return "Latitude/longitude must be valid numbers."
        bi = s.get("beacon_interval")
        if bi is not None:
            try:
                bi = int(bi)
                if bi < 0 or bi > 86400:
                    return "Beacon interval must be 0–1440 minutes (0 disables)."
                # APRS-IS policy: minimum 600s (10 min) for beacons
                if 0 < bi < 600:
                    return "Beacon interval must be at least 10 minutes per APRS-IS usage policy. Set to 0 to disable beacons."
            except (ValueError, TypeError):
                return "Beacon interval must be a number."
        # Validate symbol chars (single printable ASCII)
        for fld in ("symbol_table", "symbol_code"):
            v = s.get(fld, "")
            if v and (len(v) != 1 or ord(v) < 32 or ord(v) > 126):
                return f"{fld} must be a single printable ASCII character."
        phg = (s.get("phg", "") or "").strip().upper()
        if phg and not re.fullmatch(r"\d{4}", phg):
            return "PHG must be four digits (Power, Height, Gain, Direction) or left blank."
        for fld in ("equipment", "comment"):
            v = s.get(fld)
            if v is not None:
                v = str(v)
                if any(ord(ch) < 32 or ord(ch) > 126 for ch in v):
                    return f"{fld} must use printable ASCII characters only."

    if "aprs_is" in body:
        a = body["aprs_is"]
        server = a.get("server", "")
        if server and not _HOSTNAME_RE.match(server):
            return "Invalid APRS-IS server hostname."
        port = a.get("port")
        if port is not None:
            try:
                port = int(port)
                if port < 1 or port > 65535:
                    return "APRS-IS port must be 1-65535."
            except (ValueError, TypeError):
                return "APRS-IS port must be a number."
        # Validate filter string tokens
        filt = (a.get("filter", "") or "").strip()
        if filt:
            for token in filt.split():
                if token.lower() == "default":
                    continue
                if token.lower() == "filter":
                    return "Enter only the APRS-IS filter tokens, not the leading 'filter' command word."
                if not _FILTER_TOKEN_RE.match(token):
                    return f"Invalid APRS-IS filter token: '{token}'. Filters use format like r/35/-79/80, m/80, b/CALL, t/poimq, or -p/CW."

    if "tracking" in body:
        t = body["tracking"]
        blocked = t.get("blocked_callsigns", [])
        if isinstance(blocked, str):
            blocked = re.split(r"[\s,]+", blocked)
        if not isinstance(blocked, list):
            return "Station blocklist must be a list of callsigns."
        for value in blocked:
            call = str(value or "").strip().upper()
            if not call:
                continue
            if not re.fullmatch(r"[A-Z0-9]{1,9}(?:-(?:[0-9]|1[0-5]))?", call):
                return "Blocked callsigns must look like CALL or CALL-SSID, with SSID 0-15."

    if "watched_paths" in body:
        paths = body["watched_paths"]
        if isinstance(paths, str):
            paths = [line for line in paths.splitlines() if line.strip()]
        if not isinstance(paths, list):
            return "Watched paths must be a list."
        for item in paths:
            if isinstance(item, str):
                parts = [part.strip() for part in item.split("|")]
                if len(parts) < 2:
                    return "Watched path lines must use CALL|latitude|longitude or CALL|grid."
                call = parts[0]
                if len(parts) >= 3 and re.fullmatch(r"-?\d+(?:\.\d+)?", parts[1] or ""):
                    lat_value, lon_value = parts[1], parts[2]
                    grid_value = ""
                else:
                    lat_value, lon_value = 0, 0
                    grid_value = parts[1] if len(parts) > 1 else ""
            elif isinstance(item, dict):
                call = str(item.get("callsign", "") or "").strip()
                lat_value = item.get("latitude", 0)
                lon_value = item.get("longitude", 0)
                grid_value = item.get("grid", "")
            else:
                return "Watched path entries must be objects or CALL|lat|lon lines."
            if call and not re.fullmatch(r"[A-Z0-9]{1,9}(?:-(?:[0-9]|1[0-5]))?", call.upper()):
                return "Watched path callsigns must look like CALL or CALL-SSID."
            if str(grid_value or "").strip() and StationTracker.maidenhead_to_lat_lon(str(grid_value)) is None:
                return "Watched path grid squares must be valid Maidenhead locators, such as EM85 or EM85AB."
            try:
                lat = float(lat_value)
                lon = float(lon_value)
            except (TypeError, ValueError):
                return "Watched path latitude/longitude must be valid numbers."
            if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                return "Watched path latitude/longitude are out of range."

    if "callbook" in body:
        cb = body["callbook"]
        provider = str(cb.get("provider", "auto") or "auto").strip().lower()
        if provider not in {"auto", "callook", "hamdb", "hamqth", "qrz"}:
            return "Callbook provider must be auto, callook, hamdb, hamqth, or qrz."
        for field in ("hamqth_username", "qrz_username"):
            value = str(cb.get(field, "") or "").strip()
            if value and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._@+-]{0,63}", value):
                return "Callbook usernames can contain letters, numbers, dots, underscores, plus, at, and dash."

    # IGate policy checks
    if "igate" in body:
        ig = body["igate"]
        station = body.get("station", {})
        aprs_is_cfg = body.get("aprs_is", {})
        call = (station.get("callsign", "") or "").strip().upper()
        passcode = aprs_is_cfg.get("passcode", "")
        # Warn if IGate enabled but callsign is placeholder
        if ig.get("enabled") and call in _BLOCKED_CALLSIGNS:
            return _IGATE_CALLSIGN_MESSAGE
        # Warn if IGate RF→IS enabled with read-only passcode
        if ig.get("rf_to_is") and passcode == "-1":
            return _IGATE_PASSCODE_MESSAGE

    if "kiss_tcp" in body:
        kt = body["kiss_tcp"]
        host = kt.get("host", "")
        if host and not _HOSTNAME_RE.match(host):
            return "Invalid KISS TCP hostname."
        port = kt.get("port")
        if port is not None:
            try:
                port = int(port)
                if port < 1 or port > 65535:
                    return "KISS TCP port must be 1-65535."
            except (ValueError, TypeError):
                return "KISS TCP port must be a number."

    if "kiss_serial" in body:
        ks = body["kiss_serial"]
        baudrate = ks.get("baudrate")
        if baudrate is not None:
            try:
                baudrate = int(baudrate)
                if baudrate < 300 or baudrate > 921600:
                    return "KISS serial baudrate must be 300-921600."
            except (ValueError, TypeError):
                return "KISS serial baudrate must be a number."
        mode = (ks.get("mode", "kiss") or "kiss").strip().lower()
        if mode not in {"kiss", "tnc2_monitor"}:
            return "KISS serial mode must be kiss or tnc2_monitor."
        flow = (ks.get("flow_control", "none") or "none").strip().lower()
        if flow not in {"none", "xonxoff", "rtscts", "dsrdtr"}:
            return "KISS serial flow control must be none, xonxoff, rtscts, or dsrdtr."
        profile = (ks.get("init_profile", "none") or "none").strip().lower()
        if profile not in {"none", "kenwood_thd7", "kenwood_tmd700", "kenwood_thd72", "generic_tnc2_kiss"}:
            return "Unknown KISS serial init profile."

    if "rf_ports" in body:
        ports = body["rf_ports"]
        if not isinstance(ports, list):
            return "RF ports must be a list."
        if len(ports) > 16:
            return "RF ports are limited to 16 entries."
        names = set()
        for idx, port_cfg in enumerate(ports, 1):
            if not isinstance(port_cfg, dict):
                return f"RF port {idx} is invalid."
            name = (port_cfg.get("name", "") or "").strip()
            if len(name) > 40:
                return "RF port names must be 40 characters or less."
            if name:
                key = name.lower()
                if key in names:
                    return f"Duplicate RF port name: {name}."
                names.add(key)
            port_type = (port_cfg.get("type", "serial") or "serial").strip().lower()
            if port_type not in {"serial", "tcp"}:
                return "RF port type must be serial or tcp."
            if port_type == "serial":
                try:
                    baudrate = int(port_cfg.get("baudrate", 9600))
                    if baudrate < 300 or baudrate > 921600:
                        return "RF serial baudrate must be 300-921600."
                except (ValueError, TypeError):
                    return "RF serial baudrate must be a number."
                mode = (port_cfg.get("mode", "kiss") or "kiss").strip().lower()
                if mode not in {"kiss", "tnc2_monitor"}:
                    return "RF serial mode must be kiss or tnc2_monitor."
                flow = (port_cfg.get("flow_control", "none") or "none").strip().lower()
                if flow not in {"none", "xonxoff", "rtscts", "dsrdtr"}:
                    return "RF serial flow control must be none, xonxoff, rtscts, or dsrdtr."
                profile = (port_cfg.get("init_profile", "none") or "none").strip().lower()
                if profile not in {"none", "kenwood_thd7", "kenwood_tmd700", "kenwood_thd72", "generic_tnc2_kiss"}:
                    return "Unknown RF serial init profile."
            else:
                protocol = (port_cfg.get("protocol", "kiss") or "kiss").strip().lower()
                if protocol not in {"kiss", "agwpe"}:
                    return "RF TCP protocol must be kiss or agwpe."
                host = (port_cfg.get("host", "") or "").strip()
                if host and not _HOSTNAME_RE.match(host):
                    return "Invalid RF TCP hostname."
                try:
                    tcp_port = int(port_cfg.get("tcp_port", 8001))
                    if tcp_port < 1 or tcp_port > 65535:
                        return "RF TCP port must be 1-65535."
                except (ValueError, TypeError):
                    return "RF TCP port must be a number."
    if "web" in body:
        w = body["web"]
        host = w.get("host", "")
        if host and not _HOSTNAME_RE.match(host):
            return "Invalid web host."
        port = w.get("port")
        if port is not None:
            try:
                port = int(port)
                if port < 1 or port > 65535:
                    return "Web port must be 1-65535."
            except (ValueError, TypeError):
                return "Web port must be a number."
        tile_source = (w.get("map_tile_source", "osm") or "osm").strip().lower()
        if tile_source not in {"osm", "custom"}:
            return "Map tile source must be osm or custom."
        unit_system = (w.get("unit_system", "imperial") or "imperial").strip().lower()
        if unit_system not in {"imperial", "metric"}:
            return "Unit system must be imperial or metric."
        launch_browser = (w.get("launch_browser", "") or "").strip().lower()
        if launch_browser and launch_browser not in browser_ids():
            return "Unknown launch browser."
        tile_url = (w.get("map_tile_url", "") or "").strip()
        if tile_source == "custom":
            if not tile_url:
                return "Custom map tile URL is required when custom tiles are selected."
            if not all(token in tile_url for token in _TILE_URL_TOKENS):
                return "Custom map tile URL must include {z}, {x}, and {y} placeholders."
            parsed = urllib.parse.urlparse(tile_url)
            if parsed.scheme not in {"http", "https"}:
                return "Custom map tile URL must start with http:// or https://."
            try:
                max_zoom = int(w.get("map_tile_max_zoom", 19))
                if max_zoom < 1 or max_zoom > 22:
                    return "Map tile max zoom must be 1-22."
            except (ValueError, TypeError):
                return "Map tile max zoom must be a number."

    if "wxnow" in body:
        wx = body["wxnow"]
        try:
            ssid = int(wx.get("ssid", 13))
            if ssid < 0 or ssid > 15:
                return "WX SSID must be 0-15."
        except (ValueError, TypeError):
            return "WX SSID must be a number 0-15."
        try:
            interval = int(wx.get("beacon_interval", 600))
            if interval < 600 or interval > 86400:
                return "WX beacon interval must be 10-1440 minutes."
        except (ValueError, TypeError):
            return "WX beacon interval must be a number."
        try:
            max_age = int(wx.get("max_age_minutes", 15))
            if max_age < 1 or max_age > 1440:
                return "WX stale cutoff must be 1-1440 minutes."
        except (ValueError, TypeError):
            return "WX stale cutoff must be a number."
        mode = (wx.get("mode", "both") or "both").strip().lower()
        if mode not in {"both", "rf", "aprs_is"}:
            return "WX transmit mode must be RF, APRS-IS, or both."
        for fld in ("symbol_table", "symbol_code"):
            v = wx.get(fld, "")
            if v and (len(v) != 1 or ord(v) < 32 or ord(v) > 126):
                return f"WX {fld.replace('_', ' ')} must be a single printable ASCII character."

    if "status" in body:
        st = body["status"]
        try:
            interval = int(st.get("beacon_interval", 1800))
            if interval < 600 or interval > 86400:
                return "Status/DX beacon interval must be 10-1440 minutes."
        except (ValueError, TypeError):
            return "Status/DX beacon interval must be a number."
        try:
            window = int(st.get("report_window_minutes", 60))
            if window < 15 or window > 1440:
                return "Status/DX report window must be 15-1440 minutes."
        except (ValueError, TypeError):
            return "Status/DX report window must be a number."
        try:
            max_length = int(st.get("max_length", 67))
            if max_length < 20 or max_length > 120:
                return "Status/DX max length must be 20-120 characters."
        except (ValueError, TypeError):
            return "Status/DX max length must be a number."
        mode = (st.get("mode", "both") or "both").strip().lower()
        if mode not in {"both", "rf", "aprs_is"}:
            return "Status/DX transmit mode must be RF, APRS-IS, or both."

    if "gps" in body:
        g = body["gps"]
        source = (g.get("source", "browser") or "browser").strip().lower()
        if source not in _GPS_SOURCE_VALUES:
            return "Invalid GPS source."
        try:
            serial_baudrate = int(g.get("serial_baudrate", 9600))
            if serial_baudrate < 300 or serial_baudrate > 921600:
                return "GPS serial baudrate must be 300-921600."
        except (ValueError, TypeError):
            return "GPS serial baudrate must be a number."
        for field_name in ("tcp_port", "udp_port", "gpsd_port"):
            try:
                default_port = 2947 if field_name == "gpsd_port" else 10110
                port = int(g.get(field_name, default_port))
                if port < 1 or port > 65535:
                    return f"GPS {field_name.replace('_', ' ')} must be 1-65535."
            except (ValueError, TypeError):
                return f"GPS {field_name.replace('_', ' ')} must be a number."
        for field_name in ("tcp_host", "udp_host", "gpsd_host"):
            host = g.get(field_name, "")
            if host and not _HOSTNAME_RE.match(host):
                return f"Invalid GPS {field_name.replace('_', ' ')}."

    if "database" in body:
        db_cfg = body["database"]
        dbpath = db_cfg.get("path", "")
        if dbpath and not _SAFE_PATH_RE.match(dbpath):
            return "Database path must be a simple filename (alphanumeric, dots, hyphens, underscores only)."

    return None


def _validate_operational_config(body: Dict[str, Any]) -> Optional[str]:
    """Validate settings required for on-air or APRS-IS operation.

    This is intentionally narrower than _validate_config so users can save
    dashboard-only changes like weather/map settings before entering a real
    callsign.
    """
    return None


def _validate_save_request(body: Dict[str, Any]) -> Optional[str]:
    """Validate settings while allowing non-operational config to be saved."""
    validation_error = _validate_config(body)
    if not validation_error:
        return _validate_operational_config(body)

    station = body.get("station", {}) if isinstance(body.get("station"), dict) else {}
    call = (station.get("callsign", "") or "").strip().upper()
    if validation_error == _INVALID_CALLSIGN_MESSAGE and call in _BLOCKED_CALLSIGNS:
        logger.info("Ignoring non-blocking save validation warning: %s", validation_error)
        return _validate_operational_config(body)
    if validation_error in {_IGATE_CALLSIGN_MESSAGE, _IGATE_PASSCODE_MESSAGE}:
        logger.info("Ignoring non-blocking save validation warning: %s", validation_error)
        return _validate_operational_config(body)

    return validation_error


def create_app(
    config: Config,
    db: Database,
    tracker: StationTracker,
    ws_manager: WebSocketManager,
    handler: PacketHandler,
    analytics: AnalyticsEngine = None,
    alert_manager: AlertManager = None,
    aprs_is: APRSISClient = None,
    weather_manager: WeatherManager = None,
    wxnow_transmitter = None,
    status_transmitter = None,
    scheduled_transmitter = None,
    update_checker: UpdateChecker = None,
    gps_manager = None,
    mqtt_state: Optional[Dict[str, Any]] = None,
    app_version: str = "1.0.0",
    shutdown_event: Optional[asyncio.Event] = None,
    config_path: Optional[Path] = None,
) -> FastAPI:
    """Create and configure the FastAPI application."""

    app = FastAPI(title="APRS PropView", version=app_version)
    mqtt_state = mqtt_state if mqtt_state is not None else {"publisher": None}
    mqtt_lock = asyncio.Lock()
    config_path = Path(config_path or "config.toml")
    started_at = time.time()

    def _mqtt_snapshot() -> tuple:
        return (
            bool(config.mqtt.enabled),
            config.mqtt.broker,
            int(config.mqtt.port),
            config.mqtt.topic_prefix,
            config.mqtt.username,
            config.mqtt.password,
            bool(config.mqtt.discovery_enabled),
            config.mqtt.discovery_prefix,
            config.mqtt.device_name,
            config.mqtt.device_id,
            tuple(config.mqtt.watched_callsigns),
        )

    async def _apply_mqtt_runtime() -> str:
        async with mqtt_lock:
            current = mqtt_state.get("publisher")
            if current:
                await current.close()
                mqtt_state["publisher"] = None
                tracker.set_mqtt_publisher(None)
                handler.set_mqtt_publisher(None)

            if not config.mqtt.enabled:
                logger.info("MQTT: disabled")
                return "MQTT disabled"

            from server.export import MQTTPublisher
            publisher = MQTTPublisher(
                host=config.mqtt.broker,
                port=config.mqtt.port,
                topic_prefix=config.mqtt.topic_prefix,
                username=config.mqtt.username,
                password=config.mqtt.password,
                discovery_enabled=config.mqtt.discovery_enabled,
                discovery_prefix=config.mqtt.discovery_prefix,
                device_name=config.mqtt.device_name,
                device_id=config.mqtt.device_id,
                station_callsign=config.station.full_callsign,
                app_version=app_version,
                watched_callsigns=config.mqtt.watched_callsigns,
            )
            connected = await publisher.connect()
            if connected:
                mqtt_state["publisher"] = publisher
                tracker.set_mqtt_publisher(publisher)
                handler.set_mqtt_publisher(publisher)
                logger.info("MQTT: reconnected to %s:%s", config.mqtt.broker, config.mqtt.port)
                return "MQTT reconnected"

            await publisher.close()
            logger.warning("MQTT: reconnect failed (check broker settings or paho-mqtt installation)")
            return "MQTT reconnect failed"

    @app.on_event("startup")
    async def startup_update_check():
        if not update_checker:
            return
        try:
            update_checker.start_periodic_task()
        except Exception as exc:
            logger.warning("Could not start update checker: %s", exc)

    @app.on_event("shutdown")
    async def shutdown_update_check():
        if not update_checker:
            return
        await update_checker.stop_periodic_task()

    # ── CORS — restrict to same-origin only ──────────────────────────
    web_origin = f"http://{config.web.host}:{config.web.port}"
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[web_origin, "http://127.0.0.1:" + str(config.web.port), "http://localhost:" + str(config.web.port)],
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )

    # ── Static files ────────────────────────────────────────────────

    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @app.get("/api/health")
    async def get_health(full: bool = Query(False)):
        status = handler.get_status() if handler else {}
        payload = {
            "ok": True,
            "version": app_version,
            "station": config.station.full_callsign,
            "web": {
                "host": config.web.host,
                "port": config.web.port,
            },
            "rf_connected": bool(status.get("rf_connected")),
            "aprs_is_connected": bool(status.get("aprs_is_connected")),
            "rf_interfaces": status.get("rf_interfaces", []),
        }
        if full:
            payload.update({
                "uptime_seconds": round(time.time() - started_at),
                "update_checks_enabled": bool(config.web.update_check_enabled),
                "paths": {
                    "config": str(config_path),
                    "database": str(config.database.path),
                    "map_tile_cache": str(MAP_TILE_CACHE_DIR),
                    "user_audio": str(USER_AUDIO_DIR),
                },
                "configuration_warnings": [
                    warning for warning in (
                        "station_callsign_is_placeholder"
                        if config.station.callsign.upper() in {"N0CALL", "NOCALL", "MYCALL", "TEST"}
                        else "",
                        "station_position_not_set"
                        if float(config.station.latitude or 0.0) == 0.0 and float(config.station.longitude or 0.0) == 0.0
                        else "",
                    )
                    if warning
                ],
            })
        return payload

    @app.get("/")
    async def index():
        html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
        return HTMLResponse(
            html
            .replace("__ASSET_VERSION__", app_version)
            .replace("__APP_VERSION__", app_version)
        )

    @app.get("/mobile")
    async def mobile_page():
        return FileResponse(str(STATIC_DIR / "mobile.html"))

    @app.post("/api/mobile/verify-pin")
    async def verify_mobile_pin(request: Request):
        """Verify PIN for mobile access. Returns success if PIN matches or no PIN is set."""
        try:
            body = await request.json()
            pin = (body.get("pin", "") or "").strip()
            configured_pin = (config.web.mobile_pin or "").strip()
            if not configured_pin:
                return {"success": True}  # No PIN configured
            if pin == configured_pin:
                return {"success": True}
            return JSONResponse(status_code=403, content={"success": False, "message": "Incorrect PIN."})
        except Exception:
            return JSONResponse(status_code=400, content={"success": False, "message": "Invalid request."})

    @app.get("/api/mobile/pin-required")
    async def mobile_pin_required():
        """Check if a mobile PIN is configured."""
        return {"required": bool((config.web.mobile_pin or "").strip())}

    @app.get("/favicon.ico")
    async def favicon():
        return FileResponse(str(STATIC_DIR / "ico" / "favicon.ico"))

    @app.get("/api/map-tiles/{z}/{x}/{y}")
    async def get_map_tile(z: int, x: int, y: int):
        if z < 0 or z > 22 or x < 0 or y < 0 or x >= (1 << z) or y >= (1 << z):
            return JSONResponse(status_code=404, content={"success": False, "message": "Tile not found."})

        tile_cfg = _tile_source_config(config)
        tile_url = tile_cfg["url"]
        path = _tile_cache_path(tile_url, z, x, y)
        if not path.exists() or path.stat().st_size <= 0:
            path = await asyncio.to_thread(_download_tile, tile_url, z, x, y)
        if not path or not path.exists():
            return JSONResponse(status_code=404, content={"success": False, "message": "Tile not cached and upstream is unavailable."})
        media_type = mimetypes.guess_type(path.name)[0] or "image/png"
        return FileResponse(path, media_type=media_type)

    @app.get("/api/map-tiles/status")
    async def get_map_tile_cache_status():
        tile_cfg = _tile_source_config(config)
        cache_root = MAP_TILE_CACHE_DIR / _tile_cache_key(tile_cfg["url"])
        count = 0
        size_bytes = 0
        if cache_root.exists():
            for path in cache_root.rglob("*"):
                if path.is_file() and path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}:
                    count += 1
                    size_bytes += path.stat().st_size
        return {
            "enabled": True,
            "tile_count": count,
            "size_bytes": size_bytes,
            "size_mb": round(size_bytes / (1024 * 1024), 2),
            "source": config.web.map_tile_source,
            "max_zoom": tile_cfg["max_zoom"],
        }

    @app.post("/api/map-tiles/cache-current-view")
    async def cache_current_map_view(request: Request):
        try:
            body = await request.json()
            bounds = body.get("bounds") or {}
            zoom = int(body.get("zoom", 0))
            min_zoom = int(body.get("min_zoom", zoom))
            max_zoom = int(body.get("max_zoom", zoom))
            tile_cfg = _tile_source_config(config)
            max_source_zoom = min(22, max(1, int(tile_cfg["max_zoom"])))
            min_zoom = max(0, min(max_source_zoom, min_zoom))
            max_zoom = max(min_zoom, min(max_source_zoom, max_zoom))
            coords = _tile_coords_for_bounds(bounds, min_zoom, max_zoom)
        except Exception:
            return JSONResponse(status_code=400, content={"success": False, "message": "Invalid map bounds or zoom."})

        if not coords:
            return {"success": True, "requested": 0, "downloaded": 0, "cached": 0, "failed": 0}
        if len(coords) > MAX_TILE_CACHE_REQUEST:
            return JSONResponse(
                status_code=400,
                content={
                    "success": False,
                    "message": f"Current view would request {len(coords)} tiles. Zoom in or cache fewer zoom levels; limit is {MAX_TILE_CACHE_REQUEST}.",
                    "requested": len(coords),
                    "limit": MAX_TILE_CACHE_REQUEST,
                },
            )

        tile_url = tile_cfg["url"]
        downloaded = 0
        cached = 0
        failed = 0
        semaphore = asyncio.Semaphore(6)

        async def cache_one(coord):
            nonlocal downloaded, cached, failed
            z, x, y = coord
            path = _tile_cache_path(tile_url, z, x, y)
            if path.exists() and path.stat().st_size > 0:
                cached += 1
                return
            async with semaphore:
                result = await asyncio.to_thread(_download_tile, tile_url, z, x, y)
            if result:
                downloaded += 1
            else:
                failed += 1

        await asyncio.gather(*(cache_one(coord) for coord in coords))
        return {
            "success": True,
            "requested": len(coords),
            "downloaded": downloaded,
            "cached": cached,
            "failed": failed,
        }

    # ── WebSocket ───────────────────────────────────────────────────

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket):
        accepted = await ws_manager.connect(websocket)
        if not accepted:
            return
        try:
            # Send initial state
            status = handler.get_status()
            await ws_manager.send_to(websocket, {"type": "status", "data": status})

            # Send current stations
            station_since = (
                time.time() - config.web.expire_after_minutes * 60
                if config.web.expire_after_minutes > 0
                else None
            )
            rf_stations = await tracker.get_rf_stations(since=station_since)
            is_stations = await tracker.get_is_stations(since=station_since)
            await ws_manager.send_to(
                websocket,
                {
                    "type": "initial_stations",
                    "rf": rf_stations,
                    "aprs_is": is_stations,
                },
            )

            # Send propagation data
            prop_data = await tracker.get_propagation_data()
            prop_data["watched_paths"] = await tracker.evaluate_watched_paths(allow_alerts=False)
            await ws_manager.send_to(websocket, {"type": "propagation", "data": prop_data})

            # Keep connection alive and handle incoming messages
            while True:
                data = await websocket.receive_text()
                # Handle client requests if needed
                logger.debug(f"WS received: {data}")

        except WebSocketDisconnect:
            ws_manager.disconnect(websocket)
        except (ConnectionResetError, OSError, RuntimeError) as e:
            logger.info(f"WebSocket closed: {e}")
            ws_manager.disconnect(websocket)
        except Exception as e:
            logger.error(f"WebSocket error: {e}")
            ws_manager.disconnect(websocket)

    # ── REST API ────────────────────────────────────────────────────

    @app.get("/api/version")
    async def get_version():
        return {"version": app_version}

    @app.get("/api/update-status")
    async def get_update_status(force: bool = Query(False)):
        installer_install_supported = _sys.platform == "win32"
        if not update_checker:
            return {
                "checked": False,
                "current_version": app_version,
                "update_available": False,
                "current_is_newer_than_release": False,
                "latest_version": app_version,
                "release_name": "",
                "release_url": "https://github.com/RF-YVY/APRS-PropView/releases",
                "installer_url": "",
                "installer_name": "",
                "installer_install_supported": installer_install_supported,
                "published_at": "",
                "prerelease": False,
                "checked_at": None,
                "message": "Update checker is not configured.",
                "error": "unavailable",
            }
        status = await update_checker.get_status(force=force)
        status["installer_install_supported"] = installer_install_supported
        return status

    def _download_update_installer_sync(url: str, filename: str) -> str:
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme != "https" or parsed.netloc.lower() not in {
            "github.com",
            "objects.githubusercontent.com",
            "github-releases.githubusercontent.com",
        }:
            raise RuntimeError("Installer download URL is not a trusted GitHub URL.")

        safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", filename or "APRSPropViewSetup.exe")
        if not safe_name.lower().endswith(".exe"):
            safe_name = "APRSPropViewSetup.exe"
        update_dir = Path(tempfile.gettempdir()) / "APRSPropViewUpdates"
        update_dir.mkdir(parents=True, exist_ok=True)
        target = update_dir / safe_name

        req = urllib.request.Request(
            url,
            headers={"User-Agent": f"APRSPropView/{app_version}"},
        )
        with urllib.request.urlopen(req, timeout=120, context=_github_ssl_context()) as resp:
            with open(target, "wb") as f:
                shutil.copyfileobj(resp, f)
        if target.stat().st_size < 1024 * 1024:
            raise RuntimeError("Downloaded installer is unexpectedly small.")
        return str(target)

    def _launch_update_installer(path: str) -> None:
        installer = Path(path)
        installer_arg = str(installer).replace("'", "''")
        working_dir_arg = str(installer.parent).replace("'", "''")
        helper_script = f"""
$installer = '{installer_arg}'
$workingDir = '{working_dir_arg}'
$parentPid = {os.getpid()}
Wait-Process -Id $parentPid -Timeout 90 -ErrorAction SilentlyContinue
$deadline = (Get-Date).AddSeconds(30)
while ((Get-Date) -lt $deadline) {{
    $running = Get-Process -Name 'APRSPropView' -ErrorAction SilentlyContinue
    if (-not $running) {{ break }}
    Start-Sleep -Milliseconds 500
}}
Start-Process -FilePath $installer -ArgumentList @('/SP-', '/CLOSEAPPLICATIONS', '/FORCECLOSEAPPLICATIONS', '/NORESTARTAPPLICATIONS', '/PROPVIEWINAPPUPDATE=1') -WorkingDirectory $workingDir
"""
        encoded_script = base64.b64encode(helper_script.encode("utf-16le")).decode("ascii")
        subprocess.Popen(
            [
                "powershell.exe",
                "-NoProfile",
                "-WindowStyle",
                "Hidden",
                "-ExecutionPolicy",
                "Bypass",
                "-EncodedCommand",
                encoded_script,
            ],
            cwd=str(installer.parent),
            close_fds=True,
        )

    async def _shutdown_after_update_helper_launch() -> None:
        await asyncio.sleep(4.0)
        if shutdown_event:
            logger.info("Update installer helper launched; requesting application shutdown.")
            shutdown_event.set()
        else:
            logger.warning("Update installer helper launched, but no shutdown event is configured.")

    @app.post("/api/update-install")
    async def download_and_launch_update(background_tasks: BackgroundTasks):
        if _sys.platform != "win32":
            return JSONResponse(
                status_code=400,
                content={"success": False, "message": "Installer updates are available only on Windows."},
            )
        if not update_checker:
            return JSONResponse(
                status_code=503,
                content={"success": False, "message": "Update checker is not configured."},
            )

        status = await update_checker.get_status(force=True)
        if not status.get("update_available"):
            return JSONResponse(
                status_code=409,
                content={"success": False, "message": status.get("message") or "No update is available."},
            )

        installer_url = (status.get("installer_url") or "").strip()
        installer_name = (status.get("installer_name") or "").strip()
        if not installer_url:
            return JSONResponse(
                status_code=404,
                content={
                    "success": False,
                    "message": "This release does not include a setup installer asset. Open GitHub releases to update manually.",
                    "release_url": status.get("release_url"),
                },
            )

        loop = asyncio.get_running_loop()
        try:
            installer_path = await loop.run_in_executor(
                None,
                _download_update_installer_sync,
                installer_url,
                installer_name,
            )
        except Exception as e:
            logger.warning("Update installer download failed: %s", e)
            return JSONResponse(
                status_code=502,
                content={"success": False, "message": "Could not download the update installer."},
            )

        background_tasks.add_task(_launch_update_installer, installer_path)
        background_tasks.add_task(_shutdown_after_update_helper_launch)
        return {
            "success": True,
            "message": "Update installer downloaded. APRS PropView will close, then setup will launch to replace the application while keeping your settings.",
            "installer_path": installer_path,
        }

    @app.get("/api/status")
    async def get_status():
        return handler.get_status()

    @app.get("/api/diagnostics")
    async def get_diagnostics():
        mqtt_publisher = mqtt_state.get("publisher")
        audio_files = {}
        for alert_key, attr in ALERT_AUDIO_KEYS.items():
            filename = getattr(config.alerts, attr, "") or ""
            audio_files[alert_key] = {
                "assigned": bool(filename),
                "filename": filename,
                "exists": bool(filename and (USER_AUDIO_DIR / filename).exists()),
            }
        weather_status = {
            "current_loaded": bool(getattr(weather_manager, "_current", None)) if weather_manager else False,
            "alert_count": len(getattr(weather_manager, "_alerts", []) or []) if weather_manager else 0,
            "ducting_loaded": bool(getattr(weather_manager, "_ducting", None)) if weather_manager else False,
        }
        return {
            "version": app_version,
            "station": config.station.full_callsign,
            "websocket_connections": len(getattr(ws_manager, "active_connections", []) or []),
            "mqtt": {
                "enabled": bool(config.mqtt.enabled),
                "broker": config.mqtt.broker,
                "port": config.mqtt.port,
                "topic_prefix": config.mqtt.topic_prefix,
                "connected": bool(getattr(mqtt_publisher, "_connected", False)),
                "discovery_enabled": bool(config.mqtt.discovery_enabled),
                "watched_callsigns": len(config.mqtt.watched_callsigns or []),
            },
            "weather": {
                "enabled": bool(config.weather.enabled),
                "configured": bool(config.weather.location_code),
                "location_code": config.weather.location_code,
                **weather_status,
            },
            "alerts": {
                "enabled": bool(config.alerts.enabled),
                "message_notifications_enabled": bool(config.alerts.msg_notify_enabled),
                "audio_output_device_configured": bool(config.alerts.audio_output_device_id),
                "audio_files": audio_files,
            },
            "connections": handler.get_status(),
        }

    @app.post("/api/gps/location")
    async def update_gps_location(request: Request):
        """Ingest a live GPS position from browser/mobile or a companion app."""
        if not gps_manager:
            return JSONResponse(
                status_code=503,
                content={"success": False, "message": "GPS manager is not available."},
            )
        try:
            body = await request.json()
            source = (body.get("source", "browser") or "browser").strip().lower()
            if source not in {"browser", "companion", "nmea_serial", "nmea_tcp", "nmea_udp", "gpsd", "self_packet"}:
                return JSONResponse(
                    status_code=400,
                    content={"success": False, "message": "Invalid GPS source."},
                )
            if not gps_manager._should_accept_source(source) and not (
                source == "companion" and gps_manager._should_accept_source("browser")
            ):
                return JSONResponse(
                    status_code=409,
                    content={"success": False, "message": "GPS source is not enabled in settings."},
                )
            if "map_update_enabled" in body:
                config.gps.map_update_enabled = bool(body.get("map_update_enabled"))
            if "update_station_position" in body:
                config.gps.update_station_position = bool(body.get("update_station_position"))
            if "station_position_locked" in body:
                config.gps.station_position_locked = bool(body.get("station_position_locked"))
            status = await gps_manager.update_location(
                float(body.get("latitude")),
                float(body.get("longitude")),
                source=source,
                accuracy_m=body.get("accuracy_m"),
                update_station_position=body.get("update_station_position"),
                station_position_locked=body.get("station_position_locked"),
            )
            return {"success": True, "gps": status}
        except (ValueError, TypeError):
            return JSONResponse(
                status_code=400,
                content={"success": False, "message": "Invalid GPS latitude/longitude."},
            )
        except Exception as e:
            logger.error(f"GPS location update failed: {e}")
            return JSONResponse(
                status_code=500,
                content={"success": False, "message": "Error updating GPS location."},
            )

    @app.get("/api/stations/rf")
    async def get_rf_stations(
        since: Optional[float] = Query(None, description="Unix timestamp filter"),
        hours: Optional[float] = Query(None, description="Hours ago filter"),
        max_distance: Optional[float] = Query(None, description="Max distance in km"),
    ):
        since_ts = None
        if since:
            since_ts = since
        elif hours:
            since_ts = time.time() - (hours * 3600)
        stations = await tracker.get_rf_stations(since=since_ts, max_distance=max_distance)
        return {"stations": stations, "count": len(stations)}

    @app.get("/api/stations/is")
    async def get_is_stations(
        since: Optional[float] = Query(None),
        hours: Optional[float] = Query(None),
    ):
        since_ts = None
        if since:
            since_ts = since
        elif hours:
            since_ts = time.time() - (hours * 3600)
        stations = await tracker.get_is_stations(since=since_ts)
        return {"stations": stations, "count": len(stations)}

    @app.get("/api/stations/all")
    async def get_all_stations(
        hours: Optional[float] = Query(24, description="Hours ago filter"),
    ):
        since_ts = time.time() - (hours * 3600) if hours else None
        data = await tracker.get_all_stations(since=since_ts)
        return {
            "rf": data["rf"],
            "aprs_is": data["aprs_is"],
            "rf_count": len(data["rf"]),
            "is_count": len(data["aprs_is"]),
        }

    @app.delete("/api/stations/{source}/{callsign}")
    async def delete_station(source: str, callsign: str):
        normalized_source = "aprs_is" if source in {"aprs_is", "is"} else source
        if normalized_source not in {"rf", "aprs_is"}:
            return JSONResponse(
                status_code=400,
                content={"success": False, "message": "Invalid station source."},
            )
        deleted = await tracker.delete_station(callsign.strip().upper(), normalized_source)
        if not deleted:
            return JSONResponse(
                status_code=404,
                content={"success": False, "message": "Station not found."},
            )
        prop_data = await tracker.get_propagation_data()
        prop_data["watched_paths"] = await tracker.evaluate_watched_paths(allow_alerts=False)
        await ws_manager.broadcast({"type": "propagation", "data": prop_data})
        return {"success": True}

    @app.get("/api/packets")
    async def get_packets(
        limit: int = Query(100, ge=1, le=1000),
        source: Optional[str] = Query(None),
    ):
        packets = await db.get_recent_packets(limit=limit, source=source)
        return {"packets": packets, "count": len(packets)}

    @app.get("/api/propagation")
    async def get_propagation():
        prop_data = await tracker.get_propagation_data()
        prop_data["watched_paths"] = await tracker.evaluate_watched_paths(allow_alerts=False)
        return prop_data

    @app.post("/api/callbook/lookup")
    async def callbook_lookup(request: Request):
        body = await request.json()
        callsign = str(body.get("callsign", "") or "").strip().upper()
        if not callsign:
            return JSONResponse(status_code=400, content={"success": False, "message": "Enter a callsign to look up."})
        base_call = callsign.split("-", 1)[0]
        if not re.fullmatch(r"[A-Z0-9]{1,9}", base_call):
            return JSONResponse(status_code=400, content={"success": False, "message": "Callsign must look like a valid station callsign."})

        credentials = CallbookCredentials(
            provider=config.callbook.provider,
            hamqth_username=config.callbook.hamqth_username,
            hamqth_password=config.callbook.hamqth_password,
            qrz_username=config.callbook.qrz_username,
            qrz_password=config.callbook.qrz_password,
        )
        try:
            result = await lookup_callsign(credentials, base_call)
        except Exception as exc:
            logger.warning("Callbook lookup failed for %s: %s", base_call, exc)
            return JSONResponse(status_code=502, content={"success": False, "message": "Callbook lookup failed. Check provider credentials and network access."})
        status = 200 if result.get("success") else 404
        return JSONResponse(status_code=status, content=result)

    @app.get("/api/propagation/history")
    async def get_propagation_history(hours: int = Query(24, ge=1, le=168)):
        history = await db.get_propagation_history(hours=hours)
        return {"history": history, "count": len(history)}

    @app.get("/api/stats")
    async def get_stats():
        return await db.get_stats()

    # ── Messaging API ───────────────────────────────────────────

    @app.get("/api/messages")
    async def get_messages(
        limit: int = Query(100, ge=1, le=500),
    ):
        messages = handler.get_messages(limit=limit)
        return {"messages": messages, "count": len(messages)}

    @app.delete("/api/messages")
    async def clear_messages():
        """Clear all stored messages."""
        await handler.clear_messages()
        return {"success": True, "message": "Messages cleared."}

    @app.delete("/api/messages/conversation/{callsign}")
    async def clear_message_conversation(callsign: str):
        """Clear stored messages involving one station or addressee."""
        call = (callsign or "").strip().upper()
        if not _is_valid_message_addressee(call):
            return JSONResponse(
                status_code=400,
                content={"success": False, "message": "Invalid station callsign or addressee."},
            )
        deleted = await handler.clear_message_conversation(call)
        return {"success": True, "deleted": deleted, "message": f"Cleared {deleted} message(s) for {call}."}

    @app.get("/api/messages/contacts")
    async def get_message_contacts():
        contacts = await db.get_message_contacts()
        return {"contacts": contacts, "count": len(contacts)}

    @app.post("/api/messages/contacts")
    async def save_message_contact(request: Request):
        body = await request.json()
        callsign = (body.get("callsign", "") or "").strip().upper()
        display_name = (body.get("display_name", "") or "").strip()
        if not _is_valid_message_addressee(callsign):
            return JSONResponse(
                status_code=400,
                content={"success": False, "message": "Invalid contact callsign or addressee."},
            )
        contact = await db.upsert_message_contact(callsign, display_name=display_name)
        return {"success": True, "contact": contact}

    @app.delete("/api/messages/contacts/{callsign}")
    async def delete_message_contact(callsign: str):
        deleted = await db.delete_message_contact(callsign)
        return {"success": True, "deleted": deleted}

    @app.post("/api/messages/send")
    async def send_message(request: Request):
        """Send an APRS message to a station, tactical address, or bot."""
        try:
            body = await request.json()
            to_call = (body.get("to", "") or "").strip().upper()
            text = (body.get("text", "") or "").strip()
            route = (body.get("source", "") or body.get("route", "") or "").strip().lower()
            reply_source = route or (body.get("reply_source", "") or "").strip().lower()

            if not to_call:
                return JSONResponse(
                    status_code=400,
                    content={"success": False, "message": "Recipient addressee is required."},
                )
            if not text:
                return JSONResponse(
                    status_code=400,
                    content={"success": False, "message": "Message text is required."},
                )
            if len(text) > 67:
                return JSONResponse(
                    status_code=400,
                    content={"success": False, "message": "Message text too long (max 67 characters per APRS spec)."},
                )
            if not _is_valid_message_addressee(to_call):
                return JSONResponse(
                    status_code=400,
                    content={"success": False, "message": "Invalid APRS message addressee."},
                )
            if reply_source and reply_source not in {"rf", "aprs_is", "both"}:
                return JSONResponse(
                    status_code=400,
                    content={"success": False, "message": "Invalid reply source."},
                )

            msg = await handler.send_message(
                to_call,
                text,
                preferred_source=reply_source or None,
            )
            return {"success": True, "message": msg}

        except ValueError as e:
            logger.warning("Message send validation failed: %s", e)
            return JSONResponse(
                status_code=400,
                content={"success": False, "message": "Message could not be sent. Check the addressee, text, and selected route."},
            )
        except Exception as e:
            logger.error(f"Failed to send message: {e}")
            return JSONResponse(
                status_code=500,
                content={"success": False, "message": "Error sending message."},
            )

    # ── Analytics API ───────────────────────────────────────────

    @app.post("/api/beacon/transmit")
    async def transmit_beacon(request: Request):
        """Transmit a beacon immediately, independent of the interval timer."""
        try:
            try:
                body = await request.json()
            except Exception:
                body = {}
            mode = (body.get("mode", "both") or "both").strip().lower()
            if mode not in {"both", "rf", "aprs_is"}:
                return JSONResponse(
                    status_code=400,
                    content={"success": False, "message": "Invalid beacon transmit mode."},
                )
            result = await handler.transmit_beacon_now(mode=mode)
            return {"success": True, **result}
        except ValueError as e:
            logger.warning("Beacon transmit validation failed: %s", e)
            return JSONResponse(
                status_code=400,
                content={"success": False, "message": "Beacon could not be transmitted. Check station position and transmit connections."},
            )
        except Exception as e:
            logger.error(f"Failed to transmit beacon: {e}")
            return JSONResponse(
                status_code=500,
                content={"success": False, "message": "Error transmitting beacon."},
            )

    @app.get("/api/beacon/preview")
    async def beacon_preview(mode: str = Query("both", pattern="^(both|rf|aprs_is)$")):
        """Preview the next station beacon without transmitting."""
        try:
            return {"success": True, **handler.preview_beacon(mode=mode)}
        except ValueError as e:
            return JSONResponse(
                status_code=400,
                content={"success": False, "message": str(e)},
            )
        except Exception as e:
            logger.error("Failed to preview beacon: %s", e)
            return JSONResponse(
                status_code=500,
                content={"success": False, "message": "Error previewing beacon."},
            )

    @app.get("/api/wxnow/status")
    async def wxnow_status():
        if not wxnow_transmitter:
            return {"enabled": False, "configured": False, "message": "WXnow transmitter is not available."}
        return wxnow_transmitter.get_status()

    @app.get("/api/wxnow/preview")
    async def wxnow_preview():
        if not wxnow_transmitter:
            return JSONResponse(
                status_code=503,
                content={"success": False, "message": "WXnow transmitter is not available."},
            )
        try:
            return {"success": True, **wxnow_transmitter.preview()}
        except ValueError as e:
            logger.warning("WXnow preview validation failed: %s", e)
            return JSONResponse(
                status_code=400,
                content={"success": False, "message": str(e)},
            )
        except Exception as e:
            logger.error("Failed to preview WXnow packet: %s", e)
            return JSONResponse(
                status_code=500,
                content={"success": False, "message": "Error previewing WXnow packet."},
            )

    @app.post("/api/wxnow/transmit")
    async def wxnow_transmit():
        if not wxnow_transmitter:
            return JSONResponse(
                status_code=503,
                content={"success": False, "message": "WXnow transmitter is not available."},
            )
        try:
            result = await wxnow_transmitter.transmit_once(force=True)
            return {"success": True, **result}
        except ValueError as e:
            logger.warning("WXnow transmit validation failed: %s", e)
            return JSONResponse(
                status_code=400,
                content={"success": False, "message": "WXnow packet could not be transmitted. Check WXnow settings and file status."},
            )
        except Exception as e:
            logger.error("Failed to transmit WXnow packet: %s", e)
            return JSONResponse(
                status_code=500,
                content={"success": False, "message": "Error transmitting WXnow packet."},
            )

    @app.post("/api/wxnow/select-file")
    async def wxnow_select_file():
        """Open a native file picker on the desktop host."""
        try:
            import tkinter as tk
            from tkinter import filedialog

            root = tk.Tk()
            root.withdraw()
            root.attributes("-topmost", True)
            selected = filedialog.askopenfilename(
                title="Select WXnow.txt",
                filetypes=[("WXnow.txt", "WXnow.txt"), ("Text files", "*.txt"), ("All files", "*.*")],
            )
            root.destroy()
            return {"success": True, "file_path": selected or ""}
        except Exception as e:
            logger.error("Failed to open WXnow file picker: %s", e)
            return JSONResponse(
                status_code=500,
                content={"success": False, "message": "Could not open the file picker."},
            )

    @app.get("/api/status-dx/status")
    async def status_dx_status():
        if not status_transmitter:
            return {"enabled": False, "message": "Status/DX transmitter is not available."}
        status = status_transmitter.get_status()
        try:
            status["preview_text"] = await status_transmitter.build_preview_text()
            status["weather_alert_preview"] = await status_transmitter.preview_weather_alert_text()
        except Exception as e:
            status["preview_text"] = ""
            status["last_error"] = str(e)
        return status

    @app.get("/api/status-dx/preview")
    async def status_dx_preview():
        if not status_transmitter:
            return JSONResponse(
                status_code=503,
                content={"success": False, "message": "Status/DX transmitter is not available."},
            )
        try:
            text = await status_transmitter.build_preview_text()
            alert_preview = await status_transmitter.preview_weather_alert_text()
            return {
                "success": True,
                "dry_run": True,
                "text": text,
                "info": f">{text}" if text else "",
                "weather_alert_preview": alert_preview,
            }
        except Exception as e:
            logger.error("Failed to preview Status/DX packet: %s", e)
            return JSONResponse(
                status_code=500,
                content={"success": False, "message": "Error previewing Status/DX packet."},
            )

    @app.post("/api/status-dx/transmit")
    async def status_dx_transmit():
        if not status_transmitter:
            return JSONResponse(
                status_code=503,
                content={"success": False, "message": "Status/DX transmitter is not available."},
            )
        try:
            result = await status_transmitter.transmit_once(force=True)
            return {"success": True, **result}
        except ValueError as e:
            logger.warning("Status/DX transmit validation failed: %s", e)
            return JSONResponse(
                status_code=400,
                content={"success": False, "message": "Status/DX packet could not be transmitted. Check transmit settings and connection status."},
            )
        except Exception as e:
            logger.error("Failed to transmit Status/DX packet: %s", e)
            return JSONResponse(
                status_code=500,
                content={"success": False, "message": "Error transmitting Status/DX packet."},
            )

    @app.get("/api/transmit/history")
    async def transmit_history():
        return {"items": handler.get_transmit_history()}

    @app.get("/api/scheduled/preview")
    async def get_scheduled_preview():
        if not scheduled_transmitter:
            return {"success": False, "message": "Scheduled packets are not available.", "bulletins": [], "objects": []}
        return {
            "success": True,
            "status": scheduled_transmitter.get_status(),
            "bulletins": scheduled_transmitter.preview_bulletins(),
            "objects": scheduled_transmitter.preview_objects(),
        }

    @app.post("/api/bulletins/transmit")
    async def transmit_bulletins_now():
        if not scheduled_transmitter:
            return JSONResponse(status_code=503, content={"success": False, "message": "Scheduled packets are not available."})
        result = await scheduled_transmitter.transmit_bulletins_once(force=True)
        return {"success": True, **result}

    @app.post("/api/objects/transmit")
    async def transmit_objects_now():
        if not scheduled_transmitter:
            return JSONResponse(status_code=503, content={"success": False, "message": "Scheduled packets are not available."})
        result = await scheduled_transmitter.transmit_objects_once(force=True)
        return {"success": True, **result}

    @app.post("/api/objects/create")
    async def create_aprs_object(request: Request):
        try:
            body = await request.json()
            item = _clean_aprs_object_item(body)
            if not item:
                return JSONResponse(status_code=400, content={"success": False, "message": "Object name is required."})
            config.aprs_objects.items = [
                existing for existing in config.aprs_objects.items
                if str(existing.get("name", "")).strip().upper() != item["name"]
            ]
            config.aprs_objects.items.append(item)
            config.save(config_path)
            if scheduled_transmitter:
                await scheduled_transmitter.transmit_objects_once(force=True)
            return {"success": True, "message": f"Object {item['name']} saved.", "item": item}
        except Exception as e:
            logger.warning("APRS object create failed: %s", e)
            return JSONResponse(status_code=400, content={"success": False, "message": "Could not create APRS object."})

    @app.get("/api/analytics/longest-paths")
    async def get_longest_paths(
        hours: int = Query(24, ge=1, le=168),
        limit: int = Query(25, ge=1, le=100),
    ):
        if not analytics:
            return {"paths": [], "count": 0}
        paths = await analytics.get_longest_paths(hours=hours, limit=limit)
        return {"paths": paths, "count": len(paths)}

    @app.get("/api/analytics/heatmap")
    async def get_heatmap(
        hours: int = Query(24, ge=1, le=168),
    ):
        if not analytics:
            return {"grid": [], "timeline": [], "hours_covered": 0}
        return await analytics.get_propagation_heatmap(hours=hours)

    @app.get("/api/analytics/reliability")
    async def get_reliability(
        hours: int = Query(24, ge=1, le=168),
    ):
        if not analytics:
            return {"stations": [], "count": 0}
        stations = await analytics.get_station_reliability(hours=hours)
        return {"stations": stations, "count": len(stations)}

    @app.get("/api/analytics/best-times")
    async def get_best_times(
        days: int = Query(7, ge=1, le=30),
    ):
        if not analytics:
            return {"hours": [], "best_hours": [], "days_analyzed": 0, "total_samples": 0, "day_of_week": []}
        return await analytics.get_best_times(days=days)

    @app.get("/api/analytics/anomaly")
    async def get_anomaly():
        if not analytics:
            return {"anomaly_score": 0, "anomaly_level": "normal"}
        return await analytics.get_anomaly_status()

    @app.get("/api/analytics/bearing-sectors")
    async def get_bearing_sectors(
        hours: int = Query(24, ge=1, le=168),
    ):
        if not analytics:
            return {"sectors": [], "dominant": None}
        return await analytics.get_bearing_sectors(hours=hours)

    @app.get("/api/analytics/historical")
    async def get_historical_comparison():
        if not analytics:
            return {"today": [], "yesterday": [], "week_avg": [], "avg_7d": []}
        return await analytics.get_historical_comparison()

    @app.get("/api/analytics/sporadic-e")
    async def get_sporadic_e(hours: int = Query(6, ge=1, le=168)):
        if not analytics:
            return {"es_level": "none", "es_score": 0, "candidates": []}
        return await analytics.detect_sporadic_e(hours=hours)

    @app.get("/api/analytics/observed-range")
    async def get_observed_range(
        hours: int = Query(24, ge=1, le=168),
    ):
        if not analytics:
            return {"sectors": [], "max_range_km": 0}
        return await analytics.get_observed_range(hours=hours)

    @app.get("/api/analytics/weather")
    async def get_weather_analytics(hours: int = Query(24, ge=1, le=168)):
        cutoff = time.time() - hours * 3600
        samples = []
        if weather_manager:
            current = await weather_manager.get_current_weather()
            if current:
                samples.append({
                    "timestamp": time.time(),
                    "source": current.get("location_name") or current.get("location_code") or "Current weather",
                    "temperature_f": current.get("temperature_f"),
                    "humidity": current.get("humidity"),
                    "pressure_mb": current.get("pressure_mb"),
                    "wind_speed_mph": current.get("wind_speed_mph"),
                    "wind_gust_mph": current.get("wind_gusts_mph"),
                    "rain_1h_in": current.get("precipitation_in"),
                })
        cursor = await db.db.execute(
            """SELECT timestamp, source, from_call, raw
               FROM packets
               WHERE timestamp >= ?
                 AND packet_type = 'weather'
               ORDER BY timestamp ASC
               LIMIT 1000""",
            (cutoff,),
        )
        rows = await cursor.fetchall()
        for row in rows:
            pkt = parse_packet(row["raw"], source=row["source"])
            if not pkt.weather:
                continue
            samples.append({
                "timestamp": row["timestamp"],
                "source": row["from_call"],
                **pkt.weather,
            })
        samples.sort(key=lambda item: item.get("timestamp") or 0)
        return {"samples": samples, "count": len(samples), "hours": hours}

    @app.get("/api/analytics/path-quality/{callsign}")
    async def get_path_quality(callsign: str):
        history = await db.get_path_history(callsign.upper())
        return {"callsign": callsign.upper(), "history": history, "count": len(history)}

    @app.get("/api/first-heard")
    async def get_first_heard(
        hours: int = Query(24, ge=1, le=168),
        direct_only: bool = Query(False),
    ):
        log = await db.get_first_heard_log(hours=hours, direct_only=direct_only)
        return {"log": log, "count": len(log)}

    @app.get("/api/ducting")
    async def get_ducting():
        if not weather_manager:
            return {"enabled": False}
        try:
            ducting = await weather_manager.get_ducting()
            return ducting or {"enabled": True, "available": False}
        except Exception as e:
            logger.error(f"Ducting fetch error: {e}")
            return {"enabled": True, "error": str(e)}

    @app.get("/api/export/stations")
    async def export_stations(
        fmt: str = Query("json", pattern="^(json|csv)$"),
    ):
        from server.export import stations_to_csv
        rows = await db.export_stations()
        if fmt == "csv":
            from fastapi.responses import Response
            return Response(
                content=stations_to_csv(rows),
                media_type="text/csv",
                headers={"Content-Disposition": "attachment; filename=stations.csv"},
            )
        return {"stations": rows, "count": len(rows)}

    @app.get("/api/export/packets")
    async def export_packets(
        fmt: str = Query("json", pattern="^(json|csv)$"),
        hours: int = Query(24, ge=1, le=168),
    ):
        from server.export import packets_to_csv
        rows = await db.export_packets(hours=hours)
        if fmt == "csv":
            from fastapi.responses import Response
            return Response(
                content=packets_to_csv(rows),
                media_type="text/csv",
                headers={"Content-Disposition": "attachment; filename=packets.csv"},
            )
        return {"packets": rows, "count": len(rows)}

    @app.get("/api/export/propagation")
    async def export_propagation(
        fmt: str = Query("json", pattern="^(json|csv)$"),
        hours: int = Query(24, ge=1, le=168),
    ):
        from server.export import propagation_to_csv
        rows = await db.export_propagation(hours=hours)
        if fmt == "csv":
            from fastapi.responses import Response
            return Response(
                content=propagation_to_csv(rows),
                media_type="text/csv",
                headers={"Content-Disposition": "attachment; filename=propagation.csv"},
            )
        return {"propagation": rows, "count": len(rows)}

    # ── Alerts API ──────────────────────────────────────────────

    @app.get("/api/alerts/status")
    async def get_alert_status():
        if not alert_manager:
            return {"enabled": False}
        return alert_manager.get_status()

    @app.get("/api/alerts/history")
    async def get_alert_history():
        if not alert_manager:
            return {"alerts": []}
        return {"alerts": alert_manager.get_alert_history()}

    @app.get("/api/alerts/recommendations")
    async def get_alert_recommendations(
        hours: int = Query(24, ge=6, le=168),
        sample_minutes: int = Query(15, ge=5, le=60),
    ):
        if not analytics:
            return JSONResponse(
                status_code=503,
                content={"success": False, "message": "Analytics are not available."},
            )
        try:
            return await analytics.get_alert_threshold_recommendations(
                config.alerts,
                hours=hours,
                sample_minutes=sample_minutes,
            )
        except Exception as e:
            logger.error("Failed to build alert recommendations: %s", e)
            return JSONResponse(
                status_code=500,
                content={"success": False, "message": "Could not build alert recommendations."},
            )

    @app.post("/api/alerts/test")
    async def test_alert_destinations(request: Request):
        """Send a test alert to the selected alert notification destinations."""
        body = await request.json()
        al = body.get("alerts", body) if isinstance(body, dict) else {}
        if not isinstance(al, dict):
            return JSONResponse(status_code=400, content={"success": False, "message": "Invalid alert settings."})

        selected = {
            "discord": bool(al.get("discord_enabled", False)),
            "email": bool(al.get("email_enabled", False)),
            "sms": bool(al.get("sms_enabled", False)),
        }
        if not any(selected.values()):
            return JSONResponse(
                status_code=400,
                content={"success": False, "message": "Select at least one alert destination to test."},
            )

        email_password = al.get("email_password", "")
        if not email_password or "*" in str(email_password):
            email_password = config.alerts.email_password

        test_config = AlertConfig(
            enabled=True,
            discord_enabled=selected["discord"],
            discord_webhook_url=(al.get("discord_webhook_url", config.alerts.discord_webhook_url) or "").strip(),
            email_enabled=selected["email"],
            email_smtp_server=(al.get("email_smtp_server", config.alerts.email_smtp_server) or "").strip(),
            email_smtp_port=int(al.get("email_smtp_port", config.alerts.email_smtp_port) or 587),
            email_from=(al.get("email_from", config.alerts.email_from) or "").strip(),
            email_to=(al.get("email_to", config.alerts.email_to) or "").strip(),
            email_password=email_password,
            sms_enabled=selected["sms"],
            sms_gateway_address=(al.get("sms_gateway_address", config.alerts.sms_gateway_address) or "").strip(),
        )

        manager = AlertManager(test_config, station_callsign=config.station.full_callsign)
        result = await manager.send_test_alert()
        status_code = 200 if result.get("success") else 400
        message = "Test alert sent." if result.get("success") else "One or more test destinations failed."
        return JSONResponse(status_code=status_code, content={**result, "message": message})

    @app.post("/api/messages/test-notification")
    async def test_message_notification_destinations(request: Request):
        """Send a test message notification to the selected message notification destinations."""
        body = await request.json()
        al = body.get("alerts", body) if isinstance(body, dict) else {}
        if not isinstance(al, dict):
            return JSONResponse(status_code=400, content={"success": False, "message": "Invalid alert settings."})

        selected = {
            "discord": bool(al.get("msg_discord_enabled", False)),
            "email": bool(al.get("msg_email_enabled", False)),
            "sms": bool(al.get("msg_sms_enabled", False)),
        }
        if not any(selected.values()):
            return JSONResponse(
                status_code=400,
                content={"success": False, "message": "Select at least one message notification destination to test."},
            )

        email_password = al.get("email_password", "")
        if not email_password or "*" in str(email_password):
            email_password = config.alerts.email_password

        test_config = AlertConfig(
            enabled=True,
            msg_notify_enabled=True,
            msg_discord_enabled=selected["discord"],
            msg_email_enabled=selected["email"],
            msg_sms_enabled=selected["sms"],
            discord_webhook_url=(al.get("discord_webhook_url", config.alerts.discord_webhook_url) or "").strip(),
            email_smtp_server=(al.get("email_smtp_server", config.alerts.email_smtp_server) or "").strip(),
            email_smtp_port=int(al.get("email_smtp_port", config.alerts.email_smtp_port) or 587),
            email_from=(al.get("email_from", config.alerts.email_from) or "").strip(),
            email_to=(al.get("email_to", config.alerts.email_to) or "").strip(),
            email_password=email_password,
            sms_gateway_address=(al.get("sms_gateway_address", config.alerts.sms_gateway_address) or "").strip(),
        )

        manager = AlertManager(test_config, station_callsign=config.station.full_callsign)
        result = await manager.send_test_message_notification()
        status_code = 200 if result.get("success") else 400
        message = "Test message notification sent." if result.get("success") else "One or more message notification destinations failed."
        return JSONResponse(status_code=status_code, content={**result, "message": message})

    # ── Weather API ─────────────────────────────────────────────

    @app.get("/api/weather")
    async def get_weather():
        """Get current weather conditions and NWS alerts."""
        if not weather_manager:
            return {"enabled": False, "configured": False}
        try:
            data = await weather_manager.get_all()
            logger.info(
                "Weather request: enabled=%s configured=%s location=%s radar=%s polygons=%s alerts=%d",
                data.get("enabled"),
                data.get("configured"),
                config.weather.location_code or "<unset>",
                config.weather.radar_enabled,
                config.weather.alert_overlay_enabled,
                len(data.get("alerts") or []),
            )
            return data
        except Exception as e:
            logger.error(f"Weather fetch error: {e}")
            return {"enabled": config.weather.enabled, "configured": False, "error": str(e)}

    @app.get("/api/weather/refresh")
    async def refresh_weather():
        """Force-refresh weather data from APIs."""
        if not weather_manager:
            return {"enabled": False, "configured": False}
        try:
            data = await weather_manager.get_all(force=True)
            logger.info(
                "Weather refresh: enabled=%s configured=%s location=%s radar=%s polygons=%s alerts=%d",
                data.get("enabled"),
                data.get("configured"),
                config.weather.location_code or "<unset>",
                config.weather.radar_enabled,
                config.weather.alert_overlay_enabled,
                len(data.get("alerts") or []),
            )
            return data
        except Exception as e:
            logger.error(f"Weather refresh error: {e}")
            return {"enabled": config.weather.enabled, "configured": False, "error": str(e)}

    @app.post("/api/weather/resolve-location")
    async def resolve_weather_location(request: Request):
        """Resolve a US zip code or worldwide ICAO code to lat/lon for weather."""
        try:
            body = await request.json()
            code = (body.get("code", "") or "").strip()
            if not code:
                return JSONResponse(
                    status_code=400,
                    content={"success": False, "message": "Location code is required."},
                )
            from server.weather import resolve_location
            result = await resolve_location(code)
            if not result:
                return JSONResponse(
                    status_code=404,
                    content={"success": False, "message": f"Could not resolve '{code}'. Enter a valid US zip code (e.g. 28801) or ICAO code (e.g. KAVL, EGLL)."},
                )
            return {"success": True, "location": result}
        except Exception as e:
            logger.error(f"Location resolve error: {e}")
            return JSONResponse(
                status_code=500,
                content={"success": False, "message": "Error resolving location."},
            )

    @app.post("/api/weather/resolve-alert-scope")
    async def resolve_weather_alert_scope(request: Request):
        """Resolve county/zone UGC identifiers for a weather location."""
        try:
            body = await request.json()
            code = (body.get("code", "") or "").strip()
            if not code:
                return JSONResponse(
                    status_code=400,
                    content={"success": False, "message": "Location code is required."},
                )
            from server.weather import resolve_location, resolve_alert_scope_from_point
            location = await resolve_location(code)
            if not location:
                return JSONResponse(
                    status_code=404,
                    content={"success": False, "message": f"Could not resolve '{code}'."},
                )
            if location.get("country") and location.get("country") != "US":
                return JSONResponse(
                    status_code=400,
                    content={"success": False, "message": "County/zone alert scopes are only available for US NWS locations."},
                )
            scope = await resolve_alert_scope_from_point(location["latitude"], location["longitude"])
            if not scope:
                return JSONResponse(
                    status_code=404,
                    content={"success": False, "message": "Could not resolve county/zone identifiers for that location."},
                )
            return {"success": True, "location": location, "scope": scope}
        except Exception as e:
            logger.error(f"Alert scope resolve error: {e}")
            return JSONResponse(
                status_code=500,
                content={"success": False, "message": "Error resolving alert scope."},
            )

    @app.post("/api/alert-audio/upload")
    async def upload_alert_audio(request: Request):
        """Store a user-selected local alert sound for browser playback."""
        try:
            body = await request.json()
            alert_key = (body.get("alert_key") or "").strip()
            original_name = body.get("filename") or ""
            data_url = body.get("data") or ""
            if alert_key not in ALERT_AUDIO_KEYS:
                return JSONResponse(status_code=400, content={"success": False, "message": "Unknown alert sound slot."})

            ext = Path(original_name).suffix.lower()
            if ext not in ALERT_AUDIO_EXTS:
                return JSONResponse(status_code=400, content={"success": False, "message": "Select a .wav or .mp3 file."})

            if "," in data_url:
                data_url = data_url.split(",", 1)[1]
            try:
                audio_bytes = base64.b64decode(data_url, validate=True)
            except (binascii.Error, ValueError):
                return JSONResponse(status_code=400, content={"success": False, "message": "Invalid audio upload."})

            if not audio_bytes:
                return JSONResponse(status_code=400, content={"success": False, "message": "Audio file is empty."})
            if len(audio_bytes) > MAX_ALERT_AUDIO_BYTES:
                return JSONResponse(status_code=400, content={"success": False, "message": "Audio file must be 15 MB or smaller."})

            USER_AUDIO_DIR.mkdir(parents=True, exist_ok=True)
            filename = f"{alert_key}_{int(time.time())}_{_safe_alert_audio_filename(original_name)}"
            path = USER_AUDIO_DIR / filename
            path.write_bytes(audio_bytes)
            return {"success": True, "filename": filename, "url": _alert_audio_url(filename)}
        except Exception as e:
            logger.error("Alert audio upload failed: %s", e, exc_info=True)
            return JSONResponse(status_code=500, content={"success": False, "message": "Error saving alert audio."})

    @app.get("/api/alert-audio/file/{filename}")
    async def get_alert_audio_file(filename: str):
        safe_name = _safe_alert_audio_filename(filename)
        if safe_name != filename or Path(filename).suffix.lower() not in ALERT_AUDIO_EXTS:
            return JSONResponse(status_code=404, content={"success": False, "message": "Audio file not found."})
        path = USER_AUDIO_DIR / safe_name
        if not path.exists() or not path.is_file():
            return JSONResponse(status_code=404, content={"success": False, "message": "Audio file not found."})
        media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        return FileResponse(path, media_type=media_type)

    @app.get("/api/config")
    async def get_config():
        return {
            "station": {
                "callsign": config.station.callsign,
                "ssid": config.station.ssid,
                "latitude": config.station.latitude,
                "longitude": config.station.longitude,
                "symbol_table": config.station.symbol_table,
                "symbol_code": config.station.symbol_code,
                "phg": config.station.phg,
                "equipment": config.station.equipment,
                "comment": config.station.comment,
                "beacon_interval": config.station.beacon_interval,
                "beacon_path": config.station.beacon_path,
            },
            "digipeater": {
                "enabled": config.digipeater.enabled,
                "aliases": config.digipeater.aliases,
                "dedupe_interval": config.digipeater.dedupe_interval,
            },
            "igate": {
                "enabled": config.igate.enabled,
                "rf_to_is": config.igate.rf_to_is,
                "is_to_rf": config.igate.is_to_rf,
            },
            "aprs_is": {
                "enabled": config.aprs_is.enabled,
                "server": config.aprs_is.server,
                "port": config.aprs_is.port,
                "passcode": _mask_passcode(config.aprs_is.passcode),
                "passcode_configured": bool(config.aprs_is.passcode and config.aprs_is.passcode != "-1"),
                "filter": config.aprs_is.filter,
            },
            "kiss_serial": {
                "enabled": config.kiss_serial.enabled,
                "port": config.kiss_serial.port,
                "baudrate": config.kiss_serial.baudrate,
                "mode": config.kiss_serial.mode,
                "flow_control": config.kiss_serial.flow_control,
                "init_profile": config.kiss_serial.init_profile,
                "init_commands": config.kiss_serial.init_commands,
            },
            "kiss_tcp": {
                "enabled": config.kiss_tcp.enabled,
                "host": config.kiss_tcp.host,
                "port": config.kiss_tcp.port,
            },
            "rf_ports": [
                {
                    "name": port.name,
                    "enabled": port.enabled,
                    "type": port.type,
                    "port": port.port,
                    "baudrate": port.baudrate,
                    "host": port.host,
                    "tcp_port": port.tcp_port,
                    "protocol": port.protocol,
                    "mode": port.mode,
                    "flow_control": port.flow_control,
                    "init_profile": port.init_profile,
                    "init_commands": port.init_commands,
                    "rx_only_rf": port.rx_only_rf,
                    "rx_only_is": port.rx_only_is,
                }
                for port in config.rf_ports
            ],
            "web": {
                "host": config.web.host,
                "port": config.web.port,
                "launch_browser": config.web.launch_browser,
                "font_family": config.web.font_family,
                "map_tile_source": config.web.map_tile_source,
                "map_tile_url": config.web.map_tile_url,
                "map_tile_attribution": config.web.map_tile_attribution,
                "map_tile_max_zoom": config.web.map_tile_max_zoom,
                "unit_system": config.web.unit_system,
                "ghost_after_minutes": config.web.ghost_after_minutes,
                "expire_after_minutes": config.web.expire_after_minutes,
                "mobile_pin": config.web.mobile_pin,
                "update_check_enabled": config.web.update_check_enabled,
                "update_check_interval_hours": config.web.update_check_interval_hours,
                "visual_propagation_aura": config.web.visual_propagation_aura,
                "visual_path_reveal": config.web.visual_path_reveal,
                "visual_map_harmony": config.web.visual_map_harmony,
                "visual_condition_backdrop": config.web.visual_condition_backdrop,
                "visual_home_marker": config.web.visual_home_marker,
                "visual_watched_path_flow": config.web.visual_watched_path_flow,
                "visual_activity_moments": config.web.visual_activity_moments,
                "visual_packet_animation": config.web.visual_packet_animation,
            },
            "database": {
                "path": config.database.path,
            },
            "tracking": {
                "max_station_age": config.tracking.max_station_age,
                "cleanup_interval": config.tracking.cleanup_interval,
                "blocked_callsigns": config.tracking.blocked_callsigns,
            },
            "watched_paths": [
                {
                    "enabled": item.enabled,
                    "callsign": item.callsign,
                    "latitude": item.latitude,
                    "longitude": item.longitude,
                    "grid": item.grid,
                    "band": item.band,
                    "mode": item.mode,
                    "frequency_mhz": item.frequency_mhz,
                    "min_confidence": item.min_confidence,
                    "bearing_tolerance_deg": item.bearing_tolerance_deg,
                    "min_probe_count": item.min_probe_count,
                    "target_area_radius_km": item.target_area_radius_km,
                    "max_age_minutes": item.max_age_minutes,
                    "alert_cooldown_minutes": item.alert_cooldown_minutes,
                    "my_antenna_height_m": item.my_antenna_height_m,
                    "target_antenna_height_m": item.target_antenna_height_m,
                    "my_tx_power_w": item.my_tx_power_w,
                    "my_antenna_gain_dbi": item.my_antenna_gain_dbi,
                }
                for item in config.watched_paths
            ],
            "callbook": {
                "provider": config.callbook.provider,
                "hamqth_username": config.callbook.hamqth_username,
                "hamqth_password": _mask_passcode(config.callbook.hamqth_password),
                "hamqth_password_configured": bool(config.callbook.hamqth_password),
                "qrz_username": config.callbook.qrz_username,
                "qrz_password": _mask_passcode(config.callbook.qrz_password),
                "qrz_password_configured": bool(config.callbook.qrz_password),
            },
            "messaging": {
                "message_retention_days": config.messaging.message_retention_days,
                "receive_sibling_ssids": config.messaging.receive_sibling_ssids,
            },
            "alerts": {
                "enabled": config.alerts.enabled,
                "anomaly_alert_enabled": config.alerts.anomaly_alert_enabled,
                "sporadic_e_alert_enabled": config.alerts.sporadic_e_alert_enabled,
                "my_min_stations": config.alerts.my_min_stations,
                "my_min_distance_km": config.alerts.my_min_distance_km,
                "regional_min_stations": config.alerts.regional_min_stations,
                "regional_min_distance_km": config.alerts.regional_min_distance_km,
                "cooldown_seconds": config.alerts.cooldown_seconds,
                "quiet_start": config.alerts.quiet_start,
                "quiet_end": config.alerts.quiet_end,
                "msg_notify_enabled": config.alerts.msg_notify_enabled,
                "msg_discord_enabled": config.alerts.msg_discord_enabled,
                "msg_email_enabled": config.alerts.msg_email_enabled,
                "msg_sms_enabled": config.alerts.msg_sms_enabled,
                "audio_output_device_id": config.alerts.audio_output_device_id,
                "audio_my_station_opening_file": config.alerts.audio_my_station_opening_file,
                "audio_regional_watch_file": config.alerts.audio_regional_watch_file,
                "audio_first_heard_file": config.alerts.audio_first_heard_file,
                "audio_anomaly_file": config.alerts.audio_anomaly_file,
                "audio_sporadic_e_file": config.alerts.audio_sporadic_e_file,
                "audio_message_received_file": config.alerts.audio_message_received_file,
                "audio_weather_warning_file": config.alerts.audio_weather_warning_file,
                "audio_weather_watch_file": config.alerts.audio_weather_watch_file,
                "audio_files": {
                    key: {
                        "filename": getattr(config.alerts, attr, ""),
                        "url": _alert_audio_url(getattr(config.alerts, attr, "")),
                    }
                    for key, attr in ALERT_AUDIO_KEYS.items()
                },
                "discord_enabled": config.alerts.discord_enabled,
                "discord_webhook_url": config.alerts.discord_webhook_url,
                "email_enabled": config.alerts.email_enabled,
                "email_smtp_server": config.alerts.email_smtp_server,
                "email_smtp_port": config.alerts.email_smtp_port,
                "email_from": config.alerts.email_from,
                "email_to": config.alerts.email_to,
                "email_password": _mask_passcode(config.alerts.email_password),
                "sms_enabled": config.alerts.sms_enabled,
                "sms_gateway_address": config.alerts.sms_gateway_address,
            },
            "weather": {
                "enabled": config.weather.enabled,
                "location_code": config.weather.location_code,
                "current_provider": config.weather.current_provider,
                "wxnow_condition_fallback_enabled": config.weather.wxnow_condition_fallback_enabled,
                "alert_provider": config.weather.alert_provider,
                "weatherbit_api_key": _mask_passcode(config.weather.weatherbit_api_key),
                "weatherbit_poll_minutes": config.weather.weatherbit_poll_minutes,
                "alert_range_miles": config.weather.alert_range_miles,
                "refresh_minutes": config.weather.refresh_minutes,
                "radar_enabled": config.weather.radar_enabled,
                "radar_provider": config.weather.radar_provider,
                "radar_custom_url": config.weather.radar_custom_url,
                "radar_custom_layer": config.weather.radar_custom_layer,
                "radar_custom_attribution": config.weather.radar_custom_attribution,
                "radar_custom_api_key": _mask_passcode(config.weather.radar_custom_api_key),
                "radar_opacity": config.weather.radar_opacity,
                "radar_animate": config.weather.radar_animate,
                "alert_overlay_enabled": config.weather.alert_overlay_enabled,
                "alert_overlay_range_miles": config.weather.alert_overlay_range_miles,
                "alert_overlay_groups": config.weather.alert_overlay_groups,
                "alert_scope_mode": config.weather.alert_scope_mode,
                "alert_scope_zone": config.weather.alert_scope_zone,
                "elevated_alert_polling_enabled": config.weather.elevated_alert_polling_enabled,
                "elevated_alert_polling_seconds": config.weather.elevated_alert_polling_seconds,
                "elevated_alert_cooldown_minutes": config.weather.elevated_alert_cooldown_minutes,
                "elevated_trigger_events": config.weather.elevated_trigger_events,
                "weather_alert_symbol_enabled": config.weather.weather_alert_symbol_enabled,
            },
            "wxnow": {
                "enabled": config.wxnow.enabled,
                "file_path": config.wxnow.file_path,
                "ssid": config.wxnow.ssid,
                "beacon_interval": config.wxnow.beacon_interval,
                "max_age_minutes": config.wxnow.max_age_minutes,
                "include_position": config.wxnow.include_position,
                "mode": config.wxnow.mode,
                "path": config.wxnow.path,
                "symbol_table": config.wxnow.symbol_table,
                "symbol_code": config.wxnow.symbol_code,
            },
            "gps": {
                "enabled": config.gps.enabled,
                "source": config.gps.source,
                "map_update_enabled": config.gps.map_update_enabled,
                "update_station_position": config.gps.update_station_position,
                "station_position_locked": config.gps.station_position_locked,
                "serial_port": config.gps.serial_port,
                "serial_baudrate": config.gps.serial_baudrate,
                "tcp_host": config.gps.tcp_host,
                "tcp_port": config.gps.tcp_port,
                "udp_host": config.gps.udp_host,
                "udp_port": config.gps.udp_port,
                "gpsd_host": config.gps.gpsd_host,
                "gpsd_port": config.gps.gpsd_port,
            },
            "propagation": {
                "my_station_full_count": config.propagation.my_station_full_count,
                "my_station_full_dist_km": config.propagation.my_station_full_dist_km,
                "regional_full_count": config.propagation.regional_full_count,
                "regional_full_dist_km": config.propagation.regional_full_dist_km,
            },
            "status": {
                "enabled": config.status.enabled,
                "beacon_interval": config.status.beacon_interval,
                "mode": config.status.mode,
                "path": config.status.path,
                "report_window_minutes": config.status.report_window_minutes,
                "max_length": config.status.max_length,
                "source": config.status.source,
                "dynamic_order": config.status.dynamic_order,
                "dynamic_messages": config.status.dynamic_messages,
                "weather_alert_beacon_enabled": config.status.weather_alert_beacon_enabled,
                "weather_alert_cooldown_minutes": config.status.weather_alert_cooldown_minutes,
            },
            "smart_beaconing": {
                "enabled": config.smart_beaconing.enabled,
                "slow_interval": config.smart_beaconing.slow_interval,
                "fast_interval": config.smart_beaconing.fast_interval,
                "speed_threshold_mph": config.smart_beaconing.speed_threshold_mph,
            },
            "bulletins": {
                "enabled": config.bulletins.enabled,
                "interval": config.bulletins.interval,
                "mode": config.bulletins.mode,
                "path": config.bulletins.path,
                "items": config.bulletins.items,
            },
            "aprs_objects": {
                "enabled": config.aprs_objects.enabled,
                "interval": config.aprs_objects.interval,
                "mode": config.aprs_objects.mode,
                "path": config.aprs_objects.path,
                "items": config.aprs_objects.items,
            },
            "mqtt": {
                "enabled": config.mqtt.enabled,
                "broker": config.mqtt.broker,
                "port": config.mqtt.port,
                "topic_prefix": config.mqtt.topic_prefix,
                "username": config.mqtt.username,
                "password": _mask_passcode(config.mqtt.password),
                "discovery_enabled": config.mqtt.discovery_enabled,
                "discovery_prefix": config.mqtt.discovery_prefix,
                "device_name": config.mqtt.device_name,
                "device_id": config.mqtt.device_id,
                "watched_callsigns": config.mqtt.watched_callsigns,
            },
        }

    @app.get("/api/config/export")
    async def export_config():
        path = config_path
        if not path.exists() or not path.is_file():
            return JSONResponse(
                status_code=404,
                content={"success": False, "message": f"{path.name} was not found."},
            )
        return FileResponse(
            path,
            media_type="application/toml",
            filename="aprs-propview-config.toml",
        )

    @app.post("/api/config/import")
    async def import_config(request: Request):
        try:
            body = await request.json()
            content = body.get("content", "")
            if not isinstance(content, str) or not content.strip():
                return JSONResponse(
                    status_code=400,
                    content={"success": False, "message": "Imported settings file is empty."},
                )
            if len(content.encode("utf-8")) > 512 * 1024:
                return JSONResponse(
                    status_code=400,
                    content={"success": False, "message": "Imported settings file is too large."},
                )

            temp_name = ""
            try:
                with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".toml", delete=False) as temp:
                    temp.write(content)
                    temp_name = temp.name
                Config.load(Path(temp_name))
            finally:
                if temp_name:
                    Path(temp_name).unlink(missing_ok=True)

            config_path.parent.mkdir(parents=True, exist_ok=True)
            config_path.write_text(content, encoding="utf-8")
            return {
                "success": True,
                "needRestart": True,
                "applicationRestartRequired": True,
                "applicationRestartReasons": ["imported configuration"],
                "browserRefreshRequired": False,
                "browserRefreshReasons": [],
                "message": "Settings imported. Restart APRS PropView to load the imported configuration.",
            }

        except Exception as e:
            logger.warning("Config import failed: %s", e)
            return JSONResponse(
                status_code=400,
                content={"success": False, "message": "Imported settings could not be read as a valid PropView TOML config."},
            )

    @app.get("/api/browsers")
    async def get_browsers():
        return {"browsers": available_browsers()}

    @app.post("/api/config/save")
    async def save_config(request: Request):
        """Save configuration to config.toml. Hot-reloads most settings live."""
        try:
            body: Dict[str, Any] = await request.json()

            # Validate before applying. Full structural validation stays in
            # place, but operational checks are limited so users can save
            # dashboard/weather settings before configuring a real callsign.
            validation_error = _validate_save_request(body)
            if validation_error:
                logger.warning("Config save rejected: %s", validation_error)
                return JSONResponse(
                    status_code=400,
                    content={"success": False, "message": validation_error},
                )

            live_applied = []   # Settings applied immediately
            need_restart = []   # Settings that need a restart
            need_browser_refresh = []  # Saved UI changes that require a page reload

            # Snapshot APRS-IS settings before update (for change detection)
            old_aprs_is = (
                config.aprs_is.enabled,
                config.aprs_is.server,
                config.aprs_is.port,
                config.aprs_is.passcode,
                config.aprs_is.filter,
            )
            old_mqtt = _mqtt_snapshot()
            mqtt_save_requested = False

            # Update station config
            if "station" in body:
                s = body["station"]
                config.station.callsign = s.get("callsign", config.station.callsign)
                config.station.ssid = int(s.get("ssid", config.station.ssid))
                config.station.latitude = float(s.get("latitude", config.station.latitude))
                config.station.longitude = float(s.get("longitude", config.station.longitude))
                tracker.set_my_position(config.station.latitude, config.station.longitude)
                config.station.symbol_table = s.get("symbol_table", config.station.symbol_table)
                config.station.symbol_code = s.get("symbol_code", config.station.symbol_code)
                config.station.phg = (s.get("phg", config.station.phg) or "").strip().upper()
                config.station.equipment = (s.get("equipment", config.station.equipment) or "").strip()
                config.station.comment = s.get("comment", config.station.comment)
                config.station.beacon_interval = int(s.get("beacon_interval", config.station.beacon_interval))
                config.station.beacon_path = s.get("beacon_path", config.station.beacon_path)
                live_applied.append("station info & beacon")

            # Update digipeater config
            if "digipeater" in body:
                d = body["digipeater"]
                config.digipeater.enabled = bool(d.get("enabled", config.digipeater.enabled))
                if "aliases" in d:
                    aliases = d["aliases"]
                    if isinstance(aliases, str):
                        aliases = [a.strip() for a in aliases.split(",") if a.strip()]
                    config.digipeater.aliases = aliases
                config.digipeater.dedupe_interval = int(d.get("dedupe_interval", config.digipeater.dedupe_interval))
                live_applied.append("digipeater")

            # Update igate config
            if "igate" in body:
                ig = body["igate"]
                config.igate.enabled = bool(ig.get("enabled", config.igate.enabled))
                config.igate.rf_to_is = bool(ig.get("rf_to_is", config.igate.rf_to_is))
                config.igate.is_to_rf = bool(ig.get("is_to_rf", config.igate.is_to_rf))
                live_applied.append("igate")

            # Update APRS-IS config
            if "aprs_is" in body:
                a = body["aprs_is"]
                config.aprs_is.enabled = bool(a.get("enabled", config.aprs_is.enabled))
                config.aprs_is.server = a.get("server", config.aprs_is.server)
                config.aprs_is.port = int(a.get("port", config.aprs_is.port))
                # Don't overwrite passcode if client sent the masked version back
                new_passcode = a.get("passcode", "")
                if new_passcode and "*" not in new_passcode:
                    config.aprs_is.passcode = new_passcode
                config.aprs_is.filter = a.get("filter", config.aprs_is.filter)

            # Detect APRS-IS changes and trigger reconnect
            new_aprs_is = (
                config.aprs_is.enabled,
                config.aprs_is.server,
                config.aprs_is.port,
                config.aprs_is.passcode,
                config.aprs_is.filter,
            )
            if new_aprs_is != old_aprs_is and aprs_is:
                await aprs_is.reconnect()
                live_applied.append("APRS-IS (reconnecting)")

            # Update KISS serial config
            if "kiss_serial" in body:
                ks = body["kiss_serial"]
                old_kiss_serial = (
                    config.kiss_serial.enabled,
                    config.kiss_serial.port,
                    config.kiss_serial.baudrate,
                    config.kiss_serial.mode,
                    config.kiss_serial.flow_control,
                    config.kiss_serial.init_profile,
                    config.kiss_serial.init_commands,
                )
                config.kiss_serial.enabled = bool(ks.get("enabled", config.kiss_serial.enabled))
                config.kiss_serial.port = ks.get("port", config.kiss_serial.port)
                config.kiss_serial.baudrate = int(ks.get("baudrate", config.kiss_serial.baudrate))
                config.kiss_serial.mode = (ks.get("mode", config.kiss_serial.mode) or "kiss").strip().lower()
                config.kiss_serial.flow_control = (ks.get("flow_control", config.kiss_serial.flow_control) or "none").strip().lower()
                config.kiss_serial.init_profile = (ks.get("init_profile", config.kiss_serial.init_profile) or "none").strip().lower()
                config.kiss_serial.init_commands = ks.get("init_commands", config.kiss_serial.init_commands) or ""
                new_kiss_serial = (
                    config.kiss_serial.enabled,
                    config.kiss_serial.port,
                    config.kiss_serial.baudrate,
                    config.kiss_serial.mode,
                    config.kiss_serial.flow_control,
                    config.kiss_serial.init_profile,
                    config.kiss_serial.init_commands,
                )
                if new_kiss_serial != old_kiss_serial:
                    need_restart.append("KISS serial")

            # Update KISS TCP config
            if "kiss_tcp" in body:
                kt = body["kiss_tcp"]
                old_kiss_tcp = (
                    config.kiss_tcp.enabled,
                    config.kiss_tcp.host,
                    config.kiss_tcp.port,
                )
                config.kiss_tcp.enabled = bool(kt.get("enabled", config.kiss_tcp.enabled))
                config.kiss_tcp.host = kt.get("host", config.kiss_tcp.host)
                config.kiss_tcp.port = int(kt.get("port", config.kiss_tcp.port))
                new_kiss_tcp = (
                    config.kiss_tcp.enabled,
                    config.kiss_tcp.host,
                    config.kiss_tcp.port,
                )
                if new_kiss_tcp != old_kiss_tcp:
                    need_restart.append("KISS TCP")

            # Update multi RF port config. When this list is present it replaces
            # the legacy single serial/TCP startup path on the next restart.
            if "rf_ports" in body:
                old_rf_ports = _rf_ports_signature(config.rf_ports)
                legacy_rf_was_enabled = bool(config.kiss_serial.enabled or config.kiss_tcp.enabled)
                rf_ports = []
                for idx, item in enumerate(body["rf_ports"], 1):
                    port_type = (item.get("type", "serial") or "serial").strip().lower()
                    enabled = bool(item.get("enabled", True))
                    if port_type == "tcp":
                        host = (item.get("host", "127.0.0.1") or "127.0.0.1").strip()
                        tcp_port = int(item.get("tcp_port", 8001))
                        default_name = f"KISS TCP {host}:{tcp_port}"
                        rf_ports.append(RFPortConfig(
                            name=(item.get("name") or default_name).strip(),
                            enabled=enabled,
                            type="tcp",
                            host=host,
                            tcp_port=tcp_port,
                            protocol=(item.get("protocol", "kiss") or "kiss").strip().lower(),
                            mode="kiss",
                            rx_only_rf=bool(item.get("rx_only_rf", False)),
                            rx_only_is=bool(item.get("rx_only_is", False)),
                        ))
                    else:
                        serial_port = (item.get("port", "COM3") or "COM3").strip()
                        default_name = f"KISS Serial {serial_port}"
                        rf_ports.append(RFPortConfig(
                            name=(item.get("name") or default_name).strip(),
                            enabled=enabled,
                            type="serial",
                            port=serial_port,
                            baudrate=int(item.get("baudrate", 9600)),
                            mode=(item.get("mode", "kiss") or "kiss").strip().lower(),
                            flow_control=(item.get("flow_control", "none") or "none").strip().lower(),
                            init_profile=(item.get("init_profile", "none") or "none").strip().lower(),
                            init_commands=item.get("init_commands", "") or "",
                            rx_only_rf=bool(item.get("rx_only_rf", False)),
                            rx_only_is=bool(item.get("rx_only_is", False)),
                        ))
                config.rf_ports = rf_ports
                config.kiss_serial.enabled = False
                config.kiss_tcp.enabled = False
                if _rf_ports_signature(config.rf_ports) != old_rf_ports or legacy_rf_was_enabled:
                    need_restart.append("RF ports")

            # Update web config
            if "web" in body:
                w = body["web"]
                old_host = config.web.host
                old_port = config.web.port
                config.web.host = w.get("host", config.web.host)
                config.web.port = int(w.get("port", config.web.port))
                config.web.launch_browser = (w.get("launch_browser", config.web.launch_browser) or "").strip().lower()
                config.web.font_family = w.get("font_family", config.web.font_family) or ""
                config.web.map_tile_source = (w.get("map_tile_source", config.web.map_tile_source) or "osm").strip().lower()
                config.web.map_tile_url = (w.get("map_tile_url", config.web.map_tile_url) or "").strip()
                config.web.map_tile_attribution = (w.get("map_tile_attribution", config.web.map_tile_attribution) or "").strip()
                config.web.map_tile_max_zoom = min(22, max(1, int(w.get("map_tile_max_zoom", config.web.map_tile_max_zoom))))
                unit_system = (w.get("unit_system", config.web.unit_system) or "imperial").strip().lower()
                config.web.unit_system = unit_system if unit_system in {"imperial", "metric"} else "imperial"
                config.web.ghost_after_minutes = int(w.get("ghost_after_minutes", config.web.ghost_after_minutes))
                config.web.expire_after_minutes = int(w.get("expire_after_minutes", config.web.expire_after_minutes))
                config.web.mobile_pin = (w.get("mobile_pin", config.web.mobile_pin) or "").strip()
                config.web.update_check_enabled = bool(w.get("update_check_enabled", config.web.update_check_enabled))
                config.web.update_check_interval_hours = max(1, int(w.get("update_check_interval_hours", config.web.update_check_interval_hours)))
                config.web.visual_propagation_aura = bool(w.get("visual_propagation_aura", config.web.visual_propagation_aura))
                config.web.visual_path_reveal = bool(w.get("visual_path_reveal", config.web.visual_path_reveal))
                config.web.visual_map_harmony = bool(w.get("visual_map_harmony", config.web.visual_map_harmony))
                config.web.visual_condition_backdrop = bool(w.get("visual_condition_backdrop", config.web.visual_condition_backdrop))
                config.web.visual_home_marker = bool(w.get("visual_home_marker", config.web.visual_home_marker))
                config.web.visual_watched_path_flow = bool(w.get("visual_watched_path_flow", config.web.visual_watched_path_flow))
                config.web.visual_activity_moments = bool(w.get("visual_activity_moments", config.web.visual_activity_moments))
                packet_animation = str(w.get("visual_packet_animation", config.web.visual_packet_animation) or "basic").strip().lower()
                config.web.visual_packet_animation = packet_animation if packet_animation in {"off", "basic", "enhanced"} else "basic"
                if update_checker:
                    update_checker.configure(
                        config.web.update_check_enabled,
                        config.web.update_check_interval_hours * 3600,
                    )
                    await update_checker.stop_periodic_task()
                    update_checker.start_periodic_task()
                if config.web.host != old_host or config.web.port != old_port:
                    need_restart.append("web host/port")
                else:
                    live_applied.append("web UI")

            # Update GPS ingestion config
            if "gps" in body:
                g = body["gps"]
                config.gps.enabled = bool(g.get("enabled", config.gps.enabled))
                config.gps.source = (g.get("source", config.gps.source) or "browser").strip().lower()
                config.gps.map_update_enabled = bool(g.get("map_update_enabled", config.gps.map_update_enabled))
                config.gps.update_station_position = bool(g.get("update_station_position", config.gps.update_station_position))
                config.gps.station_position_locked = bool(g.get("station_position_locked", config.gps.station_position_locked))
                config.gps.serial_port = g.get("serial_port", config.gps.serial_port)
                config.gps.serial_baudrate = int(g.get("serial_baudrate", config.gps.serial_baudrate))
                config.gps.tcp_host = g.get("tcp_host", config.gps.tcp_host)
                config.gps.tcp_port = int(g.get("tcp_port", config.gps.tcp_port))
                config.gps.udp_host = g.get("udp_host", config.gps.udp_host)
                config.gps.udp_port = int(g.get("udp_port", config.gps.udp_port))
                config.gps.gpsd_host = g.get("gpsd_host", config.gps.gpsd_host)
                config.gps.gpsd_port = int(g.get("gpsd_port", config.gps.gpsd_port))
                live_applied.append("GPS ingestion")
                if gps_manager:
                    await ws_manager.broadcast({"type": "gps_location", "data": gps_manager.get_status()})

            # Update database config
            if "database" in body:
                db_cfg = body["database"]
                old_database_path = config.database.path
                config.database.path = db_cfg.get("path", config.database.path)
                if config.database.path != old_database_path:
                    need_restart.append("database path")

            # Update tracking config
            if "tracking" in body:
                t = body["tracking"]
                config.tracking.max_station_age = int(t.get("max_station_age", config.tracking.max_station_age))
                config.tracking.cleanup_interval = int(t.get("cleanup_interval", config.tracking.cleanup_interval))
                config.tracking.blocked_callsigns = StationTracker.normalize_blocked_callsigns(
                    t.get("blocked_callsigns", config.tracking.blocked_callsigns)
                )
                live_applied.append("tracking")

            if "watched_paths" in body:
                raw_paths = body["watched_paths"]
                if isinstance(raw_paths, str):
                    raw_paths = [line for line in raw_paths.splitlines() if line.strip()]
                parsed_paths = []
                path_items = raw_paths if isinstance(raw_paths, list) else []
                def watched_float(item, key, default, min_value=None, max_value=None):
                    try:
                        value = float(item.get(key, default) or default)
                    except (TypeError, ValueError):
                        value = float(default)
                    if min_value is not None:
                        value = max(float(min_value), value)
                    if max_value is not None:
                        value = min(float(max_value), value)
                    return value

                for item in path_items:
                    if isinstance(item, str):
                        parts = [part.strip() for part in item.split("|")]
                        if len(parts) < 2:
                            continue
                        if len(parts) >= 3 and re.fullmatch(r"-?\d+(?:\.\d+)?", parts[1] or ""):
                            item = {
                                "callsign": parts[0],
                                "latitude": parts[1],
                                "longitude": parts[2],
                                "band": parts[3] if len(parts) > 3 else "2m",
                                "min_confidence": parts[4] if len(parts) > 4 else "medium",
                                "mode": parts[5] if len(parts) > 5 else "",
                                "frequency_mhz": parts[6] if len(parts) > 6 else 0,
                                "my_antenna_height_m": parts[7] if len(parts) > 7 else 10.0,
                                "target_antenna_height_m": parts[8] if len(parts) > 8 else 10.0,
                                "my_tx_power_w": parts[9] if len(parts) > 9 else 50.0,
                                "my_antenna_gain_dbi": parts[10] if len(parts) > 10 else 0.0,
                            }
                        else:
                            item = {
                                "callsign": parts[0],
                                "grid": parts[1],
                                "latitude": 0,
                                "longitude": 0,
                                "band": parts[2] if len(parts) > 2 else "2m",
                                "min_confidence": parts[3] if len(parts) > 3 else "medium",
                                "mode": parts[4] if len(parts) > 4 else "",
                                "frequency_mhz": parts[5] if len(parts) > 5 else 0,
                                "my_antenna_height_m": parts[6] if len(parts) > 6 else 10.0,
                                "target_antenna_height_m": parts[7] if len(parts) > 7 else 10.0,
                                "my_tx_power_w": parts[8] if len(parts) > 8 else 50.0,
                                "my_antenna_gain_dbi": parts[9] if len(parts) > 9 else 0.0,
                            }
                    if not isinstance(item, dict):
                        continue
                    call = (item.get("callsign", "") or "").strip().upper()
                    if not call:
                        continue
                    confidence = (item.get("min_confidence", "medium") or "medium").strip().lower()
                    if confidence not in {"low", "medium", "high"}:
                        confidence = "medium"
                    parsed_paths.append(WatchedPathConfig(
                        enabled=bool(item.get("enabled", True)),
                        callsign=call,
                        latitude=float(item.get("latitude", 0) or 0),
                        longitude=float(item.get("longitude", 0) or 0),
                        grid=(item.get("grid", "") or "").strip().upper()[:8],
                        band=(item.get("band", "2m") or "2m").strip()[:24],
                        mode=(item.get("mode", "") or "").strip()[:24],
                        frequency_mhz=watched_float(item, "frequency_mhz", 0.0, 0.0, 10000.0),
                        min_confidence=confidence,
                        bearing_tolerance_deg=max(5, min(90, int(item.get("bearing_tolerance_deg", 30) or 30))),
                        min_probe_count=max(1, min(10, int(item.get("min_probe_count", 2) or 2))),
                        target_area_radius_km=watched_float(item, "target_area_radius_km", 100.0, 10.0, 500.0),
                        max_age_minutes=max(5, min(360, int(item.get("max_age_minutes", 60) or 60))),
                        alert_cooldown_minutes=max(5, min(1440, int(item.get("alert_cooldown_minutes", 30) or 30))),
                        my_antenna_height_m=watched_float(item, "my_antenna_height_m", 10.0, 0.0, 610.0),
                        target_antenna_height_m=watched_float(item, "target_antenna_height_m", 10.0, 0.0, 610.0),
                        my_tx_power_w=watched_float(item, "my_tx_power_w", 50.0, 0.1, 2000.0),
                        my_antenna_gain_dbi=watched_float(item, "my_antenna_gain_dbi", 0.0, -20.0, 30.0),
                    ))
                config.watched_paths = parsed_paths[:50]
                live_applied.append("watched paths")

            if "callbook" in body:
                cb = body["callbook"]
                provider = (cb.get("provider", config.callbook.provider) or "auto").strip().lower()
                if provider not in {"auto", "callook", "hamdb", "hamqth", "qrz"}:
                    provider = "auto"
                config.callbook.provider = provider
                config.callbook.hamqth_username = (cb.get("hamqth_username", config.callbook.hamqth_username) or "").strip()
                config.callbook.hamqth_password = _merge_secret_value(
                    config.callbook.hamqth_password,
                    cb.get("hamqth_password", ""),
                    submitted_present="hamqth_password" in cb,
                )
                config.callbook.qrz_username = (cb.get("qrz_username", config.callbook.qrz_username) or "").strip()
                config.callbook.qrz_password = _merge_secret_value(
                    config.callbook.qrz_password,
                    cb.get("qrz_password", ""),
                    submitted_present="qrz_password" in cb,
                )
                live_applied.append("callbook")

            if "messaging" in body:
                m = body["messaging"]
                config.messaging.message_retention_days = max(1, int(m.get("message_retention_days", config.messaging.message_retention_days)))
                config.messaging.receive_sibling_ssids = bool(m.get("receive_sibling_ssids", config.messaging.receive_sibling_ssids))
                await handler.cleanup_messages()
                live_applied.append("messaging")

            # Update alerts config
            if "alerts" in body:
                al = body["alerts"]
                config.alerts.enabled = bool(al.get("enabled", config.alerts.enabled))
                config.alerts.anomaly_alert_enabled = bool(al.get("anomaly_alert_enabled", config.alerts.anomaly_alert_enabled))
                config.alerts.sporadic_e_alert_enabled = bool(al.get("sporadic_e_alert_enabled", config.alerts.sporadic_e_alert_enabled))
                config.alerts.my_min_stations = max(1, int(al.get("my_min_stations", config.alerts.my_min_stations)))
                config.alerts.my_min_distance_km = max(1.0, float(al.get("my_min_distance_km", config.alerts.my_min_distance_km)))
                config.alerts.regional_min_stations = max(1, int(al.get("regional_min_stations", config.alerts.regional_min_stations)))
                config.alerts.regional_min_distance_km = max(1.0, float(al.get("regional_min_distance_km", config.alerts.regional_min_distance_km)))
                config.alerts.cooldown_seconds = int(al.get("cooldown_seconds", config.alerts.cooldown_seconds))
                config.alerts.quiet_start = al.get("quiet_start", config.alerts.quiet_start) or ""
                config.alerts.quiet_end = al.get("quiet_end", config.alerts.quiet_end) or ""
                config.alerts.msg_notify_enabled = bool(al.get("msg_notify_enabled", config.alerts.msg_notify_enabled))
                config.alerts.msg_discord_enabled = bool(al.get("msg_discord_enabled", config.alerts.msg_discord_enabled))
                config.alerts.msg_email_enabled = bool(al.get("msg_email_enabled", config.alerts.msg_email_enabled))
                config.alerts.msg_sms_enabled = bool(al.get("msg_sms_enabled", config.alerts.msg_sms_enabled))
                config.alerts.audio_output_device_id = (al.get("audio_output_device_id", config.alerts.audio_output_device_id) or "").strip()
                for alert_key, attr in ALERT_AUDIO_KEYS.items():
                    value = al.get(attr, getattr(config.alerts, attr))
                    setattr(config.alerts, attr, _safe_alert_audio_filename(value) if value else "")
                config.alerts.discord_enabled = bool(al.get("discord_enabled", config.alerts.discord_enabled))
                config.alerts.discord_webhook_url = al.get("discord_webhook_url", config.alerts.discord_webhook_url)
                config.alerts.email_enabled = bool(al.get("email_enabled", config.alerts.email_enabled))
                config.alerts.email_smtp_server = al.get("email_smtp_server", config.alerts.email_smtp_server)
                config.alerts.email_smtp_port = int(al.get("email_smtp_port", config.alerts.email_smtp_port))
                config.alerts.email_from = al.get("email_from", config.alerts.email_from)
                config.alerts.email_to = al.get("email_to", config.alerts.email_to)
                new_email_pw = al.get("email_password", "")
                if new_email_pw and "*" not in new_email_pw:
                    config.alerts.email_password = new_email_pw
                config.alerts.sms_enabled = bool(al.get("sms_enabled", config.alerts.sms_enabled))
                config.alerts.sms_gateway_address = al.get("sms_gateway_address", config.alerts.sms_gateway_address)

                # Sync alert_manager config at runtime
                if alert_manager:
                    from server.alerts import AlertConfig
                    alert_manager.config = AlertConfig(
                        enabled=config.alerts.enabled,
                        anomaly_alert_enabled=config.alerts.anomaly_alert_enabled,
                        sporadic_e_alert_enabled=config.alerts.sporadic_e_alert_enabled,
                        my_min_stations=config.alerts.my_min_stations,
                        my_min_distance_km=config.alerts.my_min_distance_km,
                        regional_min_stations=config.alerts.regional_min_stations,
                        regional_min_distance_km=config.alerts.regional_min_distance_km,
                        cooldown_seconds=config.alerts.cooldown_seconds,
                        quiet_start=config.alerts.quiet_start,
                        quiet_end=config.alerts.quiet_end,
                        msg_notify_enabled=config.alerts.msg_notify_enabled,
                        msg_discord_enabled=config.alerts.msg_discord_enabled,
                        msg_email_enabled=config.alerts.msg_email_enabled,
                        msg_sms_enabled=config.alerts.msg_sms_enabled,
                        discord_enabled=config.alerts.discord_enabled,
                        discord_webhook_url=config.alerts.discord_webhook_url,
                        email_enabled=config.alerts.email_enabled,
                        email_smtp_server=config.alerts.email_smtp_server,
                        email_smtp_port=config.alerts.email_smtp_port,
                        email_from=config.alerts.email_from,
                        email_to=config.alerts.email_to,
                        email_password=config.alerts.email_password,
                        sms_enabled=config.alerts.sms_enabled,
                        sms_gateway_address=config.alerts.sms_gateway_address,
                    )
                live_applied.append("alerts")

            # Update weather config
            if "weather" in body:
                wc = body["weather"]
                config.weather.enabled = bool(wc.get("enabled", config.weather.enabled))
                config.weather.location_code = (wc.get("location_code", config.weather.location_code) or "").strip()
                current_provider = (wc.get("current_provider", config.weather.current_provider) or "open_meteo").strip().lower()
                config.weather.current_provider = current_provider if current_provider in {"open_meteo", "wxnow"} else "open_meteo"
                config.weather.wxnow_condition_fallback_enabled = bool(wc.get(
                    "wxnow_condition_fallback_enabled",
                    config.weather.wxnow_condition_fallback_enabled,
                ))
                alert_provider = (wc.get("alert_provider", config.weather.alert_provider) or "auto").strip().lower()
                if alert_provider in {"nws", "open_meteo_risk"}:
                    alert_provider = "auto"
                config.weather.alert_provider = alert_provider if alert_provider in {"auto", "weatherbit", "disabled"} else "auto"
                new_weatherbit_key = wc.get("weatherbit_api_key", "")
                if new_weatherbit_key and "*" not in new_weatherbit_key:
                    config.weather.weatherbit_api_key = new_weatherbit_key.strip()
                config.weather.weatherbit_poll_minutes = max(30, int(wc.get("weatherbit_poll_minutes", config.weather.weatherbit_poll_minutes)))
                config.weather.alert_range_miles = max(1, int(wc.get("alert_range_miles", config.weather.alert_range_miles)))
                config.weather.refresh_minutes = max(5, int(wc.get("refresh_minutes", config.weather.refresh_minutes)))
                config.weather.radar_enabled = bool(wc.get("radar_enabled", config.weather.radar_enabled))
                provider = (wc.get("radar_provider", config.weather.radar_provider) or "rainviewer").strip().lower()
                valid_radar_providers = {"rainviewer", "iem_nexrad", "custom_xyz", "custom_wms"}
                config.weather.radar_provider = provider if provider in valid_radar_providers else "rainviewer"
                config.weather.radar_custom_url = (wc.get("radar_custom_url", config.weather.radar_custom_url) or "").strip()
                config.weather.radar_custom_layer = (wc.get("radar_custom_layer", config.weather.radar_custom_layer) or "").strip()
                config.weather.radar_custom_attribution = (wc.get("radar_custom_attribution", config.weather.radar_custom_attribution) or "").strip()
                new_radar_key = wc.get("radar_custom_api_key", "")
                if new_radar_key and "*" not in new_radar_key:
                    config.weather.radar_custom_api_key = new_radar_key.strip()
                config.weather.radar_opacity = min(1.0, max(0.1, float(wc.get("radar_opacity", config.weather.radar_opacity))))
                config.weather.radar_animate = bool(wc.get("radar_animate", config.weather.radar_animate))
                config.weather.alert_overlay_enabled = bool(wc.get("alert_overlay_enabled", config.weather.alert_overlay_enabled))
                config.weather.alert_overlay_range_miles = max(1, int(wc.get("alert_overlay_range_miles", config.weather.alert_overlay_range_miles)))
                groups = wc.get("alert_overlay_groups", config.weather.alert_overlay_groups)
                if not isinstance(groups, list):
                    groups = config.weather.alert_overlay_groups
                valid_groups = {"warnings", "watches", "flood", "winter", "marine", "fire_heat", "other"}
                config.weather.alert_overlay_groups = [g for g in groups if g in valid_groups]
                scope_mode = (wc.get("alert_scope_mode", config.weather.alert_scope_mode) or "point").strip().lower()
                config.weather.alert_scope_mode = scope_mode if scope_mode in {"point", "county_zone", "radius"} else "point"
                config.weather.alert_scope_zone = (wc.get("alert_scope_zone", config.weather.alert_scope_zone) or "").strip().upper()
                config.weather.elevated_alert_polling_enabled = bool(wc.get("elevated_alert_polling_enabled", config.weather.elevated_alert_polling_enabled))
                config.weather.elevated_alert_polling_seconds = max(30, int(wc.get("elevated_alert_polling_seconds", config.weather.elevated_alert_polling_seconds)))
                config.weather.elevated_alert_cooldown_minutes = max(1, int(wc.get("elevated_alert_cooldown_minutes", config.weather.elevated_alert_cooldown_minutes)))
                trigger_events = wc.get("elevated_trigger_events", config.weather.elevated_trigger_events)
                if not isinstance(trigger_events, list):
                    trigger_events = config.weather.elevated_trigger_events
                config.weather.elevated_trigger_events = [
                    str(event).strip() for event in trigger_events if str(event).strip()
                ]
                config.weather.weather_alert_symbol_enabled = bool(wc.get(
                    "weather_alert_symbol_enabled",
                    config.weather.weather_alert_symbol_enabled,
                ))
                live_applied.append("weather")

            if "wxnow" in body:
                wx = body["wxnow"]
                config.wxnow.enabled = bool(wx.get("enabled", config.wxnow.enabled))
                config.wxnow.file_path = (wx.get("file_path", config.wxnow.file_path) or "").strip()
                config.wxnow.ssid = max(0, min(15, int(wx.get("ssid", config.wxnow.ssid))))
                config.wxnow.beacon_interval = max(600, int(wx.get("beacon_interval", config.wxnow.beacon_interval)))
                config.wxnow.max_age_minutes = max(1, int(wx.get("max_age_minutes", config.wxnow.max_age_minutes)))
                config.wxnow.include_position = bool(wx.get("include_position", config.wxnow.include_position))
                mode = (wx.get("mode", config.wxnow.mode) or "both").strip().lower()
                config.wxnow.mode = mode if mode in {"both", "rf", "aprs_is"} else "both"
                config.wxnow.path = (wx.get("path", config.wxnow.path) or "").strip()
                config.wxnow.symbol_table = (wx.get("symbol_table", config.wxnow.symbol_table) or "/")[:1]
                config.wxnow.symbol_code = (wx.get("symbol_code", config.wxnow.symbol_code) or "_")[:1]
                live_applied.append("WXnow transmit")

            # Update propagation config
            if "propagation" in body:
                pc = body["propagation"]
                config.propagation.my_station_full_count = max(1, int(pc.get("my_station_full_count", config.propagation.my_station_full_count)))
                config.propagation.my_station_full_dist_km = max(1.0, float(pc.get("my_station_full_dist_km", config.propagation.my_station_full_dist_km)))
                config.propagation.regional_full_count = max(1, int(pc.get("regional_full_count", config.propagation.regional_full_count)))
                config.propagation.regional_full_dist_km = max(1.0, float(pc.get("regional_full_dist_km", config.propagation.regional_full_dist_km)))
                live_applied.append("propagation meters")

            if "status" in body:
                st = body["status"]
                config.status.enabled = bool(st.get("enabled", config.status.enabled))
                config.status.beacon_interval = max(600, int(st.get("beacon_interval", config.status.beacon_interval)))
                mode = (st.get("mode", config.status.mode) or "both").strip().lower()
                config.status.mode = mode if mode in {"both", "rf", "aprs_is"} else "both"
                config.status.path = (st.get("path", config.status.path) or "").strip()
                config.status.report_window_minutes = max(15, int(st.get("report_window_minutes", config.status.report_window_minutes)))
                config.status.max_length = min(120, max(20, int(st.get("max_length", config.status.max_length))))
                source = (st.get("source", config.status.source) or "dx").strip().lower()
                config.status.source = source if source in {"dx", "dynamic", "mheard"} else "dx"
                order = (st.get("dynamic_order", config.status.dynamic_order) or "sequential").strip().lower()
                config.status.dynamic_order = order if order in {"sequential", "random"} else "sequential"
                dynamic_messages = st.get("dynamic_messages", config.status.dynamic_messages)
                if isinstance(dynamic_messages, str):
                    dynamic_messages = [line.strip() for line in dynamic_messages.splitlines()]
                if not isinstance(dynamic_messages, list):
                    dynamic_messages = config.status.dynamic_messages
                config.status.dynamic_messages = [
                    str(message).strip()
                    for message in dynamic_messages[:20]
                    if str(message).strip()
                ]
                config.status.weather_alert_beacon_enabled = bool(st.get(
                    "weather_alert_beacon_enabled",
                    config.status.weather_alert_beacon_enabled,
                ))
                config.status.weather_alert_cooldown_minutes = max(1, int(st.get(
                    "weather_alert_cooldown_minutes",
                    config.status.weather_alert_cooldown_minutes,
                )))
                live_applied.append("Status/DX transmit")

            if "smart_beaconing" in body:
                sb = body["smart_beaconing"]
                config.smart_beaconing.enabled = bool(sb.get("enabled", config.smart_beaconing.enabled))
                config.smart_beaconing.slow_interval = max(600, int(sb.get("slow_interval", config.smart_beaconing.slow_interval)))
                config.smart_beaconing.fast_interval = max(60, int(sb.get("fast_interval", config.smart_beaconing.fast_interval)))
                config.smart_beaconing.speed_threshold_mph = max(0.0, float(sb.get("speed_threshold_mph", config.smart_beaconing.speed_threshold_mph)))
                live_applied.append("smart beaconing")

            if "bulletins" in body:
                bln = body["bulletins"]
                config.bulletins.enabled = bool(bln.get("enabled", config.bulletins.enabled))
                config.bulletins.interval = max(600, int(bln.get("interval", config.bulletins.interval)))
                mode = (bln.get("mode", config.bulletins.mode) or "both").strip().lower()
                config.bulletins.mode = mode if mode in {"both", "rf", "aprs_is"} else "both"
                config.bulletins.path = (bln.get("path", config.bulletins.path) or "").strip()
                items = bln.get("items", config.bulletins.items)
                if isinstance(items, str):
                    parsed = []
                    for line in items.splitlines():
                        if not line.strip():
                            continue
                        ident, sep, text = line.partition("|")
                        parsed.append({"id": ident.strip() or str(len(parsed) + 1), "text": text.strip() if sep else ident.strip()})
                    items = parsed
                config.bulletins.items = [
                    {"id": str(item.get("id", "1")).strip()[:5], "text": str(item.get("text", "")).strip()[:67]}
                    for item in (items if isinstance(items, list) else [])
                    if str(item.get("text", "")).strip()
                ][:10]
                live_applied.append("bulletins")

            if "aprs_objects" in body:
                obj = body["aprs_objects"]
                config.aprs_objects.enabled = bool(obj.get("enabled", config.aprs_objects.enabled))
                config.aprs_objects.interval = max(600, int(obj.get("interval", config.aprs_objects.interval)))
                mode = (obj.get("mode", config.aprs_objects.mode) or "both").strip().lower()
                config.aprs_objects.mode = mode if mode in {"both", "rf", "aprs_is"} else "both"
                config.aprs_objects.path = (obj.get("path", config.aprs_objects.path) or "").strip()
                items = obj.get("items", config.aprs_objects.items)
                if isinstance(items, str):
                    parsed = []
                    for line in items.splitlines():
                        parts = [p.strip() for p in line.split("|")]
                        if len(parts) >= 3:
                            parsed.append({
                                "name": parts[0],
                                "latitude": parts[1],
                                "longitude": parts[2],
                                "symbol_table": parts[3] if len(parts) > 3 else "\\",
                                "symbol_code": parts[4] if len(parts) > 4 else "\\",
                                "comment": parts[5] if len(parts) > 5 else "",
                                "enabled": parts[6].lower() != "false" if len(parts) > 6 else True,
                                "active": parts[7].lower() != "false" if len(parts) > 7 else True,
                                "permanent": parts[8].lower() == "true" if len(parts) > 8 else False,
                                "scope": parts[9] if len(parts) > 9 else "global",
                                "speed_mph": parts[10] if len(parts) > 10 else 0,
                                "course_deg": parts[11] if len(parts) > 11 else 0,
                                "frequency": parts[12] if len(parts) > 12 else "",
                                "tone": parts[13] if len(parts) > 13 else "",
                                "duplex": parts[14] if len(parts) > 14 else "",
                                "qru": parts[15] if len(parts) > 15 else "",
                                "path": parts[16] if len(parts) > 16 else "",
                                "mode": parts[17] if len(parts) > 17 else "",
                                "overlay": parts[18] if len(parts) > 18 else "",
                            })
                    items = parsed
                cleaned = []
                for item in (items if isinstance(items, list) else []):
                    cleaned_item = _clean_aprs_object_item(item)
                    if cleaned_item:
                        cleaned.append(cleaned_item)
                config.aprs_objects.items = cleaned[:50]
                live_applied.append("APRS objects")

            # Update MQTT config
            if "mqtt" in body:
                mqtt_save_requested = True
                mc = body["mqtt"]
                config.mqtt.enabled = bool(mc.get("enabled", config.mqtt.enabled))
                config.mqtt.broker = mc.get("broker", config.mqtt.broker)
                config.mqtt.port = int(mc.get("port", config.mqtt.port))
                config.mqtt.topic_prefix = (mc.get("topic_prefix", config.mqtt.topic_prefix) or "aprs/propview").strip().strip("/")
                config.mqtt.username = mc.get("username", config.mqtt.username)
                config.mqtt.password = _merge_secret_value(
                    config.mqtt.password,
                    mc.get("password", ""),
                    submitted_present="password" in mc,
                )
                config.mqtt.discovery_enabled = bool(mc.get("discovery_enabled", config.mqtt.discovery_enabled))
                config.mqtt.discovery_prefix = (mc.get("discovery_prefix", config.mqtt.discovery_prefix) or "homeassistant").strip().strip("/")
                config.mqtt.device_name = (mc.get("device_name", config.mqtt.device_name) or "APRS PropView").strip()
                config.mqtt.device_id = (mc.get("device_id", config.mqtt.device_id) or "aprs_propview").strip()
                watched = mc.get("watched_callsigns", config.mqtt.watched_callsigns)
                if isinstance(watched, str):
                    watched = re.split(r"[\s,]+", watched)
                if not isinstance(watched, list):
                    watched = config.mqtt.watched_callsigns
                normalized_watched = []
                seen_watched = set()
                for value in watched:
                    call = str(value or "").strip().upper()
                    if not call or call in seen_watched:
                        continue
                    if not re.fullmatch(r"[A-Z0-9]{1,9}(?:-[0-9]{1,2})?", call):
                        continue
                    seen_watched.add(call)
                    normalized_watched.append(call)
                config.mqtt.watched_callsigns = normalized_watched[:40]

            config.save(config_path)
            if mqtt_save_requested:
                if _mqtt_snapshot() != old_mqtt or (config.mqtt.enabled and not mqtt_state.get("publisher")):
                    live_applied.append(await _apply_mqtt_runtime())
                else:
                    live_applied.append("MQTT unchanged")
            logger.info(
                "Config saved: weather enabled=%s location=%s radar=%s polygons=%s scope=%s/%s",
                config.weather.enabled,
                config.weather.location_code or "<unset>",
                config.weather.radar_enabled,
                config.weather.alert_overlay_enabled,
                config.weather.alert_scope_mode,
                config.weather.alert_scope_zone or "<unset>",
            )

            container_override_warnings = _container_env_override_warnings(body)

            # Build response message
            parts = []
            if need_restart:
                parts.append(f"Application restart required for: {', '.join(need_restart)}.")
            elif need_browser_refresh:
                parts.append(
                    f"Browser refresh required for: {', '.join(need_browser_refresh)}. "
                    "APRS PropView does not need to be restarted."
                )
            else:
                parts.append("Settings saved and applied. No browser refresh or application restart is needed.")
            if container_override_warnings:
                parts.append(
                    "Container environment overrides are active; after a Docker/TrueNAS restart these saved values "
                    f"may be replaced unless changed in the app's environment: {'; '.join(container_override_warnings)}."
                )

            return {
                "success": True,
                "message": " ".join(parts),
                "needRestart": bool(need_restart),
                "applicationRestartRequired": bool(need_restart),
                "applicationRestartReasons": need_restart,
                "browserRefreshRequired": bool(need_browser_refresh),
                "browserRefreshReasons": need_browser_refresh,
                "liveApplied": live_applied,
                "containerOverrideWarnings": container_override_warnings,
            }

        except Exception as e:
            logger.error(f"Failed to save config: {e}")
            return JSONResponse(
                status_code=500,
                content={"success": False, "message": "Error saving configuration. Check server logs for details."},
            )

    return app
