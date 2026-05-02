"""APRS packet parser — extracts position, type, and metadata from APRS info fields."""

import re
import math
import logging
from dataclasses import dataclass, field
from typing import Optional, Dict, Any

logger = logging.getLogger("propview.parser")


@dataclass
class APRSPacket:
    """Parsed APRS packet data."""
    raw: str = ""
    from_call: str = ""
    to_call: str = ""
    path: str = ""
    source: str = ""  # 'rf' or 'aprs_is'
    packet_type: str = ""  # position, message, status, weather, object, item, mic_e, telemetry
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    altitude: Optional[float] = None  # meters
    course: Optional[float] = None
    speed: Optional[float] = None  # km/h
    symbol_table: str = "/"
    symbol_code: str = "-"
    comment: str = ""
    timestamp: str = ""
    # Message fields
    addressee: str = ""
    message_text: str = ""
    message_id: str = ""
    # Weather
    weather: Dict[str, Any] = field(default_factory=dict)
    # Object/Item
    object_name: str = ""
    alive: bool = True

    @property
    def has_position(self) -> bool:
        return self.latitude is not None and self.longitude is not None


# ── Mic-E decoding tables ───────────────────────────────────────────

MIC_E_DEST_DIGITS = {
    "0": 0, "1": 1, "2": 2, "3": 3, "4": 4,
    "5": 5, "6": 6, "7": 7, "8": 8, "9": 9,
    "A": 0, "B": 1, "C": 2, "D": 3, "E": 4,
    "F": 5, "G": 6, "H": 7, "I": 8, "J": 9,
    "K": 0, "L": 1, "P": 0, "Q": 1, "R": 2,
    "S": 3, "T": 4, "U": 5, "V": 6, "W": 7,
    "X": 8, "Y": 9, "Z": 0,
}

MIC_E_NORTH_SOUTH = {
    "0": "S", "1": "S", "2": "S", "3": "S", "4": "S",
    "5": "S", "6": "S", "7": "S", "8": "S", "9": "S",
    "L": "S", "P": "N", "Q": "N", "R": "N", "S": "N",
    "T": "N", "U": "N", "V": "N", "W": "N", "X": "N",
    "Y": "N", "Z": "N",
    "A": "0", "B": "0", "C": "0", "D": "0", "E": "0",
    "F": "0", "G": "0", "H": "0", "I": "0", "J": "0",
    "K": "0",
}

MIC_E_LONG_OFFSET = {
    "0": 0, "1": 0, "2": 0, "3": 0, "4": 0,
    "5": 0, "6": 0, "7": 0, "8": 0, "9": 0,
    "A": 0, "B": 0, "C": 0, "D": 0, "E": 0,
    "F": 0, "G": 0, "H": 0, "I": 0, "J": 0,
    "K": 0, "L": 0,
    "P": 100, "Q": 100, "R": 100, "S": 100, "T": 100,
    "U": 100, "V": 100, "W": 100, "X": 100, "Y": 100, "Z": 100,
}

MIC_E_EAST_WEST = {
    "0": "E", "1": "E", "2": "E", "3": "E", "4": "E",
    "5": "E", "6": "E", "7": "E", "8": "E", "9": "E",
    "A": "E", "B": "E", "C": "E", "D": "E", "E": "E",
    "F": "E", "G": "E", "H": "E", "I": "E", "J": "E",
    "K": "E", "L": "E",
    "P": "W", "Q": "W", "R": "W", "S": "W", "T": "W",
    "U": "W", "V": "W", "W": "W", "X": "W", "Y": "W", "Z": "W",
}


