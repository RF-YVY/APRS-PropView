"""Central packet handler — routes packets between RF, APRS-IS, digipeater, IGate, and tracker."""

import asyncio
import logging
import time
from typing import Optional, List

from server.config import Config
from server.ax25 import AX25Frame
from server.aprs_parser import parse_packet, make_position_packet, APRSPacket
from server.digipeater import Digipeater
from server.igate import IGate
from server.station_tracker import StationTracker
from server.websocket_manager import WebSocketManager

logger = logging.getLogger("propview.handler")


class PacketHandler:
    """Routes packets between all system components."""

    def __init__(
        self,
        config: Config,
        tracker: StationTracker,
        digipeater: Optional[Digipeater],
        igate: Optional[IGate],
        ws_manager: WebSocketManager,
    ):
        self.config = config
        self.tracker = tracker
        self.digipeater = digipeater
        self.igate = igate
        self.ws = ws_manager
        self.aprs_is = None
        self.rf_interfaces = []

        # Statistics
        self.stats = {
            "rf_rx": 0,
            "rf_tx": 0,
            "is_rx": 0,
            "is_tx": 0,
            "digipeated": 0,
            "gated_rf_to_is": 0,
            "gated_is_to_rf": 0,
            "start_time": time.time(),
        }

    def add_rf_interface(self, interface):
        """Register an RF interface (KISS client)."""
        self.rf_interfaces.append(interface)

    def set_aprs_is(self, client):
        """Set the APRS-IS client."""
        self.aprs_is = client

    async def handle_rf_packet(self, raw_bytes: bytes, interface=None):
        """Handle a packet received from RF (KISS TNC)."""
        self.stats["rf_rx"] += 1

        # Decode AX.25 frame
        frame = AX25Frame.decode(raw_bytes)
        if not frame:
            logger.debug("Failed to decode AX.25 frame")
            return

        # Convert to APRS string for parsing
        raw_str = frame.to_aprs_string()
        logger.debug(f"RF RX: {raw_str}")

        # Parse APRS content
        packet = parse_packet(raw_str, source="rf")

        # Track the station
        await self.tracker.track_packet(packet)

        # Note RF station for IGate IS→RF decisions
        if self.igate:
            self.igate.note_rf_station(frame.from_call)

        # Digipeater processing
        if self.digipeater:
            new_frame = self.digipeater.should_digipeat(frame)
            if new_frame:
                await self._transmit_rf(new_frame)
                self.stats["digipeated"] += 1

        # IGate RF→IS
        if self.igate and self.aprs_is:
            gated = self.igate.should_gate_rf_to_is(raw_str, frame.from_call)
            if gated:
                await self.aprs_is.send(gated)
                self.stats["gated_rf_to_is"] += 1
                self.stats["is_tx"] += 1

    async def handle_is_packet(self, raw_str: str):
        """Handle a packet received from APRS-IS."""
        self.stats["is_rx"] += 1

        # Parse APRS content
        packet = parse_packet(raw_str, source="aprs_is")

        # Track the station
        await self.tracker.track_packet(packet)

        # IGate IS→RF
        if self.igate and self.rf_interfaces:
            gated_info = self.igate.should_gate_is_to_rf(
                raw_str, packet.from_call, packet.to_call
            )
            if gated_info:
                # Build frame for RF transmission
                frame = AX25Frame.from_aprs_string(raw_str)
                if frame:
                    # APRS-IS policy: gated packets must NOT request further
                    # digipeating. Use only our callsign (with has-been-repeated
                    # flag) — no WIDE path.
                    from server.ax25 import AX25Address

                    frame.digipeaters = [
                        AX25Address.from_string(self.config.station.full_callsign + "*"),
                    ]
                    await self._transmit_rf(frame)
                    self.stats["gated_is_to_rf"] += 1
                    self.stats["rf_tx"] += 1

    async def _transmit_rf(self, frame: AX25Frame):
        """Transmit an AX.25 frame on all RF interfaces."""
        encoded = frame.encode()
        for iface in self.rf_interfaces:
            try:
                await iface.send(encoded)
                self.stats["rf_tx"] += 1
                logger.debug(f"RF TX via {iface.name}: {frame.to_aprs_string()}")
            except Exception as e:
                logger.error(f"RF TX error on {iface.name}: {e}")

    async def beacon_loop(self):
        """Periodically transmit our station beacon."""
        # Warn about read-only mode
        if self.aprs_is and not getattr(self.aprs_is, 'verified', False):
            logger.warning(
                "APRS-IS is unverified (read-only). Beacons will only be sent on RF."
            )

        # Wait a bit before first beacon
        await asyncio.sleep(10)

        while True:
            try:
                # Re-read interval each iteration so config changes apply live
                interval = self.config.station.beacon_interval
                if interval <= 0:
                    # Beaconing disabled — check again after a while
                    await asyncio.sleep(60)
                    continue

                # APRS-IS policy: enforce minimum beacon interval (10 minutes)
                if interval < 600:
                    logger.warning(
                        f"Beacon interval {interval}s is below APRS-IS minimum (600s). "
                        "Clamping to 600 seconds."
                    )
                    interval = 600

                await self._send_beacon()
                await asyncio.sleep(interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Beacon error: {e}")
                await asyncio.sleep(60)

    async def _send_beacon(self):
        """Send our position beacon on RF and APRS-IS."""
        cfg = self.config.station
        if cfg.latitude == 0.0 and cfg.longitude == 0.0:
            return

        info = make_position_packet(
            cfg.full_callsign,
            cfg.latitude,
            cfg.longitude,
            cfg.symbol_table,
            cfg.symbol_code,
            cfg.comment,
        )

        # Beacon on RF
        if self.rf_interfaces:
            from server.ax25 import AX25Address

            frame = AX25Frame()
            frame.source = AX25Address.from_string(cfg.full_callsign)
            frame.destination = AX25Address.from_string("APRSPV")
            frame.digipeaters = [AX25Address.from_string("WIDE1-1")]
            frame.info = info.encode("ascii")
            await self._transmit_rf(frame)

        # Beacon on APRS-IS
        if self.aprs_is and self.aprs_is.connected:
            await self.aprs_is.send_position()

        logger.info("Beacon sent")

    def get_status(self) -> dict:
        """Get current system status."""
        uptime = time.time() - self.stats["start_time"]
        rf_connected = any(iface.connected for iface in self.rf_interfaces)
        is_connected = self.aprs_is.connected if self.aprs_is else False

        return {
            "station": self.config.station.full_callsign,
            "latitude": self.config.station.latitude,
            "longitude": self.config.station.longitude,
            "uptime_seconds": round(uptime),
            "rf_connected": rf_connected,
            "rf_interfaces": [
                {"name": iface.name, "connected": iface.connected}
                for iface in self.rf_interfaces
            ],
            "aprs_is_connected": is_connected,
            "digipeater_enabled": self.config.digipeater.enabled,
            "igate_enabled": self.config.igate.enabled,
            "stats": dict(self.stats),
        }
