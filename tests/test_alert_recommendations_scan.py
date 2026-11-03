"""Threshold recommendations scale with the rows and stay off the event loop."""
import asyncio
import random
import tempfile
import threading
import time
import unittest
from types import SimpleNamespace

from server.analytics import AnalyticsEngine
from server.database import Database

HOUR = 3600


def old_scan(rows, sample_times):
    """The per-sample scan the single pass replaced, kept as the reference."""
    direct_counts, direct_distances, regional_counts, regional_distances = [], [], [], []
    for end_ts in sample_times:
        window_start = end_ts - HOUR
        direct_seen, regional_seen = set(), set()
        direct_max = regional_max = 0.0
        for row in rows:
            ts = float(row.get("timestamp") or 0)
            if ts < window_start or ts > end_ts:
                continue
            call = (row.get("callsign") or "").upper()
            if not call:
                continue
            dist = float(row.get("distance_km") or 0)
            if int(row.get("is_direct") or 0) == 1:
                direct_seen.add(call)
                direct_max = max(direct_max, dist)
            else:
                regional_seen.add(call)
                regional_max = max(regional_max, dist)
        direct_counts.append(len(direct_seen))
        direct_distances.append(direct_max)
        regional_counts.append(len(regional_seen))
        regional_distances.append(regional_max)
    return direct_counts, direct_distances, regional_counts, regional_distances


def random_rows(rng, count, span):
    rows = []
    for _ in range(count):
        rows.append({
            "timestamp": rng.random() * span,
            "callsign": rng.choice(["K1AA", "k1aa", "W2BB", "N3CC", "AD4D-1", "", None]),
            "distance_km": rng.choice([None, 0, 12.5, 88.0, 240.0, rng.random() * 400]),
            "is_direct": rng.choice([0, 1, None]),
        })
    rows.sort(key=lambda row: row["timestamp"])
    return rows


class SinglePassTests(unittest.TestCase):
    def assert_matches_old_scan(self, rows, sample_times):
        self.assertEqual(
            AnalyticsEngine._threshold_series(rows, sample_times),
            old_scan(rows, sample_times),
        )

    def test_matches_the_old_scan_on_random_history(self):
        rng = random.Random(1140)
        for trial in range(200):
            span = rng.choice([2, 6, 30]) * HOUR
            rows = random_rows(rng, rng.randint(0, 120), span)
            step = rng.choice([300, 900, 3600])
            samples = [HOUR + step * n for n in range(int(span / step))]
            with self.subTest(trial=trial):
                self.assert_matches_old_scan(rows, samples)

    def test_window_edges_are_inclusive(self):
        rows = [
            {"timestamp": 1000.0, "callsign": "K1AA", "distance_km": 50.0, "is_direct": 1},
            {"timestamp": 4600.0, "callsign": "W2BB", "distance_km": 20.0, "is_direct": 1},
        ]
        self.assert_matches_old_scan(rows, [999.0, 1000.0, 4600.0, 4600.5])

    def test_repeat_station_stays_counted_until_its_last_row_ages_out(self):
        rows = [
            {"timestamp": 0.0, "callsign": "K1AA", "distance_km": 300.0, "is_direct": 0},
            {"timestamp": 1800.0, "callsign": "K1AA", "distance_km": 10.0, "is_direct": 0},
        ]
        series = AnalyticsEngine._threshold_series(rows, [1800.0, 3600.0, 3601.0, 5401.0])
        self.assertEqual(series[2], [1, 1, 1, 0])
        self.assertEqual(series[3], [300.0, 300.0, 10.0, 0.0])

    def test_no_rows(self):
        self.assert_matches_old_scan([], [HOUR, 2 * HOUR])


class RecommendationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Database(f"{self.tmp.name}/test.db")
        await self.db.initialize()
        self.addAsyncCleanup(self.db.close)
        now = time.time()
        await self.db.db.executemany(
            "INSERT INTO path_history (timestamp, callsign, distance_km, is_direct) VALUES (?,?,?,?)",
            [(now - minutes * 60, f"N0T{minutes % 7}", 40.0 + minutes % 90, minutes % 2)
             for minutes in range(0, 1400, 3)],
        )
        await self.db.db.commit()

    async def test_scan_runs_off_the_event_loop(self):
        seen = []
        original = AnalyticsEngine._threshold_series

        def spy(rows, sample_times):
            seen.append(threading.current_thread())
            return original(rows, sample_times)

        engine = AnalyticsEngine(self.db)
        engine._threshold_series = spy
        await engine.get_alert_threshold_recommendations(SimpleNamespace(), hours=24, sample_minutes=15)
        self.assertEqual(len(seen), 1)
        self.assertIsNot(seen[0], threading.current_thread())

    async def test_packet_logging_takes_turns_with_the_history_read(self):
        now = time.time()
        await self.db.db.executemany(
            "INSERT INTO path_history (timestamp, callsign, distance_km, is_direct) VALUES (?,?,?,?)",
            [(now - 60 - n * 0.1, "K1AA", 80.0, 1) for n in range(30000)],
        )
        await self.db.db.commit()
        finished = False
        logged = 0

        async def log_packets():
            nonlocal logged
            while not finished:
                await self.db.log_packet(source="rf", from_call="K1AA", raw="x")
                logged += 1

        writer = asyncio.create_task(log_packets())
        await asyncio.sleep(0)
        result = await AnalyticsEngine(self.db).get_alert_threshold_recommendations(
            SimpleNamespace(), hours=24, sample_minutes=15
        )
        during_read = logged
        finished = True
        await writer
        self.assertEqual(result["event_count"], 30467)
        self.assertGreaterEqual(during_read, 4)

    async def test_response_keeps_its_fields(self):
        result = await AnalyticsEngine(self.db).get_alert_threshold_recommendations(
            SimpleNamespace(), hours=24, sample_minutes=15
        )
        self.assertTrue(result["enough_data"])
        self.assertEqual(result["event_count"], 467)
        self.assertEqual(result["sample_count"], 97)
        self.assertIn("my_min_stations", result["recommendations"])


if __name__ == "__main__":
    unittest.main()
