"""Analytics engine — longest path, heatmap, reliability, best time-of-day,
anomaly detection, bearing-sector analysis, historical comparison, sporadic-E."""

import math
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

    # ── Propagation Anomaly Detection ───────────────────────────

    async def get_anomaly_status(self) -> Dict[str, Any]:
        """Compare current propagation to historical baselines by hour-of-day.

        Computes mean and standard deviation per hour from the last 7 days,
        then compares the current hour's values. Returns how many SDs
        above or below the baseline the current conditions are.
        """
        now = time.time()
        current_hour = datetime.now().hour

        # Build baseline from the last 7 days of propagation logs
        cutoff_7d = now - (7 * 86400)
        cursor = await self.db.db.execute(
            """SELECT timestamp, rf_station_count, max_distance_km, avg_distance_km
               FROM propagation_log
               WHERE timestamp >= ?
               ORDER BY timestamp ASC""",
            (cutoff_7d,),
        )
        rows = await cursor.fetchall()

        # Bucket by hour
        hour_counts = defaultdict(list)
        hour_max_dists = defaultdict(list)
        for row in rows:
            dt = datetime.fromtimestamp(row["timestamp"])
            h = dt.hour
            hour_counts[h].append(row["rf_station_count"] or 0)
            if row["max_distance_km"]:
                hour_max_dists[h].append(row["max_distance_km"])

        def _mean_std(values):
            if not values:
                return 0, 0
            n = len(values)
            mean = sum(values) / n
            if n < 2:
                return mean, 0
            variance = sum((v - mean) ** 2 for v in values) / (n - 1)
            return mean, math.sqrt(variance)

        # Baseline for current hour
        count_mean, count_std = _mean_std(hour_counts.get(current_hour, []))
        dist_mean, dist_std = _mean_std(hour_max_dists.get(current_hour, []))

        # Current values (last propagation log entry)
        cursor2 = await self.db.db.execute(
            """SELECT rf_station_count, max_distance_km
               FROM propagation_log
               ORDER BY timestamp DESC LIMIT 1"""
        )
        latest = await cursor2.fetchone()
        current_count = latest["rf_station_count"] if latest else 0
        current_max_dist = latest["max_distance_km"] if latest and latest["max_distance_km"] else 0

        # Compute Z-scores
        count_z = ((current_count - count_mean) / count_std) if count_std > 0 else 0
        dist_z = ((current_max_dist - dist_mean) / dist_std) if dist_std > 0 else 0

        # Combined anomaly score
        anomaly_score = max(count_z, dist_z)

        if anomaly_score >= 2.5:
            anomaly_level = "extreme"
        elif anomaly_score >= 1.5:
            anomaly_level = "significant"
        elif anomaly_score >= 1.0:
            anomaly_level = "notable"
        elif anomaly_score >= 0.5:
            anomaly_level = "slight"
        else:
            anomaly_level = "normal"

        # Percentage above/below average
        count_pct = ((current_count - count_mean) / count_mean * 100) if count_mean > 0 else 0
        dist_pct = ((current_max_dist - dist_mean) / dist_mean * 100) if dist_mean > 0 else 0

        return {
            "current_hour": current_hour,
            "anomaly_score": round(anomaly_score, 2),
            "anomaly_level": anomaly_level,
            "count_z_score": round(count_z, 2),
            "dist_z_score": round(dist_z, 2),
            "current_count": current_count,
            "current_max_dist_km": round(current_max_dist, 1),
            "baseline_count_mean": round(count_mean, 1),
            "baseline_count_std": round(count_std, 1),
            "baseline_dist_mean": round(dist_mean, 1),
            "baseline_dist_std": round(dist_std, 1),
            "count_pct_above_avg": round(count_pct, 1),
            "dist_pct_above_avg": round(dist_pct, 1),
            "baseline_samples": len(hour_counts.get(current_hour, [])),
        }

    # ── Bearing-Sector Analysis ─────────────────────────────────

    async def get_bearing_sectors(self, hours: int = 24) -> Dict[str, Any]:
        """Analyze propagation by compass bearing sector.

        Divides the compass into 8 sectors (N, NE, E, SE, S, SW, W, NW)
        and aggregates RF station count, max distance, and avg distance per sector.
        """
        cutoff = time.time() - (hours * 3600)

        cursor = await self.db.db.execute(
            """SELECT callsign, distance_km, heading, latitude, longitude,
                      last_heard, packet_count
               FROM stations
               WHERE source = 'rf'
                 AND distance_km IS NOT NULL
                 AND distance_km > 0
                 AND heading IS NOT NULL
                 AND last_heard >= ?
               ORDER BY heading ASC""",
            (cutoff,),
        )
        rows = await cursor.fetchall()

        sector_names = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
        sectors = {name: {"stations": [], "distances": [], "max_distance": 0} for name in sector_names}

        for row in rows:
            heading = row["heading"]
            # Map heading to sector index (each sector = 45°, centered)
            idx = int(((heading + 22.5) % 360) / 45)
            sector_name = sector_names[idx]
            s = sectors[sector_name]
            s["stations"].append(dict(row))
            dist = row["distance_km"]
            s["distances"].append(dist)
            if dist > s["max_distance"]:
                s["max_distance"] = dist

        result_sectors = []
        for name in sector_names:
            s = sectors[name]
            dists = s["distances"]
            result_sectors.append({
                "sector": name,
                "station_count": len(s["stations"]),
                "max_distance_km": round(s["max_distance"], 1),
                "avg_distance_km": round(sum(dists) / len(dists), 1) if dists else 0,
                "total_packets": sum(st["packet_count"] for st in s["stations"]),
                "stations": [
                    {"callsign": st["callsign"], "distance_km": round(st["distance_km"], 1), "heading": round(st["heading"], 1)}
                    for st in sorted(s["stations"], key=lambda x: x["distance_km"], reverse=True)[:5]
                ],
            })

        # Find dominant sector(s)
        max_count = max((s["station_count"] for s in result_sectors), default=0)
        max_dist = max((s["max_distance_km"] for s in result_sectors), default=0)
        dominant_by_count = [s["sector"] for s in result_sectors if s["station_count"] == max_count and max_count > 0]
        dominant_by_dist = [s["sector"] for s in result_sectors if s["max_distance_km"] == max_dist and max_dist > 0]

        return {
            "sectors": result_sectors,
            "dominant_count": dominant_by_count,
            "dominant_distance": dominant_by_dist,
            "total_stations": len(rows),
            "hours": hours,
        }

    # ── Historical Propagation Comparison ───────────────────────

    async def get_historical_comparison(self, hours: int = 24) -> Dict[str, Any]:
        """Compare current propagation timeline to yesterday and 7-day average.

        Returns three time series: today, yesterday, and 7-day average,
        aligned by hour-of-day for overlay charting.
        """
        now = time.time()

        # Today: last N hours
        today_cutoff = now - (hours * 3600)
        cursor = await self.db.db.execute(
            """SELECT timestamp, rf_station_count, max_distance_km, avg_distance_km
               FROM propagation_log WHERE timestamp >= ? ORDER BY timestamp ASC""",
            (today_cutoff,),
        )
        today_rows = await cursor.fetchall()

        # Yesterday: same time window shifted back 24h
        yesterday_start = today_cutoff - 86400
        yesterday_end = now - 86400
        cursor2 = await self.db.db.execute(
            """SELECT timestamp, rf_station_count, max_distance_km, avg_distance_km
               FROM propagation_log WHERE timestamp >= ? AND timestamp <= ?
               ORDER BY timestamp ASC""",
            (yesterday_start, yesterday_end),
        )
        yesterday_rows = await cursor2.fetchall()

        # 7-day average: bucket by hour-of-day
        week_cutoff = now - (7 * 86400)
        cursor3 = await self.db.db.execute(
            """SELECT timestamp, rf_station_count, max_distance_km, avg_distance_km
               FROM propagation_log WHERE timestamp >= ? ORDER BY timestamp ASC""",
            (week_cutoff,),
        )
        week_rows = await cursor3.fetchall()

        # Bucket 7-day data by hour
        week_buckets = defaultdict(lambda: {"counts": [], "max_dists": [], "avg_dists": []})
        for row in week_rows:
            h = datetime.fromtimestamp(row["timestamp"]).hour
            week_buckets[h]["counts"].append(row["rf_station_count"] or 0)
            if row["max_distance_km"]:
                week_buckets[h]["max_dists"].append(row["max_distance_km"])
            if row["avg_distance_km"]:
                week_buckets[h]["avg_dists"].append(row["avg_distance_km"])

        def _build_timeline(rows):
            timeline = []
            for row in rows:
                timeline.append({
                    "timestamp": row["timestamp"],
                    "hour": datetime.fromtimestamp(row["timestamp"]).hour,
                    "minute": datetime.fromtimestamp(row["timestamp"]).minute,
                    "station_count": row["rf_station_count"] or 0,
                    "rf_station_count": row["rf_station_count"] or 0,
                    "max_distance_km": row["max_distance_km"] or 0,
                    "avg_distance_km": row["avg_distance_km"] or 0,
                })
            return timeline

        # Build 7-day average as 24-hour profile
        avg_7d = []
        for h in range(24):
            b = week_buckets[h]
            avg_7d.append({
                "hour": h,
                "station_count": round(sum(b["counts"]) / len(b["counts"]), 1) if b["counts"] else 0,
                "rf_station_count": round(sum(b["counts"]) / len(b["counts"]), 1) if b["counts"] else 0,
                "max_distance_km": round(sum(b["max_dists"]) / len(b["max_dists"]), 1) if b["max_dists"] else 0,
                "avg_distance_km": round(sum(b["avg_dists"]) / len(b["avg_dists"]), 1) if b["avg_dists"] else 0,
            })

        return {
            "today": _build_timeline(today_rows),
            "yesterday": _build_timeline(yesterday_rows),
            "week_avg": avg_7d,
            "avg_7d": avg_7d,
            "hours": hours,
        }

    # ── Sporadic-E Detection ────────────────────────────────────

    async def detect_sporadic_e(self, hours: int = 6) -> Dict[str, Any]:
        """Detect possible sporadic-E events by looking for sudden long-distance contacts.

        Indicators:
        - Contacts at 500+ km on 2m (or 800+ km general VHF)
        - Sudden appearance of distant, never-before-seen stations
        - Time of year (May-August in Northern Hemisphere)
        - Time of day (late morning and early evening peaks)
        """
        cutoff = time.time() - (hours * 3600)

        # Get RF stations with large distances
        cursor = await self.db.db.execute(
            """SELECT callsign, distance_km, heading, latitude, longitude,
                      first_heard, last_heard, packet_count
               FROM stations
               WHERE source = 'rf'
                 AND distance_km IS NOT NULL
                 AND distance_km >= 300
                 AND last_heard >= ?
               ORDER BY distance_km DESC""",
            (cutoff,),
        )
        rows = await cursor.fetchall()

        es_candidates = []
        for row in rows:
            dist = row["distance_km"]
            score = 0
            indicators = []

            # Distance scoring
            if dist >= 800:
                score += 40
                indicators.append(f"Extreme distance ({dist:.0f} km)")
            elif dist >= 500:
                score += 30
                indicators.append(f"Long distance ({dist:.0f} km)")
            elif dist >= 300:
                score += 15
                indicators.append(f"Extended distance ({dist:.0f} km)")

            # Newly heard station (first_heard == last_heard or very recent first)
            if row["first_heard"] >= cutoff:
                score += 20
                indicators.append("Newly heard station")

            # Low packet count (transient contact typical of Es)
            if row["packet_count"] <= 3:
                score += 10
                indicators.append("Transient contact")

            # Seasonal check (May-August in Northern Hemisphere)
            month = datetime.now().month
            if 5 <= month <= 8:
                score += 10
                indicators.append("Peak Es season")
            elif month in (4, 9):
                score += 5
                indicators.append("Shoulder Es season")

            # Time of day check (10-14 UTC and 17-21 UTC peaks)
            hour_utc = datetime.utcnow().hour
            if 10 <= hour_utc <= 14 or 17 <= hour_utc <= 21:
                score += 10
                indicators.append("Peak Es time of day")

            if score >= 25:
                es_candidates.append({
                    "callsign": row["callsign"],
                    "distance_km": round(dist, 1),
                    "heading": round(row["heading"], 1) if row["heading"] else None,
                    "latitude": row["latitude"],
                    "longitude": row["longitude"],
                    "first_heard": row["first_heard"],
                    "last_heard": row["last_heard"],
                    "packet_count": row["packet_count"],
                    "es_score": min(score, 100),
                    "indicators": indicators,
                })

        # Overall Es probability
        if es_candidates:
            max_score = max(c["es_score"] for c in es_candidates)
            avg_score = sum(c["es_score"] for c in es_candidates) / len(es_candidates)
        else:
            max_score = 0
            avg_score = 0

        if max_score >= 70:
            es_level = "likely"
        elif max_score >= 50:
            es_level = "possible"
        elif max_score >= 25:
            es_level = "unlikely"
        else:
            es_level = "none"

        return {
            "es_level": es_level,
            "es_score": round(max_score, 1),
            "max_score": round(max_score, 1),
            "avg_score": round(avg_score, 1),
            "candidate_count": len(es_candidates),
            "candidates": es_candidates[:20],  # Top 20
            "hours_analyzed": hours,
        }

    # ── Dynamic Range Data (actual coverage footprint) ──────────

    async def get_observed_range(self, hours: int = 168) -> Dict[str, Any]:
        """Compute actual observed max-distance by bearing sector from historical data.

        Returns the real coverage footprint (not theoretical circles) based on
        actually-received stations over the given time window.
        """
        cutoff = time.time() - (hours * 3600)

        cursor = await self.db.db.execute(
            """SELECT distance_km, heading
               FROM stations
               WHERE source = 'rf'
                 AND distance_km IS NOT NULL
                 AND distance_km > 0
                 AND heading IS NOT NULL
                 AND last_heard >= ?""",
            (cutoff,),
        )
        rows = await cursor.fetchall()

        # 16-sector resolution for smoother ring
        num_sectors = 16
        sector_size = 360.0 / num_sectors
        sector_labels = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
                         "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]
        sectors = {i: {"max": 0, "avg_dists": [], "count": 0} for i in range(num_sectors)}

        for row in rows:
            heading = row["heading"]
            dist = row["distance_km"]
            idx = int(((heading + sector_size / 2) % 360) / sector_size)
            s = sectors[idx]
            s["count"] += 1
            s["avg_dists"].append(dist)
            if dist > s["max"]:
                s["max"] = dist

        # Also compute current range (last 24h only)
        cutoff_24h = time.time() - 86400
        cursor2 = await self.db.db.execute(
            """SELECT distance_km, heading
               FROM stations
               WHERE source = 'rf'
                 AND distance_km IS NOT NULL
                 AND distance_km > 0
                 AND heading IS NOT NULL
                 AND last_heard >= ?""",
            (cutoff_24h,),
        )
        rows_24h = await cursor2.fetchall()
        current_sectors = {i: 0 for i in range(num_sectors)}
        for row in rows_24h:
            idx = int(((row["heading"] + sector_size / 2) % 360) / sector_size)
            if row["distance_km"] > current_sectors[idx]:
                current_sectors[idx] = row["distance_km"]

        ring_data = []
        for i in range(num_sectors):
            s = sectors[i]
            ring_data.append({
                "sector": sector_labels[i],
                "bearing": i * sector_size,
                "historical_max_km": round(s["max"], 1),
                "current_max_km": round(current_sectors[i], 1),
                "avg_km": round(sum(s["avg_dists"]) / len(s["avg_dists"]), 1) if s["avg_dists"] else 0,
                "station_count": s["count"],
            })

        return {
            "ring": ring_data,
            "hours_historical": hours,
            "total_stations": len(rows),
        }
