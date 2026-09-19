import time
import unittest
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from server.config import Config, WatchedPathConfig
from server.lightning import LightningManager, select_satellite


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


class LightningTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.config = Config()
        self.config.station.callsign = "N0CALL"
        self.config.station.latitude = 35.0
        self.config.station.longitude = -80.0
        self.config.weather.lightning_enabled = True

    def test_auto_satellite_uses_station_longitude(self):
        self.assertEqual(select_satellite("auto", 35, -80), "goes19")
        self.assertEqual(select_satellite("auto", 45, -125), "goes18")
        self.assertEqual(select_satellite("goes18", 35, -80), "goes18")

    def test_stale_flashes_and_seen_keys_are_pruned(self):
        manager = LightningManager(self.config)
        now = time.time()
        manager._flashes = deque([
            {"timestamp": now - 700},
            {"timestamp": now - 30},
        ])
        manager._seen = {"old": now - 8000, "current": now}
        manager.prune(now)
        self.assertEqual(len(manager._flashes), 1)
        self.assertEqual(set(manager._seen), {"current"})

    def test_config_round_trip(self):
        self.config.weather.lightning_satellite = "goes18"
        self.config.weather.lightning_history_minutes = 15
        self.config.weather.lightning_alert_enabled = True
        self.config.weather.lightning_alert_radius_miles = 42
        self.config.weather.lightning_alert_cooldown_minutes = 20
        self.config.weather.lightning_info_card_enabled = False
        self.config.weather.lightning_alert_email_enabled = True
        self.config.weather.satellite_imagery_enabled = True
        self.config.weather.space_weather_enabled = True
        self.config.weather.space_weather_alert_enabled = True
        self.config.weather.space_weather_alert_min_kp = 6.0
        self.config.weather.space_weather_alert_cooldown_minutes = 90
        self.config.weather.space_weather_alert_sms_enabled = True
        self.config.propagation.psk_reporter_enabled = True
        self.config.propagation.psk_reporter_window_minutes = 45
        self.config.web.club_display_rotation_seconds = 35
        self.config.web.club_display_scenes = ["map", "weather", "heatmap", "packets"]
        self.config.watched_paths = [WatchedPathConfig(
            callsign="REPEATER",
            latitude=35.5,
            longitude=-80.5,
            watch_weather_enabled=True,
            watch_lightning_enabled=True,
            watch_alert_radius_miles=35,
            watch_alert_cooldown_minutes=45,
            watch_discord_enabled=True,
        )]
        with TemporaryDirectory() as folder:
            path = Path(folder) / "config.toml"
            self.config.save(path)
            loaded = Config.load(path)
        self.assertTrue(loaded.weather.lightning_enabled)
        self.assertEqual(loaded.weather.lightning_satellite, "goes18")
        self.assertEqual(loaded.weather.lightning_history_minutes, 15)
        self.assertEqual(loaded.weather.lightning_alert_radius_miles, 42)
        self.assertEqual(loaded.weather.lightning_alert_cooldown_minutes, 20)
        self.assertFalse(loaded.weather.lightning_info_card_enabled)
        self.assertTrue(loaded.weather.lightning_alert_email_enabled)
        self.assertTrue(loaded.weather.satellite_imagery_enabled)
        self.assertTrue(loaded.weather.space_weather_enabled)
        self.assertTrue(loaded.weather.space_weather_alert_enabled)
        self.assertEqual(loaded.weather.space_weather_alert_min_kp, 6.0)
        self.assertEqual(loaded.weather.space_weather_alert_cooldown_minutes, 90)
        self.assertTrue(loaded.weather.space_weather_alert_sms_enabled)
        self.assertTrue(loaded.propagation.psk_reporter_enabled)
        self.assertEqual(loaded.propagation.psk_reporter_window_minutes, 45)
        self.assertEqual(loaded.web.club_display_rotation_seconds, 35)
        self.assertEqual(loaded.web.club_display_scenes, ["map", "weather", "heatmap", "packets"])
        self.assertTrue(loaded.watched_paths[0].watch_weather_enabled)
        self.assertTrue(loaded.watched_paths[0].watch_lightning_enabled)
        self.assertEqual(loaded.watched_paths[0].watch_alert_radius_miles, 35)
        self.assertTrue(loaded.watched_paths[0].watch_discord_enabled)

    async def test_poll_downloads_each_granule_once(self):
        downloads = []
        keys = ["one.nc", "two.nc"]

        def download(satellite, key):
            downloads.append((satellite, key))
            return key.encode()

        def parse(payload, key):
            return [{"lat": 35.1, "lon": -80.1, "timestamp": time.time(), "source": key}]

        manager = LightningManager(
            self.config,
            list_keys=lambda satellite, now: keys,
            download=download,
            parse=parse,
        )
        now = datetime.now(timezone.utc)
        await manager.poll_once(now)
        await manager.poll_once(now)
        self.assertEqual(len(downloads), 2)
        self.assertEqual(len(manager.snapshot()["flashes"]), 2)

    async def test_radius_alert_respects_cooldown(self):
        alerts = _AlertStub()
        self.config.weather.lightning_alert_enabled = True
        self.config.weather.lightning_alert_radius_miles = 25
        self.config.weather.lightning_alert_cooldown_minutes = 30
        self.config.weather.lightning_alert_discord_enabled = True
        manager = LightningManager(self.config, alert_manager=alerts)
        manager._satellite = "goes19"
        manager._last_data = time.time()
        manager._flashes.append({
            "lat": 35.05,
            "lon": -80.0,
            "timestamp": time.time(),
            "source": "test.nc",
        })
        await manager._maybe_alert()
        await manager._maybe_alert()
        self.assertEqual(len(alerts.sent), 1)
        self.assertEqual(alerts.sent[0][0]["type"], "lightning_proximity")
        self.assertEqual(alerts.sent[0][1], ["discord"])

    async def test_watched_site_lightning_alert_uses_its_own_radius_and_channels(self):
        alerts = _AlertStub()
        self.config.weather.lightning_alert_enabled = False
        self.config.watched_paths = [WatchedPathConfig(
            callsign="REPEATER",
            latitude=36.0,
            longitude=-90.0,
            watch_lightning_enabled=True,
            watch_alert_radius_miles=25,
            watch_alert_cooldown_minutes=30,
            watch_email_enabled=True,
        )]
        manager = LightningManager(self.config, alert_manager=alerts)
        manager._flashes.append({
            "lat": 36.05, "lon": -90.0, "timestamp": time.time(), "source": "test.nc",
        })
        await manager._maybe_alert()
        await manager._maybe_alert()
        self.assertEqual(len(alerts.sent), 1)
        self.assertEqual(alerts.sent[0][0]["watch_location"], "REPEATER")
        self.assertEqual(alerts.sent[0][1], ["email"])


if __name__ == "__main__":
    unittest.main()
