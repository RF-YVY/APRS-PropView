"""IGate — bidirectional RF ↔ APRS-IS gateway."""

import asyncio
import logging
import time
import re
from typing import Optional, Set
from collections import OrderedDict

from server.config import Config

logger = logging.getLogger("propview.igate")


class IGate:
    """APRS Internet Gateway (IGate) logic."""

    def __init__(self, config: Config):
        self.config = config
        self.my_call = config.station.full_callsign

        # Track recently gated packets to avoid loops
        self._gated_rf_to_is: OrderedDict[str, float] = OrderedDict()
        self._gated_is_to_rf: OrderedDict[str, float] = OrderedDict()
        self._gate_dedupe_seconds = 30

        # Track stations heard on RF (for IS→RF gating decisions)
        self._rf_stations: dict[str, float] = {}  # callsign -> last_heard_time

        logger.info(
            f"IGate initialized: rf_to_is={config.igate.rf_to_is}, "
            f"is_to_rf={config.igate.is_to_rf}"
        )

    def note_rf_station(self, callsign: str):
        """Record that a station was heard on RF (for IS→RF routing)."""
        self._rf_stations[callsign] = time.time()

    def should_gate_rf_to_is(self, raw_packet: str, from_call: str) -> Optional[str]:
        """
        Determine if an RF packet should be gated to APRS-IS.
        Returns the packet string to send to APRS-IS, or None.
        """
        if not self.config.igate.rf_to_is:
            return None

        # Don't gate our own packets
        if from_call.upper() == self.my_call.upper():
            return None

        # Don't gate packets from TCPIP (already on IS)
        if "TCPIP" in raw_packet.upper() or "TCPXX" in raw_packet.upper():
            return None

        # Don't gate generic query/response packets
        if ":?" in raw_packet:
            return None

        # Deduplicate
        key = self._packet_key(raw_packet)
        now = time.time()
        self._purge_cache(self._gated_rf_to_is)
        if key in self._gated_rf_to_is:
            return None
        self._gated_rf_to_is[key] = now

        # Build the APRS-IS packet with q-construct
        # Format: FROM>TO,PATH,qAR,IGATECALL:info
        if ":" not in raw_packet:
            return None

        header, info = raw_packet.split(":", 1)

        # Add qAR construct (heard directly on RF by this IGate)
        gated_packet = f"{header},qAR,{self.my_call}:{info}"

        logger.info(f"IGate RF→IS: {from_call}")
        return gated_packet

    def should_gate_is_to_rf(
        self, raw_packet: str, from_call: str, to_call: str = ""
    ) -> Optional[str]:
        """
        Determine if an APRS-IS packet should be gated to RF.
        Returns the info field to transmit, or None.
        """
        if not self.config.igate.is_to_rf:
            return None

        # Only gate messages addressed to stations heard on RF
        if ":" not in raw_packet:
            return None

        header, info = raw_packet.split(":", 1)

        # Only gate APRS messages (not positions, etc.)
        if not info or info[0] != ":":
            return None

        # Extract addressee from message
        if len(info) < 11:
            return None
        addressee = info[1:10].strip()

        # Check if addressee was recently heard on RF
        if addressee.upper() not in {k.upper() for k in self._rf_stations}:
            return None

        # Check recency (only gate if heard within last hour)
        last_heard = self._rf_stations.get(addressee, 0)
        if time.time() - last_heard > 3600:
            return None

        # Deduplicate
        key = self._packet_key(raw_packet)
        now = time.time()
        self._purge_cache(self._gated_is_to_rf)
        if key in self._gated_is_to_rf:
            return None
        self._gated_is_to_rf[key] = now

        logger.info(f"IGate IS→RF: {from_call} → {addressee}")
        return info

    def _packet_key(self, raw: str) -> str:
        """Create a dedup key from a raw packet."""
        # Strip path variations to match same content
        if ":" in raw:
            parts = raw.split(":", 1)
            header = parts[0]
            # Extract just source and info
            src = header.split(">")[0] if ">" in header else header
            return f"{src}:{parts[1]}"
        return raw

    def _purge_cache(self, cache: OrderedDict):
        """Remove expired entries from a dedup cache."""
        cutoff = time.time() - self._gate_dedupe_seconds
        while cache:
            key, ts = next(iter(cache.items()))
            if ts < cutoff:
                cache.pop(key)
            else:
                break