def parse_packet(raw: str, source: str = "rf") -> APRSPacket:
    """Parse a raw APRS packet string into an APRSPacket."""
    pkt = APRSPacket(raw=raw, source=source)

    try:
        # Split header and info
        if ":" not in raw:
            return pkt

        header, info = raw.split(":", 1)

        # Parse header: FROM>TO,PATH
        if ">" not in header:
            return pkt

        from_part, rest = header.split(">", 1)
        pkt.from_call = from_part.strip()

        path_parts = rest.split(",")
        pkt.to_call = path_parts[0].strip()
        if len(path_parts) > 1:
            pkt.path = ",".join(path_parts[1:])

        if not info:
            return pkt

        # Third-party traffic embeds another APRS packet after the } DTI.
        # Parse the embedded packet for display, messaging, and position handling.
        if info[0] == "}":
            inner = parse_packet(info[1:], source=source)
            inner.raw = raw
            return inner

        # Determine packet type from data type identifier
        dti = info[0]

        if dti in ("!", "="):
            _parse_position(pkt, info[1:], with_messaging=(dti == "="))
            pkt.packet_type = "position"
        elif dti in ("/", "@"):
            _parse_position_with_timestamp(pkt, info[1:], with_messaging=(dti == "@"))
            pkt.packet_type = "position"
        elif dti == ":":
            _parse_message(pkt, info[1:])
            pkt.packet_type = "message"
        elif dti == ">":
            pkt.comment = info[1:]
            pkt.packet_type = "status"
        elif dti == ";":
            _parse_object(pkt, info[1:])
            pkt.packet_type = "object"
        elif dti == ")":
            _parse_item(pkt, info[1:])
            pkt.packet_type = "item"
        elif dti in ("`", "\x1c", "'"):
            _parse_mic_e(pkt, info)
            pkt.packet_type = "mic_e"
        elif dti == "_":
            pkt.packet_type = "weather"
        elif dti == "T":
            pkt.packet_type = "telemetry"
        elif dti == "#" or dti == "$":
            pkt.packet_type = "other"
        else:
            # Try to detect position in the info field anyway
            _try_parse_position(pkt, info)

    except Exception as e:
        logger.debug(f"Parse error for '{raw}': {e}")

    return pkt


def _parse_lat_lon(data: str):
    """Parse uncompressed lat/lon: DDMM.hhN/DDDMM.hhW returns (lat, lon, rest, sym_table, sym_code)."""
    if len(data) < 19:
        return None

    try:
        lat_str = data[0:8]  # DDMM.hhN
        sym_table = data[8]
        lon_str = data[9:18]  # DDDMM.hhW
        sym_code = data[18]
        rest = data[19:] if len(data) > 19 else ""

        # Parse latitude
        lat_deg = int(lat_str[0:2])
        lat_min = float(lat_str[2:7])
        lat = lat_deg + lat_min / 60.0
        if lat_str[7] in ("S", "s"):
            lat = -lat

        # Parse longitude
        lon_deg = int(lon_str[0:3])
        lon_min = float(lon_str[3:8])
        lon = lon_deg + lon_min / 60.0
        if lon_str[8] in ("W", "w"):
            lon = -lon

        return lat, lon, rest, sym_table, sym_code
    except (ValueError, IndexError):
        return None


def _is_uncompressed_position(data: str) -> bool:
    """Return True when data begins with an uncompressed APRS position."""
    return bool(re.match(r"^\d{4}\.\d{2}[NSns].\d{5}\.\d{2}[EWew]", data))


def _is_base91_position_chars(value: str) -> bool:
    return all(33 <= ord(ch) <= 123 for ch in value)


def _looks_like_compressed_position(data: str) -> bool:
    """Return True when data has the fixed compressed position shape."""
    if len(data) < 13 or _is_uncompressed_position(data):
        return False
    if not (33 <= ord(data[0]) <= 126):
        return False
    return _is_base91_position_chars(data[1:9])


