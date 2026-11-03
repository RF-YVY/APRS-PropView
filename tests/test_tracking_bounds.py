import tempfile
import unittest
from pathlib import Path

from server.app import _validate_config
from server.config import Config


def _load(text):
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "config.toml"
        path.write_text(text, encoding="utf-8")
        return Config.load(path)


class TrackingSaveBoundsTests(unittest.TestCase):
    def test_zero_and_negative_values_are_rejected(self):
        for key in ("cleanup_interval", "max_station_age"):
            for value in (0, -60, "", None, "abc"):
                with self.subTest(key=key, value=value):
                    self.assertIsNotNone(_validate_config({"tracking": {key: value}}))

    def test_values_below_the_minimum_are_rejected(self):
        self.assertIsNotNone(_validate_config({"tracking": {"cleanup_interval": 59}}))
        self.assertIsNotNone(_validate_config({"tracking": {"max_station_age": 599}}))

    def test_values_above_the_maximum_are_rejected(self):
        self.assertIsNotNone(_validate_config({"tracking": {"cleanup_interval": 86401}}))
        self.assertIsNotNone(_validate_config({"tracking": {"max_station_age": 365 * 86400 + 1}}))

    def test_defaults_and_bounds_are_accepted(self):
        for body in (
            {"cleanup_interval": 3600, "max_station_age": 86400},
            {"cleanup_interval": 60, "max_station_age": 600},
            {"cleanup_interval": 86400, "max_station_age": 365 * 86400},
        ):
            with self.subTest(body=body):
                self.assertIsNone(_validate_config({"tracking": body}))

    def test_blocked_callsigns_alone_still_save(self):
        self.assertIsNone(_validate_config({"tracking": {"blocked_callsigns": ["N0CALL"]}}))


class TrackingLoadBoundsTests(unittest.TestCase):
    def test_hand_edited_zero_is_raised_to_the_minimum(self):
        config = _load("[tracking]\ncleanup_interval = 0\nmax_station_age = -5\n")
        self.assertEqual(config.tracking.cleanup_interval, 60)
        self.assertEqual(config.tracking.max_station_age, 600)

    def test_in_range_values_load_unchanged(self):
        config = _load("[tracking]\ncleanup_interval = 900\nmax_station_age = 7200\n")
        self.assertEqual(config.tracking.cleanup_interval, 900)
        self.assertEqual(config.tracking.max_station_age, 7200)


if __name__ == "__main__":
    unittest.main()
