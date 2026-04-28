"""AX.25 frame encoding and decoding for APRS UI frames."""

import logging
from dataclasses import dataclass, field
from typing import List, Optional

logger = logging.getLogger("propview.ax25")

# AX.25 constants
AX25_FLAG = 0x7E
AX25_UI_CONTROL = 0x03
AX25_PID_NO_LAYER3 = 0xF0

# Address field constants
ADDR_LEN = 7  # Each address is 7 bytes (6 callsign + 1 SSID)
SSID_MASK = 0x1E  # bits 1-4
SSID_HBIT = 0x80  # H-bit / has-been-digipeated bit
SSID_LAST = 0x01  # End-of-address marker


@dataclass
class AX25Address:
    callsign: str = ""
    ssid: int = 0
    h_bit: bool = False  # Has-been-repeated for digi path

    @property
    def full_call(self) -> str:
        if self.ssid > 0:
            return f"{self.callsign}-{self.ssid}"
        return self.callsign

    @staticmethod
    def from_string(s: str) -> "AX25Address":
        """Parse 'CALL-SSID' or 'CALL' string. An asterisk suffix marks h_bit."""
        h_bit = False
        if s.endswith("*"):
            h_bit = True
            s = s[:-1]
        parts = s.split("-", 1)
        callsign = parts[0].upper().strip()
        ssid = int(parts[1]) if len(parts) > 1 else 0
        return AX25Address(callsign=callsign, ssid=ssid, h_bit=h_bit)

    def encode(self, is_last: bool = False) -> bytes:
        """Encode address to 7-byte AX.25 format."""
        # Pad callsign to 6 chars, shift left by 1
        call = self.callsign.ljust(6)[:6]
        encoded = bytes([ord(c) << 1 for c in call])

        # SSID byte: 0b0HSSSSXE
        # H = h_bit, SSSS = SSID, X = reserved (1), E = extension bit (last address)
        ssid_byte = 0x60  # Reserved bits set
        ssid_byte |= (self.ssid & 0x0F) << 1
        if self.h_bit:
            ssid_byte |= SSID_HBIT
        if is_last:
            ssid_byte |= SSID_LAST

        return encoded + bytes([ssid_byte])

    @staticmethod
    def decode(data: bytes) -> "AX25Address":
        """Decode 7-byte AX.25 address."""
        if len(data) < 7:
            return AX25Address()

        callsign = "".join(chr(b >> 1) for b in data[:6]).strip()
        ssid_byte = data[6]
        ssid = (ssid_byte & SSID_MASK) >> 1
        h_bit = bool(ssid_byte & SSID_HBIT)

        return AX25Address(callsign=callsign, ssid=ssid, h_bit=h_bit)


@dataclass
class AX25Frame:
    destination: AX25Address = field(default_factory=AX25Address)
    source: AX25Address = field(default_factory=AX25Address)
    digipeaters: List[AX25Address] = field(default_factory=list)
    control: int = AX25_UI_CONTROL
    pid: int = AX25_PID_NO_LAYER3
    info: bytes = b""

    @property
    def from_call(self) -> str:
        return self.source.full_call

    @property
    def to_call(self) -> str:
        return self.destination.full_call

    @property
    def path_str(self) -> str:
        parts = []
        for d in self.digipeaters:
            s = d.full_call
            if d.h_bit:
                s += "*"
            parts.append(s)
        return ",".join(parts)

    @property
    def info_str(self) -> str:
        try:
            return self.info.decode("latin-1")
        except Exception:
            return ""

    def to_aprs_string(self) -> str:
        """Convert to standard APRS string format: SRC>DST,PATH:info"""
        path = self.path_str
        header = f"{self.from_call}>{self.to_call}"
        if path:
            header += f",{path}"
        return f"{header}:{self.info_str}"

    def encode(self) -> bytes:
        """Encode to raw AX.25 frame bytes (without flags and FCS)."""
        # Determine which address is last
        all_addrs = [self.destination, self.source] + self.digipeaters
        data = b""
        for i, addr in enumerate(all_addrs):
            is_last = i == len(all_addrs) - 1
            data += addr.encode(is_last=is_last)

        data += bytes([self.control, self.pid])
        data += self.info
        return data

    @staticmethod
    def decode(data: bytes) -> Optional["AX25Frame"]:
        """Decode raw AX.25 frame bytes."""
        if len(data) < 16:  # Minimum: 2 addresses + control + PID + 1 info
            return None

        try:
            frame = AX25Frame()
            frame.destination = AX25Address.decode(data[0:7])
            frame.source = AX25Address.decode(data[7:14])

            pos = 14
            # Check if source address is last
            if not (data[13] & SSID_LAST):
                # Read digipeater addresses
                while pos + 7 <= len(data):
                    digi = AX25Address.decode(data[pos : pos + 7])
                    frame.digipeaters.append(digi)
                    is_last = bool(data[pos + 6] & SSID_LAST)
                    pos += 7
                    if is_last:
                        break

            if pos + 2 > len(data):
                return None

            frame.control = data[pos]
            frame.pid = data[pos + 1]
            frame.info = data[pos + 2 :]
            return frame

        except Exception as e:
            logger.debug(f"Failed to decode AX.25 frame: {e}")
            return None

    @staticmethod
    def from_aprs_string(raw: str) -> Optional["AX25Frame"]:
        """Parse APRS string format: SRC>DST,PATH:info into AX25Frame."""
        try:
            header, info = raw.split(":", 1)
            src_rest = header.split(">", 1)
            if len(src_rest) != 2:
                return None

            source_str = src_rest[0]
            dst_path = src_rest[1].split(",")
            dest_str = dst_path[0]
            path_strs = dst_path[1:] if len(dst_path) > 1 else []

            frame = AX25Frame()
            frame.source = AX25Address.from_string(source_str)
            frame.destination = AX25Address.from_string(dest_str)
            frame.digipeaters = [AX25Address.from_string(p) for p in path_strs]
            frame.info = info.encode("latin-1")
            return frame

        except Exception as e:
            logger.debug(f"Failed to parse APRS string '{raw}': {e}")
            return None