def _parse_compressed_lat_lon(data: str):
    """Parse compressed position: /YYYYXXXX$cs... returns (lat, lon, rest, sym_table, sym_code)."""
    if len(data) < 13:
        return None

    try:
        if not _looks_like_compressed_position(data):
            return None

        sym_table = data[0]
        y1 = ord(data[1]) - 33
        y2 = ord(data[2]) - 33
        y3 = ord(data[3]) - 33
        y4 = ord(data[4]) - 33
        x1 = ord(data[5]) - 33
        x2 = ord(data[6]) - 33
        x3 = ord(data[7]) - 33
        x4 = ord(data[8]) - 33
        sym_code = data[9]

        lat_val = y1 * 91**3 + y2 * 91**2 + y3 * 91 + y4
        lon_val = x1 * 91**3 + x2 * 91**2 + x3 * 91 + x4

        lat = 90.0 - lat_val / 380926.0
        lon = -180.0 + lon_val / 190463.0

        rest = data[13:] if len(data) > 13 else ""
        return lat, lon, rest, sym_table, sym_code
    except (ValueError, IndexError):
        return None


def _parse_position(pkt: APRSPacket, info: str, with_messaging: bool = False):
    """Parse position without timestamp."""
    if not info:
        return

    # Try compressed first (symbol table/overlay char followed by base-91)
    if _looks_like_compressed_position(info):
        result = _parse_compressed_lat_lon(info)
        if result:
            pkt.latitude, pkt.longitude, rest, pkt.symbol_table, pkt.symbol_code = result
            pkt.comment = rest.strip()
            _extract_altitude(pkt)
            return

    # Try uncompressed
    result = _parse_lat_lon(info)
    if result:
        pkt.latitude, pkt.longitude, rest, pkt.symbol_table, pkt.symbol_code = result
        _extract_data_extension(pkt, rest)
        _extract_altitude(pkt)


def _parse_position_with_timestamp(pkt: APRSPacket, info: str, with_messaging: bool = False):
    """Parse position with timestamp (/ or @ prefix already consumed)."""
    if len(info) < 7:
        return

    pkt.timestamp = info[0:7]
    _parse_position(pkt, info[7:], with_messaging)


def _parse_message(pkt: APRSPacket, info: str):
    """Parse APRS message: addressee (9 chars padded) : message {id}."""
    if len(info) < 10 or ":" not in info:
        pkt.comment = info
        return

    pkt.addressee = info[0:9].strip()
    msg_part = info[10:]  # Skip the second ':'

    # Check for message ID
    if "{" in msg_part:
        parts = msg_part.rsplit("{", 1)
        pkt.message_text = parts[0]
        pkt.message_id = parts[1].rstrip("}")
    else:
        pkt.message_text = msg_part


def _parse_object(pkt: APRSPacket, info: str):
    """Parse object: name(9 chars)*DDMM.hhN/DDDMM.hhW..."""
    if len(info) < 10:
        return
    pkt.object_name = info[0:9].strip()
    pkt.alive = info[9] == "*"
    if len(info) > 10:
        _parse_position_with_timestamp(pkt, info[10:])


def _parse_item(pkt: APRSPacket, info: str):
    """Parse item: name!DDMM.hhN/DDDMM.hhW..."""
    match = re.match(r"(.+?)([!_])(.*)", info)
    if match:
        pkt.object_name = match.group(1).strip()
        pkt.alive = match.group(2) == "!"
        _parse_position(pkt, match.group(3))


