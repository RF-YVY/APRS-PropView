"""Analytics engine — longest path, heatmap, reliability, best time-of-day."""

import time
import logging
from typing import Dict, Any, List, Optional
from collections import defaultdict
from datetime import datetime

logger = logging.getLogger("propview.analytics")


class AnalyticsEngine:
    """Provides advanced analytics computed from the station database."""

    def __init__(self, db):
        self.db = db

    # ── Longest Path Today ──────────────────────────────────────

    async def get_longest_paths(self, hours: int = 24, limit: int = 25) -> List[Dict[str, Any]]:
        """Return top N longest-distance RF contacts within the time window."""
        cutoff = time.time() - (hours * 3600)

        cursor = await self.db.db.execute(
            """SELECT callsign, latitude, longitude, distance_km, heading,
                      last_heard, first_heard, packet_count,
                      symbol_table, symbol_code, last_comment
               FROM stations
               WHERE source = 'rf'
                 AND distance_km IS NOT NULL
                 AND distance_km > 0
                 AND last_heard >= ?
               ORDER BY distance_km DESC
               LIMIT ?""",
            (cutoff, limit),
        )
        rows = await cursor.fetchall()

        results = []
        for rank, row in enumerate(rows, 1):
            r = dict(row)
            r["rank"] = rank
            r["distance_mi"] = round(r["distance_km"] * 0.621371, 1)
            results.append(r)

        return results

    # ── Propagation Heatmap Over Time ───────────────────────────

    async def get_propagation_heatmap(self, hours: int = 24) -> Dict[str, Any]:
        """Build a heatmap grid: hours-of-day x metric values.

        Returns hour-by-hour aggregated propagation data suitable for
        rendering as a heat-map on the frontend.
        """
        cutoff = time.time() - (hours * 3600)

        # Get propagation log entries
        cursor = await self.db.db.execute(
            """SELECT timestamp, rf_station_count, max_distance_km, avg_distance_km,
                      unique_stations_1h
               FROM propagation_log
               WHERE timestamp >= ?
               ORDER BY timestamp ASC""",
            (cutoff,),
        )
        rows = await cursor.fetchall()

        # Also get individual station packets bucketed by hour
        cursor2 = await self.db.db.execute(
            """SELECT p.timestamp, s.distance_km
               FROM packets p
               INNER JOIN stations s ON p.from_call = s.callsign AND s.source = 'rf'
               WHERE p.source = 'rf'
                 AND p.timestamp >= ?
                 AND s.distance_km IS NOT NULL
                 AND s.distance_km > 0""",
            (cutoff,),
        )
        try:
            packet_rows = await cursor2.fetchall()
        except Exception:
            packet_rows = []

        # Hour buckets (0-23)
        hour_data = defaultdict(lambda: {
            "station_count": 0,
            "max_distance": 0,
            "total_distance": 0,
            "packet_count": 0,
            "samples": 0,
        })

        # Aggregate propagation log by hour of day
        for row in rows:
            dt = datetime.fromtimestamp(row["timestamp"])
            h = dt.hour
            bucket = hour_data[h]
            bucket["station_count"] += row["rf_station_count"] or 0
            bucket["max_distance"] = max(bucket["max_distance"], row["max_distance_km"] or 0)
            bucket["samples"] += 1

        # Aggregate packet distances by hour
        for row in packet_rows:
            dt = datetime.fromtimestamp(row["timestamp"])
            h = dt.hour
            bucket = hour_data[h]
            dist = row["distance_km"] or 0
            if dist > 0:
                bucket["total_distance"] += dist
                bucket["packet_count"] += 1

        # Build output: 24-hour grid
        grid = []
        for h in range(24):
            b = hour_data[h]
            avg_stations = (b["station_count"] / b["samples"]) if b["samples"] > 0 else 0
            avg_distance = (b["total_distance"] / b["packet_count"]) if b["packet_count"] > 0 else 0

            grid.append({
                "hour": h,
                "label": f"{h:02d}:00",
                "avg_stations": round(avg_stations, 1),
                "max_distance_km": round(b["max_distance"], 1),
                "avg_distance_km": round(avg_distance, 1),
                "packet_count": b["packet_count"],
                "samples": b["samples"],
            })

        # Also build a timeline for the actual hours covered
        timeline = []
        for row in rows:
            timeline.append({
                "timestamp": row["timestamp"],
                "rf_station_count": row["rf_station_count"] or 0,
                "max_distance_km": row["max_distance_km"] or 0,
                "avg_distance_km": row["avg_distance_km"] or 0,
            })

        return {
            "grid": grid,
            "timeline": timeline,
            "hours_covered": hours,
        }

    # ── Station Reliability Scoring ─────────────────────────────

    async def get_station_reliability(self, hours: int = 24, min_packets: int = 2) -> List[Dict[str, Any]]:
        """Score RF stations by reliability — consistency of beaconing.

        Factors:
        - packet_count: more packets = more reliable
        - time_span: how long the station has been active
        - avg_interval: average time between packets (lower = more consistent)
        - distance stability: consistent distance readings
        """
        cutoff = time.time() - (hours * 3600)

        cursor = await self.db.db.execute(
            """SELECT callsign, first_heard, last_heard, packet_count,
                      distance_km, latitude, longitude, symbol_table, symbol_code
               FROM stations
               WHERE source = 'rf'
                 AND last_heard >= ?
                 AND packet_count >= ?
               ORDER BY packet_count DESC""",
            (cutoff, min_packets),
        )
        rows = await cursor.fetchall()

        results = []
        for row in rows:
            r = dict(row)
            pkt_count = r["packet_count"]
            first = r["first_heard"]
            last = r["last_heard"]
            time_span = last - first

            # Average interval between packets (estimate)
            avg_interval = (time_span / (pkt_count - 1)) if pkt_count > 1 and time_span > 0 else 0

            # Reliability score components (0-100)
            # 1. Packet density: more packets = better (up to 40 pts)
            pkt_score = min(pkt_count * 4, 40)

            # 2. Time coverage: longer presence = better (up to 30 pts)
            coverage_hours = time_span / 3600
            coverage_score = min(coverage_hours * 5, 30)

            # 3. Beacon consistency: regular intervals = better (up to 30 pts)
            # Ideal interval around 600-1800 seconds; penalize erratic
            if avg_interval > 0:
                if avg_interval <= 1800:  # <= 30 min average
                    interval_score = 30
                elif avg_interval <= 3600:  # <= 1 hour
                    interval_score = 20
                elif avg_interval <= 7200:
                    interval_score = 10
                else:
                    interval_score = 5
            else:
                interval_score = 0

            total_score = min(pkt_score + coverage_score + interval_score, 100)

            # Grade
            if total_score >= 80:
                grade = "A"
            elif total_score >= 60:
                grade = "B"
            elif total_score >= 40:
                grade = "C"
            elif total_score >= 20:
                grade = "D"
            else:
                grade = "F"

            results.append({
                "callsign": r["callsign"],
                "score": round(total_score, 1),
                "grade": grade,
                "packet_count": pkt_count,
                "first_heard": first,
                "last_heard": last,
                "time_span_hours": round(time_span / 3600, 2),
                "avg_interval_min": round(avg_interval / 60, 1) if avg_interval else 0,
                "distance_km": round(r["distance_km"], 1) if r["distance_km"] else None,
                "latitude": r["latitude"],
                "longitude": r["longitude"],
            })

        # Sort by score descending
        results.sort(key=lambda x: x["score"], reverse=True)
        return results

    # ── Best Time of Day Analytics ──────────────────────────────

    async def get_best_times(self, days: int = 7) -> Dict[str, Any]:
        """Analyze propagation data to find the best hours of day.

        Looks at historical propagation log across multiple days and
        identifies which hours consistently have the best conditions.
        """
        cutoff = time.time() - (days * 86400)

        cursor = await self.db.db.execute(
            """SELECT timestamp, rf_station_count, max_distance_km, avg_distance_km,
                      unique_stations_1h
               FROM propagation_log
               WHERE timestamp >= ?
               ORDER BY timestamp ASC""",
            (cutoff,),
        )
        rows = await cursor.fetchall()

        # Bucket by hour-of-day, collecting all samples
        hour_buckets = defaultdict(lambda: {
            "station_counts": [],
            "max_distances": [],
            "avg_distances": [],
        })

        for row in rows:
            dt = datetime.fromtimestamp(row["timestamp"])
            h = dt.hour
            bucket = hour_buckets[h]
            bucket["station_counts"].append(row["rf_station_count"] or 0)
            if row["max_distance_km"]:
                bucket["max_distances"].append(row["max_distance_km"])
            if row["avg_distance_km"]:
                bucket["avg_distances"].append(row["avg_distance_km"])

        # Compute composite score per hour
        hours = []
        for h in range(24):
            b = hour_buckets[h]
            counts = b["station_counts"]
            dists = b["max_distances"]

            avg_count = sum(counts) / len(counts) if counts else 0
            max_count = max(counts) if counts else 0
            avg_max_dist = sum(dists) / len(dists) if dists else 0
            peak_dist = max(dists) if dists else 0

            # Composite score: weighted station count + distance
            count_score = min(avg_count * 5, 50)
            dist_score = min(avg_max_dist / 4, 50)
            composite = min(count_score + dist_score, 100)

            hours.append({
                "hour": h,
                "label": f"{h:02d}:00",
                "avg_stations": round(avg_count, 1),
                "max_stations": max_count,
                "avg_max_distance_km": round(avg_max_dist, 1),
                "peak_distance_km": round(peak_dist, 1),
                "composite_score": round(composite, 1),
                "sample_count": len(counts),
            })

        # Find best hours
        sorted_hours = sorted(hours, key=lambda x: x["composite_score"], reverse=True)
        best_hours = sorted_hours[:3]

        # Day-of-week analysis
        dow_buckets = defaultdict(lambda: {"station_counts": [], "max_distances": []})
        for row in rows:
            dt = datetime.fromtimestamp(row["timestamp"])
            dow = dt.weekday()  # 0=Monday
            dow_buckets[dow]["station_counts"].append(row["rf_station_count"] or 0)
            if row["max_distance_km"]:
                dow_buckets[dow]["max_distances"].append(row["max_distance_km"])

        day_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        day_stats = []
        for d in range(7):
            b = dow_buckets[d]
            counts = b["station_counts"]
            dists = b["max_distances"]
            day_stats.append({
                "day": d,
                "name": day_names[d],
                "avg_stations": round(sum(counts) / len(counts), 1) if counts else 0,
                "avg_max_distance_km": round(sum(dists) / len(dists), 1) if dists else 0,
                "sample_count": len(counts),
            })

        return {
            "hours": hours,
            "best_hours": best_hours,
            "days_analyzed": days,
            "total_samples": len(rows),
            "day_of_week": day_stats,
        }
