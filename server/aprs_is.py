"""APRS-IS client — connects to the APRS Internet System for igate operations."""

import asyncio
import logging
import time
from typing import Callable, Optional

from server.config import Config

logger = logging.getLogger("propview.aprs_is")


# Placeholder callsigns that must never connect to APRS-IS
_BLOCKED_CALLSIGNS = {'N0CALL', 'NOCALL', 'MYCALL', 'TEST'}


def _decode_aprs_line(raw_line: bytes) -> str:
    """Decode APRS bytes losslessly after trimming only CR/LF terminators."""
    return raw_line.rstrip(b"\r\n").decode("latin-1")


class APRSISClient:
    """Asynchronous APRS-IS client with auto-reconnect."""

    def __init__(self, config: Config, on_packet: Callable):
        self.config = config
        self.on_packet = on_packet
        self.reader: Optional[asyncio.StreamReader] = None
        self.writer: Optional[asyncio.StreamWriter] = None
        self.connected = False
        self.verified = False  # True only after server confirms verified login
        self._reconnect_delay = 5
        self.server_banner = ""
        self._last_rx = 0.0

    async def _reset_connection(self):
        """Clear connection state and close the current socket."""
        writer = self.writer
        self.reader = None
        self.writer = None
        self.connected = False
        self.verified = False

        if writer:
            try:
                writer.close()
            except Exception:
                pass
            try:
                await writer.wait_closed()
            except Exception:
                pass

    @property
    def name(self) -> str:
        return f"APRS-IS({self.config.aprs_is.server})"

    def _build_login(self) -> str:
        """Build APRS-IS login string."""
        callsign = self.config.station.full_callsign
        passcode = self.config.aprs_is.passcode
        login = f"user {callsign} pass {passcode} vers APRSPropView 1.0"
        if self.config.aprs_is.filter:
            login += f" filter {self.config.aprs_is.filter}"
        return login

    async def connect(self):
        """Connect to APRS-IS with auto-reconnect and exponential backoff."""
        # APRS-IS policy: never connect with placeholder callsigns
        base_call = self.config.station.callsign.upper()
        if base_call in _BLOCKED_CALLSIGNS or not base_call:
            logger.error(
                f"Cannot connect to APRS-IS with callsign '{base_call}'. "
                "Set a valid amateur radio callsign in settings."
            )
            return

        delay = self._reconnect_delay
        while True:
            try:
                server = self.config.aprs_is.server
                port = self.config.aprs_is.port
                logger.info(f"Connecting to APRS-IS {server}:{port}...")

                self.reader, self.writer = await asyncio.open_connection(server, port)

                # Read server banner
                banner = await asyncio.wait_for(self.reader.readline(), timeout=10)
                self.server_banner = _decode_aprs_line(banner)
                logger.info(f"APRS-IS banner: {self.server_banner}")

                # Send login
                login = self._build_login()
                self.writer.write((login + "\r\n").encode("ascii"))
                await self.writer.drain()
                logger.info(f"APRS-IS login sent: {login}")

                # Read login response
                response = await asyncio.wait_for(self.reader.readline(), timeout=10)
                resp_str = _decode_aprs_line(response)
                logger.info(f"APRS-IS response: {resp_str}")

                if "logresp" in resp_str.lower() and "verified" in resp_str.lower():
                    # Check for "unverified" first since it also contains "verified"
                    if "unverified" in resp_str.lower():
                        self.verified = False
                        logger.warning(
                            "APRS-IS login UNVERIFIED (read-only). "
                            "Transmit/gating to APRS-IS is disabled. Check your passcode."
                        )
                    else:
                        self.verified = True
                        logger.info("APRS-IS login verified (read-write)")
                else:
                    self.verified = False
                    logger.warning(f"APRS-IS unexpected response: {resp_str}")

                self.connected = True
                delay = self._reconnect_delay
                await self._read_loop()

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"APRS-IS connection error: {e}")
                await self._reset_connection()
                await asyncio.sleep(delay)
                delay = min(delay * 2, 60)

    async def _read_loop(self):
        """Read packets from APRS-IS."""
        try:
            while True:
                line = await self.reader.readline()
                if not line:
                    break

                text = _decode_aprs_line(line)
                self._last_rx = time.time()

                # Skip server comments
                if text.startswith("#"):
                    continue

                if not text:
                    continue

                try:
                    await self.on_packet(text)
                except Exception as e:
                    logger.error(f"APRS-IS packet handler error: {e}")

        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"APRS-IS read error: {e}")
        finally:
            await self._reset_connection()
            logger.info("APRS-IS disconnected")

    async def send(self, packet: str):
        """Send a packet to APRS-IS (only if verified/read-write)."""
        if not self.connected or not self.writer:
            logger.warning("Cannot send to APRS-IS: not connected")
            return False

        # APRS-IS policy: unverified connections are read-only
        if not self.verified:
            logger.warning("Cannot send to APRS-IS: unverified (read-only). Check your passcode.")
            return False

        try:
            self.writer.write(packet.encode("latin-1") + b"\r\n")
            await self.writer.drain()
            logger.debug(f"APRS-IS TX: {packet}")
            return True
        except Exception as e:
            logger.error(f"APRS-IS send error: {e}")
            await self._reset_connection()
            return False

    async def send_position(self):
        """Send our station's position beacon to APRS-IS."""
        from server.aprs_parser import make_position_packet, build_station_beacon_comment

        cfg = self.config.station
        if cfg.latitude == 0.0 and cfg.longitude == 0.0:
            return False

        info = make_position_packet(
            cfg.full_callsign,
            cfg.latitude,
            cfg.longitude,
            cfg.symbol_table,
            cfg.symbol_code,
            build_station_beacon_comment(
                comment=cfg.comment,
                phg=cfg.phg,
                equipment=cfg.equipment,
            ),
        )
        packet = f"{cfg.full_callsign}>APRSPV,TCPIP*:{info}"
        return await self.send(packet)

    async def close(self):
        await self._reset_connection()

    async def reconnect(self):
        """Close the current connection and reconnect with (possibly updated) config.

        Call this after config changes to APRS-IS server/port/filter/passcode.
        The existing connect() loop will handle the reconnection automatically
        once we close the current writer — it will break out of _read_loop,
        then loop back to the top of connect() and re-read config.
        """
        logger.info("APRS-IS reconnect requested (settings changed)")
        await self._reset_connection()
        # The connect() coroutine is already running in a task and will
        # automatically reconnect after _read_loop exits.

    async def keepalive(self):
        """Send periodic keepalive to APRS-IS."""
        while True:
            try:
                await asyncio.sleep(300)  # Every 5 minutes
                if self.connected and self.writer:
                    self.writer.write(b"#keepalive\r\n")
                    await self.writer.drain()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning(f"APRS-IS keepalive failed: {e}")
                await self._reset_connection()
