"""IGate — bidirectional RF ↔ APRS-IS gateway."""

import logging
import time
from typing import Optional
from collections import OrderedDict

from server.config import Config

logger = logging.getLogger("propview.igate")


class IGate:
    """APRS Internet Gateway (IGate) logic."""

    def __init__(self, config: Config):
        self.config = config
        self.my_call = config.station.full_callsign

        self._gated_is_to_rf: OrderedDict[str, float] = OrderedDict()
        self._gate_dedupe_seconds = 30

        # Track stations heard on RF (for IS→RF gating decisions)
        self._rf_stations: dict[str, float] = {}  # callsign -> last_heard_time
        self._is_stations: dict[str, float] = {}  # callsign -> last_heard_time

        logger.info(
            f"IGate initialized: rf_to_is={config.igate.rf_to_is}, "
            f"is_to_rf={config.igate.is_to_rf}"
        )

    def note_rf_station(self, callsign: str):
        """Record that a station was heard on RF (for IS→RF routing)."""
        normalized = (callsign or "").strip().upper()
        if normalized:
            self._rf_stations[normalized] = time.time()

    def note_is_station(self, callsign: str):
        """Record that a station was heard via APRS-IS."""
        normalized = (callsign or "").strip().upper()
        if normalized:
            self._is_stations[normalized] = time.time()

    def should_gate_rf_to_is(
        self,
        raw_packet: str,
        from_call: str,
        can_tx_rf: bool = True,
    ) -> Optional[str]:
        """
        Determine if an RF packet should be gated to APRS-IS.
        Returns the packet string to send to APRS-IS, or None.
        """
        if not self.config.igate.rf_to_is:
            return None

        # Don't gate our own packets
        if from_call.upper() == self.my_call.upper():
            return None

        header, sep, info = raw_packet.partition(":")
        if not sep:
            return None

        # Don't gate packets from TCPIP/TCPXX or optional RF-only/no-gate paths.
        if self._header_contains_any(header, {"TCPIP", "TCPXX", "NOGATE", "RFONLY"}):
            return None

        packet_to_gate = raw_packet
        gate_info = info

        # Generic queries must not be gated.
        if gate_info.startswith("?"):
            return None

        # Third-party packets must be unwrapped before gating, unless the inner
        # header already shows Internet-originated traffic.
        if gate_info.startswith("}"):
            inner_packet = gate_info[1:]
            inner_header, inner_sep, inner_info = inner_packet.partition(":")
            if not inner_sep:
                return None
            if self._header_contains_any(inner_header, {"TCPIP", "TCPXX", "NOGATE", "RFONLY"}):
                return None
            if inner_info.startswith("?"):
                return None
            packet_to_gate = inner_packet

        gate_header, gate_sep, gate_info = packet_to_gate.partition(":")
        if not gate_sep:
            return None

        q_construct = "qAR" if can_tx_rf else "qAO"
        gated_packet = f"{gate_header},{q_construct},{self.my_call}:{gate_info}"

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
        now = time.time()

        # Only gate APRS messages (not positions, etc.)
        if not info or info[0] != ":":
            return None

        # Extract addressee from message
        if len(info) < 11:
            return None
        addressee = info[1:10].strip()
        sender_key = (from_call or "").strip().upper()

        # Check if addressee was recently heard on RF
        addressee_key = addressee.upper()
        if addressee_key not in self._rf_stations:
            return None

        # Check recency (only gate if heard within last hour)
        last_heard = self._rf_stations.get(addressee_key, 0)
        if now - last_heard > 3600:
            return None

        # The sender must not already look reachable via RF.
        if sender_key and now - self._rf_stations.get(sender_key, 0) <= 3600:
            return None

        # Suppress traffic that already carries Internet/no-gate markers.
        if self._header_contains_any(header, {"TCPXX", "NOGATE", "RFONLY"}):
            return None

        # If the recipient is also active on APRS-IS, don't relay back to RF.
        if addressee_key in self._is_stations and now - self._is_stations.get(addressee_key, 0) <= 3600:
            return None

        # Deduplicate
        key = self._packet_key(raw_packet)
        self._purge_cache(self._gated_is_to_rf)
        if key in self._gated_is_to_rf:
            return None
        self._gated_is_to_rf[key] = now

        logger.info(f"IGate IS→RF: {from_call} → {addressee}")
        return self.build_third_party_payload(raw_packet)

    def build_third_party_payload(self, raw_packet: str) -> Optional[str]:
        """Build APRS third-party payload for gating APRS-IS traffic to RF."""
        header, sep, info = raw_packet.partition(":")
        if not sep or ">" not in header:
            return None

        from_call, to_and_path = header.split(">", 1)
        to_call = to_and_path.split(",", 1)[0].strip()
        if not from_call.strip() or not to_call:
            return None

        # APRS-IS paths must be removed; the embedded third-party path is fixed.
        return f"}}{from_call.strip()}>{to_call},TCPIP,{self.my_call}*:{info}"

    @staticmethod
    def _header_contains_any(header: str, tokens: set[str]) -> bool:
        upper_tokens = [part.strip().upper() for part in header.split(",")]
        return any(
            part == token or part.startswith(f"{token}*")
            for part in upper_tokens
            for token in tokens
        )

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
