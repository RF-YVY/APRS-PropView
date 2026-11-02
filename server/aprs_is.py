"""APRS-IS client — connects to the APRS Internet System for igate operations."""

import asyncio
import logging
import time
import re
from typing import Callable, Optional

from server.config import Config

logger = logging.getLogger("propview.aprs_is")


# Placeholder callsigns that must never connect to APRS-IS
_BLOCKED_CALLSIGNS = {'N0CALL', 'NOCALL', 'MYCALL', 'TEST'}


def _decode_aprs_line(raw_line: bytes) -> str:
    """Decode APRS bytes losslessly after trimming only CR/LF terminators."""
    return raw_line.rstrip(b"\r\n").decode("latin-1")


def _looks_like_aprs_packet(text: str) -> bool:
    """Return True when a line has the basic TNC2 APRS packet shape."""
    if not text or text.startswith("#"):
        return False
    header, sep, _info = text.partition(":")
    return bool(sep and ">" in header)


async def _timed(awaitable, timeout: Optional[float]):
    """Await with a timeout, like asyncio.wait_for, and never lose a cancel.

    Before Python 3.12, wait_for returns the result when the awaitable
    finishes in the same tick as a cancellation, which leaves connect()
    running after it was cancelled.
    """
    task = asyncio.ensure_future(awaitable)
    try:
        done, _ = await asyncio.wait({task}, timeout=timeout)
    except asyncio.CancelledError:
        task.cancel()
        raise
    if not done:
        task.cancel()
        await asyncio.wait({task})
        raise asyncio.TimeoutError
    return task.result()


