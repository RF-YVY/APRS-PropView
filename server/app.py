"""FastAPI web application — serves UI and WebSocket endpoints."""

import re
import time
import logging
from pathlib import Path
from typing import Optional, Dict, Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from server.config import (
    Config, StationConfig, DigiConfig, IGateConfig, APRSISConfig,
    KISSSerialConfig, KISSTCPConfig, WebConfig, DatabaseConfig, TrackingConfig,
    AlertsConfig, PropagationConfig, WeatherConfig, MQTTConfig,
)
from server.database import Database
from server.station_tracker import StationTracker
from server.websocket_manager import WebSocketManager
from server.packet_handler import PacketHandler
from server.analytics import AnalyticsEngine
from server.alerts import AlertManager
from server.aprs_is import APRSISClient
from server.weather import WeatherManager

logger = logging.getLogger("propview.app")

# Support PyInstaller frozen builds
import sys as _sys
if getattr(_sys, 'frozen', False):
    STATIC_DIR = Path(_sys._MEIPASS) / "static"
else:
    STATIC_DIR = Path(__file__).parent.parent / "static"

# ── Validation helpers ──────────────────────────────────────────────

# Amateur callsign: 1-2 letter prefix + digit + 1-3 letter suffix, optional SSID
_CALLSIGN_RE = re.compile(r'^[A-Za-z]{1,2}[0-9][A-Za-z]{1,3}$')
_HOSTNAME_RE = re.compile(r'^[A-Za-z0-9._-]{1,253}$')
_SAFE_PATH_RE = re.compile(r'^[A-Za-z0-9._-]{1,100}$')
_FILTER_TOKEN_RE = re.compile(r'^[a-z]/[\w.\-*/,]+$', re.IGNORECASE)
# Disallowed callsigns (common placeholders)
_BLOCKED_CALLSIGNS = {'N0CALL', 'NOCALL', 'MYCALL', 'TEST'}


def _mask_passcode(passcode: str) -> str:
    """Mask passcode for API responses — show only last char."""
    if not passcode or passcode == "-1":
        return passcode
    return "*" * (len(passcode) - 1) + passcode[-1]


