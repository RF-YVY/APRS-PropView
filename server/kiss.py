"""KISS and legacy TNC protocol handlers for RF connections."""

import asyncio
import struct
import logging
from typing import Callable, Optional, Awaitable

logger = logging.getLogger("propview.kiss")

# KISS special bytes
FEND = 0xC0
FESC = 0xDB
TFEND = 0xDC
TFESC = 0xDD

# KISS commands
CMD_DATA = 0x00
CMD_TXDELAY = 0x01
CMD_P = 0x02
CMD_SLOTTIME = 0x03
CMD_TXTAIL = 0x04
CMD_FULLDUPLEX = 0x05
CMD_RETURN = 0xFF

FLOW_CONTROL_OPTIONS = {"none", "xonxoff", "rtscts", "dsrdtr"}


def normalize_flow_control(value: str) -> str:
    flow = (value or "none").strip().lower()
    return flow if flow in FLOW_CONTROL_OPTIONS else "none"


def serial_flow_kwargs(flow_control: str) -> dict:
    flow = normalize_flow_control(flow_control)
    return {
        "xonxoff": flow == "xonxoff",
        "rtscts": flow == "rtscts",
        "dsrdtr": flow == "dsrdtr",
    }


def profile_init_commands(profile: str, callsign: str = "N0CALL", mode: str = "kiss") -> list[str]:
    """Return command-mode startup commands for common TNC profiles."""
    profile = (profile or "none").strip().lower()
    mode = (mode or "kiss").strip().lower()

    if profile in {"kenwood_thd7", "kenwood_tmd700", "generic_tnc2_kiss"}:
        if mode == "tnc2_monitor":
            return ["\x03", "MYCALL {callsign}", "HB 1200", "MON ON", "MCOM OFF", "MCON OFF"]
        return ["\x03", "MYCALL {callsign}", "HB 1200", "KISS ON", "RESTART"]
    if profile == "kenwood_thd72":
        if mode == "tnc2_monitor":
            return ["\r", "MYCALL {callsign}", "HB 1200", "MON ON", "MCOM OFF", "MCON OFF"]
        return ["\r", "MYCALL {callsign}", "HB 1200", "KISS ON", "RESTART"]

    return []


def render_init_commands(profile: str, custom_commands: str, callsign: str = "N0CALL", mode: str = "kiss") -> list[str]:
    """Merge profile and custom commands, expanding simple placeholders."""
    commands = profile_init_commands(profile, callsign, mode)
    commands.extend(
        line.strip()
        for line in (custom_commands or "").splitlines()
        if line.strip()
    )
    call = (callsign or "N0CALL").strip().upper()
    return [cmd.replace("{callsign}", call) for cmd in commands]


def kiss_escape(data: bytes) -> bytes:
    """Escape special bytes in KISS data."""
    result = bytearray()
    for b in data:
        if b == FEND:
            result.extend([FESC, TFEND])
        elif b == FESC:
            result.extend([FESC, TFESC])
        else:
            result.append(b)
    return bytes(result)


def kiss_unescape(data: bytes) -> bytes:
    """Unescape KISS data."""
    result = bytearray()
    i = 0
    while i < len(data):
        if data[i] == FESC and i + 1 < len(data):
            if data[i + 1] == TFEND:
                result.append(FEND)
            elif data[i + 1] == TFESC:
                result.append(FESC)
            else:
                result.append(data[i + 1])
            i += 2
        else:
            result.append(data[i])
            i += 1
    return bytes(result)


def make_kiss_frame(ax25_data: bytes, port: int = 0) -> bytes:
    """Wrap AX.25 data in a KISS frame."""
    cmd = (port << 4) | CMD_DATA
    return bytes([FEND, cmd]) + kiss_escape(ax25_data) + bytes([FEND])


