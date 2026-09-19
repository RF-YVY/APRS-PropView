import time
import unittest
from types import SimpleNamespace

from server.config import Config
from server.source_health import build_source_health
from server.station_tracker import StationTracker


class SourceHealthTests(unittest.TestCase):
    def setUp(self):
        self.config = Config()
        self.config.aprs_is.enabled = True
        self.config.weather.enabled = True
        self.config.weather.location_code = "KAVL"
        self.now = 2_000_000.0

    def test_reports_connected_sources_and_stale_rf_evidence_separately(self):
        self.config.rf_ports = [SimpleNamespace(enabled=True)]
        tracker = SimpleNamespace(_last_rf_packet_time=self.now - 1800)
        aprs_is = SimpleNamespace(_last_rx=self.now - 10)
        weather = SimpleNamespace(
            is_configured=True,
            _last_fetch=self.now - 30,
            _last_alert_fetch=self.now - 60,
            _alerts=[],
            _get_alert_poll_interval_seconds=lambda: 300,
        )
        payload = build_source_health(
            self.config,
            {
                "rf_connected": True,
                "rf_interfaces": [{"connected": True, "last_error": ""}],
                "aprs_is_connected": True,
                "aprs_is_verified": True,
            },
            tracker,
            weather_manager=weather,
            aprs_is=aprs_is,
            now=self.now,
        )
        states = {item["id"]: item["state"] for item in payload["sources"]}
        self.assertEqual(states["rf"], "stale")
        self.assertEqual(states["aprs_is"], "live")
        self.assertEqual(states["weather"], "live")
        self.assertEqual(payload["summary"], "attention")

    def test_disabled_sources_do_not_raise_attention(self):
        self.config.rf_ports = []
        self.config.aprs_is.enabled = False
        self.config.weather.enabled = False
        payload = build_source_health(
            self.config,
            {"rf_connected": False, "rf_interfaces": [], "aprs_is_connected": False},
            SimpleNamespace(_last_rf_packet_time=0),
            now=self.now,
        )
        self.assertEqual(payload["attention_count"], 0)

    def test_confidence_is_explicitly_evidence_quality(self):
        none = StationTracker._evidence_confidence(5, None, 60)
        fresh = StationTracker._evidence_confidence(5, 30, 60)
        stale = StationTracker._evidence_confidence(5, 1800, 60)
        self.assertEqual(none["level"], "none")
        self.assertEqual(fresh["level"], "high")
        self.assertLess(stale["score"], fresh["score"])
        self.assertIn("stale", stale["reason"].lower())

    def test_propagation_event_requires_sustained_evidence_and_then_fades(self):
        tracker = object.__new__(StationTracker)
        tracker._propagation_event = {
            "state": "normal", "active": False, "started_at": None, "updated_at": 0,
            "peak_score": 0.0, "current_score": 0.0, "sample_count": 0,
            "above_count": 0, "below_count": 0, "strongest_scope": "regional",
            "strongest_bearing": None, "transitions": [],
        }
        strong = {
            "my_score": 60, "score": 70, "my_top_station": {"heading": 90},
            "evidence": {"confidence": {"direct": {"score": 70}, "regional": {"score": 70}}},
        }
        for second in range(3):
            tracker._update_propagation_event(strong, self.now + second * 60)
        self.assertEqual(tracker._propagation_event["state"], "confirmed")
        self.assertTrue(tracker._propagation_event["active"])

        quiet = {
            "my_score": 10, "score": 20, "my_top_station": None,
            "evidence": {"confidence": {"direct": {"score": 20}, "regional": {"score": 20}}},
        }
        tracker._update_propagation_event(quiet, self.now + 180)
        self.assertEqual(tracker._propagation_event["state"], "fading")
        tracker._update_propagation_event(quiet, self.now + 240)
        tracker._update_propagation_event(quiet, self.now + 300)
        self.assertEqual(tracker._propagation_event["state"], "normal")
        self.assertFalse(tracker._propagation_event["active"])


if __name__ == "__main__":
    unittest.main()
