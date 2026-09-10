"""Analytics engine — longest path, heatmap, reliability, best time-of-day,
anomaly detection, bearing-sector analysis, historical comparison, sporadic-E."""

from server.rf_analytics import RFHistoryAnalytics
import math
import time
import logging
from typing import Dict, Any, List, Optional
from collections import defaultdict
from datetime import datetime

logger = logging.getLogger("propview.analytics")


class AnalyticsEngine(RFHistoryAnalytics):
    """Provides advanced analytics computed from the station database."""

    def __init__(self, db):
        self.db = db

    @staticmethod
    def _percentile(values: List[float], pct: float) -> float:
        """Return a simple interpolated percentile for a sorted or unsorted list."""
        clean = sorted(float(v) for v in values if v is not None)
        if not clean:
            return 0.0
        if len(clean) == 1:
            return clean[0]
        rank = (len(clean) - 1) * max(0.0, min(100.0, pct)) / 100.0
        low = math.floor(rank)
        high = math.ceil(rank)
        if low == high:
            return clean[int(rank)]
        return clean[low] + (clean[high] - clean[low]) * (rank - low)

    @staticmethod
    def _summarize_series(values: List[float]) -> Dict[str, Any]:
        clean = [float(v) for v in values if v is not None]
        if not clean:
            return {
                "min": 0,
                "median": 0,
                "p75": 0,
                "p90": 0,
                "max": 0,
                "average": 0,
            }
        return {
            "min": round(min(clean), 1),
            "median": round(AnalyticsEngine._percentile(clean, 50), 1),
            "p75": round(AnalyticsEngine._percentile(clean, 75), 1),
            "p90": round(AnalyticsEngine._percentile(clean, 90), 1),
            "max": round(max(clean), 1),
            "average": round(sum(clean) / len(clean), 1),
        }

    @staticmethod
    def _recommend_count(values: List[int], current: int) -> Dict[str, Any]:
        stats = AnalyticsEngine._summarize_series(values)
        p75 = int(math.ceil(stats["p75"]))
        p90 = int(math.ceil(stats["p90"]))
        maximum = int(math.ceil(stats["max"]))
        suggested = max(1, p90 + 1)
        if maximum <= 0:
            suggested = max(1, int(current or 1))
        suggested = min(100, suggested)
        if current and current > suggested:
            suggested = int(current)
        if current and current <= stats["median"] and maximum > 0:
            reason = (
                f"Current threshold {current} is at or below the normal baseline "
                f"median of {stats['median']:.0f}; use above the 90th percentile."
            )
        elif current and current <= p75 and maximum > 0:
            reason = (
                f"Current threshold {current} is within normal 75th-percentile traffic; "
                "raise it to reduce routine alerts."
            )
        elif maximum <= 0:
            reason = "Not enough station activity was found, so the current value is retained."
        else:
            reason = "Current threshold is already above typical recent traffic."
        return {
            "current": int(current or 0),
            "suggested": int(suggested),
            "stats": stats,
            "reason": reason,
        }

    @staticmethod
    def _recommend_distance(values: List[float], current_km: float) -> Dict[str, Any]:
        stats = AnalyticsEngine._summarize_series(values)
        p90 = float(stats["p90"])
        maximum = float(stats["max"])
        suggested = math.ceil((p90 * 1.1) / 5.0) * 5.0 if p90 > 0 else float(current_km or 0)
        suggested = max(1.0, min(3219.0, suggested))
        if current_km and current_km > suggested:
            suggested = float(current_km)
        if current_km and current_km <= stats["median"] and maximum > 0:
            reason = (
                f"Current threshold {current_km:.0f} km is at or below the normal "
                f"median of {stats['median']:.0f} km; use a value above recent peaks."
            )
        elif current_km and current_km <= p90 and maximum > 0:
            reason = "Current distance is reached during normal recent conditions; raise it slightly."
        elif maximum <= 0:
            reason = "Not enough distance history was found, so the current value is retained."
        else:
            reason = "Current distance threshold is already above typical recent traffic."
        return {
            "current": round(float(current_km or 0), 1),
            "suggested": round(float(suggested), 1),
            "stats": stats,
            "reason": reason,
        }

    @staticmethod
    def _recommend_cooldown(samples_per_hour: float, current_seconds: int) -> Dict[str, Any]:
        current_minutes = max(1, int(round((current_seconds or 0) / 60)))
        suggested_minutes = current_minutes
        reason = "Current cooldown looks reasonable for the amount of recent sample data."
        if samples_per_hour >= 8 and current_minutes < 45:
            suggested_minutes = 45
            reason = "Recent data is dense enough that a longer cooldown can reduce repeated alerts."
        elif samples_per_hour >= 16 and current_minutes < 60:
            suggested_minutes = 60
            reason = "Recent data is very dense; a 60-minute cooldown is safer for noise control."
        return {
            "current_minutes": current_minutes,
            "suggested_minutes": suggested_minutes,
            "reason": reason,
        }

    async def get_alert_threshold_recommendations(
        self,
        alert_config: Any,
        hours: int = 24,
        sample_minutes: int = 15,
    ) -> Dict[str, Any]:
        """Recommend band-opening alert thresholds from recent RF path history.

        Each sample evaluates the previous one-hour window, matching the live
        alert thresholds that also use one-hour station counts and distances.
        """
        hours = max(6, min(168, int(hours or 24)))
        sample_minutes = max(5, min(60, int(sample_minutes or 15)))
        now = time.time()
        start = now - hours * 3600
        history_start = start - 3600

        cursor = await self.db.db.execute(
            """SELECT timestamp, callsign, distance_km, is_direct
               FROM path_history
               WHERE timestamp >= ?
               ORDER BY timestamp ASC""",
            (history_start,),
        )
        rows = [dict(r) for r in await cursor.fetchall()]

        step = sample_minutes * 60
        sample_times = []
        t = start
        while t <= now:
            sample_times.append(t)
            t += step

        direct_counts: List[int] = []
        direct_distances: List[float] = []
        regional_counts: List[int] = []
        regional_distances: List[float] = []

        for end_ts in sample_times:
            window_start = end_ts - 3600
            direct_seen = set()
            regional_seen = set()
            direct_max = 0.0
            regional_max = 0.0
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

        usable_samples = len(sample_times)
        samples_per_hour = usable_samples / max(hours, 1)
        current_my_count = int(getattr(alert_config, "my_min_stations", 3) or 3)
        current_my_dist = float(getattr(alert_config, "my_min_distance_km", 100.0) or 100.0)
        current_reg_count = int(getattr(alert_config, "regional_min_stations", 5) or 5)
        current_reg_dist = float(getattr(alert_config, "regional_min_distance_km", 100.0) or 100.0)
        current_cooldown = int(getattr(alert_config, "cooldown_seconds", 1800) or 1800)

        enough_data = bool(rows) and usable_samples >= 4
        return {
            "success": True,
            "enough_data": enough_data,
            "hours": hours,
            "sample_minutes": sample_minutes,
            "sample_count": usable_samples,
            "event_count": len(rows),
            "generated_at": now,
            "recommendations": {
                "my_min_stations": self._recommend_count(direct_counts, current_my_count),
                "my_min_distance_km": self._recommend_distance(direct_distances, current_my_dist),
                "regional_min_stations": self._recommend_count(regional_counts, current_reg_count),
                "regional_min_distance_km": self._recommend_distance(regional_distances, current_reg_dist),
                "cooldown_minutes": self._recommend_cooldown(samples_per_hour, current_cooldown),
            },
            "summary": (
                "Recommendations are based on rolling one-hour RF path windows. "
                "Suggested station counts sit above the recent 90th percentile so baseline traffic "
                "does not trigger routine band-opening alerts."
            ),
        }

    # ── Longest Path Today ──────────────────────────────────────


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
            """SELECT timestamp, distance_km FROM path_history
               WHERE timestamp >= ? AND is_direct=1 AND distance_km > 0""",
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


    # ── Dynamic Range Data (actual coverage footprint) ──────────