class KISSFrameParser:
    """Accumulates bytes and extracts complete KISS frames."""

    def __init__(self):
        self.buffer = bytearray()
        self.in_frame = False
        self.text_buffer = bytearray()

    def feed(self, data: bytes) -> list:
        """Feed raw bytes and return list of extracted KISS data frames."""
        frames, _text_lines = self.feed_with_text(data)
        return frames

    def feed_with_text(self, data: bytes) -> tuple[list, list[str]]:
        """Feed raw bytes and return KISS frames plus out-of-frame text lines."""
        frames = []
        text_lines = []
        for b in data:
            if b == FEND:
                if self.text_buffer:
                    line = self.text_buffer.decode("ascii", errors="ignore").strip()
                    if line:
                        text_lines.append(line)
                    self.text_buffer.clear()
                if self.in_frame and len(self.buffer) > 0:
                    # End of frame
                    frame_data = kiss_unescape(bytes(self.buffer))
                    if len(frame_data) > 1:
                        cmd = frame_data[0]
                        if (cmd & 0x0F) == CMD_DATA:
                            frames.append(frame_data[1:])
                    self.buffer.clear()
                self.in_frame = True
                self.buffer.clear()
            elif self.in_frame:
                self.buffer.append(b)
            elif b in (10, 13):
                line = self.text_buffer.decode("ascii", errors="ignore").strip()
                if line:
                    text_lines.append(line)
                self.text_buffer.clear()
            elif 32 <= b <= 126:
                self.text_buffer.append(b)
                if len(self.text_buffer) > 120:
                    self.text_buffer.clear()
            elif self.text_buffer:
                self.text_buffer.clear()
        return frames, text_lines


class KISSSerialClient:
    """KISS TNC connection over serial port."""

    can_transmit = True

    def __init__(
        self,
        port: str,
        baudrate: int,
        on_frame: Callable,
        on_text_line: Optional[Callable] = None,
        flow_control: str = "none",
        init_profile: str = "none",
        init_commands: str = "",
        callsign: str = "N0CALL",
        name: str = "",
    ):
        self.port = port
        self.baudrate = baudrate
        self.on_frame = on_frame
        self.on_text_line = on_text_line
        self.flow_control = normalize_flow_control(flow_control)
        self.init_profile = init_profile
        self.init_commands = init_commands
        self.callsign = callsign
        self.writer: Optional[asyncio.StreamWriter] = None
        self.reader: Optional[asyncio.StreamReader] = None
        self.parser = KISSFrameParser()
        self.connected = False
        self._name = name or f"KISS-Serial({port})"

    @property
    def name(self) -> str:
        return self._name

    async def connect(self):
        """Connect to serial KISS TNC with auto-reconnect."""
        while True:
            try:
                import serial_asyncio

                self.reader, self.writer = await serial_asyncio.open_serial_connection(
                    url=self.port,
                    baudrate=self.baudrate,
                    bytesize=8,
                    parity="N",
                    stopbits=1,
                    **serial_flow_kwargs(self.flow_control),
                )
                self.connected = True
                logger.info(f"{self._name}: Connected")
                await self._run_init_commands()
                await self._read_loop()
            except ImportError:
                logger.error("pyserial-asyncio is required for serial KISS. Install with: pip install pyserial-asyncio")
                return
            except Exception as e:
                logger.error(f"{self._name}: Connection failed: {e}")
                self.connected = False
                await asyncio.sleep(5)

    async def _read_loop(self):
        """Read data from serial port and extract KISS frames."""
        try:
            while True:
                data = await self.reader.read(1024)
                if not data:
                    break
                frames, text_lines = self.parser.feed_with_text(data)
                for line in text_lines:
                    if not line.startswith("$"):
                        continue
                    try:
                        if self.on_text_line:
                            await self.on_text_line(line, self)
                    except Exception as e:
                        logger.error(f"{self._name}: Text line handler error: {e}")
                for frame in frames:
                    try:
                        await self.on_frame(frame, self)
                    except Exception as e:
                        logger.error(f"{self._name}: Frame handler error: {e}")
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"{self._name}: Read error: {e}")
        finally:
            self.connected = False
            logger.info(f"{self._name}: Disconnected")

    async def send(self, ax25_data: bytes):
        """Send an AX.25 frame via KISS."""
        if self.writer and self.connected:
            frame = make_kiss_frame(ax25_data)
            self.writer.write(frame)
            await self.writer.drain()
            logger.debug(f"{self._name}: Sent {len(ax25_data)} bytes")

    async def _run_init_commands(self):
        commands = render_init_commands(self.init_profile, self.init_commands, self.callsign, "kiss")
        if not commands or not self.writer:
            return

        logger.info(f"{self._name}: Running {len(commands)} TNC init command(s)")
        for command in commands:
            payload = command.encode("ascii", errors="ignore")
            if payload == b"\\x03":
                payload = b"\x03"
            if not payload.endswith(b"\r"):
                payload += b"\r"
            self.writer.write(payload)
            await self.writer.drain()
            await asyncio.sleep(0.35)

    async def close(self):
        if self.writer:
            self.writer.close()
            self.connected = False


