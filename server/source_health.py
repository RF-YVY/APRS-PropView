"""Unified, read-only freshness summaries for dashboard data sources."""

import time
from typing import Any, Dict, Optional


def _age(now: float, timestamp: Any) -> Optional[int]:
    try:
        value = float(timestamp or 0)
    except (TypeError, ValueError):
        return None
    return max(0, round(now - value)) if value > 0 else None


def _timed_source(
    source_id: str,
    label: str,
    enabled: bool,
    age_seconds: Optional[int],
    expected_seconds: int,
    detail: str,
    *,
    error: str = "",
) -> Dict[str, Any]:
    if not enabled:
        state = "disabled"
    elif error and age_seconds is None:
        state = "offline"
    elif age_seconds is None:
        state = "waiting"
    elif age_seconds <= expected_seconds * 2:
        state = "live"
    elif age_seconds <= expected_seconds * 4:
        state = "delayed"
    else:
        state = "stale"
    return {
        "id": source_id,
        "label": label,
        "state": state,
        "enabled": bool(enabled),
        "age_seconds": age_seconds,
        "expected_seconds": expected_seconds,
        "detail": detail,
        "error": error or "",
    }


def build_source_health(
    config,
    connection_status: Dict[str, Any],
    tracker,
    weather_manager=None,
    lightning_manager=None,
    space_weather_manager=None,
    psk_reporter_manager=None,
    aprs_is=None,
    now: Optional[float] = None,
) -> Dict[str, Any]:
    """Return normalized source health without performing network requests."""
    now = float(now or time.time())
    sources = []

    enabled_ports = [port for port in getattr(config, "rf_ports", []) if getattr(port, "enabled", False)]
    rf_connected = bool(connection_status.get("rf_connected"))
    rf_age = _age(now, getattr(tracker, "_last_rf_packet_time", 0))
    if not enabled_ports:
        rf_state = "disabled"
    elif not rf_connected:
        rf_state = "offline"
    elif rf_age is None:
        rf_state = "waiting"
    elif rf_age <= 900:
        rf_state = "live"
    else:
        rf_state = "stale"
    sources.append({
        "id": "rf",
        "label": "RF receiver",
        "state": rf_state,
        "enabled": bool(enabled_ports),
        "age_seconds": rf_age,
        "expected_seconds": None,
        "detail": f"{sum(1 for item in connection_status.get('rf_interfaces', []) if item.get('connected'))}/{len(enabled_ports)} interfaces connected",
        "error": next((str(item.get("last_error")) for item in connection_status.get("rf_interfaces", []) if item.get("last_error")), ""),
    })

    is_enabled = bool(getattr(config.aprs_is, "enabled", False))
    is_connected = bool(connection_status.get("aprs_is_connected"))
    is_age = _age(now, getattr(aprs_is, "_last_rx", 0) if aprs_is else 0)
    is_state = "disabled" if not is_enabled else "offline" if not is_connected else "waiting" if is_age is None else "live" if is_age <= 900 else "stale"
    sources.append({
        "id": "aprs_is",
        "label": "APRS-IS",
        "state": is_state,
        "enabled": is_enabled,
        "age_seconds": is_age,
        "expected_seconds": None,
        "detail": "Connected and verified" if is_connected and connection_status.get("aprs_is_verified") else "Connected read-only" if is_connected else "Network feed disconnected",
        "error": "",
    })

    weather_enabled = bool(weather_manager and weather_manager.is_configured)
    refresh_seconds = max(60, int(getattr(config.weather, "refresh_minutes", 10) or 10) * 60)
    sources.append(_timed_source(
        "weather",
        "Current weather",
        weather_enabled,
        _age(now, getattr(weather_manager, "_last_fetch", 0) if weather_manager else 0),
        refresh_seconds,
        (getattr(config.weather, "current_provider", "open_meteo") or "open_meteo").replace("_", " ").title(),
    ))

    space_enabled = bool(space_weather_manager and space_weather_manager.enabled)
    space = space_weather_manager.snapshot() if space_weather_manager else {}
    sources.append(_timed_source(
        "space_weather",
        "NOAA space weather",
        space_enabled,
        space.get("age_seconds"),
        1800,
        f"Kp {space.get('kp', '--')} · G{space.get('g_scale', 0)} R{space.get('r_scale', 0)}",
        error=str(space.get("last_error") or ""),
    ))

    psk_enabled = bool(psk_reporter_manager and psk_reporter_manager.enabled)
    psk = psk_reporter_manager.snapshot() if psk_reporter_manager else {}
    sources.append(_timed_source(
        "psk_reporter",
        "PSK Reporter VHF/UHF",
        psk_enabled,
        psk.get("age_seconds"),
        600,
        f"{psk.get('report_count', 0)} station-specific digital reports",
        error=str(psk.get("last_error") or ""),
    ))

    alert_provider = (getattr(config.weather, "alert_provider", "auto") or "auto").strip().lower()
    alert_enabled = weather_enabled and alert_provider != "disabled"
    alert_interval = weather_manager._get_alert_poll_interval_seconds() if weather_manager else 300
    sources.append(_timed_source(
        "weather_alerts",
        "Weather alerts",
        alert_enabled,
        _age(now, getattr(weather_manager, "_last_alert_fetch", 0) if weather_manager else 0),
        alert_interval,
        f"{alert_provider.replace('_', ' ').title()} · {len(getattr(weather_manager, '_alerts', []) or [])} active",
    ))

    lightning_enabled = bool(lightning_manager and lightning_manager.enabled)
    lightning = lightning_manager.snapshot(now) if lightning_manager else {}
    lightning_age = lightning.get("data_age_seconds")
    sources.append(_timed_source(
        "lightning",
        "GOES GLM lightning",
        lightning_enabled,
        round(lightning_age) if lightning_age is not None else None,
        max(60, int(getattr(config.weather, "lightning_stale_seconds", 120) or 120)),
        lightning.get("satellite_label", "NOAA NODD"),
        error=str(lightning.get("last_error") or ""),
    ))

    for source_id, label, enabled, detail in (
        ("radar", "Radar tiles", bool(config.weather.radar_enabled), str(config.weather.radar_provider or "Configured browser layer")),
        ("satellite", "Satellite imagery", bool(config.weather.satellite_imagery_enabled), "NOAA/NESDIS browser tile layer"),
    ):
        sources.append({
            "id": source_id,
            "label": label,
            "state": "configured" if enabled else "disabled",
            "enabled": enabled,
            "age_seconds": None,
            "expected_seconds": None,
            "detail": detail,
            "error": "",
        })

    attention = sum(1 for source in sources if source["enabled"] and source["state"] in {"offline", "stale"})
    delayed = sum(1 for source in sources if source["enabled"] and source["state"] in {"delayed", "waiting"})
    return {
        "timestamp": now,
        "summary": "attention" if attention else "delayed" if delayed else "healthy",
        "attention_count": attention,
        "sources": sources,
    }
