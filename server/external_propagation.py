"""Optional, rate-limited PSK Reporter context for the local station."""

import asyncio
import logging
import math
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter
from typing import Any, Callable, Dict, List, Optional

from server.station_tracker import StationTracker

logger = logging.getLogger("propview.external_propagation")
QUERY_URL = "https://retrieve.pskreporter.info/query"


def _distance_km(a, b) -> float:
    lat1, lon1 = map(math.radians, a)
    lat2, lon2 = map(math.radians, b)
    dlat, dlon = lat2 - lat1, lon2 - lon1
    value = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 6371.0 * 2 * math.atan2(math.sqrt(value), math.sqrt(1 - value))


def _band(frequency: int) -> str:
    mhz = frequency / 1_000_000
    for low, high, label in (
        (50, 54, "6 m"), (70, 71, "4 m"), (144, 148, "2 m"),
        (219, 225, "1.25 m"), (420, 450, "70 cm"), (902, 928, "33 cm"),
        (1240, 1300, "23 cm"),
    ):
        if low <= mhz <= high:
            return label
    return f"{mhz:g} MHz"


class PskReporterManager:
    """Retrieve only station-specific VHF/UHF reports, no more than every five minutes."""

    def __init__(self, config, ws_manager=None, fetch_xml: Optional[Callable[[str], bytes]] = None):
        self.config = config
        self.ws_manager = ws_manager
        self._fetch_xml = fetch_xml or self._download_xml
        self._snapshot: Dict[str, Any] = {}
        self._last_fetch = 0.0
        self._last_success = 0.0
        self._last_error = ""

    @property
    def enabled(self) -> bool:
        callsign = str(getattr(self.config.station, "callsign", "") or "").strip().upper()
        return bool(getattr(self.config.propagation, "psk_reporter_enabled", False) and callsign and callsign != "N0CALL")

    @staticmethod
    def _download_xml(url: str) -> bytes:
        request = urllib.request.Request(url, headers={"User-Agent": "APRSPropView/1.0", "Accept-Encoding": "identity"})
        with urllib.request.urlopen(request, timeout=25) as response:
            payload = response.read(2_000_001)
            if len(payload) > 2_000_000:
                raise ValueError("PSK Reporter response exceeded 2 MB")
            return payload

    def _url(self) -> str:
        callsign = str(self.config.station.callsign).strip().upper().split("-", 1)[0]
        minutes = max(5, min(360, int(getattr(self.config.propagation, "psk_reporter_window_minutes", 30) or 30)))
        query = urllib.parse.urlencode({
            "callsign": callsign,
            "flowStartSeconds": -(minutes * 60),
            "frange": "50000000-1500000000",
            "rptlimit": 100,
            "rronly": 1,
            "noactive": 1,
        })
        return f"{QUERY_URL}?{query}"

    @staticmethod
    def _parse(payload: bytes, own_callsign: str) -> List[Dict[str, Any]]:
        root = ET.fromstring(payload)
        own_base = own_callsign.upper().split("-", 1)[0]
        reports = []
        for node in root.iter("receptionReport"):
            attrs = node.attrib
            sender = str(attrs.get("senderCallsign", "")).upper()
            receiver = str(attrs.get("receiverCallsign", "")).upper()
            if own_base not in {sender.split("-", 1)[0], receiver.split("-", 1)[0]}:
                continue
            try:
                frequency = int(attrs.get("frequency", 0) or 0)
                observed_at = int(attrs.get("flowStartSeconds", 0) or 0)
            except (TypeError, ValueError):
                continue
            sender_pos = StationTracker.maidenhead_to_lat_lon(attrs.get("senderLocator", ""))
            receiver_pos = StationTracker.maidenhead_to_lat_lon(attrs.get("receiverLocator", ""))
            distance = round(_distance_km(sender_pos, receiver_pos), 1) if sender_pos and receiver_pos else None
            reports.append({
                "sender": sender,
                "receiver": receiver,
                "sender_grid": attrs.get("senderLocator", ""),
                "receiver_grid": attrs.get("receiverLocator", ""),
                "frequency": frequency,
                "band": _band(frequency),
                "mode": attrs.get("mode", "") or "Unknown",
                "observed_at": observed_at,
                "distance_km": distance,
                "direction": "outbound" if sender.split("-", 1)[0] == own_base else "inbound",
            })
        return sorted(reports, key=lambda item: item["observed_at"], reverse=True)

    async def poll_once(self):
        if not self.enabled:
            self._snapshot = {}
            return
        self._last_fetch = time.time()
        try:
            payload = await asyncio.to_thread(self._fetch_xml, self._url())
            reports = self._parse(payload, self.config.station.callsign)
            bands = Counter(item["band"] for item in reports)
            modes = Counter(item["mode"] for item in reports)
            distances = [item["distance_km"] for item in reports if item["distance_km"] is not None]
            peers = {
                item["receiver"] if item["direction"] == "outbound" else item["sender"]
                for item in reports
            }
            self._snapshot = {
                "enabled": True,
                "report_count": len(reports),
                "unique_peers": len(peers),
                "max_distance_km": max(distances) if distances else None,
                "bands": dict(bands.most_common()),
                "modes": dict(modes.most_common(5)),
                "reports": reports[:25],
                "source": "PSK Reporter",
                "note": "Independent digital-mode reception reports; supporting context, not APRS RF evidence.",
            }
            self._last_success = time.time()
            self._last_error = ""
            if self.ws_manager:
                await self.ws_manager.broadcast({"type": "external_propagation", "data": self.snapshot()})
        except Exception as exc:
            self._last_error = str(exc)
            logger.warning("PSK Reporter update failed: %s", exc)

    def snapshot(self) -> Dict[str, Any]:
        age = time.time() - self._last_success if self._last_success else None
        return {
            "enabled": self.enabled,
            **self._snapshot,
            "updated_at": self._last_success or None,
            "age_seconds": round(age) if age is not None else None,
            "stale": age is None or age > 900,
            "last_error": self._last_error,
        }

    async def run(self):
        while True:
            try:
                if self.enabled:
                    await self.poll_once()
                    await asyncio.sleep(300)
                else:
                    await asyncio.sleep(30)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("PSK Reporter loop failed: %s", exc)
                await asyncio.sleep(60)