class KISSTCPClient:
    """KISS TNC connection over TCP."""

    can_transmit = True

    def __init__(self, host: str, port: int, on_frame: Callable, name: str = ""):
        self.host = host
        self.port = port
        self.on_frame = on_frame
        self.writer: Optional[asyncio.StreamWriter] = None
        self.reader: Optional[asyncio.StreamReader] = None
        self.parser = KISSFrameParser()
        self.connected = False
        self._name = name or f"KISS-TCP({host}:{port})"
        self._reconnect_delay = 5

    @property
    def name(self) -> str:
        return self._name

    async def connect(self):
        """Connect to TCP KISS TNC with auto-reconnect and exponential backoff."""
        delay = self._reconnect_delay
        while True:
            try:
                self.reader, self.writer = await asyncio.open_connection(
                    self.host, self.port
                )
                self.connected = True
                delay = self._reconnect_delay  # Reset backoff
                logger.info(f"{self._name}: Connected")
                await self._read_loop()
            except Exception as e:
                logger.error(f"{self._name}: Connection failed: {e}")
                self.connected = False
                await asyncio.sleep(delay)
                delay = min(delay * 2, 60)

    async def _read_loop(self):
        """Read data from TCP and extract KISS frames."""
        try:
            while True:
                data = await self.reader.read(4096)
                if not data:
                    break
                frames = self.parser.feed(data)
                for frame in frames:
                    try:
                        await self.on_frame(frame, self)
                    except Exception as e:
                        logger.error(f"{self._name}: Frame handler error: {e}")
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"{self._name}: Read error: {e}")
        finally:
            self.connected = False
            logger.info(f"{self._name}: Disconnected")

    async def send(self, ax25_data: bytes):
        """Send an AX.25 frame via KISS."""
        if self.writer and self.connected:
            frame = make_kiss_frame(ax25_data)
            self.writer.write(frame)
            await self.writer.drain()
            logger.debug(f"{self._name}: Sent {len(ax25_data)} bytes")

    async def close(self):
        if self.writer:
            self.writer.close()
            self.connected = False


def _agwpe_header(kind: str, data_len: int = 0, port: int = 0, pid: int = 0) -> bytes:
    """Build the fixed 36-byte AGWPE TCP API header."""
    kind_byte = (kind or " ").encode("ascii", errors="ignore")[:1] or b" "
    return struct.pack("<B3sBBBB10s10sII", port & 0xFF, b"\x00\x00\x00", kind_byte[0], 0, pid & 0xFF, 0, b"", b"", data_len, 0)


