"""Digipeater — WIDEn-N compliant packet repeater."""

import asyncio
import hashlib
import logging
import time
from typing import Optional, List, Set
from collections import OrderedDict

from server.config import Config
from server.ax25 import AX25Frame, AX25Address

logger = logging.getLogger("propview.digipeater")


class DedupeCache:
    """LRU cache for duplicate packet detection."""

    def __init__(self, max_age: int = 30):
        self.max_age = max_age
        self._cache: OrderedDict[str, float] = OrderedDict()

    def _make_key(self, frame: AX25Frame) -> str:
        """Create a dedup key from source + destination + info."""
        key_data = f"{frame.from_call}>{frame.to_call}:{frame.info_str}"
        return hashlib.md5(key_data.encode()).hexdigest()

    def is_duplicate(self, frame: AX25Frame) -> bool:
        """Check if frame is a duplicate within the dedupe window."""
        self._purge()
        key = self._make_key(frame)
        if key in self._cache:
            return True
        self._cache[key] = time.time()
        return False

    def _purge(self):
        """Remove expired entries."""
        cutoff = time.time() - self.max_age
        while self._cache:
            key, ts = next(iter(self._cache.items()))
            if ts < cutoff:
                self._cache.pop(key)
            else:
                break


class Digipeater:
    """APRS WIDEn-N digipeater logic."""

    def __init__(self, config: Config):
        self.config = config
        self.my_call = config.station.full_callsign
        self.aliases: Set[str] = set()
        self.dedupe = DedupeCache(config.digipeater.dedupe_interval)

        # Parse aliases into a set for matching
        for alias in config.digipeater.aliases:
            self.aliases.add(alias.upper())

        logger.info(
            f"Digipeater initialized: call={self.my_call}, "
            f"aliases={self.aliases}, dedupe={config.digipeater.dedupe_interval}s"
        )

    def should_digipeat(self, frame: AX25Frame) -> Optional[AX25Frame]:
        """
        Determine if we should digipeat this frame.
        Returns a new frame to transmit if yes, None if no.
        """
        if not self.config.digipeater.enabled:
            return None

        # Don't digipeat our own packets
        if frame.from_call.upper() == self.my_call.upper():
            return None

        # Check for duplicates
        if self.dedupe.is_duplicate(frame):
            logger.debug(f"Duplicate suppressed: {frame.from_call}")
            return None

        # Find the first unused digipeater address we should respond to
        for i, digi in enumerate(frame.digipeaters):
            if digi.h_bit:
                continue  # Already digipeated

            digi_call = digi.full_call.upper()

            # Direct address to us
            if digi_call == self.my_call.upper():
                return self._mark_digipeated(frame, i)

            # WIDEn-N handling
            if self._is_wide_alias(digi_call):
                return self._handle_wide(frame, i, digi)

            # Check against configured aliases
            if digi_call in self.aliases:
                return self._mark_digipeated(frame, i)

            # If we encounter an unused, non-matching digi address, stop
            break

        return None

    def _is_wide_alias(self, call: str) -> bool:
        """Check if call matches WIDEn-N pattern."""
        import re
        return bool(re.match(r"^WIDE[1-7]-[0-7]$", call))

    def _handle_wide(self, frame: AX25Frame, idx: int, digi: AX25Address) -> Optional[AX25Frame]:
        """Handle WIDEn-N digipeating with proper decrement."""
        # Parse n and N
        call = digi.full_call.upper()
        try:
            n = int(call[4])  # The request level
            remaining = digi.ssid  # Current remaining count
        except (IndexError, ValueError):
            return None

        if remaining <= 0:
            return None

        # Apply hop limit (don't digipeat WIDE7-7 etc, limit to 3 hops typically)
        if n > 3:
            logger.debug(f"Ignoring excessive WIDE path: {call}")
            return None

        # Create new frame
        new_frame = AX25Frame()
        new_frame.destination = frame.destination
        new_frame.source = frame.source
        new_frame.control = frame.control
        new_frame.pid = frame.pid
        new_frame.info = frame.info

        # Rebuild digipeater path
        new_digis = list(frame.digipeaters[:idx])

        # Insert our callsign as used
        my_addr = AX25Address.from_string(self.my_call)
        my_addr.h_bit = True
        new_digis.append(my_addr)

        if remaining > 1:
            # Decrement and keep
            new_wide = AX25Address(callsign=f"WIDE{n}", ssid=remaining - 1, h_bit=False)
            new_digis.append(new_wide)
        else:
            # Last hop — mark as used
            used_wide = AX25Address(callsign=f"WIDE{n}", ssid=0, h_bit=True)
            new_digis.append(used_wide)

        # Add remaining path elements
        new_digis.extend(frame.digipeaters[idx + 1 :])

        new_frame.digipeaters = new_digis

        logger.info(f"Digipeating: {frame.from_call} via {call} → inserted {self.my_call}")
        return new_frame

    def _mark_digipeated(self, frame: AX25Frame, idx: int) -> AX25Frame:
        """Mark a specific digi address as used and return new frame."""
        new_frame = AX25Frame()
        new_frame.destination = frame.destination
        new_frame.source = frame.source
        new_frame.control = frame.control
        new_frame.pid = frame.pid
        new_frame.info = frame.info

        new_digis = []
        for i, d in enumerate(frame.digipeaters):
            if i == idx:
                # Replace with our callsign, marked as used
                my_addr = AX25Address.from_string(self.my_call)
                my_addr.h_bit = True
                new_digis.append(my_addr)
            else:
                new_digis.append(d)

        new_frame.digipeaters = new_digis
        logger.info(f"Digipeating: {frame.from_call} (direct address)")
        return new_frame
