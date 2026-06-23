import unittest
import asyncio
import json
import tempfile
from pathlib import Path

import server.analytics as analytics_module
from server.aprs_is import APRSISClient
from server.aprs_parser import make_message_packet, parse_packet
from server.app import (
    _is_valid_message_addressee,
    _is_valid_station_callsign,
    _merge_secret_value,
    _rf_ports_signature,
    _tile_cache_key,
    _tile_cache_path,
    _tile_coords_for_bounds,
    _validate_config,
)
from server.analytics import AnalyticsEngine
from server.alerts import AlertConfig, AlertManager
from server.ax25 import AX25Address, AX25Frame
from server.callbook import (
    CallbookCredentials,
    lookup_callook_sync,
    lookup_hamdb_sync,
    lookup_hamqth_sync,
    lookup_qrz_sync,
)
from server.config import Config, RFPortConfig, WatchedPathConfig
from server.database import Database
from server.digipeater import Digipeater
from server.export import MQTTPublisher
from server.packet_handler import PacketHandler
from server.station_tracker import StationTracker
from server.websocket_manager import WebSocketManager
from server.gps import GPSManager, parse_gpsd_tpv, parse_nmea_position, split_nmea_stream
from server.status_report import build_dx_status_text, build_mheard_status_text, build_weather_alert_status_text, trim_status_text
from server.wxnow import build_wxnow_info, build_wxnow_position_info, parse_weather_body_values, parse_wxnow_text


class SettingsImpactTests(unittest.TestCase):
    def test_rf_port_signature_only_changes_when_port_settings_change(self):
        original = RFPortConfig(
            name="KISS TCP",
            enabled=True,
            type="tcp",
            host="127.0.0.1",
            tcp_port=8001,
            protocol="kiss",
            rx_only_rf=True,
        )
        unchanged = RFPortConfig(**vars(original))
        changed = RFPortConfig(**{**vars(original), "tcp_port": 8100})

        self.assertEqual(_rf_ports_signature([original]), _rf_ports_signature([unchanged]))
        self.assertNotEqual(_rf_ports_signature([original]), _rf_ports_signature([changed]))


class APRSParserComplianceTests(unittest.TestCase):
    def test_message_packet_id_has_no_closing_brace(self):
        self.assertEqual(
            make_message_packet("KK7PZE-10", "hello 501", "4"),
            ":KK7PZE-10:hello 501{4",
        )

    def test_third_party_message_is_unwrapped(self):
        packet = parse_packet(
            "G9RXG>APRS:}WB4APR-14>APRS,TCPIP,G9RXG*::N0CALL   :Hi{001",
            source="rf",
        )

        self.assertEqual(packet.packet_type, "message")
        self.assertEqual(packet.from_call, "WB4APR-14")
        self.assertEqual(packet.to_call, "APRS")
        self.assertEqual(packet.path, "TCPIP,G9RXG*")
        self.assertEqual(packet.addressee, "N0CALL")
        self.assertEqual(packet.message_text, "Hi")
        self.assertEqual(packet.message_id, "001")

    def test_position_weather_symbol_is_weather_packet(self):
        packet = parse_packet(
            "K5ABC-13>APPRPV:@071400z3530.00N/09745.00W_292/004g011t098h36b10139",
            source="rf",
        )

        self.assertEqual(packet.packet_type, "weather")
        self.assertAlmostEqual(packet.latitude, 35.5)
        self.assertEqual(packet.symbol_code, "_")

    def test_position_weather_without_timestamp_keeps_weather_body(self):
        packet = parse_packet(
            "KK7PZE-13>APDW18:!3345.29N/11146.39W_098/003g004t082r000p000P000h26b10088Ambient Weather WS-2902",
            source="aprs_is",
        )

        self.assertEqual(packet.packet_type, "weather")
        self.assertEqual(packet.symbol_code, "_")
        self.assertTrue(packet.comment.startswith("098/003g004t082"))
        self.assertEqual(packet.weather["wind_direction"], 98)
        self.assertEqual(packet.weather["wind_speed_mph"], 3)
        self.assertEqual(packet.weather["temperature_f"], 82)
        self.assertEqual(packet.weather["humidity"], 26)
        self.assertEqual(packet.weather["pressure_mb"], 1008.8)

    def test_positionless_weather_timestamp_is_parsed(self):
        packet = parse_packet(
            "K5ABC-13>APPRPV:_05250942c067s000g...t074P...h99b09977",
            source="aprs_is",
        )

        self.assertEqual(packet.packet_type, "weather")
        self.assertEqual(packet.timestamp, "05250942")
        self.assertEqual(packet.comment, "c067s000g...t074P...h99b09977")
        self.assertEqual(packet.weather["wind_direction"], 67)
        self.assertEqual(packet.weather["wind_speed_mph"], 0)
        self.assertEqual(packet.weather["temperature_f"], 74)
        self.assertEqual(packet.weather["humidity"], 99)
        self.assertEqual(packet.weather["pressure_mb"], 997.7)

    def test_positionless_weather_without_timestamp_is_parsed(self):
        packet = parse_packet(
            "K5ABC-13>APPRPV:_272/010g006t069r010p030P020h61b10150",
            source="rf",
        )

        self.assertEqual(packet.packet_type, "weather")
        self.assertEqual(packet.weather["wind_direction"], 272)
        self.assertEqual(packet.weather["wind_speed_mph"], 10)
        self.assertEqual(packet.weather["wind_gust_mph"], 6)
        self.assertEqual(packet.weather["rain_1h_in"], 0.1)

    def test_position_weather_forms_are_explicitly_supported(self):
        bodies = [
            "!3345.28N/11146.40W_119/002g003t086r000p000P000h15b10038Ambient Weather WS-2902",
            "=3345.28N/11146.40W_119/002g003t086r000p000P000h15b10038Ambient Weather WS-2902",
            "@261750z3345.28N/11146.40W_119/002g003t086r000p000P000h15b10038Ambient Weather WS-2902",
            "/261750z3345.28N/11146.40W_119/002g003t086r000p000P000h15b10038Ambient Weather WS-2902",
        ]

        for body in bodies:
            with self.subTest(body=body[:8]):
                packet = parse_packet(f"KK7PZE-13>APDW18:{body}", source="rf")

                self.assertEqual(packet.packet_type, "weather")
                self.assertAlmostEqual(packet.latitude, 33.754666666666665)
                self.assertAlmostEqual(packet.longitude, -111.77333333333333)
                self.assertEqual(packet.symbol_table, "/")
                self.assertEqual(packet.symbol_code, "_")
                self.assertEqual(packet.weather["wind_direction"], 119)
                self.assertEqual(packet.weather["wind_speed_mph"], 2)
                self.assertEqual(packet.weather["wind_gust_mph"], 3)
                self.assertEqual(packet.weather["temperature_f"], 86)
                self.assertEqual(packet.weather["humidity"], 15)
                self.assertEqual(packet.weather["pressure_mb"], 1003.8)

    def test_compressed_position_keeps_full_comment(self):
        packet = parse_packet("CALL>APRS:!/5L!!<*e7Pxyzcomment", source="rf")

        self.assertEqual(packet.packet_type, "position")
        self.assertAlmostEqual(packet.latitude, 49.5, places=3)
        self.assertAlmostEqual(packet.longitude, -72.75, places=3)
        self.assertEqual(packet.comment, "comment")

    def test_compressed_position_accepts_overlay_table_id(self):
        packet = parse_packet("CALL>APRS:!A5L!!<*e7Pxyzoverlay", source="rf")

        self.assertEqual(packet.packet_type, "position")
        self.assertEqual(packet.symbol_table, "A")
        self.assertEqual(packet.comment, "overlay")

    def test_compressed_weather_symbol_parses_weather_body(self):
        packet = parse_packet("CALL>APRS:!/5L!!<*e7_xyzg011t098h36b10139", source="rf")

        self.assertEqual(packet.packet_type, "weather")
        self.assertEqual(packet.symbol_code, "_")
        self.assertEqual(packet.weather["wind_gust_mph"], 11)
        self.assertEqual(packet.weather["temperature_f"], 98)
        self.assertEqual(packet.weather["humidity"], 36)
        self.assertEqual(packet.weather["pressure_mb"], 1013.9)

    def test_malformed_uncompressed_latitude_is_not_decoded_as_compressed(self):
        packet = parse_packet(
            r"VE3STP-10>APZ0,VE2REH-3*,WIDE2*:!44518.91N\07653.58W-STP2 Telemetry",
            source="rf",
        )

        self.assertEqual(packet.packet_type, "other")
        self.assertIsNone(packet.latitude)
        self.assertIsNone(packet.longitude)

    def test_valid_uncompressed_packet_after_malformed_regression(self):
        packet = parse_packet(
            r"VE3STP-10>APZ0,VE2REH-3*,WIDE2*:!4451.89N\07653.58W-STP2 Telemetry",
            source="rf",
        )

        self.assertEqual(packet.packet_type, "position")
        self.assertAlmostEqual(packet.latitude, 44.86483333333334)
        self.assertAlmostEqual(packet.longitude, -76.893)

    def test_double_bang_telemetry_is_not_compressed_position(self):
        packet = parse_packet(
            "K4CCC-9>APRS,NC4CD-1*,WIDE2-1:!!0000005B028C015D27E002E8--------008B01B600000000",
            source="rf",
        )

        self.assertEqual(packet.packet_type, "other")
        self.assertIsNone(packet.latitude)
        self.assertIsNone(packet.longitude)

    def test_third_party_tcpip_position_preserves_internet_path_metadata(self):
        packet = parse_packet(
            "WINNSB>APDW16,NE4SC-12*,WIDE2*:}OH6SC>APRS,TCPIP,WINNSB*:!6247.33N/02248.17E-",
            source="rf",
        )

        self.assertEqual(packet.packet_type, "position")
        self.assertTrue(packet.third_party)
        self.assertEqual(packet.from_call, "OH6SC")
        self.assertEqual(packet.path, "TCPIP,WINNSB*")
        self.assertEqual(packet.outer_from_call, "WINNSB")
        self.assertEqual(packet.outer_path, "NE4SC-12*,WIDE2*")

    def test_uncompressed_course_speed_extension(self):
        packet = parse_packet(
            "CALL>APRS:=4903.50N/07201.75W>088/036Moving",
            source="rf",
        )

        self.assertEqual(packet.packet_type, "position")
        self.assertEqual(packet.course, 88)
        self.assertAlmostEqual(packet.speed, 66.672, places=3)
        self.assertEqual(packet.comment, "Moving")


