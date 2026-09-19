import unittest

from server.config import Config
from server.space_weather import KP_URL, SCALES_URL, SpaceWeatherManager


class _AlertStub:
    def __init__(self):
        self.recorded = []
        self.sent = []

    def _is_quiet_time(self):
        return False

    def record_alert(self, alert):
        self.recorded.append(alert)

    async def send_alert(self, alert, channels=None):
        self.sent.append((alert, channels))


class SpaceWeatherTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.config = Config()
        self.config.weather.space_weather_enabled = True

    @staticmethod
    def _fetch(url):
        if url == KP_URL:
            return [
                {"time_tag": "2026-09-17 12:00:00", "Kp": "4.00", "a_running": "12", "station_count": "8"},
                {"time_tag": "2026-09-17 15:00:00", "Kp": "5.67", "a_running": "22", "station_count": "8"},
            ]
        if url == SCALES_URL:
            return {
                "0": {"G": {"Scale": "1"}, "R": {"Scale": "2"}, "S": {"Scale": "0"}},
                "1": {"G": {"Scale": "2"}},
            }
        raise AssertionError(f"Unexpected URL: {url}")

    async def test_poll_parses_latest_noaa_context(self):
        manager = SpaceWeatherManager(self.config, fetch_json=self._fetch)
        await manager.poll_once()
        snapshot = manager.snapshot()
        self.assertEqual(snapshot["kp"], 5.67)
        self.assertEqual(snapshot["g_scale"], 1)
        self.assertEqual(snapshot["r_scale"], 2)
        self.assertEqual(snapshot["forecast_g_scale"], 2)
        self.assertEqual(snapshot["context"]["level"], "elevated")
        self.assertFalse(snapshot["stale"])
        self.assertIsNotNone(snapshot["observed_at"])

    async def test_threshold_alert_uses_selected_channels_and_cooldown(self):
        alerts = _AlertStub()
        self.config.weather.space_weather_alert_enabled = True
        self.config.weather.space_weather_alert_min_kp = 5
        self.config.weather.space_weather_alert_discord_enabled = True
        self.config.weather.space_weather_alert_email_enabled = True
        manager = SpaceWeatherManager(self.config, alert_manager=alerts, fetch_json=self._fetch)
        await manager.poll_once()
        await manager.poll_once()
        self.assertEqual(len(alerts.sent), 1)
        self.assertEqual(alerts.sent[0][0]["type"], "space_weather")
        self.assertEqual(alerts.sent[0][1], ["discord", "email"])


if __name__ == "__main__":
    unittest.main()
