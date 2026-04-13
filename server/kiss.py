"""KISS protocol handler for serial and TCP TNC connections."""

import asyncio
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

    def feed(self, data: bytes) -> list:
        """Feed raw bytes and return list of extracted KISS data frames."""
        frames = []
        for b in data:
            if b == FEND:
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
        return frames


class KISSSerialClient:
    """KISS TNC connection over serial port."""

    def __init__(self, port: str, baudrate: int, on_frame: Callable):
        self.port = port
        self.baudrate = baudrate
        self.on_frame = on_frame
        self.writer: Optional[asyncio.StreamWriter] = None
        self.reader: Optional[asyncio.StreamReader] = None
        self.parser = KISSFrameParser()
        self.connected = False
        self._name = f"KISS-Serial({port})"

    @property
    def name(self) -> str:
        return self._name

    async def connect(self):
        """Connect to serial KISS TNC with auto-reconnect."""
        while True:
            try:
                import serial_asyncio

                self.reader, self.writer = await serial_asyncio.open_serial_connection(
                    url=self.port, baudrate=self.baudrate
                )
                self.connected = True
                logger.info(f"{self._name}: Connected")
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


class KISSTCPClient:
    """KISS TNC connection over TCP."""

    def __init__(self, host: str, port: int, on_frame: Callable):
        self.host = host
        self.port = port
        self.on_frame = on_frame
        self.writer: Optional[asyncio.StreamWriter] = None
        self.reader: Optional[asyncio.StreamReader] = None
        self.parser = KISSFrameParser()
        self.connected = False
        self._name = f"KISS-TCP({host}:{port})"
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