def _looks_like_ax25_address(data: bytes) -> bool:
    """Return True when bytes appear to begin with AX.25 destination/source addresses."""
    if len(data) < 16:
        return False

    def valid_call(addr: bytes) -> bool:
        if len(addr) < 7:
            return False
        call = "".join(chr((b >> 1) & 0x7F) for b in addr[:6]).strip()
        if not call or len(call) > 6:
            return False
        return all(c.isalnum() or c == " " for c in call)

    return valid_call(data[0:7]) and valid_call(data[7:14])


def _agwpe_raw_payload_to_ax25(data: bytes, port: int = 0) -> bytes:
    """Strip the AGWPE raw-frame TNC byte when present."""
    if not data:
        return data
    if _looks_like_ax25_address(data):
        return data

    # AGWPE raw K frames include a leading TNC byte before the AX.25 frame:
    # 0x00 for port 1, 0x10 for port 2, etc. Some servers echo the API port
    # number instead, so prefer structural validation over one exact value.
    if len(data) > 1 and _looks_like_ax25_address(data[1:]):
        return data[1:]
    return data


class AGWPETCPClient:
    """AGWPE server-port connection using raw AX.25 frames."""

    can_transmit = True

    def __init__(self, host: str, port: int, on_frame: Callable, name: str = ""):
        self.host = host
        self.port = port
        self.on_frame = on_frame
        self.writer: Optional[asyncio.StreamWriter] = None
        self.reader: Optional[asyncio.StreamReader] = None
        self.connected = False
        self._name = name or f"AGWPE({host}:{port})"
        self._reconnect_delay = 5

    @property
    def name(self) -> str:
        return self._name

    async def connect(self):
        delay = self._reconnect_delay
        while True:
            try:
                self.reader, self.writer = await asyncio.open_connection(self.host, self.port)
                self.connected = True
                delay = self._reconnect_delay
                logger.info(f"{self._name}: Connected")
                await self._enable_raw_frames()
                await self._read_loop()
            except Exception as e:
                logger.error(f"{self._name}: Connection failed: {e}")
                self.connected = False
                await asyncio.sleep(delay)
                delay = min(delay * 2, 60)

    async def _enable_raw_frames(self):
        if not self.writer:
            return
        self.writer.write(_agwpe_header("k"))
        await self.writer.drain()

    async def _read_loop(self):
        try:
            while True:
                header = await self.reader.readexactly(36)
                port, _reserved1, kind, _reserved2, _pid, _reserved3, _from, _to, data_len, _user = struct.unpack("<B3sBBBB10s10sII", header)
                data = await self.reader.readexactly(data_len) if data_len else b""
                kind_ch = chr(kind)
                if kind_ch in {"K", "k"} and data:
                    frame_data = _agwpe_raw_payload_to_ax25(data, port)
                    try:
                        await self.on_frame(frame_data, self)
                    except Exception as e:
                        logger.error(f"{self._name}: Frame handler error: {e}")
                elif kind_ch in {"U", "M"} and data:
                    line = data.decode("latin-1", errors="ignore").strip("\x00\r\n ")
                    logger.debug("%s: monitor frame on AGWPE port %s ignored: %s", self._name, port, line)
        except asyncio.IncompleteReadError:
            pass
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"{self._name}: Read error: {e}")
        finally:
            self.connected = False
            logger.info(f"{self._name}: Disconnected")

    async def send(self, ax25_data: bytes):
        if self.writer and self.connected:
            payload = bytes([0]) + ax25_data
            self.writer.write(_agwpe_header("K", len(payload)) + payload)
            await self.writer.drain()
            logger.debug(f"{self._name}: Sent {len(ax25_data)} bytes")

    async def close(self):
        if self.writer:
            self.writer.close()
            self.connected = False


