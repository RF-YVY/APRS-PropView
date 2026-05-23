import unittest
import asyncio
import tempfile

from server.aprs_is import APRSISClient
from server.aprs_parser import make_message_packet, parse_packet
from server.app import _is_valid_message_addressee, _is_valid_station_callsign, _validate_config
from server.analytics import AnalyticsEngine
from server.alerts import AlertConfig, AlertManager
from server.config import Config
from server.database import Database
from server.gps import GPSManager, parse_nmea_position


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
        client = APRSISClient(config, lambda packet: None, app_version="1.4.4")

        self.assertIn("vers APRSPropView 1.4.4", client._build_login())


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
        self.assertIn("Top Direct Station: K1ABC bearing NW (315°)", alert["message"])
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


if __name__ == "__main__":
    unittest.main()
