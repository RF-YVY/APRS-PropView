"""Regression tests for untrusted radio data and public display boundaries."""
import csv
import io
import unittest

from server.export import stations_to_csv, packets_to_csv, propagation_to_csv
from server.kiss import KISSFrameParser, make_kiss_frame
from server.operator_auth import public_socket_message


class ExportSecurityTests(unittest.TestCase):
    def test_csv_text_cannot_start_formulas(self):
        for value in ('=1+1', '+SUM(1,2)', '-1+2', '@SUM(1,2)', ' \t=1+1', '\r\n=1+1'):
            for exporter, key in ((stations_to_csv, 'last_comment'),
                                  (packets_to_csv, 'from_call'),
                                  (propagation_to_csv, 'rf_station_count')):
                with self.subTest(value=value, exporter=exporter.__name__):
                    row = next(csv.DictReader(io.StringIO(exporter([{key: value}]))))
                    self.assertEqual(row[key], "'" + value)

    def test_csv_preserves_numeric_values_and_normal_text(self):
        row = next(csv.DictReader(io.StringIO(stations_to_csv([
            {'callsign': 'W1AW', 'longitude': -72.7, 'last_comment': 'normal, "text" & more'}
        ]))))
        self.assertEqual(row['longitude'], '-72.7')
        self.assertEqual(row['last_comment'], 'normal, "text" & more')


class KISSBoundsTests(unittest.TestCase):
    def test_unterminated_frame_is_bounded_and_parser_recovers(self):
        parser = KISSFrameParser()
        parser.feed(b'\xc0\x00')
        for _ in range(20):
            self.assertEqual(parser.feed(b'A' * 4096), [])
            self.assertLessEqual(len(parser.buffer), parser.MAX_FRAME_BYTES)
        frame = b'normal\xc0\xdbframe'
        frames, text = parser.feed_with_text(b'ATTACK>APRS:>tail\r\n' + make_kiss_frame(frame))
        self.assertEqual(frames, [frame])
        self.assertEqual(text, [])


class PublicPropagationTests(unittest.TestCase):
    def test_socket_does_not_publish_watched_target_details(self):
        message = {'type': 'propagation', 'data': {'score': 10, 'watched_paths': {
            'opportunities': [{'callsign': 'PRIVATE', 'target_latitude': 34, 'port_name': 'secret-port'}]}}}
        filtered = public_socket_message(message)
        self.assertEqual(filtered['data']['score'], 10)
        self.assertEqual(filtered['data']['watched_paths']['opportunities'], [])
        self.assertEqual(message['data']['watched_paths']['opportunities'][0]['callsign'], 'PRIVATE')
