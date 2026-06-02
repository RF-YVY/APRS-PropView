#!/usr/bin/env python3
"""APRS PropView — VHF Propagation Monitor & Digipeater/IGate

Launch this to start the application. The web interface opens automatically.
"""

APP_VERSION = "1.5.5.2"

import asyncio
import sys
import logging
import webbrowser
import os
import socket
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
from server.kiss import KISSSerialClient, KISSTCPClient, TNC2MonitorSerialClient, AGWPETCPClient
from server.digipeater import Digipeater
from server.igate import IGate
from server.station_tracker import StationTracker
from server.packet_handler import PacketHandler
from server.websocket_manager import WebSocketManager
from server.analytics import AnalyticsEngine
from server.alerts import AlertManager, AlertConfig
from server.weather import WeatherManager
from server.update_checker import UpdateChecker
from server.gps import GPSManager
from server.wxnow import WxNowTransmitter
from server.status_report import StatusReportTransmitter
from server.scheduled_packets import ScheduledPacketTransmitter

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("propview")

# The Windows proactor loop is prone to noisy ConnectionResetError logs when
# browsers close WebSocket connections abruptly. The selector loop is quieter
# and works well for this app's socket usage.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


def _pause_for_packaged_error():
    """Keep double-clicked packaged consoles open after fatal startup errors."""
    if not getattr(sys, "frozen", False):
        return
    if not getattr(sys.stdin, "isatty", lambda: False)():
        return
    try:
        input("\n  Press Enter to close APRS PropView...")
    except (EOFError, OSError):
        pass


def _web_port_available(host: str, port: int) -> bool:
    family = socket.AF_INET6 if ":" in str(host) else socket.AF_INET
    try:
        with socket.socket(family, socket.SOCK_STREAM) as sock:
            sock.bind((host, int(port)))
    except OSError:
        return False
    return True


# ── System Tray ─────────────────────────────────────────────────────

