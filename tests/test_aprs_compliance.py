import unittest
import asyncio

from server.aprs_is import APRSISClient
from server.aprs_parser import parse_packet
from server.app import _is_valid_message_addressee, _is_valid_station_callsign, _validate_config
from server.config import Config
from server.gps import GPSManager, parse_nmea_position


class APRSParserComplianceTests(unittest.TestCase):
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
        client = APRSISClient(config, lambda packet: None, app_version="1.4.0")

        self.assertIn("vers APRSPropView 1.4.0", client._build_login())


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


if __name__ == "__main__":
    unittest.main()
