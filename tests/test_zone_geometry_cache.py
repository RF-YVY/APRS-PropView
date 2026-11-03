import unittest
from unittest import mock

import server.weather as weather_module

ZONE = "https://api.weather.gov/zones/county/KSC001"
GEOMETRY = {
    "type": "Polygon",
    "coordinates": [[[-98.0, 37.0], [-98.1, 37.0], [-98.1, 37.1], [-98.0, 37.0]]],
}


class _Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class ZoneGeometryCacheTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        weather_module._ZONE_GEOMETRY_CACHE.clear()
        self.clock = _Clock()
        patcher = mock.patch.object(weather_module, "_zone_cache_now", self.clock, create=True)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.calls = []
        self.zone_up = False
        original = weather_module._async_http_get
        self.addCleanup(setattr, weather_module, "_async_http_get", original)
        self.addCleanup(weather_module._ZONE_GEOMETRY_CACHE.clear)

        async def fake_http_get(url, timeout=10, retries=1, log_fail=True):
            if "/alerts/active" in url:
                return {
                    "features": [{
                        "id": "watch-1",
                        "geometry": None,
                        "properties": {
                            "event": "Severe Thunderstorm Watch",
                            "severity": "Severe",
                            "status": "Actual",
                            "affectedZones": [ZONE],
                        },
                    }],
                }
            self.calls.append(url)
            return {"geometry": GEOMETRY} if self.zone_up else None

        weather_module._async_http_get = fake_http_get

    async def test_failed_fetch_is_retried_after_the_short_ttl(self):
        self.assertIsNone(await weather_module._fetch_zone_geometry(ZONE))
        self.zone_up = True
        self.clock.now += 29
        self.assertEqual(await weather_module._fetch_zone_geometry(ZONE), GEOMETRY)
        self.assertEqual(len(self.calls), 2)

    async def test_failed_fetch_is_not_refetched_inside_the_ttl(self):
        await weather_module._fetch_zone_geometry(ZONE)
        await weather_module._fetch_zone_geometry(ZONE)
        self.assertEqual(len(self.calls), 1)

    async def test_success_is_cached_then_refreshed(self):
        self.zone_up = True
        await weather_module._fetch_zone_geometry(ZONE)
        self.clock.now += 60 * 60
        await weather_module._fetch_zone_geometry(ZONE)
        self.assertEqual(len(self.calls), 1)
        self.clock.now += 24 * 60 * 60
        await weather_module._fetch_zone_geometry(ZONE)
        self.assertEqual(len(self.calls), 2)

    async def test_cache_size_is_bounded(self):
        self.zone_up = True
        for n in range(weather_module._ZONE_GEOMETRY_CACHE_MAX + 50):
            await weather_module._fetch_zone_geometry(f"{ZONE}{n}")
        self.assertLessEqual(len(weather_module._ZONE_GEOMETRY_CACHE), weather_module._ZONE_GEOMETRY_CACHE_MAX)
        self.assertIn(f"{ZONE}{weather_module._ZONE_GEOMETRY_CACHE_MAX + 49}", weather_module._ZONE_GEOMETRY_CACHE)

    async def test_radius_alert_returns_on_the_next_poll_after_a_timeout(self):
        first = await weather_module.fetch_nws_alerts(37.0, -98.0, 50, "radius", area="KS")
        self.assertEqual(first, [])
        self.zone_up = True
        self.clock.now += 30
        second = await weather_module.fetch_nws_alerts(37.0, -98.0, 50, "radius", area="KS")
        self.assertEqual([alert["event"] for alert in second], ["Severe Thunderstorm Watch"])
        self.assertEqual(second[0]["geometry_source"], "affected_zones")


if __name__ == "__main__":
    unittest.main()
