import tempfile
import unittest
from pathlib import Path

from server.config import Config


def _load(text):
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "config.toml"
        path.write_text(text, encoding="utf-8")
        return Config.load(path)


class UnknownConfigKeysTests(unittest.TestCase):
    def test_unknown_key_in_section_is_ignored(self):
        with self.assertLogs("propview.config", level="WARNING") as logs:
            config = _load('[station]\ncallsign = "W1AW"\nfuture_option = 5\n')
        self.assertEqual(config.station.callsign, "W1AW")
        self.assertTrue(any("station.future_option" in line for line in logs.output))

    def test_typo_keeps_the_rest_of_the_section(self):
        with self.assertLogs("propview.config", level="WARNING"):
            config = _load("[digipeater]\nenabled = true\ndedupe_intervall = 45\n")
        self.assertTrue(config.digipeater.enabled)
        self.assertEqual(config.digipeater.dedupe_interval, Config().digipeater.dedupe_interval)

    def test_every_section_tolerates_unknown_keys(self):
        names = [
            "station", "digipeater", "igate", "aprs_is", "kiss_serial", "kiss_tcp",
            "web", "database", "tracking", "callbook", "messaging", "alerts",
            "propagation", "status", "smart_beaconing", "bulletins", "aprs_objects",
            "weather", "wxnow", "gps", "mqtt",
        ]
        text = "".join(f"[{name}]\nnot_a_real_setting = 1\n\n" for name in names)
        with self.assertLogs("propview.config", level="WARNING") as logs:
            _load(text)
        self.assertEqual(len(logs.output), len(names))

    def test_section_that_is_not_a_table_keeps_defaults(self):
        with self.assertLogs("propview.config", level="WARNING"):
            config = _load('station = "W1AW"\n')
        self.assertEqual(config.station.callsign, Config().station.callsign)

    def test_known_keys_load_without_warnings(self):
        with self.assertNoLogs("propview.config", level="WARNING"):
            config = _load('[station]\ncallsign = "W1AW"\nssid = 10\n')
        self.assertEqual(config.station.ssid, 10)

    def test_saved_config_round_trips_without_warnings(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.toml"
            Config().save(path)
            with self.assertNoLogs("propview.config", level="WARNING"):
                Config.load(path)


if __name__ == "__main__":
    unittest.main()