def _validate_config(body: Dict[str, Any]) -> Optional[str]:
    """Validate config values per APRS-IS usage policies.
    Returns an error message or None if valid."""

    warnings = []  # Non-blocking policy warnings

    if "station" in body:
        s = body["station"]
        call = (s.get("callsign", "") or "").strip().upper()
        if call:
            if not _CALLSIGN_RE.match(call):
                return "Invalid callsign format. Must be a valid amateur radio callsign (e.g. W1ABC, KA9XYZ)."
            if call in _BLOCKED_CALLSIGNS:
                return f"'{call}' is a placeholder callsign. Enter your real amateur radio callsign."
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
                if not _FILTER_TOKEN_RE.match(token):
                    return f"Invalid APRS-IS filter token: '{token}'. Filters use format like r/lat/lon/range, b/CALL, t/poimq etc."

    # IGate policy checks
    if "igate" in body:
        ig = body["igate"]
        station = body.get("station", {})
        aprs_is_cfg = body.get("aprs_is", {})
        call = (station.get("callsign", "") or "").strip().upper()
        passcode = aprs_is_cfg.get("passcode", "")
        # Warn if IGate enabled but callsign is placeholder
        if ig.get("enabled") and call in _BLOCKED_CALLSIGNS:
            return "IGate requires a valid amateur radio callsign. Change your callsign from the default."
        # Warn if IGate RF→IS enabled with read-only passcode
        if ig.get("rf_to_is") and passcode == "-1":
            return "RF→APRS-IS gating requires a valid APRS-IS passcode. Read-only (passcode -1) cannot inject packets."

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

    if "database" in body:
        db_cfg = body["database"]
        dbpath = db_cfg.get("path", "")
        if dbpath and not _SAFE_PATH_RE.match(dbpath):
            return "Database path must be a simple filename (alphanumeric, dots, hyphens, underscores only)."

    return None


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
    app_version: str = "1.0.0",
) -> FastAPI:
    """Create and configure the FastAPI application."""

    app = FastAPI(title="APRS PropView", version=app_version)

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

    @app.get("/")
    async def index():
        return FileResponse(str(STATIC_DIR / "index.html"))

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
            rf_stations = await tracker.get_rf_stations()
            is_stations = await tracker.get_is_stations()
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

    @app.get("/api/status")
    async def get_status():
        return handler.get_status()

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

    @app.get("/api/packets")
    async def get_packets(
        limit: int = Query(100, ge=1, le=1000),
        source: Optional[str] = Query(None),
    ):
        packets = await db.get_recent_packets(limit=limit, source=source)
        return {"packets": packets, "count": len(packets)}

    @app.get("/api/propagation")
    async def get_propagation():
        return await tracker.get_propagation_data()

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
        handler.clear_messages()
        return {"success": True, "message": "Messages cleared."}

    @app.post("/api/messages/send")
    async def send_message(request: Request):
        """Send an APRS message to another station."""
        try:
            body = await request.json()
            to_call = (body.get("to", "") or "").strip().upper()
            text = (body.get("text", "") or "").strip()
            reply_source = (body.get("reply_source", "") or "").strip().lower()

            if not to_call:
                return JSONResponse(
                    status_code=400,
                    content={"success": False, "message": "Recipient callsign is required."},
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
            if not _CALLSIGN_RE.match(to_call.split("-")[0]):
                return JSONResponse(
                    status_code=400,
                    content={"success": False, "message": "Invalid recipient callsign format."},
                )
            if reply_source and reply_source not in {"rf", "aprs_is"}:
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
            return JSONResponse(
                status_code=400,
                content={"success": False, "message": str(e)},
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
            return JSONResponse(
                status_code=400,
                content={"success": False, "message": str(e)},
            )
        except Exception as e:
            logger.error(f"Failed to transmit beacon: {e}")
            return JSONResponse(
                status_code=500,
                content={"success": False, "message": "Error transmitting beacon."},
            )

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
    async def get_sporadic_e():
        if not analytics:
            return {"es_level": "none", "es_score": 0, "candidates": []}
        return await analytics.detect_sporadic_e()

    @app.get("/api/analytics/observed-range")
    async def get_observed_range(
        hours: int = Query(24, ge=1, le=168),
    ):
        if not analytics:
            return {"sectors": [], "max_range_km": 0}
        return await analytics.get_observed_range(hours=hours)

    @app.get("/api/analytics/path-quality/{callsign}")
    async def get_path_quality(callsign: str):
        history = await db.get_path_history(callsign.upper())
        return {"callsign": callsign.upper(), "history": history, "count": len(history)}

    @app.get("/api/first-heard")
    async def get_first_heard(
        hours: int = Query(24, ge=1, le=168),
    ):
        log = await db.get_first_heard_log(hours=hours)
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
        fmt: str = Query("json", regex="^(json|csv)$"),
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
        fmt: str = Query("json", regex="^(json|csv)$"),
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
        fmt: str = Query("json", regex="^(json|csv)$"),
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

    # ── Weather API ─────────────────────────────────────────────

    @app.get("/api/weather")
    async def get_weather():
        """Get current weather conditions and NWS alerts."""
        if not weather_manager:
            return {"enabled": False, "configured": False}
        try:
            return await weather_manager.get_all()
        except Exception as e:
            logger.error(f"Weather fetch error: {e}")
            return {"enabled": config.weather.enabled, "configured": False, "error": str(e)}

    @app.get("/api/weather/refresh")
    async def refresh_weather():
        """Force-refresh weather data from APIs."""
        if not weather_manager:
            return {"enabled": False, "configured": False}
        try:
            return await weather_manager.get_all(force=True)
        except Exception as e:
            logger.error(f"Weather refresh error: {e}")
            return {"enabled": config.weather.enabled, "configured": False, "error": str(e)}

    @app.post("/api/weather/resolve-location")
    async def resolve_weather_location(request: Request):
        """Resolve a US zip code or ICAO code to lat/lon for weather."""
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
                    content={"success": False, "message": f"Could not resolve '{code}'. Enter a valid US zip code (e.g. 28801) or ICAO code (e.g. KAVL)."},
                )
            return {"success": True, "location": result}
        except Exception as e:
            logger.error(f"Location resolve error: {e}")
            return JSONResponse(
                status_code=500,
                content={"success": False, "message": "Error resolving location."},
            )

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
                "filter": config.aprs_is.filter,
            },
            "kiss_serial": {
                "enabled": config.kiss_serial.enabled,
                "port": config.kiss_serial.port,
                "baudrate": config.kiss_serial.baudrate,
            },
            "kiss_tcp": {
                "enabled": config.kiss_tcp.enabled,
                "host": config.kiss_tcp.host,
                "port": config.kiss_tcp.port,
            },
            "web": {
                "host": config.web.host,
                "port": config.web.port,
                "font_family": config.web.font_family,
                "ghost_after_minutes": config.web.ghost_after_minutes,
                "expire_after_minutes": config.web.expire_after_minutes,
                "mobile_pin": config.web.mobile_pin,
            },
            "database": {
                "path": config.database.path,
            },
            "tracking": {
                "max_station_age": config.tracking.max_station_age,
                "cleanup_interval": config.tracking.cleanup_interval,
            },
            "alerts": {
                "enabled": config.alerts.enabled,
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
                "alert_range_miles": config.weather.alert_range_miles,
                "refresh_minutes": config.weather.refresh_minutes,
            },
            "propagation": {
                "my_station_full_count": config.propagation.my_station_full_count,
                "my_station_full_dist_km": config.propagation.my_station_full_dist_km,
                "regional_full_count": config.propagation.regional_full_count,
                "regional_full_dist_km": config.propagation.regional_full_dist_km,
            },
            "mqtt": {
                "enabled": config.mqtt.enabled,
                "broker": config.mqtt.broker,
                "port": config.mqtt.port,
                "topic_prefix": config.mqtt.topic_prefix,
                "username": config.mqtt.username,
                "password": _mask_passcode(config.mqtt.password),
            },
        }

    @app.post("/api/config/save")
    async def save_config(request: Request):
        """Save configuration to config.toml. Hot-reloads most settings live."""
        try:
            body: Dict[str, Any] = await request.json()

            # Validate before applying
            validation_error = _validate_config(body)
            if validation_error:
                return JSONResponse(
                    status_code=400,
                    content={"success": False, "message": validation_error},
                )

            live_applied = []   # Settings applied immediately
            need_restart = []   # Settings that need a restart

            # Snapshot APRS-IS settings before update (for change detection)
            old_aprs_is = (
                config.aprs_is.enabled,
                config.aprs_is.server,
                config.aprs_is.port,
                config.aprs_is.passcode,
                config.aprs_is.filter,
            )

            # Update station config
            if "station" in body:
                s = body["station"]
                config.station.callsign = s.get("callsign", config.station.callsign)
                config.station.ssid = int(s.get("ssid", config.station.ssid))
                config.station.latitude = float(s.get("latitude", config.station.latitude))
                config.station.longitude = float(s.get("longitude", config.station.longitude))
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
                config.kiss_serial.enabled = bool(ks.get("enabled", config.kiss_serial.enabled))
                config.kiss_serial.port = ks.get("port", config.kiss_serial.port)
                config.kiss_serial.baudrate = int(ks.get("baudrate", config.kiss_serial.baudrate))
                need_restart.append("KISS serial")

            # Update KISS TCP config
            if "kiss_tcp" in body:
                kt = body["kiss_tcp"]
                config.kiss_tcp.enabled = bool(kt.get("enabled", config.kiss_tcp.enabled))
                config.kiss_tcp.host = kt.get("host", config.kiss_tcp.host)
                config.kiss_tcp.port = int(kt.get("port", config.kiss_tcp.port))
                need_restart.append("KISS TCP")

            # Update web config
            if "web" in body:
                w = body["web"]
                config.web.host = w.get("host", config.web.host)
                config.web.port = int(w.get("port", config.web.port))
                config.web.font_family = w.get("font_family", config.web.font_family) or ""
                config.web.ghost_after_minutes = int(w.get("ghost_after_minutes", config.web.ghost_after_minutes))
                config.web.expire_after_minutes = int(w.get("expire_after_minutes", config.web.expire_after_minutes))
                config.web.mobile_pin = (w.get("mobile_pin", config.web.mobile_pin) or "").strip()
                need_restart.append("web host/port")

            # Update database config
            if "database" in body:
                db_cfg = body["database"]
                config.database.path = db_cfg.get("path", config.database.path)
                need_restart.append("database path")

            # Update tracking config
            if "tracking" in body:
                t = body["tracking"]
                config.tracking.max_station_age = int(t.get("max_station_age", config.tracking.max_station_age))
                config.tracking.cleanup_interval = int(t.get("cleanup_interval", config.tracking.cleanup_interval))
                live_applied.append("tracking")

            # Update alerts config
            if "alerts" in body:
                al = body["alerts"]
                config.alerts.enabled = bool(al.get("enabled", config.alerts.enabled))
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
                config.weather.alert_range_miles = int(wc.get("alert_range_miles", config.weather.alert_range_miles))
                config.weather.refresh_minutes = max(5, int(wc.get("refresh_minutes", config.weather.refresh_minutes)))
                live_applied.append("weather")

            # Update propagation config
            if "propagation" in body:
                pc = body["propagation"]
                config.propagation.my_station_full_count = max(1, int(pc.get("my_station_full_count", config.propagation.my_station_full_count)))
                config.propagation.my_station_full_dist_km = max(1.0, float(pc.get("my_station_full_dist_km", config.propagation.my_station_full_dist_km)))
                config.propagation.regional_full_count = max(1, int(pc.get("regional_full_count", config.propagation.regional_full_count)))
                config.propagation.regional_full_dist_km = max(1.0, float(pc.get("regional_full_dist_km", config.propagation.regional_full_dist_km)))
                live_applied.append("propagation meters")

            # Update MQTT config
            if "mqtt" in body:
                mc = body["mqtt"]
                config.mqtt.enabled = bool(mc.get("enabled", config.mqtt.enabled))
                config.mqtt.broker = mc.get("broker", config.mqtt.broker)
                config.mqtt.port = int(mc.get("port", config.mqtt.port))
                config.mqtt.topic_prefix = mc.get("topic_prefix", config.mqtt.topic_prefix)
                config.mqtt.username = mc.get("username", config.mqtt.username)
                new_mqtt_pw = mc.get("password", "")
                if new_mqtt_pw and "*" not in new_mqtt_pw:
                    config.mqtt.password = new_mqtt_pw
                live_applied.append("mqtt")

            # Save to file
            config_path = Path("config.toml")
            config.save(config_path)

            # Build response message
            parts = []
            if live_applied:
                parts.append(f"Applied live: {', '.join(live_applied)}.")
            if need_restart:
                parts.append(f"Restart required for: {', '.join(need_restart)}.")
            if not parts:
                parts.append("Configuration saved (no changes detected).")

            return {"success": True, "message": " ".join(parts), "needRestart": bool(need_restart)}

        except Exception as e:
            logger.error(f"Failed to save config: {e}")
            return JSONResponse(
                status_code=500,
                content={"success": False, "message": "Error saving configuration. Check server logs for details."},
            )

    return app