def _parse_mic_e(pkt: APRSPacket, info: str):
    """Parse Mic-E encoded position from destination field and info field."""
    # Mic-E latitude is encoded in the destination address (pkt.to_call)
    dest = pkt.to_call.split("-")[0]  # Remove SSID
    if len(dest) < 6:
        dest = dest.ljust(6)

    try:
        # Extract latitude digits from destination
        lat_digits = ""
        ns = "N"
        lon_offset = 0
        ew = "E"

        for i in range(6):
            c = dest[i]
            if c in MIC_E_DEST_DIGITS:
                lat_digits += str(MIC_E_DEST_DIGITS[c])
            else:
                return

            # N/S from char 3 (index 3)
            if i == 3 and c in MIC_E_NORTH_SOUTH:
                ns_val = MIC_E_NORTH_SOUTH[c]
                if ns_val in ("N", "S"):
                    ns = ns_val

            # Longitude offset from char 4 (index 4)
            if i == 4 and c in MIC_E_LONG_OFFSET:
                lon_offset = MIC_E_LONG_OFFSET[c]

            # E/W from char 5 (index 5)
            if i == 5 and c in MIC_E_EAST_WEST:
                ew = MIC_E_EAST_WEST[c]

        # Parse latitude: first 2 digits = degrees, next 2 = minutes, last 2 = hundredths
        lat_deg = int(lat_digits[0:2])
        lat_min = int(lat_digits[2:4])
        lat_hundredths = int(lat_digits[4:6])
        lat = lat_deg + (lat_min + lat_hundredths / 100.0) / 60.0
        if ns == "S":
            lat = -lat

        # Parse longitude from info field
        # info[0] is the DTI (` or ')
        # info[1] = lon degrees
        # info[2] = lon minutes
        # info[3] = lon hundredths
        # info[4] = speed/course
        # info[5] = speed/course
        # info[6] = speed/course
        # info[7] = symbol code
        # info[8] = symbol table
        if len(info) < 9:
            return

        d28 = ord(info[1]) - 28
        m28 = ord(info[2]) - 28
        h28 = ord(info[3]) - 28

        # Apply longitude offset
        lon_deg = d28 + lon_offset
        if 180 <= lon_deg <= 189:
            lon_deg -= 80
        elif 190 <= lon_deg <= 199:
            lon_deg -= 190

        lon_min = m28
        if lon_min >= 60:
            lon_min -= 60

        lon = lon_deg + (lon_min + h28 / 100.0) / 60.0
        if ew == "W":
            lon = -lon

        pkt.latitude = lat
        pkt.longitude = lon

        # Symbol
        if len(info) >= 9:
            pkt.symbol_code = info[7]
            pkt.symbol_table = info[8]

        # Speed and course from bytes 4-6
        sp28 = ord(info[4]) - 28
        dc28 = ord(info[5]) - 28
        se28 = ord(info[6]) - 28

        speed = (sp28 * 10) + (dc28 // 10)
        if speed >= 800:
            speed -= 800
        pkt.speed = speed * 1.852  # knots to km/h

        course = ((dc28 % 10) * 100) + se28
        if course >= 400:
            course -= 400
        pkt.course = course

        # Comment after symbol
        if len(info) > 9:
            pkt.comment = info[9:].strip()

    except Exception as e:
        logger.debug(f"Mic-E parse error: {e}")


def _try_parse_position(pkt: APRSPacket, info: str):
    """Try to find a position in an unrecognized packet."""
    # Look for coordinate patterns
    match = re.search(r"(\d{4}\.\d{2}[NS])(.)(\d{5}\.\d{2}[EW])(.)", info)
    if match:
        try:
            lat_str = match.group(1)
            sym_table = match.group(2)
            lon_str = match.group(3)
            sym_code = match.group(4)

            lat_deg = int(lat_str[0:2])
            lat_min = float(lat_str[2:7])
            lat = lat_deg + lat_min / 60.0
            if lat_str[7] == "S":
                lat = -lat

            lon_deg = int(lon_str[0:3])
            lon_min = float(lon_str[3:8])
            lon = lon_deg + lon_min / 60.0
            if lon_str[8] == "W":
                lon = -lon

            pkt.latitude = lat
            pkt.longitude = lon
            pkt.symbol_table = sym_table
            pkt.symbol_code = sym_code
            pkt.packet_type = "position"
        except (ValueError, IndexError):
            pass


def _extract_altitude(pkt: APRSPacket):
    """Extract altitude from comment field if present (/A=NNNNNN)."""
    match = re.search(r"/A=(\d{6})", pkt.comment)
    if match:
        pkt.altitude = int(match.group(1)) * 0.3048  # feet to meters


def _extract_data_extension(pkt: APRSPacket, rest: str):
    """Extract APRS data extensions that this app can use."""
    if not rest:
        pkt.comment = ""
        return

    course_speed = re.match(r"^(\d{3})/(\d{3})(.*)$", rest, re.DOTALL)
    if course_speed:
        course = int(course_speed.group(1))
        speed_knots = int(course_speed.group(2))
        if 1 <= course <= 360:
            pkt.course = 360 if course == 360 else course
        elif course == 0:
            pkt.course = 0
        pkt.speed = speed_knots * 1.852
        pkt.comment = course_speed.group(3).strip()
        return

    pkt.comment = rest.strip()


def calculate_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate great-circle distance between two points in km using Haversine."""
    R = 6371.0  # Earth radius in km
    lat1_r = math.radians(lat1)
    lat2_r = math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)

    a = math.sin(dlat / 2) ** 2 + math.cos(lat1_r) * math.cos(lat2_r) * math.sin(dlon / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c


def calculate_bearing(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate initial bearing from point 1 to point 2 in degrees."""
    lat1_r = math.radians(lat1)
    lat2_r = math.radians(lat2)
    dlon_r = math.radians(lon2 - lon1)

    x = math.sin(dlon_r) * math.cos(lat2_r)
    y = math.cos(lat1_r) * math.sin(lat2_r) - math.sin(lat1_r) * math.cos(lat2_r) * math.cos(dlon_r)
    bearing = math.degrees(math.atan2(x, y))
    return (bearing + 360) % 360


def make_message_packet(addressee: str, message_text: str, message_id: str = "") -> str:
    """Create an APRS message info field.

    Format: :ADDRESSEE :message{id}
    Addressee is padded to 9 characters.
    """
    padded = addressee.ljust(9)[:9]
    info = f":{padded}:{message_text}"
    if message_id:
        info += f"{{{message_id}}}"
    return info


def make_ack_packet(addressee: str, message_id: str) -> str:
    """Create an APRS message acknowledgement info field.

    Format: :ADDRESSEE :ack{id}
    """
    padded = addressee.ljust(9)[:9]
    return f":{padded}:ack{message_id}"


def make_rej_packet(addressee: str, message_id: str) -> str:
    """Create an APRS message rejection info field.

    Format: :ADDRESSEE :rej{id}
    """
    padded = addressee.ljust(9)[:9]
    return f":{padded}:rej{message_id}"


def make_position_packet(
    callsign: str,
    lat: float,
    lon: float,
    symbol_table: str = "/",
    symbol_code: str = "#",
    comment: str = "",
) -> str:
    """Create an uncompressed APRS position packet info field."""
    # Convert decimal degrees to APRS format
    lat_dir = "N" if lat >= 0 else "S"
    lat = abs(lat)
    lat_deg = int(lat)
    lat_min = (lat - lat_deg) * 60

    lon_dir = "E" if lon >= 0 else "W"
    lon = abs(lon)
    lon_deg = int(lon)
    lon_min = (lon - lon_deg) * 60

    return (
        f"={lat_deg:02d}{lat_min:05.2f}{lat_dir}"
        f"{symbol_table}"
        f"{lon_deg:03d}{lon_min:05.2f}{lon_dir}"
        f"{symbol_code}"
        f"{comment}"
    )


def build_station_beacon_comment(
    comment: str = "",
    phg: str = "",
    equipment: str = "",
) -> str:
    """Build a position comment with optional PHG and equipment text."""
    parts = []
    phg_value = (phg or "").strip().upper()
    equipment_text = (equipment or "").strip()
    comment_text = (comment or "").strip()

    if phg_value:
        parts.append(f"PHG{phg_value}")
    if equipment_text:
        parts.append(equipment_text)
    if comment_text:
        parts.append(comment_text)

    return " ".join(parts)