class APRSISComplianceTests(unittest.TestCase):
    def test_login_uses_current_app_version(self):
        config = Config()
        config.station.callsign = "K5ABC"
        config.aprs_is.passcode = "12345"
        client = APRSISClient(config, lambda packet: None, app_version="1.5.5.3")

        self.assertIn("vers APRSPropView 1.5.5.3", client._build_login())

    def test_packet_sent_instead_of_logresp_is_not_dropped(self):
        async def run_test():
            received = []
            got_packet = asyncio.Event()
            got_login = asyncio.Event()
            packet_line = "K1ABC>APRS,TCPIP*:!3600.00N/09800.00W-Test"

            async def handle_client(reader, writer):
                login = await reader.readline()
                if login.startswith(b"user K5ABC"):
                    got_login.set()
                writer.write((packet_line + "\r\n").encode("latin-1"))
                await writer.drain()
                await got_packet.wait()
                writer.close()
                await writer.wait_closed()

            server = await asyncio.start_server(handle_client, "127.0.0.1", 0)
            host, port = server.sockets[0].getsockname()[:2]
            config = Config()
            config.station.callsign = "K5ABC"
            config.aprs_is.server = host
            config.aprs_is.port = port
            config.aprs_is.passcode = "-1"

            async def on_packet(packet):
                received.append(packet)
                got_packet.set()

            client = APRSISClient(config, on_packet)
            client._handshake_timeout = 0.1
            task = asyncio.create_task(client.connect())
            try:
                await asyncio.wait_for(got_login.wait(), timeout=2)
                await asyncio.wait_for(got_packet.wait(), timeout=2)
            finally:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
                server.close()
                await server.wait_closed()

            self.assertEqual(received, [packet_line])
            self.assertFalse(client.verified)

        import contextlib

        asyncio.run(run_test())


