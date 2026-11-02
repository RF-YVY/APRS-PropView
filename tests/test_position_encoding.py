"""Encoded positions never carry a 60.00 minutes field."""
import unittest

from server.aprs_parser import make_position_packet, parse_packet
from server.scheduled_packets import _coord_to_aprs
from server.wxnow import format_aprs_lat_lon as wxnow_lat_lon


def encoded(lat, lon):
    info = make_position_packet("N0CALL", lat, lon)
    return info[1:9], info[10:19]


class PositionEncodingTests(unittest.TestCase):
    def test_latitude_carries_into_degrees(self):
        self.assertEqual(encoded(38.99999, -97.5)[0], "3900.00N")

    def test_longitude_carries_into_degrees(self):
        self.assertEqual(encoded(38.5, -97.99999)[1], "09800.00W")

    def test_scheduled_packets_carry_into_degrees(self):
        self.assertEqual(_coord_to_aprs(38.99999, -97.99999), ("3900.00N", "09800.00W"))

    def test_wxnow_packets_carry_into_degrees(self):
        self.assertEqual(wxnow_lat_lon(38.99999, -97.99999), ("3900.00N", "09800.00W"))

    def test_limits_of_the_globe(self):
        self.assertEqual(encoded(89.99999, 179.99999), ("9000.00N", "18000.00E"))
        self.assertEqual(encoded(-89.99999, -179.99999), ("9000.00S", "18000.00W"))

    def test_sweep_parses_back_near_the_input(self):
        for lat_deg in range(-89, 90, 7):
            for lon_deg in range(-179, 180, 11):
                for fraction in (0.0, 0.49999, 0.99984, 0.99999, 0.999999):
                    sign_lat = -1 if lat_deg < 0 else 1
                    sign_lon = -1 if lon_deg < 0 else 1
                    lat = lat_deg + sign_lat * fraction
                    lon = lon_deg + sign_lon * fraction
                    info = make_position_packet("N0CALL", lat, lon)
                    packet = parse_packet(f"N0CALL>APRS:{info}", source="rf")
                    self.assertIsNotNone(packet.latitude, info)
                    self.assertAlmostEqual(packet.latitude, lat, delta=0.01, msg=info)
                    self.assertAlmostEqual(packet.longitude, lon, delta=0.01, msg=info)
                    tx_lat, tx_lon = _coord_to_aprs(lat, lon)
                    self.assertLess(float(tx_lat[2:7]), 60, tx_lat)
                    self.assertLess(float(tx_lon[3:8]), 60, tx_lon)


if __name__ == "__main__":
    unittest.main()
