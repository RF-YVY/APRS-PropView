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

[kiss_tcp]
enabled = false
host = "127.0.0.1"
port = 8001

[web]
host = "127.0.0.1"
port = 14501
font_family = ""
ghost_after_minutes = 60
expire_after_minutes = 0
mobile_pin = ""

[database]
path = "propview.db"

[tracking]
max_station_age = 86400
cleanup_interval = 3600

[alerts]
enabled = false
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
alert_range_miles = 50
refresh_minutes = 15

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
    ghost_after_minutes: int = 60
    expire_after_minutes: int = 0
    mobile_pin: str = ""


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
    alert_range_miles: int = 50    # Range for severe weather alerts
    refresh_minutes: int = 15      # How often to refresh weather data


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
            f"ghost_after_minutes = {int(self.web.ghost_after_minutes)}",
            f"expire_after_minutes = {int(self.web.expire_after_minutes)}",
            f'mobile_pin = "{esc(self.web.mobile_pin)}"',
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
            f"alert_range_miles = {int(self.weather.alert_range_miles)}",
            f"refresh_minutes = {int(self.weather.refresh_minutes)}",
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
