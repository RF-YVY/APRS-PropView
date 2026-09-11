"""Shared RF path and coordinate rules for tracking and API responses."""
import math
from collections import defaultdict


# A single very distant APRS position is easy to create with a bad radio/GPS
# configuration.  It is still valid latitude/longitude, so range checks alone
# cannot distinguish it from an unusual VHF opening.  Long observations become
# leaderboard evidence after a second reception from roughly the same area.
LONG_PATH_CONFIRMATION_KM = 800.0
POSITION_SUPPORT_RADIUS_KM = 80.0
POSITION_CONFLICT_KM = 250.0
MAX_EARTH_SURFACE_DISTANCE_KM = 20040.0


def valid_position(latitude, longitude):
    try:
        return (latitude is not None and longitude is not None
                and math.isfinite(float(latitude)) and math.isfinite(float(longitude))
                and -90 <= float(latitude) <= 90 and -180 <= float(longitude) <= 180)
    except (TypeError, ValueError):
        return False


def _surface_distance_km(lat1, lon1, lat2, lon2):
    """Small local haversine helper kept independent of station_tracker."""
    lat1, lon1, lat2, lon2 = map(float, (lat1, lon1, lat2, lon2))
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2))
         * math.sin(dlon / 2) ** 2)
    return 6371.0 * 2 * math.atan2(math.sqrt(a), math.sqrt(max(0.0, 1 - a)))


def grade_position_observations(rows):
    """Separate usable path evidence from isolated or contradictory positions.

    Normal regional paths remain usable after one packet. Paths of 800 km or
    more require two positions within 80 km of one another. If a callsign has a
    repeated position cluster, an isolated point over 250 km away is also held
    out. Rejected rows are returned with a plain-language reason so the UI can
    expose them on request.
    """
    prepared = []
    rejected = []
    by_call = {}

    for original in rows:
        row = dict(original)
        try:
            distance = float(row.get("distance_km"))
        except (TypeError, ValueError):
            continue
        if not math.isfinite(distance) or distance <= 0 or distance > MAX_EARTH_SURFACE_DISTANCE_KM:
            row.update(quality_status="suspect", quality_reason="Impossible path distance")
            rejected.append(row)
            continue

        lat, lon = row.get("latitude"), row.get("longitude")
        has_any_coordinate = lat is not None or lon is not None
        if has_any_coordinate and not valid_position(lat, lon):
            row.update(quality_status="suspect", quality_reason="Invalid station coordinates")
            rejected.append(row)
            continue
        if valid_position(lat, lon) and float(lat) == 0.0 and float(lon) == 0.0:
            row.update(quality_status="suspect", quality_reason="Station reported the default 0°, 0° position")
            rejected.append(row)
            continue

        row["distance_km"] = distance
        prepared.append(row)
        by_call.setdefault((row.get("callsign") or "").upper(), []).append(row)

    # Compute each callsign's coordinate support once. This is quadratic only
    # within a callsign, rather than repeating that work for every candidate.
    group_metrics = {}
    for callsign, group in by_call.items():
        positioned = [row for row in group if valid_position(row.get("latitude"), row.get("longitude"))]
        chord = 2 * math.sin((POSITION_SUPPORT_RADIUS_KM / 6371.0) / 2)
        buckets = defaultdict(list)
        vectors = {}
        for row in positioned:
            lat = math.radians(float(row["latitude"]))
            lon = math.radians(float(row["longitude"]))
            vector = (math.cos(lat) * math.cos(lon), math.cos(lat) * math.sin(lon), math.sin(lat))
            vectors[id(row)] = vector
            key = tuple(math.floor(component / chord) for component in vector)
            buckets[key].append(row)
        supports = {}
        for row in positioned:
            vector = vectors[id(row)]
            key = tuple(math.floor(component / chord) for component in vector)
            candidates = (
                other
                for dx in (-1, 0, 1) for dy in (-1, 0, 1) for dz in (-1, 0, 1)
                for other in buckets.get((key[0] + dx, key[1] + dy, key[2] + dz), ())
            )
            support = 0
            for other in candidates:
                if sum((a - b) ** 2 for a, b in zip(vector, vectors[id(other)])) <= chord ** 2:
                    support += 1
                    # The policy only distinguishes isolated from confirmed;
                    # counting a busy beacon hundreds of times adds no value.
                    if support >= 2:
                        break
            supports[id(row)] = support
        strongest = max(supports.values(), default=0)
        cluster_rows = [row for row in positioned if supports.get(id(row), 0) == strongest]
        group_metrics[callsign] = supports, strongest, cluster_rows

    accepted = []
    for row in prepared:
        callsign = (row.get("callsign") or "").upper()
        supports, strongest_cluster, cluster_rows = group_metrics.get(callsign, ({}, 0, []))
        has_position = valid_position(row.get("latitude"), row.get("longitude"))
        support = supports.get(id(row), 0)

        reason = ""
        if row["distance_km"] >= LONG_PATH_CONFIRMATION_KM and support < 2:
            reason = ("Long path has no confirming reception"
                      if has_position else "Long path has no stored coordinates to verify")
        # Pre-1.10 path_history rows have no stored coordinates. They can still
        # carry a valid distance, but cannot be compared with a newer position
        # cluster. Only run the geographic conflict check for positioned rows.
        elif has_position and strongest_cluster >= 2 and support < 2:
            if cluster_rows and min(
                _surface_distance_km(row["latitude"], row["longitude"],
                                     candidate["latitude"], candidate["longitude"])
                for candidate in cluster_rows
            ) > POSITION_CONFLICT_KM:
                reason = "Position conflicts with this station's repeated location"

        row["position_confirmations"] = support
        if reason:
            row.update(quality_status="suspect", quality_reason=reason)
            rejected.append(row)
        else:
            row.update(quality_status="confirmed" if support >= 2 else "plausible", quality_reason="")
            accepted.append(row)

    return accepted, rejected


def is_direct_path(path):
    for hop in (path or '').split(','):
        hop = hop.strip()
        if hop.endswith('*') and not hop[:-1].upper().startswith(('WIDE', 'RELAY', 'TRACE')):
            return False
    return True


def classify_station(station):
    station['is_direct'] = station.get('source') == 'rf' and is_direct_path(station.get('last_path'))
    return station