class ConfigTests(unittest.TestCase):
    def test_merge_secret_value_allows_clear_without_resaving_masks(self):
        self.assertEqual(
            _merge_secret_value("secret", "", submitted_present=True),
            "",
        )
        self.assertEqual(
            _merge_secret_value("secret", "*****t", submitted_present=True),
            "secret",
        )
        self.assertEqual(
            _merge_secret_value("secret", "newsecret", submitted_present=True),
            "newsecret",
        )
        self.assertEqual(
            _merge_secret_value("secret", "", submitted_present=False),
            "secret",
        )

    def test_loads_and_saves_multiple_rf_ports(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.toml"
            path.write_text(
                """
[station]
callsign = "K5ABC"

[[rf_ports]]
name = "Vertical"
enabled = true
type = "serial"
port = "COM7"
baudrate = 19200
mode = "kiss"
flow_control = "xonxoff"
init_profile = "kenwood_thd7"
init_commands = "MYCALL {callsign}"

[[rf_ports]]
name = "Yagi"
enabled = false
type = "tcp"
host = "tnc.local"
tcp_port = 8100
""".strip(),
                encoding="utf-8",
            )

            config = Config.load(path)

            self.assertEqual(len(config.rf_ports), 2)
            self.assertEqual(config.rf_ports[0].name, "Vertical")
            self.assertEqual(config.rf_ports[0].port, "COM7")
            self.assertEqual(config.rf_ports[0].flow_control, "xonxoff")
            self.assertEqual(config.rf_ports[1].name, "Yagi")
            self.assertEqual(config.rf_ports[1].host, "tnc.local")
            self.assertEqual(config.rf_ports[1].tcp_port, 8100)

            config.rf_ports.append(RFPortConfig(name="Backup", enabled=True, type="tcp", host="127.0.0.1", tcp_port=8002))
            saved_path = Path(tmp) / "saved.toml"
            config.save(saved_path)
            reloaded = Config.load(saved_path)

            self.assertEqual([port.name for port in reloaded.rf_ports], ["Vertical", "Yagi", "Backup"])
            self.assertEqual(reloaded.rf_ports[2].tcp_port, 8002)

    def test_loads_and_saves_mqtt_discovery_settings(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.toml"
            path.write_text(
                """
[mqtt]
enabled = true
broker = "ha.local"
port = 1883
topic_prefix = "ham/aprs"
username = "propview"
password = "secret"
discovery_enabled = true
discovery_prefix = "homeassistant"
device_name = "APRS PropView K5ABC"
device_id = "k5abc_propview"
watched_callsigns = ["WB5TZN-1", "KJ4AJP-5"]
""".strip(),
                encoding="utf-8",
            )

            config = Config.load(path)
            self.assertTrue(config.mqtt.discovery_enabled)
            self.assertEqual(config.mqtt.discovery_prefix, "homeassistant")
            self.assertEqual(config.mqtt.device_name, "APRS PropView K5ABC")
            self.assertEqual(config.mqtt.device_id, "k5abc_propview")
            self.assertEqual(config.mqtt.watched_callsigns, ["WB5TZN-1", "KJ4AJP-5"])

            saved_path = Path(tmp) / "saved.toml"
            config.save(saved_path)
            reloaded = Config.load(saved_path)

            self.assertTrue(reloaded.mqtt.discovery_enabled)
            self.assertEqual(reloaded.mqtt.device_name, "APRS PropView K5ABC")
            self.assertEqual(reloaded.mqtt.device_id, "k5abc_propview")
            self.assertEqual(reloaded.mqtt.watched_callsigns, ["WB5TZN-1", "KJ4AJP-5"])

    def test_loads_and_saves_watched_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.toml"
            path.write_text(
                """
[[watched_paths]]
enabled = true
callsign = "WT1W"
latitude = 35.0
longitude = -80.0
grid = "EM85"
band = "2m SSB"
mode = "SSB"
frequency_mhz = 144.2
min_confidence = "high"
bearing_tolerance_deg = 25
min_probe_count = 3
max_age_minutes = 45
alert_cooldown_minutes = 20
my_antenna_height_m = 12.0
target_antenna_height_m = 18.0
my_tx_power_w = 100.0
my_antenna_gain_dbi = 6.0
""".strip(),
                encoding="utf-8",
            )

            config = Config.load(path)
            self.assertEqual(len(config.watched_paths), 1)
            self.assertEqual(config.watched_paths[0].callsign, "WT1W")
            self.assertEqual(config.watched_paths[0].min_confidence, "high")
            self.assertEqual(config.watched_paths[0].bearing_tolerance_deg, 25)
            self.assertEqual(config.watched_paths[0].grid, "EM85")
            self.assertEqual(config.watched_paths[0].mode, "SSB")
            self.assertAlmostEqual(config.watched_paths[0].frequency_mhz, 144.2)
            self.assertAlmostEqual(config.watched_paths[0].my_tx_power_w, 100.0)
            self.assertAlmostEqual(config.watched_paths[0].my_antenna_gain_dbi, 6.0)

            saved_path = Path(tmp) / "saved.toml"
            config.save(saved_path)
            reloaded = Config.load(saved_path)
            self.assertEqual(reloaded.watched_paths[0].band, "2m SSB")
            self.assertEqual(reloaded.watched_paths[0].min_probe_count, 3)
            self.assertEqual(reloaded.watched_paths[0].grid, "EM85")
            self.assertAlmostEqual(reloaded.watched_paths[0].target_antenna_height_m, 18.0)
            self.assertAlmostEqual(reloaded.watched_paths[0].my_tx_power_w, 100.0)
            self.assertAlmostEqual(reloaded.watched_paths[0].my_antenna_gain_dbi, 6.0)

    def test_loads_and_saves_callbook_settings(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.toml"
            path.write_text(
                """
[callbook]
provider = "auto"
hamqth_username = "N0CALL"
hamqth_password = "hamsecret"
qrz_username = "N0CALL"
qrz_password = "qrzsecret"
""".strip(),
                encoding="utf-8",
            )

            config = Config.load(path)
            self.assertEqual(config.callbook.provider, "auto")
            self.assertEqual(config.callbook.hamqth_username, "N0CALL")
            self.assertEqual(config.callbook.hamqth_password, "hamsecret")
            self.assertEqual(config.callbook.qrz_password, "qrzsecret")

            saved_path = Path(tmp) / "saved.toml"
            config.save(saved_path)
            reloaded = Config.load(saved_path)

            self.assertEqual(reloaded.callbook.provider, "auto")
            self.assertEqual(reloaded.callbook.hamqth_password, "hamsecret")
            self.assertEqual(reloaded.callbook.qrz_username, "N0CALL")

    def test_tile_cache_key_separates_tile_sources(self):
        osm = "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        local = "http://127.0.0.1:8080/tile/{z}/{x}/{y}.png"

        self.assertNotEqual(_tile_cache_key(osm), _tile_cache_key(local))
        self.assertNotEqual(_tile_cache_path(osm, 5, 8, 12), _tile_cache_path(local, 5, 8, 12))

    def test_tile_coords_for_current_view_bounds(self):
        coords = _tile_coords_for_bounds(
            {"north": 36.0, "south": 35.0, "east": -79.0, "west": -80.0},
            8,
            8,
        )

        self.assertTrue(coords)
        self.assertTrue(all(z == 8 for z, _x, _y in coords))
        self.assertEqual(len(coords), len(set(coords)))

class CallbookTests(unittest.TestCase):
    def test_callook_lookup_extracts_current_fcc_location(self):
        response = b"""{
            "status": "VALID",
            "current": {"callsign": "WT1W", "operClass": "EXTRA"},
            "name": "JIM H PERRY",
            "address": {"line2": "HOPE HULL, AL 36043"},
            "location": {"latitude": "32.1757206", "longitude": "-86.3493209", "gridsquare": "EM62te"}
        }"""

        def fake_fetch(url, timeout):
            self.assertIn("callook.info/WT1W/json", url)
            return response

        result = lookup_callook_sync(CallbookCredentials(provider="callook"), "WT1W", fetcher=fake_fetch)

        self.assertTrue(result["success"])
        self.assertEqual(result["source"], "callook")
        self.assertEqual(result["callsign"], "WT1W")
        self.assertEqual(result["grid"], "EM62TE")
        self.assertAlmostEqual(result["latitude"], 32.1757206)
        self.assertAlmostEqual(result["longitude"], -86.3493209)
        self.assertEqual(result["country"], "United States")

    def test_hamdb_lookup_extracts_location_fields(self):
        response = b"""{
            "hamdb": {
                "callsign": {
                    "call": "WT1W",
                    "class": "E",
                    "status": "A",
                    "grid": "EM62te",
                    "lat": "32.1757035",
                    "lon": "-86.3493001",
                    "fname": "Jim",
                    "name": "Perry",
                    "addr2": "Hope Hull",
                    "state": "AL",
                    "zip": "36043",
                    "country": "United States"
                },
                "messages": {"status": "OK"}
            }
        }"""

        def fake_fetch(url, timeout):
            self.assertIn("api.hamdb.org/WT1W/json/APRSPropView", url)
            return response

        result = lookup_hamdb_sync(CallbookCredentials(provider="hamdb"), "WT1W", fetcher=fake_fetch)

        self.assertTrue(result["success"])
        self.assertEqual(result["source"], "hamdb")
        self.assertEqual(result["callsign"], "WT1W")
        self.assertEqual(result["grid"], "EM62TE")
        self.assertAlmostEqual(result["latitude"], 32.1757035)
        self.assertAlmostEqual(result["longitude"], -86.3493001)
        self.assertEqual(result["state"], "AL")

    def test_hamqth_lookup_extracts_location_fields(self):
        responses = [
            b"""<?xml version="1.0"?><HamQTH><session><session_id>abc123</session_id></session></HamQTH>""",
            b"""<?xml version="1.0"?><HamQTH><search><callsign>wt1w</callsign><grid>FM15</grid><latitude>35.5</latitude><longitude>-77.0</longitude><qth>Raleigh</qth><adr_country>United States</adr_country></search></HamQTH>""",
        ]
        urls = []

        def fake_fetch(url, timeout):
            urls.append(url)
            return responses.pop(0)

        result = lookup_hamqth_sync(
            CallbookCredentials(provider="hamqth", hamqth_username="N0CALL", hamqth_password="secret"),
            "WT1W",
            fetcher=fake_fetch,
        )

        self.assertTrue(result["success"])
        self.assertEqual(result["source"], "hamqth")
        self.assertEqual(result["callsign"], "WT1W")
        self.assertEqual(result["grid"], "FM15")
        self.assertAlmostEqual(result["latitude"], 35.5)
        self.assertAlmostEqual(result["longitude"], -77.0)
        self.assertIn("xml.php", urls[0])

    def test_qrz_lookup_extracts_location_fields(self):
        responses = [
            b"""<?xml version="1.0"?><QRZDatabase><Session><Key>xyz789</Key></Session></QRZDatabase>""",
            b"""<?xml version="1.0"?><QRZDatabase><Callsign><call>WT1W</call><grid>FM15</grid><lat>35.5</lat><lon>-77.0</lon><addr2>Raleigh</addr2><country>United States</country></Callsign></QRZDatabase>""",
        ]

        def fake_fetch(_url, _timeout):
            return responses.pop(0)

        result = lookup_qrz_sync(
            CallbookCredentials(provider="qrz", qrz_username="N0CALL", qrz_password="secret"),
            "WT1W",
            fetcher=fake_fetch,
        )

        self.assertTrue(result["success"])
        self.assertEqual(result["source"], "qrz")
        self.assertEqual(result["callsign"], "WT1W")
        self.assertEqual(result["grid"], "FM15")
        self.assertAlmostEqual(result["latitude"], 35.5)
        self.assertAlmostEqual(result["longitude"], -77.0)


class WxNowTests(unittest.TestCase):
    def test_parse_wxnow_two_line_file(self):
        reading = parse_wxnow_text("Jul 07 2012 14:00\n292/004g011t098h36b10139jDvs9\n")

        self.assertEqual(reading.timestamp.year, 2012)
        self.assertEqual(reading.weather_body, "292/004g011t098h36b10139jDvs9")

    def test_build_positioned_wx_packet(self):
        config = Config()
        config.station.callsign = "K5ABC"
        config.station.latitude = 35.5
        config.station.longitude = -97.75
        reading = parse_wxnow_text("Jul 07 2012 14:00\n292/004g011t098h36b10139jDvs9\n")

        self.assertEqual(
            build_wxnow_info(config, reading),
            "/071400z3530.00N/09745.00W_292/004g011t098h36b10139jDvs9",
        )

    def test_build_positionless_wx_packet(self):
        config = Config()
        config.wxnow.include_position = False
        reading = parse_wxnow_text("Jul 07 2012 14:00\n292/004g011t098h36b10139jDvs9\n")

        self.assertEqual(
            build_wxnow_info(config, reading),
            "_07071400c292s004g011t098h36b10139jDvs9",
        )

    def test_build_positioned_wx_packet_inserts_missing_temperature_tag(self):
        config = Config()
        config.station.callsign = "K5ABC"
        config.station.latitude = 35.5321667
        config.station.longitude = -79.75
        reading = parse_wxnow_text("May 25 2026 09:35\n180/000074P9616h99b09976\n")

        self.assertEqual(reading.weather_body, "180/000t074P...h99b09976")
        self.assertEqual(
            build_wxnow_info(config, reading),
            "/250935z3531.93N/07945.00W_180/000t074P...h99b09976",
        )

    def test_build_positionless_wx_packet_inserts_missing_temperature_tag(self):
        config = Config()
        config.wxnow.include_position = False
        reading = parse_wxnow_text("May 25 2026 09:42\n067/000074P9616h99b09977\n")

        self.assertEqual(
            build_wxnow_info(config, reading),
            "_05250942c067s000g...t074P...h99b09977",
        )

    def test_positionless_wx_packet_matches_aprslib_format(self):
        import aprslib

        config = Config()
        config.wxnow.include_position = False
        reading = parse_wxnow_text("May 25 2026 09:42\n067/000074P9616h99b09977\n")
        raw = f"K5ABC-13>APPRPV:{build_wxnow_info(config, reading)}"

        parsed = aprslib.parse(raw)

        self.assertEqual(parsed["format"], "wx")
        self.assertEqual(parsed["wx_raw_timestamp"], "05250942")
        self.assertEqual(parsed["weather"]["wind_direction"], 67)
        self.assertAlmostEqual(parsed["weather"]["temperature"], 23.333333333333332)
        self.assertEqual(parsed["weather"]["humidity"], 99)
        self.assertEqual(parsed["weather"]["pressure"], 997.7)

    def test_parse_wxnow_values_include_banner_field_names(self):
        reading = parse_wxnow_text("May 25 2026 12:55\n202/005074P9627h99b09974\n")
        values = parse_weather_body_values(reading)

        self.assertEqual(reading.weather_body, "202/005t074P...h99b09974")
        self.assertEqual(values["temperature_f"], 74)
        self.assertEqual(values["feels_like_f"], 74)
        self.assertEqual(values["humidity"], 99)
        self.assertEqual(values["pressure_mb"], 997.4)

    def test_parse_wxnow_preserves_valid_rain_since_midnight(self):
        reading = parse_wxnow_text("May 25 2026 12:55\n202/005074P123h99b09974\n")

        self.assertEqual(reading.weather_body, "202/005t074P123h99b09974")

    def test_build_positionless_wx_position_uses_weather_station_symbol(self):
        config = Config()
        config.station.latitude = 35.5321667
        config.station.longitude = -79.75

        self.assertEqual(
            build_wxnow_position_info(config),
            "!3531.93N/07945.00W_WXnow",
        )

    def test_positionless_wx_transmit_seeds_matching_position_call(self):
        from server.wxnow import WxNowTransmitter

        class FakeHandler:
            def __init__(self):
                self.sent = []

            async def transmit_aprs_info(self, **kwargs):
                self.sent.append(kwargs)
                return {"can_transmit": True, "message": "Transmitted on APRS-IS."}

        async def run_test():
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "WXnow.txt"
                path.write_text("May 25 2026 09:42\n067/000074P9616h99b09977\n", encoding="ascii")
                config = Config()
                config.station.callsign = "K5ABC"
                config.station.latitude = 35.5321667
                config.station.longitude = -79.75
                config.wxnow.enabled = True
                config.wxnow.file_path = str(path)
                config.wxnow.include_position = False
                config.wxnow.mode = "aprs_is"
                handler = FakeHandler()

                result = await WxNowTransmitter(config, handler).transmit_once(force=True)

                self.assertEqual(result["station"], "K5ABC-13")
                self.assertEqual([sent["source_call"] for sent in handler.sent], ["K5ABC-13", "K5ABC-13"])
                self.assertEqual(handler.sent[0]["info"], "!3531.93N/07945.00W_WXnow")
                self.assertEqual(handler.sent[1]["info"], "_05250942c067s000g...t074P...h99b09977")

        asyncio.run(run_test())

    def test_positionless_wx_force_does_not_resend_recent_position_seed(self):
        from server.wxnow import WxNowTransmitter

        class FakeHandler:
            def __init__(self):
                self.sent = []

            async def transmit_aprs_info(self, **kwargs):
                self.sent.append(kwargs)
                return {"can_transmit": True, "message": "Transmitted on APRS-IS."}

        async def run_test():
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "WXnow.txt"
                path.write_text("May 25 2026 09:42\n067/000074P9616h99b09977\n", encoding="ascii")
                config = Config()
                config.station.callsign = "K5ABC"
                config.station.latitude = 35.5321667
                config.station.longitude = -79.75
                config.wxnow.enabled = True
                config.wxnow.file_path = str(path)
                config.wxnow.include_position = False
                config.wxnow.mode = "aprs_is"
                handler = FakeHandler()
                transmitter = WxNowTransmitter(config, handler)

                await transmitter.transmit_once(force=True)
                path.write_text("May 25 2026 09:43\n067/000075P9617h99b09977\n", encoding="ascii")
                await transmitter.transmit_once(force=True)

                self.assertEqual(
                    [sent["info"][0] for sent in handler.sent],
                    ["!", "_", "_"],
                )

        asyncio.run(run_test())

    def test_parse_wxnow_inserts_missing_temperature_tag_after_gust(self):
        reading = parse_wxnow_text("Jun 01 2003 08:07\n272/000g006069r010p030P020h61b10150\n")

        self.assertEqual(reading.weather_body, "272/000g006t069r010p030P020h61b10150")

    def test_parse_wxnow_values_for_current_conditions(self):
        reading = parse_wxnow_text("Feb 09 2021 13:00\n086/004g008t028r000p000P000h75b10007\n")
        values = parse_weather_body_values(reading)

        self.assertEqual(values["wind_direction"], 86)
        self.assertEqual(values["wind_speed_mph"], 4)
        self.assertEqual(values["wind_gusts_mph"], 8)
        self.assertEqual(values["temperature"], 28)
        self.assertEqual(values["humidity"], 75)
        self.assertEqual(values["pressure"], 1000.7)


class DigipeaterTests(unittest.TestCase):
    def _frame(self, path):
        return AX25Frame(
            destination=AX25Address.from_string("APRS"),
            source=AX25Address.from_string("K1ABC"),
            digipeaters=[AX25Address.from_string(hop) for hop in path],
            info=b"!3530.00N/09745.00W-Test",
        )

    def test_only_configured_wide_aliases_are_digipeated(self):
        config = Config()
        config.station.callsign = "K5ABC"
        config.station.ssid = 1
        config.digipeater.aliases = ["WIDE1-1"]
        digi = Digipeater(config)

        self.assertIsNone(digi.should_digipeat(self._frame(["WIDE2-1"])))
        digi = Digipeater(config)
        self.assertIsNotNone(digi.should_digipeat(self._frame(["WIDE1-1"])))


class StatusDxTests(unittest.TestCase):
    def test_builds_compact_dx_status(self):
        text = build_dx_status_text({
            "my_top_station": {"callsign": "K1ABC", "distance_km": 321.9, "heading": 315},
            "my_stations_1h": 4,
            "regional_stations_1h": 9,
            "my_level": "good",
        })

        self.assertEqual(text, "DX 60m: K1ABC 200mi NW 4D/9RF GOOD")

    def test_status_falls_back_when_no_rf_heard(self):
        self.assertEqual(
            build_dx_status_text({"my_stations_1h": 0, "regional_stations_1h": 0}),
            "DX 60m: no RF stations heard",
        )

    def test_status_text_is_printable_and_limited(self):
        self.assertEqual(trim_status_text("DX\nbad\tchars", 8), "DX bad chars"[:20])
        self.assertEqual(len(trim_status_text("x" * 200, 67)), 67)

    def test_builds_mheard_from_direct_heard_stations(self):
        text = build_mheard_status_text({
            "direct_heard_stations": [
                {"callsign": "K1ABC"},
                {"callsign": "N5XYZ-7"},
                {"callsign": "W4TEST"},
            ],
        })

        self.assertEqual(text, "MHeard 60m: K1ABC, N5XYZ-7, W4TEST")

    def test_weather_alert_status_is_compact(self):
        text = build_weather_alert_status_text({
            "event": "Severe Thunderstorm Warning",
            "severity": "Severe",
            "alert_type": "warning",
        })

        self.assertEqual(text, "WX WARNING: Severe Thunderstorm Warning")

    def test_dynamic_preview_does_not_advance_next_message(self):
        from server.status_report import StatusReportTransmitter

        class FakeTracker:
            async def get_propagation_data(self):
                return {}

        class FakeHandler:
            async def transmit_aprs_info(self, **kwargs):
                return {"can_transmit": True, "message": "Transmitted."}

        async def run_test():
            config = Config()
            config.status.source = "dynamic"
            config.status.dynamic_messages = ["One", "Two"]
            tx = StatusReportTransmitter(config, FakeHandler(), FakeTracker())

            self.assertEqual(await tx.build_preview_text(), "One")
            self.assertEqual(await tx.build_preview_text(), "One")
            self.assertEqual((await tx.transmit_once(force=True))["text"], "One")
            self.assertEqual(await tx.build_preview_text(), "Two")

        asyncio.run(run_test())


class MessageAddresseeValidationTests(unittest.TestCase):
    def test_accepts_reported_callsign(self):
        self.assertTrue(_is_valid_message_addressee("KJ5GOV"))

    def test_accepts_callsign_with_ssid(self):
        self.assertTrue(_is_valid_message_addressee("KJ5GOV-10"))

    def test_accepts_gateway_addressee(self):
        self.assertTrue(_is_valid_message_addressee("EMAIL-2"))

    def test_accepts_aprs_bot_addressees(self):
        for addressee in ("WXBOT", "ANSRVR", "SMSGTE", "EMAIL", "WHO-IS"):
            self.assertTrue(_is_valid_message_addressee(addressee))

    def test_rejects_malformed_addressees(self):
        for addressee in ("", "-KJ5GOV", "KJ5GOV-", "TOO-LONG10", "BAD/CALL", "BAD CALL"):
            self.assertFalse(_is_valid_message_addressee(addressee))


class MessagePersistenceTests(unittest.TestCase):
    def test_messages_persist_and_dedupe_by_message_key(self):
        async def run_test():
            with tempfile.TemporaryDirectory() as tmp:
                db = Database(f"{tmp}/test.db")
                await db.initialize()
                try:
                    first = await db.add_message(
                        direction="rx",
                        from_call="KK7PZE-7",
                        to_call="KK7PZE",
                        text="Reply 1",
                        message_id="12",
                        source="rf",
                        dedupe_key="id:KK7PZE-7|KK7PZE|12",
                    )
                    duplicate = await db.add_message(
                        direction="rx",
                        from_call="KK7PZE-7",
                        to_call="KK7PZE",
                        text="Reply 1",
                        message_id="12",
                        source="aprs_is",
                        dedupe_key="id:KK7PZE-7|KK7PZE|12",
                    )
                    messages = await db.get_recent_messages()
                finally:
                    await db.close()

            self.assertIsNotNone(first)
            self.assertIsNone(duplicate)
            self.assertEqual(len(messages), 1)
            self.assertEqual(messages[0]["from"], "KK7PZE-7")
            self.assertEqual(messages[0]["to"], "KK7PZE")

        asyncio.run(run_test())

    def test_message_contacts_can_be_deleted(self):
        async def run_test():
            with tempfile.TemporaryDirectory() as tmp:
                db = Database(f"{tmp}/test.db")
                await db.initialize()
                try:
                    await db.upsert_message_contact("KK7PZE-7")
                    before = await db.get_message_contacts()
                    deleted = await db.delete_message_contact("KK7PZE-7")
                    after = await db.get_message_contacts()
                finally:
                    await db.close()

            self.assertEqual([c["callsign"] for c in before], ["KK7PZE-7"])
            self.assertTrue(deleted)
            self.assertEqual(after, [])

        asyncio.run(run_test())

    def test_self_echoed_message_is_not_stored_as_received(self):
        async def run_test():
            with tempfile.TemporaryDirectory() as tmp:
                config = Config()
                config.station.callsign = "K5YVY"
                config.station.ssid = 1
                db = Database(f"{tmp}/test.db")
                await db.initialize()
                try:
                    ws = WebSocketManager()
                    tracker = StationTracker(db, config, ws)
                    handler = PacketHandler(config, tracker, None, None, ws)
                    packet = parse_packet(
                        "K5YVY-1>APPRPV,WIDE1-1::KK7PZE   :Hello Joe{1",
                        source="rf",
                    )

                    await handler._check_incoming_message(packet, source="rf")
                    messages = await db.get_recent_messages()
                finally:
                    await db.close()

            self.assertEqual(messages, [])

        asyncio.run(run_test())

    def test_message_to_sibling_station_ssid_is_stored(self):
        async def run_test():
            with tempfile.TemporaryDirectory() as tmp:
                config = Config()
                config.station.callsign = "K5YVY"
                config.station.ssid = 1
                db = Database(f"{tmp}/test.db")
                await db.initialize()
                try:
                    ws = WebSocketManager()
                    tracker = StationTracker(db, config, ws)
                    handler = PacketHandler(config, tracker, None, None, ws)
                    packet = parse_packet(
                        "KK7PZE-7>APRS::K5YVY-7  :Sibling SSID hello{42",
                        source="rf",
                    )

                    await handler._check_incoming_message(packet, source="rf")
                    messages = await db.get_recent_messages()
                finally:
                    await db.close()

            self.assertEqual(len(messages), 1)
            self.assertEqual(messages[0]["from"], "KK7PZE-7")
            self.assertEqual(messages[0]["to"], "K5YVY-7")
            self.assertEqual(messages[0]["text"], "Sibling SSID hello")
            self.assertFalse(messages[0]["acked"])

        asyncio.run(run_test())

    def test_message_to_sibling_station_ssid_can_be_disabled(self):
        async def run_test():
            with tempfile.TemporaryDirectory() as tmp:
                config = Config()
                config.station.callsign = "K5YVY"
                config.station.ssid = 1
                config.messaging.receive_sibling_ssids = False
                db = Database(f"{tmp}/test.db")
                await db.initialize()
                try:
                    ws = WebSocketManager()
                    tracker = StationTracker(db, config, ws)
                    handler = PacketHandler(config, tracker, None, None, ws)
                    sibling_packet = parse_packet(
                        "KK7PZE-7>APRS::K5YVY-7  :Sibling SSID hello{42",
                        source="rf",
                    )
                    exact_packet = parse_packet(
                        "KK7PZE-7>APRS::K5YVY-1  :Exact station hello{43",
                        source="rf",
                    )

                    await handler._check_incoming_message(sibling_packet, source="rf")
                    await handler._check_incoming_message(exact_packet, source="rf")
                    messages = await db.get_recent_messages()
                finally:
                    await db.close()

            self.assertEqual(len(messages), 1)
            self.assertEqual(messages[0]["to"], "K5YVY-1")
            self.assertEqual(messages[0]["text"], "Exact station hello")

        asyncio.run(run_test())

    def test_message_to_other_base_callsign_is_ignored(self):
        async def run_test():
            with tempfile.TemporaryDirectory() as tmp:
                config = Config()
                config.station.callsign = "K5YVY"
                config.station.ssid = 1
                db = Database(f"{tmp}/test.db")
                await db.initialize()
                try:
                    ws = WebSocketManager()
                    tracker = StationTracker(db, config, ws)
                    handler = PacketHandler(config, tracker, None, None, ws)
                    packet = parse_packet(
                        "KK7PZE-7>APRS::W5ABC-7  :Not for this station{43",
                        source="rf",
                    )

                    await handler._check_incoming_message(packet, source="rf")
                    messages = await db.get_recent_messages()
                finally:
                    await db.close()

            self.assertEqual(messages, [])

        asyncio.run(run_test())

    def test_self_message_packet_is_not_tracked_as_rf_station(self):
        async def run_test():
            with tempfile.TemporaryDirectory() as tmp:
                config = Config()
                config.station.callsign = "K5YVY"
                config.station.ssid = 1
                db = Database(f"{tmp}/test.db")
                await db.initialize()
                try:
                    ws = WebSocketManager()
                    tracker = StationTracker(db, config, ws)
                    packet = parse_packet(
                        "K5YVY-1>APPRPV,WIDE1-1::KK7PZE   :Hello Joe{1",
                        source="rf",
                    )

                    await tracker.track_packet(packet)
                    station = await db.get_station("K5YVY-1", "rf")
                    packets = await db.get_recent_packets(limit=10)
                finally:
                    await db.close()

            self.assertIsNone(station)
            self.assertEqual(len(packets), 1)
            self.assertEqual(packets[0]["packet_type"], "message")

        asyncio.run(run_test())

    def test_own_wx_packet_is_logged_and_tracked_as_station(self):
        class FakeWebSocketManager:
            def __init__(self):
                self.messages = []

            async def broadcast(self, message):
                self.messages.append(message)

        async def run_test(source):
            with tempfile.TemporaryDirectory() as tmp:
                config = Config()
                config.station.callsign = "KK7PZE"
                config.station.ssid = 1
                config.wxnow.ssid = 13
                db = Database(f"{tmp}/test.db")
                await db.initialize()
                try:
                    ws = FakeWebSocketManager()
                    tracker = StationTracker(db, config, ws)
                    packet = parse_packet(
                        "KK7PZE-13>APDW18,W7MOT-10,KK7PZE-1*:/261750z3345.28N/11146.40W_119/002g003t086r000p000P000h15b10038Ambient Weather WS-2902",
                        source=source,
                    )

                    await tracker.track_packet(packet)
                    station = await db.get_station("KK7PZE-13", source)
                    packets = await db.get_recent_packets(limit=10)
                finally:
                    await db.close()

            self.assertIsNotNone(station)
            self.assertEqual(station["callsign"], "KK7PZE-13")
            self.assertEqual(station["symbol_code"], "_")
            self.assertEqual(len(packets), 1)
            self.assertEqual(packets[0]["packet_type"], "weather")
            self.assertEqual(packets[0]["from_call"], "KK7PZE-13")
            self.assertTrue(any(msg.get("type") == "packet" for msg in ws.messages))
            self.assertTrue(any(msg.get("type") == "station_update" for msg in ws.messages))

        asyncio.run(run_test("rf"))
        asyncio.run(run_test("aprs_is"))

    def test_rf_packet_port_name_is_stored(self):
        async def run_test():
            with tempfile.TemporaryDirectory() as tmp:
                config = Config()
                config.station.latitude = 35.0
                config.station.longitude = -97.0
                db = Database(f"{tmp}/test.db")
                await db.initialize()
                try:
                    ws = WebSocketManager()
                    tracker = StationTracker(db, config, ws)
                    packet = parse_packet(
                        "K1ABC>APRS:!3600.00N/09800.00W-Test",
                        source="rf",
                    )
                    packet.port_name = "KISS-Serial(COM7)"

                    await tracker.track_packet(packet)
                    station = await db.get_station("K1ABC", "rf")
                    packets = await db.get_recent_packets(limit=1)
                finally:
                    await db.close()

            self.assertEqual(station["last_port_name"], "KISS-Serial(COM7)")
            self.assertEqual(packets[0]["port_name"], "KISS-Serial(COM7)")

        asyncio.run(run_test())

    def test_exact_ssid_blocked_station_is_not_recorded(self):
        async def run_test():
            with tempfile.TemporaryDirectory() as tmp:
                config = Config()
                config.tracking.blocked_callsigns = ["VE3STP-10"]
                db = Database(f"{tmp}/test.db")
                await db.initialize()
                try:
                    ws = WebSocketManager()
                    tracker = StationTracker(db, config, ws)
                    blocked = parse_packet(
                        r"VE3STP-10>APZ0:!4451.89N\07653.58W-STP2 Telemetry",
                        source="rf",
                    )
                    allowed = parse_packet(
                        r"VE3STP-11>APZ0:!4451.89N\07653.58W-STP2 Telemetry",
                        source="rf",
                    )

                    await tracker.track_packet(blocked)
                    await tracker.track_packet(allowed)
                    blocked_station = await db.get_station("VE3STP-10", "rf")
                    allowed_station = await db.get_station("VE3STP-11", "rf")
                    packets = await db.get_recent_packets(limit=10)
                finally:
                    await db.close()

            self.assertIsNone(blocked_station)
            self.assertIsNotNone(allowed_station)
            self.assertEqual([p["from_call"] for p in packets], ["VE3STP-11"])

        asyncio.run(run_test())

    def test_base_callsign_block_blocks_all_ssids(self):
        async def run_test():
            with tempfile.TemporaryDirectory() as tmp:
                config = Config()
                config.tracking.blocked_callsigns = ["VE3STP"]
                db = Database(f"{tmp}/test.db")
                await db.initialize()
                try:
                    ws = WebSocketManager()
                    tracker = StationTracker(db, config, ws)
                    for call in ("VE3STP", "VE3STP-10"):
                        packet = parse_packet(
                            rf"{call}>APZ0:!4451.89N\07653.58W-STP2 Telemetry",
                            source="rf",
                        )
                        await tracker.track_packet(packet)
                    packets = await db.get_recent_packets(limit=10)
                finally:
                    await db.close()

            self.assertEqual(packets, [])

        asyncio.run(run_test())

    def test_maidenhead_grid_resolves_to_center_point(self):
        pos = StationTracker.maidenhead_to_lat_lon("FM15")

        self.assertIsNotNone(pos)
        lat, lon = pos
        self.assertAlmostEqual(lat, 35.5)
        self.assertAlmostEqual(lon, -77.0)
        self.assertIsNone(StationTracker.maidenhead_to_lat_lon("ZZ99"))

    def test_watched_path_alerts_when_rf_evidence_matches_target_path(self):
        async def run_test():
            with tempfile.TemporaryDirectory() as tmp:
                config = Config()
                config.station.latitude = 35.0
                config.station.longitude = -80.0
                config.watched_paths = [
                    WatchedPathConfig(
                        callsign="WT1W",
                        latitude=35.0,
                        longitude=-77.0,
                        min_confidence="medium",
                        min_probe_count=1,
                        bearing_tolerance_deg=35,
                    )
                ]
                db = Database(f"{tmp}/test.db")
                await db.initialize()
                try:
                    ws = WebSocketManager()
                    tracker = StationTracker(db, config, ws)
                    packet = parse_packet(
                        r"K1ABC>APRS:!3500.00N/07654.00W-East probe",
                        source="rf",
                    )
                    await tracker.track_packet(packet)
                    result = await tracker.evaluate_watched_paths()
                finally:
                    await db.close()

            self.assertEqual(len(result["opportunities"]), 1)
            self.assertGreaterEqual(result["opportunities"][0]["score"], 60)
            self.assertEqual(result["opportunities"][0]["confidence"], "high")
            self.assertEqual(len(result["alerts"]), 1)
            self.assertEqual(result["alerts"][0]["type"], "watched_path")

        asyncio.run(run_test())

    def test_watched_path_grid_target_includes_horizon_and_mode_metadata(self):
        async def run_test():
            with tempfile.TemporaryDirectory() as tmp:
                config = Config()
                config.station.latitude = 35.0
                config.station.longitude = -80.0
                config.watched_paths = [
                    WatchedPathConfig(
                        callsign="WT1W",
                        grid="FM15",
                        band="2m",
                        mode="SSB",
                        frequency_mhz=144.2,
                        min_confidence="low",
                        min_probe_count=1,
                        bearing_tolerance_deg=35,
                        my_antenna_height_m=12.0,
                        target_antenna_height_m=18.0,
                        my_tx_power_w=100.0,
                        my_antenna_gain_dbi=6.0,
                    )
                ]
                db = Database(f"{tmp}/test.db")
                await db.initialize()
                try:
                    ws = WebSocketManager()
                    tracker = StationTracker(db, config, ws)
                    packet = parse_packet(
                        r"K1ABC>APRS:!3500.00N/07654.00W-East probe",
                        source="rf",
                    )
                    await tracker.track_packet(packet)
                    result = await tracker.evaluate_watched_paths(allow_alerts=False)
                finally:
                    await db.close()

            return result

        result = asyncio.run(run_test())

        opportunity = result["opportunities"][0]
        self.assertEqual(opportunity["callsign"], "WT1W")
        self.assertEqual(opportunity["grid"], "FM15")
        self.assertEqual(opportunity["mode"], "SSB")
        self.assertAlmostEqual(opportunity["frequency_mhz"], 144.2)
        self.assertAlmostEqual(opportunity["target_latitude"], 35.5)
        self.assertAlmostEqual(opportunity["target_longitude"], -77.0)
        self.assertGreater(opportunity["radio_horizon_km"], 25.0)
        self.assertEqual(opportunity["path_geometry"], "propagation_aided")
        self.assertAlmostEqual(opportunity["my_tx_power_w"], 100.0)
        self.assertAlmostEqual(opportunity["my_antenna_gain_dbi"], 6.0)
        self.assertGreater(opportunity["my_eirp_w"], 390.0)
        self.assertGreater(opportunity["capability_bonus"], 0.0)
        self.assertEqual(result["alerts"], [])

    def test_watched_path_exact_target_can_alert_without_probe_count_quorum(self):
        async def run_test():
            with tempfile.TemporaryDirectory() as tmp:
                config = Config()
                config.station.latitude = 35.0
                config.station.longitude = -80.0
                config.watched_paths = [
                    WatchedPathConfig(
                        callsign="WT1W-7",
                        latitude=35.0,
                        longitude=-77.0,
                        min_confidence="medium",
                        min_probe_count=3,
                        bearing_tolerance_deg=10,
                    )
                ]
                db = Database(f"{tmp}/test.db")
                await db.initialize()
                try:
                    ws = WebSocketManager()
                    tracker = StationTracker(db, config, ws)
                    packet = parse_packet(
                        r"WT1W-7>APRS:!3500.00N/07654.00W-Target heard",
                        source="rf",
                    )
                    await tracker.track_packet(packet)
                    result = await tracker.evaluate_watched_paths()
                    second = await tracker.evaluate_watched_paths()
                finally:
                    await db.close()

            return result, second

        result, second = asyncio.run(run_test())

        self.assertEqual(result["opportunities"][0]["probe_count"], 1)
        self.assertEqual(len(result["alerts"]), 1)
        self.assertEqual(second["alerts"], [])

    def test_watched_path_does_not_alert_for_wrong_direction_evidence(self):
        async def run_test():
            with tempfile.TemporaryDirectory() as tmp:
                config = Config()
                config.station.latitude = 35.0
                config.station.longitude = -80.0
                config.watched_paths = [
                    WatchedPathConfig(
                        callsign="WT1W",
                        latitude=35.0,
                        longitude=-77.0,
                        min_confidence="medium",
                        min_probe_count=1,
                        bearing_tolerance_deg=20,
                    )
                ]
                db = Database(f"{tmp}/test.db")
                await db.initialize()
                try:
                    ws = WebSocketManager()
                    tracker = StationTracker(db, config, ws)
                    packet = parse_packet(
                        r"K1ABC>APRS:!3800.00N/08000.00W-North probe",
                        source="rf",
                    )
                    await tracker.track_packet(packet)
                    result = await tracker.evaluate_watched_paths()
                finally:
                    await db.close()

            self.assertEqual(result["opportunities"][0]["confidence"], "none")
            self.assertEqual(result["alerts"], [])

        asyncio.run(run_test())

    def test_packet_digipeated_by_my_station_is_flagged(self):
        class FakeWebSocketManager:
            def __init__(self):
                self.messages = []

            async def broadcast(self, message):
                self.messages.append(message)

        async def run_test():
            with tempfile.TemporaryDirectory() as tmp:
                config = Config()
                config.station.callsign = "K5YVY"
                config.station.ssid = 1
                db = Database(f"{tmp}/test.db")
                await db.initialize()
                try:
                    ws = FakeWebSocketManager()
                    tracker = StationTracker(db, config, ws)
                    packet = parse_packet(
                        "K1ABC>APRS,K5YVY-1*,WIDE1-1:!3600.00N/09800.00W-Test",
                        source="rf",
                    )

                    await tracker.track_packet(packet)
                    packets = await db.get_recent_packets(limit=1)
                finally:
                    await db.close()

            packet_messages = [msg["data"] for msg in ws.messages if msg.get("type") == "packet"]
            self.assertEqual(packets[0]["digipeated_by_me"], 1)
            self.assertTrue(packet_messages[-1]["digipeated_by_me"])

        asyncio.run(run_test())


class FirstHeardLogTests(unittest.TestCase):
    def test_first_heard_direct_only_filter(self):
        async def run_test():
            with tempfile.TemporaryDirectory() as tmp:
                db = Database(f"{tmp}/test.db")
                await db.initialize()
                try:
                    await db.log_first_heard(
                        "DIRECT",
                        "rf",
                        25.0,
                        90.0,
                        35.0,
                        -97.0,
                        path="WIDE1-1",
                        is_direct=True,
                    )
                    await db.log_first_heard(
                        "DIGI",
                        "rf",
                        125.0,
                        180.0,
                        36.0,
                        -98.0,
                        path="WIDE1-1,DIGI*",
                        hop_count=1,
                        is_direct=False,
                    )
                    direct = await db.get_first_heard_log(hours=1, direct_only=True)
                    all_rows = await db.get_first_heard_log(hours=1)
                finally:
                    await db.close()

            self.assertEqual([row["callsign"] for row in direct], ["DIRECT"])
            self.assertEqual(len(all_rows), 2)

        asyncio.run(run_test())

    def test_first_heard_log_is_unique_by_station_identity(self):
        async def run_test():
            with tempfile.TemporaryDirectory() as tmp:
                db = Database(f"{tmp}/test.db")
                await db.initialize()
                try:
                    first_inserted = await db.log_first_heard(
                        "W1ABC",
                        "rf",
                        75.0,
                        90.0,
                        35.0,
                        -97.0,
                        is_direct=True,
                    )
                    duplicate_inserted = await db.log_first_heard(
                        "w1abc",
                        "rf",
                        76.0,
                        91.0,
                        35.1,
                        -97.1,
                        is_direct=True,
                    )
                    rows = await db.get_first_heard_log(hours=1)
                finally:
                    await db.close()

            self.assertTrue(first_inserted)
            self.assertFalse(duplicate_inserted)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["callsign"], "W1ABC")

        asyncio.run(run_test())

    def test_first_heard_survives_station_cleanup(self):
        class FakeWebSocketManager:
            def __init__(self):
                self.messages = []

            async def broadcast(self, message):
                self.messages.append(message)

        async def run_test():
            with tempfile.TemporaryDirectory() as tmp:
                db = Database(f"{tmp}/test.db")
                await db.initialize()
                try:
                    config = Config()
                    config.station.callsign = "K5YVY"
                    ws = FakeWebSocketManager()
                    tracker = StationTracker(db, config, ws)
                    packet = parse_packet("W1ABC>APRS:!3600.00N/08100.00W-Test", source="rf")

                    await tracker.track_packet(packet)
                    await db.delete_old_stations(-1)
                    await tracker.track_packet(packet)

                    rows = await db.get_first_heard_log(hours=1)
                    first_heard_messages = [
                        msg for msg in ws.messages if msg.get("type") == "first_heard"
                    ]
                finally:
                    await db.close()

            self.assertEqual(len(rows), 1)
            self.assertEqual(len(first_heard_messages), 1)

        asyncio.run(run_test())


class StationCallsignValidationTests(unittest.TestCase):
    def test_accepts_country_neutral_station_identifiers(self):
        for callsign in ("KJ5GOV", "2E0ABC", "9A1A", "DL2026A", "R12345678"):
            self.assertTrue(_is_valid_station_callsign(callsign))
            self.assertIsNone(_validate_config({"station": {"callsign": callsign}}))

    def test_accepts_guam_station_callsigns(self):
        for callsign in ("KH2A", "KH2AB", "KH2ABC", "AH2A", "AH2AB", "AH2XYZ"):
            self.assertTrue(_is_valid_station_callsign(callsign))
            self.assertIsNone(_validate_config({"station": {"callsign": callsign}}))

    def test_rejects_only_packet_unsafe_station_identifiers(self):
        for callsign in ("", "TOO-LONG10", "BAD/CALL", "CALL-7", "CALL SIGN"):
            self.assertFalse(_is_valid_station_callsign(callsign))


class APRSISFilterValidationTests(unittest.TestCase):
    def test_accepts_whole_degree_and_decimal_range_filters(self):
        for filter_text in (
            "r/35/-79/80",
            "r/35.5322/-79.75/80",
            "r/33.7547/-111.7733/80 b/KK7PZE-13",
            "m/80 b/KK7PZE-13",
        ):
            with self.subTest(filter_text=filter_text):
                self.assertIsNone(_validate_config({"aprs_is": {"filter": filter_text}}))

    def test_rejects_leading_filter_command_word(self):
        self.assertEqual(
            _validate_config({"aprs_is": {"filter": "filter r/35/-79/80"}}),
            "Enter only the APRS-IS filter tokens, not the leading 'filter' command word.",
        )


class GPSIngestionTests(unittest.TestCase):
    def test_parses_rmc_nmea_position(self):
        pos = parse_nmea_position("$GPRMC,123519,A,4807.038,N,01131.000,E,022.4,084.4,230394,003.1,W*6A")

        self.assertIsNotNone(pos)
        self.assertAlmostEqual(pos["latitude"], 48.1173, places=4)
        self.assertAlmostEqual(pos["longitude"], 11.5167, places=4)

    def test_parses_gga_nmea_position(self):
        pos = parse_nmea_position("$GPGGA,123519,4807.038,N,01131.000,E,1,08,0.9,545.4,M,46.9,M,,*47")

        self.assertIsNotNone(pos)
        self.assertAlmostEqual(pos["latitude"], 48.1173, places=4)
        self.assertAlmostEqual(pos["longitude"], 11.5167, places=4)

    def test_ignores_invalid_nmea_fix(self):
        self.assertIsNone(parse_nmea_position("$GPRMC,123519,V,4807.038,N,01131.000,E,0,0,230394,,*00"))

    def test_splits_cr_only_nmea_stream(self):
        buffer = bytearray()
        lines = split_nmea_stream(
            buffer,
            b"$GPRMC,123519,A,4807.038,N,01131.000,E,022.4,084.4,230394,003.1,W*6A\r"
            b"$GPGGA,123520,4807.038,N,01131.000,E,1,08,0.9,545.4,M,46.9,M,,*47\r",
        )

        self.assertEqual(len(lines), 2)
        self.assertEqual(buffer, bytearray())
        self.assertIsNotNone(parse_nmea_position(lines[0]))
        self.assertIsNotNone(parse_nmea_position(lines[1]))

    def test_nmea_stream_recovers_after_oversized_noise(self):
        buffer = bytearray(b"x" * 32)
        lines = split_nmea_stream(
            buffer,
            b"$GPRMC,123519,A,4807.038,N,01131.000,E,0,0,230394,,*00",
            max_buffer=40,
        )

        self.assertEqual(lines, [])
        self.assertTrue(buffer.startswith(b"$GPRMC"))

    def test_parses_gpsd_tpv_position(self):
        pos = parse_gpsd_tpv('{"class":"TPV","mode":3,"lat":35.1234,"lon":-97.5678,"speed":12.0,"track":184.5,"epx":4.0,"epy":6.0}')

        self.assertIsNotNone(pos)
        self.assertAlmostEqual(pos["latitude"], 35.1234, places=4)
        self.assertAlmostEqual(pos["longitude"], -97.5678, places=4)
        self.assertAlmostEqual(pos["speed_mph"], 26.8432, places=3)
        self.assertAlmostEqual(pos["course_deg"], 184.5, places=1)
        self.assertAlmostEqual(pos["accuracy_m"], 6.0, places=1)

    def test_ignores_gpsd_without_2d_fix(self):
        self.assertIsNone(parse_gpsd_tpv('{"class":"TPV","mode":1,"lat":35.0,"lon":-97.0}'))

    def test_live_gps_can_update_station_position_when_unlocked(self):
        config = Config()
        config.gps.enabled = True
        gps = GPSManager(config)

        result = asyncio.run(gps.update_location(
            35.12345,
            -97.54321,
            source="browser",
            update_station_position=True,
            station_position_locked=False,
        ))

        self.assertTrue(result["current"]["applied_to_station"])
        self.assertAlmostEqual(config.station.latitude, 35.12345)
        self.assertAlmostEqual(config.station.longitude, -97.54321)

    def test_live_gps_respects_station_position_lock(self):
        config = Config()
        config.gps.enabled = True
        gps = GPSManager(config)

        result = asyncio.run(gps.update_location(
            35.12345,
            -97.54321,
            source="browser",
            update_station_position=True,
            station_position_locked=True,
        ))

        self.assertFalse(result["current"]["applied_to_station"])
        self.assertEqual(config.station.latitude, 0.0)
        self.assertEqual(config.station.longitude, 0.0)

    def test_status_hides_stale_fix_from_unselected_source(self):
        config = Config()
        config.gps.enabled = True
        config.gps.source = "browser"
        gps = GPSManager(config)

        asyncio.run(gps.update_location(35.0, -97.0, source="browser"))
        self.assertIsNotNone(gps.get_status()["current"])

        config.gps.source = "nmea_serial"
        status = gps.get_status()
        self.assertIsNone(status["current"])
        self.assertIn("source_status", status)

    def test_any_source_shows_latest_gpsd_fix(self):
        config = Config()
        config.gps.enabled = True
        config.gps.source = "any"
        gps = GPSManager(config)

        asyncio.run(gps.update_from_gpsd('{"class":"TPV","mode":2,"lat":35.0,"lon":-97.0}'))

        status = gps.get_status()
        self.assertIsNotNone(status["current"])
        self.assertEqual(status["current"]["source"], "gpsd")


class SporadicEDetectionTests(unittest.TestCase):
    def test_reports_diagnostics_when_no_es_candidates(self):
        async def run_test():
            with tempfile.TemporaryDirectory() as tmp:
                db = Database(f"{tmp}/test.db")
                await db.initialize()
                try:
                    await db.upsert_station(
                        callsign="LOCAL",
                        source="rf",
                        latitude=35.0,
                        longitude=-97.0,
                        distance_km=125,
                        heading=180,
                    )

                    result = await AnalyticsEngine(db).detect_sporadic_e(hours=24)
                finally:
                    await db.close()

            self.assertEqual(result["candidate_count"], 0)
            self.assertEqual(result["es_score"], 0)
            self.assertEqual(result["rf_station_count"], 1)
            self.assertEqual(result["qualifying_distance_count"], 0)
            self.assertEqual(result["max_observed_distance_km"], 125.0)
            self.assertEqual(result["strongest_stations"][0]["callsign"], "LOCAL")

        asyncio.run(run_test())

    def test_weights_direct_rf_above_digipeated_rf(self):
        async def run_test():
            with tempfile.TemporaryDirectory() as tmp:
                db = Database(f"{tmp}/test.db")
                await db.initialize()
                try:
                    await db.upsert_station(
                        callsign="DIRECT",
                        source="rf",
                        latitude=35.0,
                        longitude=-97.0,
                        distance_km=650,
                        heading=180,
                        commit=False,
                    )
                    await db.log_path_event(
                        callsign="DIRECT",
                        distance_km=650,
                        heading=180,
                        path="WIDE1-1",
                        is_direct=True,
                        commit=False,
                    )
                    await db.upsert_station(
                        callsign="DIGI",
                        source="rf",
                        latitude=36.0,
                        longitude=-98.0,
                        distance_km=900,
                        heading=90,
                        path="WIDE1-1,DIGI1*",
                        commit=False,
                    )
                    await db.log_path_event(
                        callsign="DIGI",
                        distance_km=900,
                        heading=90,
                        path="WIDE1-1,DIGI1*",
                        is_direct=False,
                        commit=False,
                    )
                    await db.upsert_station(
                        callsign="ISONLY",
                        source="aprs_is",
                        latitude=37.0,
                        longitude=-99.0,
                        distance_km=1200,
                        heading=45,
                        commit=False,
                    )
                    await db.commit()

                    result = await AnalyticsEngine(db).detect_sporadic_e()
                finally:
                    await db.close()

            self.assertEqual(result["candidate_count"], 2)
            self.assertEqual(result["candidates"][0]["callsign"], "DIRECT")
            self.assertEqual(result["candidates"][0]["path_tier"], "direct_rf")
            self.assertEqual(result["candidates"][0]["path_confidence"], 1.0)
            self.assertEqual(result["candidates"][1]["callsign"], "DIGI")
            self.assertEqual(result["candidates"][1]["path_tier"], "single_hop_rf")
            self.assertEqual(result["candidates"][1]["path_confidence"], 0.6)
            self.assertGreater(
                result["candidates"][0]["es_score"],
                result["candidates"][1]["es_score"],
            )

        asyncio.run(run_test())


class AlertRecommendationTests(unittest.TestCase):
    def test_recommends_count_above_constant_direct_baseline(self):
        async def run_test():
            with tempfile.TemporaryDirectory() as tmp:
                db = Database(f"{tmp}/test.db")
                await db.initialize()
                try:
                    now = 1_700_000_000.0
                    start = now - 24 * 3600
                    for i in range(96):
                        ts = start + i * 900
                        for idx, dist in enumerate((40.0, 55.0, 70.0), start=1):
                            await db.db.execute(
                                """INSERT INTO path_history
                                   (timestamp, callsign, distance_km, heading, path, hop_count, is_direct)
                                   VALUES (?, ?, ?, 0, '', 0, 1)""",
                                (ts, f"DIRECT{idx}", dist),
                            )
                        if i >= 88:
                            for idx, dist in enumerate((135.0, 150.0), start=4):
                                await db.db.execute(
                                    """INSERT INTO path_history
                                       (timestamp, callsign, distance_km, heading, path, hop_count, is_direct)
                                       VALUES (?, ?, ?, 0, '', 0, 1)""",
                                    (ts, f"DIRECT{idx}", dist),
                                )
                        if i % 4 == 0:
                            await db.db.execute(
                                """INSERT INTO path_history
                                   (timestamp, callsign, distance_km, heading, path, hop_count, is_direct)
                                   VALUES (?, 'DIGI1', 110.0, 0, 'WIDE1-1*', 1, 0)""",
                                (ts,),
                            )
                    await db.commit()
                    engine = AnalyticsEngine(db)
                    original_time = analytics_module.time.time
                    try:
                        analytics_module.time.time = lambda: now
                        result = await engine.get_alert_threshold_recommendations(
                            AlertConfig(
                                my_min_stations=3,
                                my_min_distance_km=50,
                                regional_min_stations=1,
                                regional_min_distance_km=100,
                                cooldown_seconds=1800,
                            ),
                            hours=24,
                            sample_minutes=15,
                        )
                    finally:
                        analytics_module.time.time = original_time
                finally:
                    await db.close()

            self.assertTrue(result["enough_data"])
            self.assertGreater(result["recommendations"]["my_min_stations"]["suggested"], 3)
            self.assertGreater(result["recommendations"]["my_min_distance_km"]["suggested"], 70)
            self.assertIn("baseline", result["recommendations"]["my_min_stations"]["reason"])

        asyncio.run(run_test())


class BandOpeningAlertTests(unittest.TestCase):
    def test_my_station_alert_includes_top_station_bearing_label(self):
        alerts = AlertManager(
            AlertConfig(
                enabled=True,
                my_min_stations=1,
                my_min_distance_km=10,
                cooldown_seconds=0,
            ),
            station_callsign="N0CALL",
        ).check_and_alert({
            "my_stations_1h": 1,
            "my_max_distance_km": 120.0,
            "my_score": 55,
            "my_level": "good",
            "my_top_station": {
                "callsign": "K1ABC",
                "distance_km": 120.0,
                "heading": 315.0,
            },
            "my_near_hop_stations": [
                {
                    "callsign": "K1ABC",
                    "distance_km": 120.0,
                    "heading": 315.0,
                    "hop_count": 0,
                },
                {
                    "callsign": "N5ONE",
                    "distance_km": 80.0,
                    "heading": 90.0,
                    "hop_count": 1,
                    "via_digipeater": "W9EN-10",
                },
            ],
        })

        self.assertEqual(len(alerts), 1)
        alert = alerts[0]
        self.assertIn("Top Direct Station: K1ABC bearing NW", alert["message"])
        self.assertIn("Direct/1-Hop RF Stations:\n- K1ABC 120.0 km", alert["message"])
        self.assertIn("- N5ONE 80.0 km (49.7 mi) E 1 hop via W9EN-10", alert["message"])
        self.assertEqual(alert["top_station"], "K1ABC")
        self.assertEqual(alert["top_station_bearing"], "NW")

    def test_bearing_label_handles_zero_degrees_as_north(self):
        self.assertEqual(AlertManager._bearing_label(0), "N")

    def test_anomaly_alert_can_be_disabled_independently(self):
        async def run_test():
            manager = AlertManager(
                AlertConfig(enabled=True, anomaly_alert_enabled=False, cooldown_seconds=0),
                station_callsign="N0CALL",
            )
            await manager.check_anomaly({
                "anomaly_score": 3.0,
                "anomaly_level": "extreme",
                "count_pct_above_avg": 200,
                "dist_pct_above_avg": 150,
            })
            self.assertEqual(manager.get_alert_history(), [])

        asyncio.run(run_test())

    def test_sporadic_e_alert_can_be_disabled_independently(self):
        async def run_test():
            manager = AlertManager(
                AlertConfig(enabled=True, sporadic_e_alert_enabled=False, cooldown_seconds=0),
                station_callsign="N0CALL",
            )
            await manager.check_sporadic_e({
                "es_level": "likely",
                "candidates": [{"callsign": "K1ABC", "distance_km": 900}],
            })
            self.assertEqual(manager.get_alert_history(), [])

        asyncio.run(run_test())

    def test_test_alert_reports_selected_channel_results(self):
        async def run_test():
            manager = AlertManager(
                AlertConfig(
                    discord_enabled=True,
                    discord_webhook_url="https://example.com/webhook",
                    email_enabled=True,
                    email_smtp_server="smtp.example.com",
                    email_from="from@example.com",
                    email_to="to@example.com",
                ),
                station_callsign="N0CALL",
            )
            sent = []

            async def fake_discord(alert):
                sent.append(("discord", alert["type"], alert["message"]))

            async def fake_email(alert):
                sent.append(("email", alert["type"], alert["message"]))

            manager._send_discord = fake_discord
            manager._send_email = fake_email

            result = await manager.send_test_alert()

            self.assertTrue(result["success"])
            self.assertEqual([item["channel"] for item in result["results"]], ["discord", "email"])
            self.assertEqual([item["ok"] for item in result["results"]], [True, True])
            self.assertEqual([item[0] for item in sent], ["discord", "email"])
            self.assertTrue(all(item[1] == "test" for item in sent))

        asyncio.run(run_test())

    def test_test_alert_reports_missing_selected_channel_config(self):
        async def run_test():
            manager = AlertManager(AlertConfig(discord_enabled=True), station_callsign="N0CALL")

            result = await manager.send_test_alert()

            self.assertFalse(result["success"])
            self.assertEqual(result["results"][0]["channel"], "discord")
            self.assertIn("webhook", result["results"][0]["message"].lower())

        asyncio.run(run_test())


class MQTTIntegrationTests(unittest.TestCase):
    def test_publisher_builds_home_assistant_discovery_payloads(self):
        publisher = MQTTPublisher(
            "localhost",
            topic_prefix="aprs/propview",
            discovery_enabled=True,
            discovery_prefix="homeassistant",
            device_name="APRS PropView K5ABC",
            device_id="K5ABC-1 PropView",
            station_callsign="K5ABC-1",
            app_version="1.5.6.0",
            watched_callsigns=["WB5TZN-1"],
        )

        payloads = publisher._discovery_payloads()

        self.assertEqual(publisher.device_id, "k5abc_1_propview")
        self.assertIn("regional_score", payloads)
        self.assertIn("band_opening_active", payloads)
        self.assertIn("watched_wb5tzn_1", payloads)
        self.assertEqual(payloads["regional_score"]["state_topic"], "aprs/propview/propagation")
        self.assertEqual(payloads["regional_score"]["value_template"], "{{ value_json.regional_score }}")
        self.assertEqual(payloads["regional_score"]["unique_id"], "k5abc_1_propview_regional_score")
        self.assertEqual(payloads["regional_score"]["availability_topic"], "aprs/propview/status")
        self.assertEqual(payloads["max_distance_km"]["unit_of_measurement"], "km")
        self.assertEqual(payloads["band_opening_active"]["_component"], "binary_sensor")
        self.assertEqual(payloads["watched_wb5tzn_1"]["_component"], "binary_sensor")
        self.assertEqual(payloads["regional_score"]["device"]["sw_version"], "1.5.6.0")

    def test_publisher_publishes_retained_home_assistant_discovery_configs(self):
        class FakeClient:
            def __init__(self):
                self.published = []

            def publish(self, topic, payload, qos=0, retain=False):
                self.published.append((topic, payload, qos, retain))

        async def run_test():
            publisher = MQTTPublisher(
                "localhost",
                topic_prefix="aprs/propview",
                discovery_enabled=True,
                discovery_prefix="homeassistant",
                device_id="aprs_propview",
                watched_callsigns=["WB5TZN-1"],
            )
            publisher._client = FakeClient()
            publisher._connected = True

            await publisher.publish_home_assistant_discovery()

            topics = [item[0] for item in publisher._client.published]
            self.assertIn("homeassistant/sensor/aprs_propview/regional_score/config", topics)
            self.assertIn("homeassistant/binary_sensor/aprs_propview/band_opening_active/config", topics)
            self.assertIn("homeassistant/binary_sensor/aprs_propview/watched_wb5tzn_1/config", topics)
            self.assertTrue(all(item[3] for item in publisher._client.published))
            regional_payload = next(
                item[1]
                for item in publisher._client.published
                if item[0] == "homeassistant/sensor/aprs_propview/regional_score/config"
            )
            self.assertEqual(json.loads(regional_payload)["unique_id"], "aprs_propview_regional_score")

        asyncio.run(run_test())

    def test_publisher_merges_home_assistant_status_snapshots(self):
        class FakeClient:
            def __init__(self):
                self.published = []

            def publish(self, topic, payload, qos=0, retain=False):
                self.published.append((topic, payload, qos, retain))

        async def run_test():
            publisher = MQTTPublisher("localhost", topic_prefix="aprs/propview")
            publisher._client = FakeClient()
            publisher._connected = True

            await publisher.publish_status_snapshot({"aprs_is_connected": "ON"})
            await publisher.publish_status_snapshot({"band_opening_active": "ON"})

            topic, payload, qos, retain = publisher._client.published[-1]
            self.assertEqual(topic, "aprs/propview/ha/status")
            self.assertTrue(retain)
            merged = json.loads(payload)
            self.assertEqual(merged["aprs_is_connected"], "ON")
            self.assertEqual(merged["band_opening_active"], "ON")

        asyncio.run(run_test())

    def test_tracker_publishes_propagation_payload_and_score_topics(self):
        class FakeMQTTPublisher:
            def __init__(self):
                self.propagation = []
                self.scores = []

            async def publish_propagation(self, prop_data):
                self.propagation.append(prop_data)

            async def publish_prop_score(self, score, level):
                self.scores.append((score, level))

            async def publish_status_snapshot(self, status):
                self.status = status

        async def run_test():
            tracker = StationTracker(None, Config(), WebSocketManager())
            publisher = FakeMQTTPublisher()
            tracker.set_mqtt_publisher(publisher)

            await tracker._publish_mqtt_propagation({"score": 42.5, "level": "fair"})

            self.assertEqual(publisher.propagation, [{"score": 42.5, "level": "fair"}])
            self.assertEqual(publisher.scores, [(42.5, "fair")])

        asyncio.run(run_test())

    def test_tracker_publishes_alert_payload(self):
        class FakeMQTTPublisher:
            def __init__(self):
                self.alerts = []

            async def publish_alert(self, alert):
                self.alerts.append(alert)

            async def publish_status_snapshot(self, status):
                self.status = status

        async def run_test():
            tracker = StationTracker(None, Config(), WebSocketManager())
            publisher = FakeMQTTPublisher()
            tracker.set_mqtt_publisher(publisher)
            alert = {"type": "regional_watch", "score": 50}

            await tracker._publish_mqtt_alert(alert)

            self.assertEqual(publisher.alerts, [alert])

        asyncio.run(run_test())

    def test_tracker_publishes_station_automation_events(self):
        class FakeMQTTPublisher:
            def __init__(self):
                self.events = []

            async def publish_event(self, event):
                self.events.append(event)

        async def run_test():
            db = Database(":memory:")
            await db.initialize()
            try:
                config = Config()
                config.station.callsign = "K5ABC"
                config.station.latitude = 35.0
                config.station.longitude = -80.0
                tracker = StationTracker(db, config, WebSocketManager())
                publisher = FakeMQTTPublisher()
                tracker.set_mqtt_publisher(publisher)

                first = parse_packet("W1ABC>APRS:!3600.00N/08100.00W-Test", source="rf")
                await tracker.track_packet(first)

                event_names = [event["event"] for event in publisher.events]
                self.assertEqual(event_names, ["first_heard", "new_max_distance"])
                self.assertEqual(publisher.events[0]["callsign"], "W1ABC")
                self.assertEqual(publisher.events[0]["source"], "rf")
                self.assertTrue(publisher.events[0]["is_direct"])
                self.assertGreater(publisher.events[1]["distance_km"], 0)
                self.assertEqual(publisher.events[1]["previous_distance_km"], 0.0)

                closer = parse_packet("W2ABC>APRS:!3505.00N/08005.00W-Test", source="rf")
                await tracker.track_packet(closer)

                event_names = [event["event"] for event in publisher.events]
                self.assertEqual(event_names, ["first_heard", "new_max_distance", "first_heard"])

                farther = parse_packet("W3ABC>APRS:!3800.00N/08400.00W-Test", source="rf")
                await tracker.track_packet(farther)

                event_names = [event["event"] for event in publisher.events]
                self.assertEqual(event_names[-2:], ["first_heard", "new_max_distance"])
                self.assertEqual(publisher.events[-1]["callsign"], "W3ABC")
                self.assertGreater(
                    publisher.events[-1]["distance_km"],
                    publisher.events[1]["distance_km"],
                )
            finally:
                await db.close()

        asyncio.run(run_test())


if __name__ == "__main__":
    unittest.main()
