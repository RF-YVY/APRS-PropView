"""Configuration management using TOML format."""

import sys
from pathlib import Path
from dataclasses import dataclass, field
from typing import List

if sys.version_info >= (3, 11):
    import tomllib
else:
    try:
        import tomllib
    except ImportError:
        import tomli as tomllib

DEFAULT_CONFIG = """\
# APRS PropView Configuration
# Edit this file with your station details before starting

[station]
callsign = "N0CALL"
ssid = 0
latitude = 0.0
longitude = 0.0
symbol_table = "/"
symbol_code = "#"
phg = ""
equipment = ""
comment = "APRS PropView Digi/IGate"
beacon_interval = 1800
beacon_path = "WIDE1-1"

[digipeater]
enabled = true
aliases = ["WIDE1-1", "WIDE2-1"]
dedupe_interval = 30

[igate]
enabled = true
rf_to_is = true
is_to_rf = false

[aprs_is]
enabled = true
server = "rotate.aprs2.net"
port = 14580
passcode = "-1"
filter = ""

[kiss_serial]
enabled = false
port = "COM3"
baudrate = 9600
mode = "kiss"
flow_control = "none"
init_profile = "none"
init_commands = ""

[kiss_tcp]
enabled = false
host = "127.0.0.1"
port = 8001

[web]
host = "127.0.0.1"
port = 14501
font_family = ""
map_tile_source = "osm"
map_tile_url = ""
map_tile_attribution = ""
map_tile_max_zoom = 19
ghost_after_minutes = 60
expire_after_minutes = 0
mobile_pin = ""
update_check_enabled = true
update_check_interval_hours = 24

[database]
path = "propview.db"

[tracking]
max_station_age = 86400
cleanup_interval = 3600

[alerts]
enabled = false
anomaly_alert_enabled = true
sporadic_e_alert_enabled = true
my_min_stations = 3
my_min_distance_km = 100.0
regional_min_stations = 5
regional_min_distance_km = 100.0
cooldown_seconds = 1800
quiet_start = ""
quiet_end = ""
msg_notify_enabled = false
msg_discord_enabled = false
msg_email_enabled = false
msg_sms_enabled = false
discord_enabled = false
discord_webhook_url = ""
email_enabled = false
email_smtp_server = ""
email_smtp_port = 587
email_from = ""
email_to = ""
email_password = ""
sms_enabled = false
sms_gateway_address = ""

[propagation]
my_station_full_count = 10
my_station_full_dist_km = 200.0
regional_full_count = 10
regional_full_dist_km = 200.0

[weather]
enabled = false
location_code = ""
current_provider = "open_meteo"
alert_provider = "auto"
weatherbit_api_key = ""
weatherbit_poll_minutes = 30
alert_range_miles = 50
refresh_minutes = 15
radar_enabled = false
radar_provider = "rainviewer"
radar_opacity = 0.55
radar_animate = true
alert_overlay_enabled = false
alert_overlay_groups = ["warnings", "watches", "flood", "winter", "marine", "fire_heat", "other"]
alert_scope_mode = "point"
alert_scope_zone = ""
elevated_alert_polling_enabled = false
elevated_alert_polling_seconds = 60
elevated_alert_cooldown_minutes = 15
elevated_trigger_events = ["Tornado Watch", "Severe Thunderstorm Watch"]

[gps]
enabled = false
source = "browser"
map_update_enabled = true
update_station_position = false
station_position_locked = true
serial_port = "COM4"
serial_baudrate = 9600
tcp_host = "127.0.0.1"
tcp_port = 10110
udp_host = "0.0.0.0"
udp_port = 10110

[mqtt]
enabled = false
broker = "localhost"
port = 1883
topic_prefix = "aprs/propview"
username = ""
password = ""
"""


@dataclass
class StationConfig:
    callsign: str = "N0CALL"
    ssid: int = 0
    latitude: float = 0.0
    longitude: float = 0.0
    symbol_table: str = "/"
    symbol_code: str = "#"
    phg: str = ""
    equipment: str = ""
    comment: str = "APRS PropView Digi/IGate"
    beacon_interval: int = 1800
    beacon_path: str = "WIDE1-1"

    @property
    def full_callsign(self) -> str:
        if self.ssid > 0:
            return f"{self.callsign}-{self.ssid}"
        return self.callsign


