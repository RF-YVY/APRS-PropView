"""Historical RF observations and explicitly provisional mechanism diagnostics."""
import time
from datetime import datetime
from collections import defaultdict
from typing import Dict, Any
from server.rf_evidence import grade_position_observations


class RFHistoryAnalytics:
    async def get_longest_paths_report(self, hours=24, limit=25, path_type="direct", port="", include_suspect=False):
        rows = await self.db.rf_observations(hours, path_type, port)
        accepted, rejected = grade_position_observations(rows)
        rows = accepted + rejected if include_suspect else accepted
        best = {}
        for row in rows:
            if row.get("distance_km") is not None and row["distance_km"] > 0:
                if row["callsign"] not in best or row["distance_km"] > best[row["callsign"]]["distance_km"]:
                    best[row["callsign"]] = row
        paths = [row | {"rank": rank, "distance_mi": round(row["distance_km"]*0.621371, 1)}
                 for rank, row in enumerate(sorted(best.values(), key=lambda r:r["distance_km"], reverse=True)[:limit], 1)]
        return {
            "paths": paths,
            "count": len(paths),
            "excluded_count": len({(row.get("callsign") or "").upper() for row in rejected}),
            "quality_note": "Very long paths require a confirming reception from the same area.",
        }

    async def get_longest_paths(self, hours=24, limit=25, path_type="direct", port="", include_suspect=False):
        report = await self.get_longest_paths_report(hours, limit, path_type, port, include_suspect)
        return report["paths"]


    async def get_bearing_sectors(self, hours: int = 24, path_type="direct", port="") -> Dict[str, Any]:
        """Analyze propagation by compass bearing sector.

        Divides the compass into 8 sectors (N, NE, E, SE, S, SW, W, NW)
        and aggregates RF station count, max distance, and avg distance per sector.
        """
        cutoff = time.time() - (hours * 3600)

        rows = [r for r in await self.db.rf_observations(hours, path_type, port)
                if r.get("distance_km") and r.get("heading") is not None]

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
                "station_count": len({st["callsign"] for st in s["stations"]}),
                "max_distance_km": round(s["max_distance"], 1),
                "avg_distance_km": round(sum(dists) / len(dists), 1) if dists else 0,
                "total_packets": len(s["stations"]),
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
            "total_stations": len({r["callsign"] for r in rows}),
            "path_type": path_type, "port": port,
            "hours": hours,
        }


    async def detect_sporadic_e(self, hours: int = 6) -> Dict[str, Any]:
        """Detect possible sporadic-E events by looking for sudden long-distance contacts.

        Indicators:
        - Contacts at 500+ km on 2m (or 800+ km general VHF)
        - Sudden appearance of distant, never-before-seen stations
        - Time of year (May-August in Northern Hemisphere)
        - Time of day (late morning and early evening peaks)
        """
        hours = max(1, min(168, int(hours or 6)))
        cutoff = time.time() - (hours * 3600)
        min_distance_km = 300.0
        min_candidate_score = 25.0

        observations = [r for r in await self.db.rf_observations(hours) if r.get("distance_km") is not None]
        rf_station_count = len({r["callsign"] for r in observations})
        distances = [r["distance_km"] for r in observations]
        max_observed_distance_km = max(distances, default=0)
        avg_observed_distance_km = sum(distances)/len(distances) if distances else 0
        cursor = await self.db.db.execute("SELECT callsign, timestamp FROM first_heard_log WHERE source='rf'")
        first_seen = {r["callsign"]: r["timestamp"] for r in await cursor.fetchall()}
        counts = defaultdict(int)
        for r in observations:
            counts[r["callsign"]] += 1
        rows = []
        for r in observations:
            if r["distance_km"] < min_distance_km:
                continue
            direct = bool(r["is_direct"])
            rows.append(r | {"first_heard": first_seen.get(r["callsign"], 0),
                "packet_count": counts[r["callsign"]],
                "path_confidence": 1.0 if direct else (0.6 if r["hop_count"] <= 1 else 0.3),
                "path_tier": "direct_rf" if direct else ("single_hop_rf" if r["hop_count"] <= 1 else "multi_hop_rf"),
                "min_hop_count": r["hop_count"]})
        strongest_stations = sorted(observations, key=lambda r:r["distance_km"], reverse=True)[:5]
        strongest_stations = [r | {"packet_count": counts[r["callsign"]]} for r in strongest_stations]

        es_candidates = []
        near_misses = []
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
            month = datetime.fromtimestamp(row["timestamp"]).month
            if row.get("latitude") is not None and row["latitude"] < 0:
                month = (month + 5) % 12 + 1
            if row.get("latitude") is not None and 5 <= month <= 8:
                score += 10
                indicators.append("Peak Es season")
            elif row.get("latitude") is not None and month in (4, 9):
                score += 5
                indicators.append("Shoulder Es season")

            # Time of day check (10-14 UTC and 17-21 UTC peaks)
            hour_utc = ((row["timestamp"] / 3600) + (row.get("longitude") or 0) / 15) % 24
            if row.get("longitude") is not None and (10 <= hour_utc <= 14 or 17 <= hour_utc <= 21):
                score += 10
                indicators.append("Local solar time supports Es hypothesis")

            path_confidence = float(row["path_confidence"] or 0)
            weighted_score = score * path_confidence
            item = {
                "callsign": row["callsign"],
                "distance_km": round(dist, 1),
                "heading": round(row["heading"], 1) if row["heading"] is not None else None,
                "latitude": row["latitude"],
                "longitude": row["longitude"],
                "first_heard": row["first_heard"],
                "last_heard": row["last_heard"],
                "packet_count": row["packet_count"],
                "raw_score": min(score, 100),
                "es_score": min(round(weighted_score, 1), 100),
                "path_confidence": round(path_confidence, 2),
                "path_tier": row["path_tier"],
                "min_hop_count": row["min_hop_count"],
                "indicators": indicators,
            }

            if weighted_score >= min_candidate_score:
                es_candidates.append(item)
            else:
                near_misses.append(item)

        # Retain each station's strongest internally consistent observation.
        best = {}
        for candidate in es_candidates:
            if candidate["callsign"] not in best or candidate["es_score"] > best[candidate["callsign"]]["es_score"]:
                best[candidate["callsign"]] = candidate
        es_candidates = list(best.values())
        es_candidates.sort(key=lambda c: c["es_score"], reverse=True)
        near_misses.sort(key=lambda c: c["es_score"], reverse=True)

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
            "interpretation": "Unconfirmed propagation hypothesis, not a measured mechanism or probability",
            "es_level": es_level,
            "es_score": round(max_score, 1),
            "max_score": round(max_score, 1),
            "avg_score": round(avg_score, 1),
            "candidate_count": len(es_candidates),
            "candidates": es_candidates[:20],  # Top 20
            "hours_analyzed": hours,
            "rf_station_count": rf_station_count,
            "qualifying_distance_count": len({r["callsign"] for r in rows}),
            "max_observed_distance_km": round(max_observed_distance_km, 1),
            "avg_observed_distance_km": round(avg_observed_distance_km, 1),
            "min_distance_km": min_distance_km,
            "min_candidate_score": min_candidate_score,
            "strongest_stations": strongest_stations,
            "near_misses": near_misses[:5],
        }


    async def get_observed_range(self, hours: int = 168, path_type="direct", port="") -> Dict[str, Any]:
        """Compute actual observed max-distance by bearing sector from historical data.

        Returns the real coverage footprint (not theoretical circles) based on
        actually-received stations over the given time window.
        """
        cutoff = time.time() - (hours * 3600)

        rows = [r for r in await self.db.rf_observations(hours, path_type, port)
                if r.get("distance_km") and r.get("heading") is not None]

        # 16-sector resolution for smoother ring
        num_sectors = 16
        sector_size = 360.0 / num_sectors
        sector_labels = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
                         "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]
        sectors = {i: {"max": 0, "avg_dists": [], "calls": set()} for i in range(num_sectors)}

        for row in rows:
            heading = row["heading"]
            dist = row["distance_km"]
            idx = int(((heading + sector_size / 2) % 360) / sector_size)
            s = sectors[idx]
            s["calls"].add(row["callsign"])
            s["avg_dists"].append(dist)
            if dist > s["max"]:
                s["max"] = dist

        # Also compute current range (last 24h only)
        rows_24h = [r for r in rows if r["timestamp"] >= time.time()-86400]
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
                "station_count": len(s["calls"]),
            })

        return {
            "ring": ring_data,
            "hours_historical": hours,
            "total_stations": len({r["callsign"] for r in rows}),
            "path_type": path_type, "port": port,
        }
