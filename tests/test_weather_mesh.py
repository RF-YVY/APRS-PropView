import time
import unittest

from fastapi import FastAPI

from server.analytics_routes import register_analytics_routes
from server.config import Config
from server.database import Database


class WeatherMeshTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.db = Database(":memory:")
        await self.db.initialize()
        self.config = Config()
        self.config.station.latitude = 35.0
        self.config.station.longitude = -90.0

    async def asyncTearDown(self):
        await self.db.close()

    async def test_mesh_returns_latest_nearby_station_with_trends(self):
        now = time.time()
        rows = [
            (now - 600, "rf", "WX1", "", "", "WX1>APRS:_09171200c090s010g020t075h50b10130", "weather", 35.2, -90.0, "2m", 0),
            (now - 60, "rf", "WX1", "", "", "WX1>APRS:_09171210c100s015g025t078h55b10110", "weather", 35.2, -90.0, "2m", 0),
            (now - 60, "aprs_is", "FARWX", "", "", "FARWX>APRS:_09171210c100s015g025t078h55b10110", "weather", 45.0, -90.0, "", 0),
        ]
        await self.db.db.executemany(
            """INSERT INTO packets
               (timestamp, source, from_call, to_call, path, raw, packet_type, latitude, longitude, port_name, digipeated_by_me)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            rows,
        )
        await self.db.db.commit()
        app = FastAPI()
        register_analytics_routes(app, self.db, None, None, config=self.config)
        endpoint = next(route.endpoint for route in app.routes if getattr(route, "path", "") == "/api/analytics/weather-mesh")
        result = await endpoint(hours=6, radius_km=200)
        self.assertEqual(result["count"], 1)
        station = result["stations"][0]
        self.assertEqual(station["callsign"], "WX1")
        self.assertEqual(station["temperature_f"], 78)
        self.assertEqual(station["temperature_trend_f"], 3)
        self.assertAlmostEqual(station["pressure_trend_mb"], -2.0)
        self.assertLess(station["distance_km"], 30)


if __name__ == "__main__":
    unittest.main()