@dataclass
class DigiConfig:
    enabled: bool = True
    aliases: List[str] = field(default_factory=lambda: ["WIDE1-1", "WIDE2-1"])
    dedupe_interval: int = 30


@dataclass
class IGateConfig:
    enabled: bool = True
    rf_to_is: bool = True
    is_to_rf: bool = False


@dataclass
class APRSISConfig:
    enabled: bool = True
    server: str = "rotate.aprs2.net"
    port: int = 14580
    passcode: str = "-1"
    filter: str = ""


@dataclass
class KISSSerialConfig:
    enabled: bool = False
    port: str = "COM3"
    baudrate: int = 9600
    mode: str = "kiss"
    flow_control: str = "none"
    init_profile: str = "none"
    init_commands: str = ""


@dataclass
class KISSTCPConfig:
    enabled: bool = False
    host: str = "127.0.0.1"
    port: int = 8001


@dataclass
class WebConfig:
    host: str = "127.0.0.1"
    port: int = 14501
    font_family: str = ""
    map_tile_source: str = "osm"
    map_tile_url: str = ""
    map_tile_attribution: str = ""
    map_tile_max_zoom: int = 19
    ghost_after_minutes: int = 60
    expire_after_minutes: int = 0
    mobile_pin: str = ""
    update_check_enabled: bool = True
    update_check_interval_hours: int = 24


@dataclass
class DatabaseConfig:
    path: str = "propview.db"


@dataclass
class TrackingConfig:
    max_station_age: int = 86400
    cleanup_interval: int = 3600


@dataclass
class AlertsConfig:
    enabled: bool = False
    anomaly_alert_enabled: bool = True
    sporadic_e_alert_enabled: bool = True
    my_min_stations: int = 3
    my_min_distance_km: float = 100.0
    regional_min_stations: int = 5
    regional_min_distance_km: float = 100.0
    cooldown_seconds: int = 1800
    quiet_start: str = ""       # HH:MM 24h — quiet period start (e.g. "22:00")
    quiet_end: str = ""         # HH:MM 24h — quiet period end (e.g. "08:00")
    msg_notify_enabled: bool = False  # Send notification on incoming APRS message
    msg_discord_enabled: bool = False
    msg_email_enabled: bool = False
    msg_sms_enabled: bool = False
    discord_enabled: bool = False
    discord_webhook_url: str = ""
    email_enabled: bool = False
    email_smtp_server: str = ""
    email_smtp_port: int = 587
    email_from: str = ""
    email_to: str = ""
    email_password: str = ""
    sms_enabled: bool = False
    sms_gateway_address: str = ""


@dataclass
class PropagationConfig:
    my_station_full_count: int = 10        # Direct stations for 100% count score
    my_station_full_dist_km: float = 200.0  # Max direct distance for 100% dist score
    regional_full_count: int = 10           # All RF stations for 100% count score
    regional_full_dist_km: float = 200.0    # Max RF distance for 100% dist score


@dataclass
class WeatherConfig:
    enabled: bool = False
    location_code: str = ""       # US zip code or ICAO code
    current_provider: str = "open_meteo"
    alert_provider: str = "auto"   # auto, nws, open_meteo_risk, weatherbit, disabled
    weatherbit_api_key: str = ""
    weatherbit_poll_minutes: int = 30
    alert_range_miles: int = 50    # Range for severe weather alerts
    refresh_minutes: int = 15      # How often to refresh weather data
    radar_enabled: bool = False
    radar_provider: str = "rainviewer"
    radar_opacity: float = 0.55
    radar_animate: bool = True
    alert_overlay_enabled: bool = False
    alert_overlay_groups: List[str] = field(default_factory=lambda: [
        "warnings", "watches", "flood", "winter", "marine", "fire_heat", "other",
    ])
    alert_scope_mode: str = "point"
    alert_scope_zone: str = ""
    elevated_alert_polling_enabled: bool = False
    elevated_alert_polling_seconds: int = 60
    elevated_alert_cooldown_minutes: int = 15
    elevated_trigger_events: List[str] = field(default_factory=lambda: [
        "Tornado Watch", "Severe Thunderstorm Watch",
    ])


