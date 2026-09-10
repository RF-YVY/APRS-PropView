"""Read-only analytics endpoints, separated from station configuration."""
import logging
import time
from fastapi import Query
from server.aprs_parser import parse_packet
logger = logging.getLogger("propview.analytics")


def register_analytics_routes(app, db, analytics, weather_manager):
    @app.get("/api/analytics/longest-paths")
    async def get_longest_paths(
        hours: int = Query(24, ge=1, le=168),
        limit: int = Query(25, ge=1, le=100),
        path_type: str = Query("direct", pattern="^(direct|relayed|all)$"),
        port: str = Query("", max_length=100),
        include_suspect: bool = Query(False),
    ):
        if not analytics:
            return {"paths": [], "count": 0}
        return await analytics.get_longest_paths_report(
            hours=hours, limit=limit, path_type=path_type, port=port,
            include_suspect=include_suspect,
        )

    @app.get("/api/analytics/heatmap")
    async def get_heatmap(
        hours: int = Query(24, ge=1, le=168),
    ):
        if not analytics:
            return {"grid": [], "timeline": [], "hours_covered": 0}
        return await analytics.get_propagation_heatmap(hours=hours)

    @app.get("/api/analytics/reliability")
    async def get_reliability(
        hours: int = Query(24, ge=1, le=168),
    ):
        if not analytics:
            return {"stations": [], "count": 0}
        stations = await analytics.get_station_reliability(hours=hours)
        return {"stations": stations, "count": len(stations)}

    @app.get("/api/analytics/best-times")
    async def get_best_times(
        days: int = Query(7, ge=1, le=30),
    ):
        if not analytics:
            return {"hours": [], "best_hours": [], "days_analyzed": 0, "total_samples": 0, "day_of_week": []}
        return await analytics.get_best_times(days=days)

    @app.get("/api/analytics/anomaly")
    async def get_anomaly():
        if not analytics:
            return {"anomaly_score": 0, "anomaly_level": "normal"}
        return await analytics.get_anomaly_status()

    @app.get("/api/analytics/bearing-sectors")
    async def get_bearing_sectors(
        hours: int = Query(24, ge=1, le=168),
        path_type: str = Query("direct", pattern="^(direct|relayed|all)$"),
        port: str = Query("", max_length=100),
    ):
        if not analytics:
            return {"sectors": [], "dominant": None}
        return await analytics.get_bearing_sectors(hours=hours, path_type=path_type, port=port)

    @app.get("/api/analytics/historical")
    async def get_historical_comparison():
        if not analytics:
            return {"today": [], "yesterday": [], "week_avg": [], "avg_7d": []}
        return await analytics.get_historical_comparison()

    @app.get("/api/analytics/sporadic-e")
    async def get_sporadic_e(hours: int = Query(6, ge=1, le=168)):
        if not analytics:
            return {"es_level": "none", "es_score": 0, "candidates": []}
        return await analytics.detect_sporadic_e(hours=hours)

    @app.get("/api/analytics/observed-range")
    async def get_observed_range(
        hours: int = Query(24, ge=1, le=168),
        path_type: str = Query("direct", pattern="^(direct|relayed|all)$"),
        port: str = Query("", max_length=100),
    ):
        if not analytics:
            return {"sectors": [], "max_range_km": 0}
        return await analytics.get_observed_range(hours=hours, path_type=path_type, port=port)

    @app.get("/api/analytics/weather")
    async def get_weather_analytics(hours: int = Query(24, ge=1, le=168)):
        cutoff = time.time() - hours * 3600
        samples = []
        if weather_manager:
            current = await weather_manager.get_current_weather()
            if current:
                samples.append({
                    "timestamp": time.time(),
                    "source": current.get("location_name") or current.get("location_code") or "Current weather",
                    "temperature_f": current.get("temperature_f"),
                    "humidity": current.get("humidity"),
                    "pressure_mb": current.get("pressure_mb"),
                    "wind_speed_mph": current.get("wind_speed_mph"),
                    "wind_gust_mph": current.get("wind_gusts_mph"),
                    "rain_1h_in": current.get("precipitation_in"),
                })
        cursor = await db.db.execute(
            """SELECT timestamp, source, from_call, raw
               FROM packets
               WHERE timestamp >= ?
                 AND packet_type = 'weather'
               ORDER BY timestamp ASC
               LIMIT 1000""",
            (cutoff,),
        )
        rows = await cursor.fetchall()
        for row in rows:
            pkt = parse_packet(row["raw"], source=row["source"])
            if not pkt.weather:
                continue
            samples.append({
                "timestamp": row["timestamp"],
                "source": row["from_call"],
                **pkt.weather,
            })
        samples.sort(key=lambda item: item.get("timestamp") or 0)
        return {"samples": samples, "count": len(samples), "hours": hours}

    @app.get("/api/analytics/path-quality/{callsign}")
    async def get_path_quality(callsign: str):
        history = await db.get_path_history(callsign.upper())
        return {"callsign": callsign.upper(), "history": history, "count": len(history)}

    @app.get("/api/first-heard")
    async def get_first_heard(
        hours: int = Query(24, ge=1, le=168),
        direct_only: bool = Query(False),
    ):
        log = await db.get_first_heard_log(hours=hours, direct_only=direct_only)
        return {"log": log, "count": len(log)}

    @app.get("/api/ducting")
    async def get_ducting():
        if not weather_manager:
            return {"enabled": False}
        try:
            ducting = await weather_manager.get_ducting()
            return ducting or {"enabled": True, "available": False}
        except Exception as e:
            logger.error(f"Ducting fetch error: {e}")
            return {"enabled": True, "error": str(e)}
