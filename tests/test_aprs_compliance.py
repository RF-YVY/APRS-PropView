import unittest
import asyncio
import tempfile
from pathlib import Path

from server.aprs_is import APRSISClient
from server.aprs_parser import make_message_packet, parse_packet
from server.app import _is_valid_message_addressee, _is_valid_station_callsign, _validate_config
from server.analytics import AnalyticsEngine
from server.alerts import AlertConfig, AlertManager
from server.ax25 import AX25Address, AX25Frame
from server.config import Config, RFPortConfig
from server.database import Database
from server.digipeater import Digipeater
from server.packet_handler import PacketHandler
from server.station_tracker import StationTracker
from server.websocket_manager import WebSocketManager
from server.gps import GPSManager, parse_nmea_position
from server.status_report import build_dx_status_text, trim_status_text
from server.wxnow import build_wxnow_info, build_wxnow_position_info, parse_weather_body_values, parse_wxnow_text


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
        client = APRSISClient(config, lambda packet: None, app_version="1.5.2.2")

        self.assertIn("vers APRSPropView 1.5.2.2", client._build_login())


class ConfigTests(unittest.TestCase):
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
            "@071400z3530.00N/09745.00W_292/004g011t098h36b10139jDvs9",
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

        self.assertEqual(reading.weather_body, "180/000t074P9616h99b09976")
        self.assertEqual(
            build_wxnow_info(config, reading),
            "@250935z3531.93N/07945.00W_180/000t074P9616h99b09976",
        )

    def test_build_positionless_wx_packet_inserts_missing_temperature_tag(self):
        config = Config()
        config.wxnow.include_position = False
        reading = parse_wxnow_text("May 25 2026 09:42\n067/000074P9616h99b09977\n")

        self.assertEqual(
            build_wxnow_info(config, reading),
            "_05250942c067s000g...t074P9616h99b09977",
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
                self.assertEqual(handler.sent[1]["info"], "_05250942c067s000g...t074P9616h99b09977")

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


class StationCallsignValidationTests(unittest.TestCase):
    def test_accepts_country_neutral_station_identifiers(self):
        for callsign in ("KJ5GOV", "2E0ABC", "9A1A", "DL2026A", "R12345678"):
            self.assertTrue(_is_valid_station_callsign(callsign))
            self.assertIsNone(_validate_config({"station": {"callsign": callsign}}))

    def test_rejects_only_packet_unsafe_station_identifiers(self):
        for callsign in ("", "TOO-LONG10", "BAD/CALL", "CALL-7", "CALL SIGN"):
            self.assertFalse(_is_valid_station_callsign(callsign))


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


class SporadicEDetectionTests(unittest.TestCase):
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
    def test_tracker_publishes_propagation_payload_and_score_topics(self):
        class FakeMQTTPublisher:
            def __init__(self):
                self.propagation = []
                self.scores = []

            async def publish_propagation(self, prop_data):
                self.propagation.append(prop_data)

            async def publish_prop_score(self, score, level):
                self.scores.append((score, level))

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

        async def run_test():
            tracker = StationTracker(None, Config(), WebSocketManager())
            publisher = FakeMQTTPublisher()
            tracker.set_mqtt_publisher(publisher)
            alert = {"type": "regional_watch", "score": 50}

            await tracker._publish_mqtt_alert(alert)

            self.assertEqual(publisher.alerts, [alert])

        asyncio.run(run_test())


if __name__ == "__main__":
    unittest.main()