@dataclass
class GPSConfig:
    enabled: bool = False
    source: str = "browser"  # browser, self_packet, nmea_serial, nmea_tcp, nmea_udp, any
    map_update_enabled: bool = True
    update_station_position: bool = False
    station_position_locked: bool = True
    serial_port: str = "COM4"
    serial_baudrate: int = 9600
    tcp_host: str = "127.0.0.1"
    tcp_port: int = 10110
    udp_host: str = "0.0.0.0"
    udp_port: int = 10110


@dataclass
class MQTTConfig:
    enabled: bool = False
    broker: str = "localhost"
    port: int = 1883
    topic_prefix: str = "aprs/propview"
    username: str = ""
    password: str = ""


@dataclass
class Config:
    station: StationConfig = field(default_factory=StationConfig)
    digipeater: DigiConfig = field(default_factory=DigiConfig)
    igate: IGateConfig = field(default_factory=IGateConfig)
    aprs_is: APRSISConfig = field(default_factory=APRSISConfig)
    kiss_serial: KISSSerialConfig = field(default_factory=KISSSerialConfig)
    kiss_tcp: KISSTCPConfig = field(default_factory=KISSTCPConfig)
    web: WebConfig = field(default_factory=WebConfig)
    database: DatabaseConfig = field(default_factory=DatabaseConfig)
    tracking: TrackingConfig = field(default_factory=TrackingConfig)
    alerts: AlertsConfig = field(default_factory=AlertsConfig)
    propagation: PropagationConfig = field(default_factory=PropagationConfig)
    weather: WeatherConfig = field(default_factory=WeatherConfig)
    gps: GPSConfig = field(default_factory=GPSConfig)
    mqtt: MQTTConfig = field(default_factory=MQTTConfig)

    @staticmethod
    def create_default(path: Path):
        path.write_text(DEFAULT_CONFIG)

    @staticmethod
    def load(path: Path) -> "Config":
        with open(path, "rb") as f:
            data = tomllib.load(f)

        config = Config()

        section_map = {
            "station": (StationConfig, "station"),
            "digipeater": (DigiConfig, "digipeater"),
            "igate": (IGateConfig, "igate"),
            "aprs_is": (APRSISConfig, "aprs_is"),
            "kiss_serial": (KISSSerialConfig, "kiss_serial"),
            "kiss_tcp": (KISSTCPConfig, "kiss_tcp"),
            "web": (WebConfig, "web"),
            "database": (DatabaseConfig, "database"),
            "tracking": (TrackingConfig, "tracking"),
            "alerts": (AlertsConfig, "alerts"),
            "propagation": (PropagationConfig, "propagation"),
            "weather": (WeatherConfig, "weather"),
            "gps": (GPSConfig, "gps"),
            "mqtt": (MQTTConfig, "mqtt"),
        }

        for key, (cls, attr) in section_map.items():
            if key in data:
                setattr(config, attr, cls(**data[key]))

        return config

    @staticmethod
    def _toml_escape(value: str) -> str:
        """Escape a string for safe inclusion in a TOML quoted value."""
        return (
            value
            .replace("\\", "\\\\")
            .replace('"', '\\"')
            .replace("\n", "\\n")
            .replace("\r", "\\r")
            .replace("\t", "\\t")
        )

    def save(self, path: Path):
        """Save current config back to TOML format."""
        esc = self._toml_escape
        lines = [
            "# APRS PropView Configuration\n",
            "[station]",
            f'callsign = "{esc(self.station.callsign)}"',
            f"ssid = {int(self.station.ssid)}",
            f"latitude = {float(self.station.latitude)}",
            f"longitude = {float(self.station.longitude)}",
            f'symbol_table = "{esc(self.station.symbol_table)}"',
            f'symbol_code = "{esc(self.station.symbol_code)}"',
            f'phg = "{esc(self.station.phg)}"',
            f'equipment = "{esc(self.station.equipment)}"',
            f'comment = "{esc(self.station.comment)}"',
            f"beacon_interval = {int(self.station.beacon_interval)}",
            f'beacon_path = "{esc(self.station.beacon_path)}"',
            "",
            "[digipeater]",
            f"enabled = {'true' if self.digipeater.enabled else 'false'}",
            'aliases = [' + ', '.join('"' + self._toml_escape(a) + '"' for a in self.digipeater.aliases) + ']',
            f"dedupe_interval = {int(self.digipeater.dedupe_interval)}",
            "",
            "[igate]",
            f"enabled = {'true' if self.igate.enabled else 'false'}",
            f"rf_to_is = {'true' if self.igate.rf_to_is else 'false'}",
            f"is_to_rf = {'true' if self.igate.is_to_rf else 'false'}",
            "",
            "[aprs_is]",
            f"enabled = {'true' if self.aprs_is.enabled else 'false'}",
            f'server = "{esc(self.aprs_is.server)}"',
            f"port = {int(self.aprs_is.port)}",
            f'passcode = "{esc(self.aprs_is.passcode)}"',
            f'filter = "{esc(self.aprs_is.filter)}"',
            "",
            "[kiss_serial]",
            f"enabled = {'true' if self.kiss_serial.enabled else 'false'}",
            f'port = "{esc(self.kiss_serial.port)}"',
            f"baudrate = {int(self.kiss_serial.baudrate)}",
            f'mode = "{esc(self.kiss_serial.mode)}"',
            f'flow_control = "{esc(self.kiss_serial.flow_control)}"',
            f'init_profile = "{esc(self.kiss_serial.init_profile)}"',
            f'init_commands = "{esc(self.kiss_serial.init_commands)}"',
            "",
            "[kiss_tcp]",
            f"enabled = {'true' if self.kiss_tcp.enabled else 'false'}",
            f'host = "{esc(self.kiss_tcp.host)}"',
            f"port = {int(self.kiss_tcp.port)}",
            "",
            "[web]",
            f'host = "{esc(self.web.host)}"',
            f"port = {int(self.web.port)}",
            f'font_family = "{esc(self.web.font_family)}"',
            f'map_tile_source = "{esc(self.web.map_tile_source)}"',
            f'map_tile_url = "{esc(self.web.map_tile_url)}"',
            f'map_tile_attribution = "{esc(self.web.map_tile_attribution)}"',
            f"map_tile_max_zoom = {int(self.web.map_tile_max_zoom)}",
            f"ghost_after_minutes = {int(self.web.ghost_after_minutes)}",
            f"expire_after_minutes = {int(self.web.expire_after_minutes)}",
            f'mobile_pin = "{esc(self.web.mobile_pin)}"',
            f"update_check_enabled = {'true' if self.web.update_check_enabled else 'false'}",
            f"update_check_interval_hours = {int(self.web.update_check_interval_hours)}",
            "",
            "[database]",
            f'path = "{esc(self.database.path)}"',
            "",
            "[tracking]",
            f"max_station_age = {int(self.tracking.max_station_age)}",
            f"cleanup_interval = {int(self.tracking.cleanup_interval)}",
            "",
            "[alerts]",
            f"enabled = {'true' if self.alerts.enabled else 'false'}",
            f"anomaly_alert_enabled = {'true' if self.alerts.anomaly_alert_enabled else 'false'}",
            f"sporadic_e_alert_enabled = {'true' if self.alerts.sporadic_e_alert_enabled else 'false'}",
            f"my_min_stations = {int(self.alerts.my_min_stations)}",
            f"my_min_distance_km = {float(self.alerts.my_min_distance_km)}",
            f"regional_min_stations = {int(self.alerts.regional_min_stations)}",
            f"regional_min_distance_km = {float(self.alerts.regional_min_distance_km)}",
            f"cooldown_seconds = {int(self.alerts.cooldown_seconds)}",
            f'quiet_start = "{esc(self.alerts.quiet_start)}"',
            f'quiet_end = "{esc(self.alerts.quiet_end)}"',
            f"msg_notify_enabled = {'true' if self.alerts.msg_notify_enabled else 'false'}",
            f"msg_discord_enabled = {'true' if self.alerts.msg_discord_enabled else 'false'}",
            f"msg_email_enabled = {'true' if self.alerts.msg_email_enabled else 'false'}",
            f"msg_sms_enabled = {'true' if self.alerts.msg_sms_enabled else 'false'}",
            f"discord_enabled = {'true' if self.alerts.discord_enabled else 'false'}",
            f'discord_webhook_url = "{esc(self.alerts.discord_webhook_url)}"',
            f"email_enabled = {'true' if self.alerts.email_enabled else 'false'}",
            f'email_smtp_server = "{esc(self.alerts.email_smtp_server)}"',
            f"email_smtp_port = {int(self.alerts.email_smtp_port)}",
            f'email_from = "{esc(self.alerts.email_from)}"',
            f'email_to = "{esc(self.alerts.email_to)}"',
            f'email_password = "{esc(self.alerts.email_password)}"',
            f"sms_enabled = {'true' if self.alerts.sms_enabled else 'false'}",
            f'sms_gateway_address = "{esc(self.alerts.sms_gateway_address)}"',
            "",
            "[propagation]",
            f"my_station_full_count = {int(self.propagation.my_station_full_count)}",
            f"my_station_full_dist_km = {float(self.propagation.my_station_full_dist_km)}",
            f"regional_full_count = {int(self.propagation.regional_full_count)}",
            f"regional_full_dist_km = {float(self.propagation.regional_full_dist_km)}",
            "",
            "[weather]",
            f"enabled = {'true' if self.weather.enabled else 'false'}",
            f'location_code = "{esc(self.weather.location_code)}"',
            f'current_provider = "{esc(self.weather.current_provider)}"',
            f'alert_provider = "{esc(self.weather.alert_provider)}"',
            f'weatherbit_api_key = "{esc(self.weather.weatherbit_api_key)}"',
            f"weatherbit_poll_minutes = {int(self.weather.weatherbit_poll_minutes)}",
            f"alert_range_miles = {int(self.weather.alert_range_miles)}",
            f"refresh_minutes = {int(self.weather.refresh_minutes)}",
            f"radar_enabled = {'true' if self.weather.radar_enabled else 'false'}",
            f'radar_provider = "{esc(self.weather.radar_provider)}"',
            f"radar_opacity = {float(self.weather.radar_opacity)}",
            f"radar_animate = {'true' if self.weather.radar_animate else 'false'}",
            f"alert_overlay_enabled = {'true' if self.weather.alert_overlay_enabled else 'false'}",
            'alert_overlay_groups = [' + ', '.join('"' + self._toml_escape(v) + '"' for v in self.weather.alert_overlay_groups) + ']',
            f'alert_scope_mode = "{esc(self.weather.alert_scope_mode)}"',
            f'alert_scope_zone = "{esc(self.weather.alert_scope_zone)}"',
            f"elevated_alert_polling_enabled = {'true' if self.weather.elevated_alert_polling_enabled else 'false'}",
            f"elevated_alert_polling_seconds = {int(self.weather.elevated_alert_polling_seconds)}",
            f"elevated_alert_cooldown_minutes = {int(self.weather.elevated_alert_cooldown_minutes)}",
            'elevated_trigger_events = [' + ', '.join('"' + self._toml_escape(v) + '"' for v in self.weather.elevated_trigger_events) + ']',
            "",
            "[gps]",
            f"enabled = {'true' if self.gps.enabled else 'false'}",
            f'source = "{esc(self.gps.source)}"',
            f"map_update_enabled = {'true' if self.gps.map_update_enabled else 'false'}",
            f"update_station_position = {'true' if self.gps.update_station_position else 'false'}",
            f"station_position_locked = {'true' if self.gps.station_position_locked else 'false'}",
            f'serial_port = "{esc(self.gps.serial_port)}"',
            f"serial_baudrate = {int(self.gps.serial_baudrate)}",
            f'tcp_host = "{esc(self.gps.tcp_host)}"',
            f"tcp_port = {int(self.gps.tcp_port)}",
            f'udp_host = "{esc(self.gps.udp_host)}"',
            f"udp_port = {int(self.gps.udp_port)}",
            "",
            "[mqtt]",
            f"enabled = {'true' if self.mqtt.enabled else 'false'}",
            f'broker = "{esc(self.mqtt.broker)}"',
            f"port = {int(self.mqtt.port)}",
            f'topic_prefix = "{esc(self.mqtt.topic_prefix)}"',
            f'username = "{esc(self.mqtt.username)}"',
            f'password = "{esc(self.mqtt.password)}"',
        ]
        path.write_text("\n".join(lines) + "\n")
