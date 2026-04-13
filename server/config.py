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
comment = "APRS PropView Digi/IGate"
beacon_interval = 1800

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

[database]
path = "propview.db"

[tracking]
max_station_age = 86400
cleanup_interval = 3600

[alerts]
enabled = false
min_stations = 5
min_distance_km = 100.0
cooldown_seconds = 1800
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

[weather]
enabled = false
location_code = ""
alert_range_miles = 50
refresh_minutes = 15
"""


@dataclass
class StationConfig:
    callsign: str = "N0CALL"
    ssid: int = 0
    latitude: float = 0.0
    longitude: float = 0.0
    symbol_table: str = "/"
    symbol_code: str = "#"
    comment: str = "APRS PropView Digi/IGate"
    beacon_interval: int = 1800

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
    min_stations: int = 5
    min_distance_km: float = 100.0
    cooldown_seconds: int = 1800
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
class WeatherConfig:
    enabled: bool = False
    location_code: str = ""       # US zip code or ICAO code
    alert_range_miles: int = 50    # Range for severe weather alerts
    refresh_minutes: int = 15      # How often to refresh weather data


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
    weather: WeatherConfig = field(default_factory=WeatherConfig)

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
            "weather": (WeatherConfig, "weather"),
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
            f'comment = "{esc(self.station.comment)}"',
            f"beacon_interval = {int(self.station.beacon_interval)}",
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
            f"min_stations = {int(self.alerts.min_stations)}",
            f"min_distance_km = {float(self.alerts.min_distance_km)}",
            f"cooldown_seconds = {int(self.alerts.cooldown_seconds)}",
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
            "[weather]",
            f"enabled = {'true' if self.weather.enabled else 'false'}",
            f'location_code = "{esc(self.weather.location_code)}"',
            f"alert_range_miles = {int(self.weather.alert_range_miles)}",
            f"refresh_minutes = {int(self.weather.refresh_minutes)}",
        ]
        path.write_text("\n".join(lines) + "\n")
