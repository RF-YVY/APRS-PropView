import unittest

import server.weather as weather_module


class WeatherAlertGeometryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        weather_module._ZONE_GEOMETRY_CACHE.clear()
        self._orig_http_get = weather_module._async_http_get

    async def asyncTearDown(self):
        weather_module._async_http_get = self._orig_http_get
        weather_module._ZONE_GEOMETRY_CACHE.clear()

    async def test_fetch_nws_alerts_keeps_native_alert_geometry(self):
        native_geometry = {
            "type": "Polygon",
            "coordinates": [[[-98.0, 37.0], [-98.1, 37.0], [-98.1, 37.1], [-98.0, 37.0]]],
        }

        async def fake_http_get(url, timeout=10, retries=1, log_fail=True):
            self.assertIn("/alerts/active?point=", url)
            return {
                "features": [{
                    "id": "alert-1",
                    "geometry": native_geometry,
                    "properties": {
                        "event": "Severe Thunderstorm Warning",
                        "severity": "Severe",
                        "status": "Actual",
                    },
                }],
            }

        weather_module._async_http_get = fake_http_get

        alerts = await weather_module.fetch_nws_alerts(37.0, -98.0)

        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0]["geometry"], native_geometry)
        self.assertEqual(alerts[0]["geometry_source"], "alert")

    async def test_fetch_nws_alerts_uses_affected_zone_geometry_fallback(self):
        zone_geometry_1 = {
            "type": "Polygon",
            "coordinates": [[[-98.0, 37.0], [-98.1, 37.0], [-98.1, 37.1], [-98.0, 37.0]]],
        }
        zone_geometry_2 = {
            "type": "Polygon",
            "coordinates": [[[-99.0, 38.0], [-99.1, 38.0], [-99.1, 38.1], [-99.0, 38.0]]],
        }

        async def fake_http_get(url, timeout=10, retries=1, log_fail=True):
            if "/alerts/active?point=" in url:
                return {
                    "features": [{
                        "id": "watch-1",
                        "geometry": None,
                        "properties": {
                            "event": "Severe Thunderstorm Watch",
                            "severity": "Severe",
                            "status": "Actual",
                            "affectedZones": [
                                "https://api.weather.gov/zones/county/KSC001",
                                "https://api.weather.gov/zones/county/KSC003",
                            ],
                        },
                    }],
                }
            if url.endswith("/KSC001"):
                return {"geometry": zone_geometry_1}
            if url.endswith("/KSC003"):
                return {"geometry": zone_geometry_2}
            self.fail(f"Unexpected URL: {url}")

        weather_module._async_http_get = fake_http_get

        alerts = await weather_module.fetch_nws_alerts(37.0, -98.0)

        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0]["geometry_source"], "affected_zones")
        self.assertEqual(alerts[0]["geometry"], {
            "type": "GeometryCollection",
            "geometries": [zone_geometry_1, zone_geometry_2],
        })

    async def test_fetch_nws_alerts_radius_filters_state_area_geometry(self):
        nearby_geometry = {
            "type": "Polygon",
            "coordinates": [[[-89.6, 34.4], [-89.5, 34.4], [-89.5, 34.5], [-89.6, 34.4]]],
        }
        far_geometry = {
            "type": "Polygon",
            "coordinates": [[[-91.5, 32.2], [-91.4, 32.2], [-91.4, 32.3], [-91.5, 32.2]]],
        }

        async def fake_http_get(url, timeout=10, retries=1, log_fail=True):
            self.assertIn("/alerts/active?area=MS", url)
            return {
                "features": [
                    {
                        "id": "nearby",
                        "geometry": nearby_geometry,
                        "properties": {
                            "event": "Severe Thunderstorm Warning",
                            "severity": "Severe",
                            "status": "Actual",
                        },
                    },
                    {
                        "id": "far",
                        "geometry": far_geometry,
                        "properties": {
                            "event": "Severe Thunderstorm Warning",
                            "severity": "Severe",
                            "status": "Actual",
                        },
                    },
                ],
            }

        weather_module._async_http_get = fake_http_get

        alerts = await weather_module.fetch_nws_alerts(
            34.45,
            -89.55,
            range_miles=40,
            scope_mode="radius",
            area="MS",
        )

        self.assertEqual([alert["id"] for alert in alerts], ["nearby"])

    async def test_fetch_ducting_data_explains_scoring_factors(self):
        async def fake_http_get(url, timeout=10, retries=1, log_fail=True):
            self.assertIn("temperature_850hPa", url)
            return {
                "current": {
                    "temperature_2m": 70.0,
                    "relative_humidity_2m": 85,
                    "pressure_msl": 1026.0,
                    "surface_pressure": 1018.0,
                    "wind_speed_10m": 4.0,
                },
                "hourly": {
                    "temperature_850hPa": [72.0],
                    "pressure_msl": [1024.0, 1025.0, 1026.0],
                },
            }

        weather_module._async_http_get = fake_http_get

        ducting = await weather_module.fetch_ducting_data(34.45, -89.55)

        self.assertIsNotNone(ducting)
        self.assertEqual(ducting["ducting_index"], 90.0)
        self.assertEqual(ducting["level"], "high")
        self.assertTrue(ducting["inversion_detected"])
        self.assertIn("Strong inversion", ducting["factors"]["inversion"])
        self.assertIn("lapse=-2.0", ducting["factors"]["inversion"])
        self.assertEqual(
            [(item["key"], item["points"], item["max_points"]) for item in ducting["scoring"]],
            [
                ("inversion", 35, 35),
                ("pressure", 20, 25),
                ("trend", 10, 15),
                ("humidity", 15, 15),
                ("wind", 10, 10),
            ],
        )
        self.assertIn("High (1026 mb)", ducting["scoring"][1]["detail"])


if __name__ == "__main__":
    unittest.main()