class APRSISClient:
    """Asynchronous APRS-IS client with auto-reconnect."""

    def __init__(self, config: Config, on_packet: Callable, app_version: str = "1.0.0"):
        self.config = config
        self.on_packet = on_packet
        self.app_version = app_version
        self.reader: Optional[asyncio.StreamReader] = None
        self.writer: Optional[asyncio.StreamWriter] = None
        self.connected = False
        self.verified = False  # True only after server confirms verified login
        self._reconnect_delay = 5
        self._stable_session = 60  # A session this long clears the backoff
        self._read_timeout = 120  # Servers send a comment line about every 20s
        self._server_comments = False  # Seen on this connection
        self.server_banner = ""
        self._last_rx = 0.0
        self._pending_rx_lines: list[str] = []
        self._handshake_timeout = 3
        self._message_recipients = set()
        self._heard_me_calls = set()
        self._wake = asyncio.Event()  # Set when settings change

    async def _reset_connection(self):
        """Clear connection state and close the current socket."""
        writer = self.writer
        self.reader = None
        self.writer = None
        self.connected = False
        self.verified = False
        self._pending_rx_lines.clear()

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
        login = f"user {callsign} pass {passcode} vers APRSPropView {self.app_version}"
        effective_filter = self._effective_filter()
        if effective_filter:
            login += f" filter {effective_filter}"
        return login

    def _effective_filter(self):
        base = (self.config.aprs_is.filter or '').strip()
        filters = [base] if base else []
        call = (self.config.station.callsign or '').upper()
        if re.fullmatch(r'[A-Z0-9]{1,9}', call) and call not in _BLOCKED_CALLSIGNS:
            watches = [call, call + '-*', *sorted(self._heard_me_calls)]
            filters.append('b/' + '/'.join(watches))
        if self._message_recipients:
            recipients = sorted(self._message_recipients | {self.config.station.full_callsign})
            filters.append('g/' + '/'.join(recipients))
        return ' '.join(filters)

    async def register_heard_me_stations(self, callsigns):
        from server.heard_me import CALL
        added = {call.upper() for call in callsigns if isinstance(call, str) and CALL.fullmatch(call.upper())}
        updated = set(sorted(self._heard_me_calls | added)[:32])
        if updated == self._heard_me_calls:
            return
        self._heard_me_calls = updated
        if self.connected and self.writer:
            try:
                self.writer.write(('#filter ' + self._effective_filter() + '\r\n').encode('ascii'))
                await self.writer.drain()
            except Exception:
                await self._reset_connection()

    async def register_message_recipient(self, callsign):
        """Include replies to a locally selected APSPOT operator in the live filter."""
        from server.aprs_spot import operator_callsign
        callsign = operator_callsign(callsign)
        if not self.connected or not self.verified or not self.writer:
            return False
        if callsign == self.config.station.full_callsign or callsign in self._message_recipients:
            return True
        self._message_recipients.add(callsign)
        try:
            self.writer.write(('#filter ' + self._effective_filter() + '\r\n').encode('ascii'))
            await self.writer.drain()
            return True
        except Exception:
            self._message_recipients.discard(callsign)
            await self._reset_connection()
            return False

    async def connect(self):
        """Connect to APRS-IS with auto-reconnect and exponential backoff.

        Runs for the life of the app. While APRS-IS can't be used, the loop
        waits here for reconnect() rather than exiting, so saving settings
        is enough to bring the connection up.
        """
        delay = self._reconnect_delay
        while True:
            self._wake.clear()

            # APRS-IS policy: never connect with placeholder callsigns
            base_call = self.config.station.callsign.upper()
            if base_call in _BLOCKED_CALLSIGNS or not base_call:
                logger.error(
                    f"Cannot connect to APRS-IS with callsign '{base_call}'. "
                    "Set your assigned callsign in settings."
                )
                await self._wake.wait()
                delay = self._reconnect_delay
                continue

            if not self.config.aprs_is.enabled:
                logger.info("APRS-IS is disabled in settings")
                await self._wake.wait()
                delay = self._reconnect_delay
                continue

            session_start = None
            try:
                server = self.config.aprs_is.server
                port = self.config.aprs_is.port
                logger.info(f"Connecting to APRS-IS {server}:{port}...")

                self.reader, self.writer = await asyncio.open_connection(server, port)

                # Public APRS-IS servers send a banner and logresp, but some
                # private/local TNC2 feeds do not. Treat early packet-looking
                # lines as receive data instead of discarding them as handshake.
                try:
                    banner = await _timed(self.reader.readline(), self._handshake_timeout)
                except asyncio.TimeoutError:
                    banner = b""

                self.server_banner = _decode_aprs_line(banner) if banner else ""
                self._server_comments = self.server_banner.startswith("#")
                if self.server_banner:
                    if _looks_like_aprs_packet(self.server_banner):
                        logger.info("APRS-IS server sent packet data before banner/logresp")
                        self._pending_rx_lines.append(self.server_banner)
                        self.server_banner = ""
                    else:
                        logger.info(f"APRS-IS banner: {self.server_banner}")
                else:
                    logger.info("APRS-IS server did not send an initial banner; continuing")

                # Send login
                login = self._build_login()
                self.writer.write((login + "\r\n").encode("ascii"))
                await self.writer.drain()
                logger.info("APRS-IS login sent for %s", self.config.station.full_callsign)

                self.connected = True
                await self._read_login_response()
                session_start = time.monotonic()
                await self._read_loop()

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"APRS-IS connection error: {e}")
                await self._reset_connection()

            # A server can accept the login and close at once, so only a
            # session that lasted clears the backoff.
            if session_start is not None and time.monotonic() - session_start >= self._stable_session:
                delay = self._reconnect_delay

            if await self._sleep_or_wake(delay):
                delay = self._reconnect_delay
            else:
                delay = min(delay * 2, 60)

    async def _sleep_or_wake(self, seconds: float) -> bool:
        """Wait out a backoff. Return True if a settings change ended it early."""
        try:
            await _timed(self._wake.wait(), seconds)
            return True
        except asyncio.TimeoutError:
            return False

    async def _read_loop(self):
        """Read packets from APRS-IS."""
        try:
            while self._pending_rx_lines:
                await self._handle_rx_line(self._pending_rx_lines.pop(0))

            while True:
                # Private TNC2 feeds can sit quiet for hours and never send
                # comments, so silence only means a dead link on a server
                # that has shown it sends them.
                limit = self._read_timeout if self._server_comments else None
                try:
                    line = await _timed(self.reader.readline(), limit)
                except asyncio.TimeoutError:
                    logger.warning("APRS-IS link silent for %s seconds; reconnecting", limit)
                    break
                if not line:
                    break

                text = _decode_aprs_line(line)
                self._last_rx = time.time()
                if text.startswith("#"):
                    self._server_comments = True
                await self._handle_rx_line(text)

        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error(f"APRS-IS read error: {e}")
        finally:
            await self._reset_connection()
            logger.info("APRS-IS disconnected")

    async def _read_login_response(self):
        """Read an optional APRS-IS logresp without dropping early packets."""
        try:
            response = await _timed(self.reader.readline(), self._handshake_timeout)
        except asyncio.TimeoutError:
            logger.info("APRS-IS server did not send a login response; using read-only mode")
            self.verified = False
            return

        resp_str = _decode_aprs_line(response)
        if not resp_str:
            self.verified = False
            return

        if _looks_like_aprs_packet(resp_str):
            self._pending_rx_lines.append(resp_str)
            self.verified = False
            logger.info("APRS-IS server sent packet data instead of logresp; using read-only mode")
            return

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

    async def _handle_rx_line(self, text: str):
        """Handle one decoded APRS-IS receive line."""
        if not text or text.startswith("#"):
            return
        try:
            await self.on_packet(text)
        except Exception as e:
            logger.error(f"APRS-IS packet handler error: {e}")

    async def send(self, packet: str):
        """Send a packet to APRS-IS (only if verified/read-write)."""
        if not self.connected or not self.writer:
            logger.warning("Cannot send to APRS-IS: not connected")
            return False

        # APRS-IS policy: unverified connections are read-only
        if not self.verified:
            logger.warning("Cannot send to APRS-IS: unverified (read-only). Check your passcode.")
            return False

        # One packet per line. A CR or LF inside the packet would let the rest
        # of it reach the server as a separate line under our login.
        if "\r" in packet or "\n" in packet:
            logger.warning("Refusing to send APRS-IS packet containing CR/LF: %r", packet[:80])
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
        packet = f"{cfg.full_callsign}>APPRPV,TCPIP*:{info}"
        return await self.send(packet)

    async def close(self):
        await self._reset_connection()

    async def reconnect(self):
        """Close the current connection and reconnect with (possibly updated) config.

        Call this after changes to the station callsign or the APRS-IS
        settings. The connect() task re-reads config from the top of its loop
        whether it was reading, backing off, or waiting for usable settings.
        """
        logger.info("APRS-IS reconnect requested (settings changed)")
        self._wake.set()
        await self._reset_connection()

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
