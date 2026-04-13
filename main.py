#!/usr/bin/env python3
"""APRS PropView — VHF Propagation Monitor & Digipeater/IGate

Launch this to start the application. The web interface opens automatically.
"""

import asyncio
import sys
import logging
import webbrowser
import os
from pathlib import Path

# Support PyInstaller frozen builds
if getattr(sys, 'frozen', False):
    # Exe directory for config/db files; _MEIPASS for bundled code/data
    EXE_DIR = Path(sys.executable).parent
    BASE_DIR = Path(sys._MEIPASS)
    os.chdir(EXE_DIR)
else:
    EXE_DIR = Path(__file__).parent
    BASE_DIR = Path(__file__).parent

# Add project root to path
sys.path.insert(0, str(BASE_DIR))

from server.config import Config
from server.app import create_app
from server.database import Database
from server.aprs_is import APRSISClient
from server.kiss import KISSSerialClient, KISSTCPClient
from server.digipeater import Digipeater
from server.igate import IGate
from server.station_tracker import StationTracker
from server.packet_handler import PacketHandler
from server.websocket_manager import WebSocketManager
from server.analytics import AnalyticsEngine
from server.alerts import AlertManager, AlertConfig
from server.weather import WeatherManager

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("propview")


async def main():
    print(
        r"""
    _    ____  ____  ____    ____                 __     ___
   / \  |  _ \|  _ \/ ___|  |  _ \ _ __ ___  _ __\ \   / (_) _____      __
  / _ \ | |_) | |_) \___ \  | |_) | '__/ _ \| '_ \\ \ / /| |/ _ \ \ /\ / /
 / ___ \|  __/|  _ < ___) | |  __/| | | (_) | |_) |\ V / | |  __/\ V  V /
/_/   \_\_|   |_| \_\____/  |_|   |_|  \___/| .__/  \_/  |_|\___| \_/\_/
                                             |_|
  VHF Propagation Monitor — Digipeater & IGate
"""
    )

    # Load or create config
    config_path = Path("config.toml")
    if not config_path.exists():
        Config.create_default(config_path)
        print(f"  Created default configuration: {config_path}")
        print("  Starting with default settings \u2014 open the web UI to configure.\n")

    config = Config.load(config_path)
    logger.info(f"Station: {config.station.full_callsign}")
    logger.info(
        f"Position: {config.station.latitude:.4f}, {config.station.longitude:.4f}"
    )

    # ── Initialize components ───────────────────────────────────────

    db = Database(config.database.path)
    await db.initialize()

    ws_manager = WebSocketManager()
    tracker = StationTracker(db, config, ws_manager)
    digipeater = Digipeater(config) if config.digipeater.enabled else None
    igate = IGate(config) if config.igate.enabled else None

    handler = PacketHandler(config, tracker, digipeater, igate, ws_manager)

    # ── Analytics & Alerts ──────────────────────────────────────────

    analytics = AnalyticsEngine(db)

    alert_config = AlertConfig(
        enabled=config.alerts.enabled,
        min_stations=config.alerts.min_stations,
        min_distance_km=config.alerts.min_distance_km,
        cooldown_seconds=config.alerts.cooldown_seconds,
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
    alert_manager = AlertManager(alert_config, config.station.full_callsign)
    tracker.set_alert_manager(alert_manager)

    logger.info(f"Alerts: {'enabled' if alert_config.enabled else 'disabled'}")

    # ── Connect RF interfaces ───────────────────────────────────────

    if config.kiss_serial.enabled:
        serial_client = KISSSerialClient(
            config.kiss_serial.port,
            config.kiss_serial.baudrate,
            handler.handle_rf_packet,
        )
        handler.add_rf_interface(serial_client)
        logger.info(f"KISS Serial: {config.kiss_serial.port} @ {config.kiss_serial.baudrate}")

    if config.kiss_tcp.enabled:
        tcp_client = KISSTCPClient(
            config.kiss_tcp.host,
            config.kiss_tcp.port,
            handler.handle_rf_packet,
        )
        handler.add_rf_interface(tcp_client)
        logger.info(f"KISS TCP: {config.kiss_tcp.host}:{config.kiss_tcp.port}")

    # ── APRS-IS client ──────────────────────────────────────────────

    aprs_is = None
    if config.aprs_is.enabled:
        aprs_is = APRSISClient(config, handler.handle_is_packet)
        handler.set_aprs_is(aprs_is)
        logger.info(f"APRS-IS: {config.aprs_is.server}:{config.aprs_is.port}")

    # ── Weather ────────────────────────────────────────────────────

    weather_manager = WeatherManager(config)
    if config.weather.enabled and config.weather.location_code:
        logger.info(f"Weather: enabled, location={config.weather.location_code}")
    else:
        logger.info("Weather: disabled or no location set")

    # ── Create web application ──────────────────────────────────────

    app = create_app(config, db, tracker, ws_manager, handler, analytics, alert_manager, aprs_is, weather_manager)

    # ── Start background tasks ──────────────────────────────────────

    tasks = []

    for iface in handler.rf_interfaces:
        tasks.append(asyncio.create_task(iface.connect()))

    if aprs_is:
        tasks.append(asyncio.create_task(aprs_is.connect()))
        tasks.append(asyncio.create_task(aprs_is.keepalive()))

    tasks.append(asyncio.create_task(tracker.cleanup_loop()))
    tasks.append(asyncio.create_task(tracker.propagation_broadcast_loop()))

    # Beacon loop always runs — it re-reads interval from config each iteration
    # so changes via the web UI apply live (interval=0 means disabled, loop sleeps)
    tasks.append(asyncio.create_task(handler.beacon_loop()))

    # ── Start web server ────────────────────────────────────────────

    url = f"http://{config.web.host}:{config.web.port}"
    logger.info(f"Web interface: {url}")

    import uvicorn

    uvi_config = uvicorn.Config(
        app,
        host=config.web.host,
        port=config.web.port,
        log_level="warning",
        access_log=False,
    )
    server = uvicorn.Server(uvi_config)

    # Open browser after a short delay
    async def open_browser():
        await asyncio.sleep(1.5)
        webbrowser.open(url)

    tasks.append(asyncio.create_task(open_browser()))

    print(f"\n  APRS PropView running at {url}")
    print("  Press Ctrl+C to stop.\n")

    try:
        await server.serve()
    finally:
        logger.info("Shutting down...")
        for task in tasks:
            task.cancel()
        if aprs_is:
            await aprs_is.close()
        for iface in handler.rf_interfaces:
            await iface.close()
        await db.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n  Goodbye. 73!")