class TNC2MonitorSerialClient:
    """Receive APRS packets from a classic TNC2-compatible monitor stream."""

    can_transmit = False

    def __init__(
        self,
        port: str,
        baudrate: int,
        on_packet: Callable,
        flow_control: str = "none",
        init_profile: str = "none",
        init_commands: str = "",
        callsign: str = "N0CALL",
        name: str = "",
    ):
        self.port = port
        self.baudrate = baudrate
        self.on_packet = on_packet
        self.flow_control = normalize_flow_control(flow_control)
        self.init_profile = init_profile
        self.init_commands = init_commands
        self.callsign = callsign
        self.writer: Optional[asyncio.StreamWriter] = None
        self.reader: Optional[asyncio.StreamReader] = None
        self.connected = False
        self._buffer = bytearray()
        self._name = name or f"TNC2-Monitor({port})"

    @property
    def name(self) -> str:
        return self._name

    async def connect(self):
        while True:
            try:
                import serial_asyncio

                self.reader, self.writer = await serial_asyncio.open_serial_connection(
                    url=self.port,
                    baudrate=self.baudrate,
                    bytesize=8,
                    parity="N",
                    stopbits=1,
                    **serial_flow_kwargs(self.flow_control),
                )
                self.connected = True
                logger.info(f"{self._name}: Connected")
                await self._run_init_commands()
                await self._read_loop()
            except ImportError:
                logger.error("pyserial-asyncio is required for serial TNC support. Install with: pip install pyserial-asyncio")
                return
            except Exception as e:
                logger.error(f"{self._name}: Connection failed: {e}")
                self.connected = False
                await asyncio.sleep(5)

    async def _run_init_commands(self):
        commands = render_init_commands(self.init_profile, self.init_commands, self.callsign, "tnc2_monitor")
        if not commands or not self.writer:
            return
        logger.info(f"{self._name}: Running {len(commands)} TNC init command(s)")
        for command in commands:
            payload = command.encode("ascii", errors="ignore")
            if payload == b"\\x03":
                payload = b"\x03"
            if not payload.endswith(b"\r"):
                payload += b"\r"
            self.writer.write(payload)
            await self.writer.drain()
            await asyncio.sleep(0.35)

    async def _read_loop(self):
        try:
            while True:
                data = await self.reader.read(1024)
                if not data:
                    break
                self._buffer.extend(data)
                while b"\n" in self._buffer or b"\r" in self._buffer:
                    line, sep, rest = self._split_line(self._buffer)
                    self._buffer = bytearray(rest)
                    packet = self._extract_aprs_line(line)
                    if packet:
                        try:
                            await self.on_packet(packet, self)
                        except Exception as e:
                            logger.error(f"{self._name}: Packet handler error: {e}")
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"{self._name}: Read error: {e}")
        finally:
            self.connected = False
            logger.info(f"{self._name}: Disconnected")

    @staticmethod
    def _split_line(buffer: bytearray):
        positions = [p for p in (buffer.find(b"\n"), buffer.find(b"\r")) if p >= 0]
        pos = min(positions)
        end = pos + 1
        while end < len(buffer) and buffer[end] in (10, 13):
            end += 1
        return bytes(buffer[:pos]), bytes(buffer[pos:end]), bytes(buffer[end:])

    @staticmethod
    def _extract_aprs_line(raw_line: bytes) -> Optional[str]:
        line = raw_line.decode("latin-1", errors="ignore").strip()
        if not line or line.lower().startswith(("cmd:", "cmd>", "connected", "disconnected")):
            return None
        if ">" not in line or ":" not in line:
            return None

        # Some TNCs prefix monitor lines with timestamps or channel labels.
        start = 0
        for idx, ch in enumerate(line):
            if ch == ">" and idx > 0:
                left = line[:idx].split()[-1]
                if left:
                    start = line.rfind(left, 0, idx)
                    break
        packet = line[start:].strip()
        return packet if ">" in packet and ":" in packet else None

    async def send(self, ax25_data: bytes):
        logger.warning(f"{self._name}: Transmit is not supported in TNC2 monitor mode")

    async def close(self):
        if self.writer:
            self.writer.close()
            self.connected = False