def _start_tray(url: str, shutdown_event: asyncio.Event, loop):
    """Start a pystray system-tray icon in a background thread."""
    try:
        import pystray
        from PIL import Image
    except ImportError:
        logger.debug("pystray or Pillow not available — skipping system tray")
        return None

    ico_path = EXE_DIR / "ico" / "favicon.ico"
    if not ico_path.exists():
        ico_path = BASE_DIR / "static" / "ico" / "favicon.ico"
    try:
        image = Image.open(ico_path)
    except Exception:
        # Create a simple colored square as fallback
        image = Image.new("RGB", (64, 64), "#58a6ff")

    def on_open(icon, item):
        webbrowser.open(url)

    def on_quit(icon, item):
        icon.stop()
        loop.call_soon_threadsafe(shutdown_event.set)

    menu = pystray.Menu(
        pystray.MenuItem("Open PropView", on_open, default=True),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Quit", on_quit),
    )

    icon = pystray.Icon("APRSPropView", image, "APRS PropView", menu)

    import threading
    t = threading.Thread(target=icon.run, daemon=True)
    t.start()
    return icon


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

    if not _web_port_available(config.web.host, config.web.port):
        logger.error(
            "Web interface cannot start because %s:%s is already in use.",
            config.web.host,
            config.web.port,
        )
        print(
            "\n  APRS PropView could not start because the web interface port is already in use."
        )
        print(f"  Address: {config.web.host}:{config.web.port}")
        print("  Close the other APRS PropView window/process, or change [web].port in config.toml.\n")
        _pause_for_packaged_error()
        return

    db = Database(config.database.path)
    await db.initialize()

    ws_manager = WebSocketManager()
    tracker = StationTracker(db, config, ws_manager)
    digipeater = Digipeater(config) if config.digipeater.enabled else None
    igate = IGate(config) if config.igate.enabled else None
    gps_manager = GPSManager(config, ws_manager, tracker)
    tracker.set_gps_manager(gps_manager)

    handler = PacketHandler(config, tracker, digipeater, igate, ws_manager)
    handler.set_gps_manager(gps_manager)
    await handler.cleanup_messages()

    # ── Analytics & Alerts ──────────────────────────────────────────

    analytics = AnalyticsEngine(db)

    alert_config = AlertConfig(
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
    alert_manager = AlertManager(alert_config, config.station.full_callsign)
    tracker.set_alert_manager(alert_manager)
    tracker.set_analytics(analytics)
    handler.set_alert_manager(alert_manager)

    logger.info(f"Alerts: {'enabled' if alert_config.enabled else 'disabled'}")

    # ── Connect RF interfaces ───────────────────────────────────────

    def _legacy_rf_ports():
        ports = []
        if config.kiss_serial.enabled:
            ports.append({
                "name": f"KISS Serial {config.kiss_serial.port}",
                "enabled": True,
                "type": "serial",
                "port": config.kiss_serial.port,
                "baudrate": config.kiss_serial.baudrate,
                "mode": config.kiss_serial.mode,
                "flow_control": config.kiss_serial.flow_control,
                "init_profile": config.kiss_serial.init_profile,
                "init_commands": config.kiss_serial.init_commands,
                "host": "",
                "tcp_port": 0,
            })
        if config.kiss_tcp.enabled:
            ports.append({
                "name": f"KISS TCP {config.kiss_tcp.host}:{config.kiss_tcp.port}",
                "enabled": True,
                "type": "tcp",
                "host": config.kiss_tcp.host,
                "tcp_port": config.kiss_tcp.port,
                "port": "",
                "baudrate": 0,
                "mode": "kiss",
                "flow_control": "none",
                "init_profile": "none",
                "init_commands": "",
            })
        return ports

    rf_port_configs = config.rf_ports if config.rf_ports else _legacy_rf_ports()

    def _port_value(port_cfg, key, default=None):
        if hasattr(port_cfg, key):
            return getattr(port_cfg, key)
        return port_cfg.get(key, default)

    for idx, port_cfg in enumerate(rf_port_configs, 1):
        if not _port_value(port_cfg, "enabled", False):
            continue
        port_type = (_port_value(port_cfg, "type", "serial") or "serial").strip().lower()
        port_name = (_port_value(port_cfg, "name", "") or "").strip()
        if not port_name:
            port_name = f"RF Port {idx}"
        if port_type == "serial":
            serial_mode = (_port_value(port_cfg, "mode", "kiss") or "kiss").strip().lower()
            serial_port = _port_value(port_cfg, "port", "COM3")
            baudrate = int(_port_value(port_cfg, "baudrate", 9600) or 9600)
            flow_control = _port_value(port_cfg, "flow_control", "none")
            init_profile = _port_value(port_cfg, "init_profile", "none")
            init_commands = _port_value(port_cfg, "init_commands", "")
            serial_cls = TNC2MonitorSerialClient if serial_mode == "tnc2_monitor" else KISSSerialClient
            frame_handler = handler.handle_rf_aprs_packet if serial_mode == "tnc2_monitor" else handler.handle_rf_packet
            serial_kwargs = {
                "flow_control": flow_control,
                "init_profile": init_profile,
                "init_commands": init_commands,
                "callsign": config.station.full_callsign,
                "name": port_name,
            }
            if serial_mode == "kiss":
                serial_kwargs["on_text_line"] = handler.handle_rf_text_line
            serial_client = serial_cls(
                serial_port,
                baudrate,
                frame_handler,
                **serial_kwargs,
            )
            serial_client.rx_only_rf = bool(_port_value(port_cfg, "rx_only_rf", False)) or serial_mode == "tnc2_monitor"
            serial_client.rx_only_is = bool(_port_value(port_cfg, "rx_only_is", False)) or serial_mode == "tnc2_monitor"
            handler.add_rf_interface(serial_client)
            logger.info(
                "RF port %s: serial %s @ %s mode=%s flow=%s profile=%s",
                port_name,
                serial_port,
                baudrate,
                serial_mode,
                flow_control,
                init_profile,
            )
        elif port_type == "tcp":
            host = _port_value(port_cfg, "host", "127.0.0.1")
            tcp_port = int(_port_value(port_cfg, "tcp_port", 8001) or 8001)
            protocol = (_port_value(port_cfg, "protocol", "kiss") or "kiss").strip().lower()
            tcp_cls = AGWPETCPClient if protocol == "agwpe" else KISSTCPClient
            tcp_client = tcp_cls(
                host,
                tcp_port,
                handler.handle_rf_packet,
                name=port_name,
            )
            tcp_client.rx_only_rf = bool(_port_value(port_cfg, "rx_only_rf", False))
            tcp_client.rx_only_is = bool(_port_value(port_cfg, "rx_only_is", False))
            handler.add_rf_interface(tcp_client)
            logger.info("RF port %s: %s TCP %s:%s", port_name, protocol.upper(), host, tcp_port)
        else:
            logger.warning("Skipping RF port %s with unknown type %s", port_name, port_type)

    # ── APRS-IS client ──────────────────────────────────────────────

    aprs_is = None
    if config.aprs_is.enabled:
        aprs_is = APRSISClient(config, handler.handle_is_packet, app_version=APP_VERSION)
        handler.set_aprs_is(aprs_is)
        logger.info(f"APRS-IS: {config.aprs_is.server}:{config.aprs_is.port}")

    # ── Weather ────────────────────────────────────────────────────

    weather_manager = WeatherManager(config)
    handler.set_weather_manager(weather_manager)
    if config.weather.enabled and config.weather.location_code:
        logger.info(f"Weather: enabled, location={config.weather.location_code}")
    else:
        logger.info("Weather: disabled or no location set")

    wxnow_transmitter = WxNowTransmitter(config, handler)
    logger.info(
        "WXnow transmit: %s",
        "enabled" if config.wxnow.enabled and config.wxnow.file_path else "disabled or no file set",
    )

    status_transmitter = StatusReportTransmitter(config, handler, tracker, weather_manager)
    logger.info("Status/DX transmit: %s", "enabled" if config.status.enabled else "disabled")
    scheduled_transmitter = ScheduledPacketTransmitter(config, handler)

    update_checker = UpdateChecker(APP_VERSION)
    update_checker.configure(
        config.web.update_check_enabled,
        max(1, int(config.web.update_check_interval_hours)) * 3600,
    )

    # ── MQTT Publisher (optional) ──────────────────────────────────

    mqtt_publisher = None
    if config.mqtt.enabled:
        from server.export import MQTTPublisher
        mqtt_publisher = MQTTPublisher(
            host=config.mqtt.broker,
            port=config.mqtt.port,
            topic_prefix=config.mqtt.topic_prefix,
            username=config.mqtt.username,
            password=config.mqtt.password,
        )
        connected = await mqtt_publisher.connect()
        if connected:
            logger.info(f"MQTT: connected to {config.mqtt.broker}:{config.mqtt.port}")
            tracker.set_mqtt_publisher(mqtt_publisher)
        else:
            logger.warning("MQTT: failed to connect (check broker settings or paho-mqtt installation)")
            mqtt_publisher = None

    # ── Create web application ──────────────────────────────────────

    app = create_app(
        config,
        db,
        tracker,
        ws_manager,
        handler,
        analytics,
        alert_manager,
        aprs_is,
        weather_manager,
        wxnow_transmitter=wxnow_transmitter,
        status_transmitter=status_transmitter,
        scheduled_transmitter=scheduled_transmitter,
        update_checker=update_checker,
        gps_manager=gps_manager,
        app_version=APP_VERSION,
    )

    # ── Start background tasks ──────────────────────────────────────

    tasks = []

    for iface in handler.rf_interfaces:
        tasks.append(asyncio.create_task(iface.connect()))

    if aprs_is:
        tasks.append(asyncio.create_task(aprs_is.connect()))
        tasks.append(asyncio.create_task(aprs_is.keepalive()))

    tasks.append(asyncio.create_task(tracker.cleanup_loop()))
    tasks.append(asyncio.create_task(tracker.propagation_broadcast_loop()))
    tasks.append(asyncio.create_task(gps_manager.run_serial_nmea()))
    tasks.append(asyncio.create_task(gps_manager.run_tcp_nmea()))
    tasks.append(asyncio.create_task(gps_manager.run_udp_nmea()))

    # Beacon loop always runs — it re-reads interval from config each iteration
    # so changes via the web UI apply live (interval=0 means disabled, loop sleeps)
    tasks.append(asyncio.create_task(handler.beacon_loop()))
    tasks.append(asyncio.create_task(wxnow_transmitter.loop()))
    tasks.append(asyncio.create_task(status_transmitter.loop()))
    tasks.append(asyncio.create_task(scheduled_transmitter.loop()))

    # ── Start web server ────────────────────────────────────────────

    # Use localhost for browser URL when binding to all interfaces
    browse_host = "127.0.0.1" if config.web.host == "0.0.0.0" else config.web.host
    url = f"http://{browse_host}:{config.web.port}"
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

    # ── System tray icon ────────────────────────────────────────────

    shutdown_event = asyncio.Event()
    tray_icon = _start_tray(url, shutdown_event, asyncio.get_event_loop())

    print(f"\n  APRS PropView running at {url}")
    if tray_icon:
        print("  System tray icon active — right-click to quit.")
    print("  Press Ctrl+C to stop.\n")

    try:
        # Run server until Ctrl+C or tray quit
        server_task = asyncio.create_task(server.serve())
        shutdown_task = asyncio.create_task(shutdown_event.wait())
        done, pending = await asyncio.wait(
            [server_task, shutdown_task],
            return_when=asyncio.FIRST_COMPLETED,
        )
        for p in pending:
            p.cancel()
    finally:
        logger.info("Shutting down...")
        for task in tasks:
            task.cancel()
        if mqtt_publisher:
            await mqtt_publisher.close()
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
    except SystemExit as exc:
        if exc.code:
            _pause_for_packaged_error()
        raise
    except Exception:
        logger.exception("Fatal startup error")
        _pause_for_packaged_error()
        raise
