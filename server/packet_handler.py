"""Central packet handler — routes packets between RF, APRS-IS, digipeater, IGate, and tracker."""

import asyncio
import logging
import time
from typing import Optional, List, Dict, Any
from collections import deque

from server.config import Config
from server.ax25 import AX25Frame
from server.aprs_parser import (
    parse_packet, make_position_packet, make_message_packet,
    make_ack_packet, APRSPacket,
)
from server.digipeater import Digipeater
from server.igate import IGate
from server.station_tracker import StationTracker
from server.websocket_manager import WebSocketManager

logger = logging.getLogger("propview.handler")

# Maximum number of messages to keep in memory
MAX_MESSAGE_HISTORY = 500


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

        # Alert manager (set later via set_alert_manager)
        self._alert_manager = None

        # Message store — newest first
        self._messages: deque = deque(maxlen=MAX_MESSAGE_HISTORY)
        self._msg_id_counter = 1
        # Track acked message IDs to avoid duplicate ack display
        self._acked_ids: dict[str, float] = {}

        # Statistics
        self.stats = {
            "rf_rx": 0,
            "rf_tx": 0,
            "is_rx": 0,
            "is_tx": 0,
            "digipeated": 0,
            "gated_rf_to_is": 0,
            "gated_is_to_rf": 0,
            "messages_rx": 0,
            "messages_tx": 0,
            "start_time": time.time(),
        }

    def set_alert_manager(self, alert_manager):
        """Inject the AlertManager for message notifications."""
        self._alert_manager = alert_manager

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

        # Check for APRS message addressed to us
        await self._check_incoming_message(packet, source="rf")

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

        # Check for APRS message addressed to us
        await self._check_incoming_message(packet, source="aprs_is")

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

    async def _check_incoming_message(self, packet: APRSPacket, source: str):
        """Detect APRS messages and handle those addressed to our station."""
        if packet.packet_type != "message" or not packet.addressee:
            return

        my_call = self.config.station.full_callsign.upper()
        addressee = packet.addressee.strip().upper()
        from_call = packet.from_call.upper()

        # Handle ACK/REJ for messages we sent
        if packet.message_text and packet.message_text.startswith("ack"):
            ack_id = packet.message_text[3:]
            self._handle_ack(from_call, ack_id)
            return
        if packet.message_text and packet.message_text.startswith("rej"):
            rej_id = packet.message_text[3:]
            self._handle_rej(from_call, rej_id)
            return

        # Only store messages involving our station (from us or to us)
        # This filters out telemetry and other station-to-station traffic
        if addressee != my_call and from_call != my_call:
            return

        msg_record = {
            "id": len(self._messages) + 1,
            "timestamp": time.time(),
            "from": packet.from_call,
            "to": packet.addressee.strip(),
            "text": packet.message_text or "",
            "message_id": packet.message_id or "",
            "source": source,
            "direction": "rx",
            "acked": False,
        }

        # If message is addressed to us, send auto-ack and count it
        if addressee == my_call:
            self.stats["messages_rx"] += 1

            # Send ACK if message has an ID
            if packet.message_id:
                await self._send_ack(packet.from_call, packet.message_id)
                msg_record["acked"] = True

            logger.info(
                f"Message RX ({source}): {packet.from_call} → {packet.addressee}: "
                f"{packet.message_text}"
            )

            # Send message notification via configured channels
            if self._alert_manager:
                asyncio.ensure_future(
                    self._alert_manager.send_message_notification(msg_record)
                )

        self._messages.appendleft(msg_record)

        # Broadcast to web clients
        await self.ws.broadcast({
            "type": "message",
            "data": msg_record,
        })

    def _handle_ack(self, from_call: str, ack_id: str):
        """Mark a sent message as acknowledged."""
        self._acked_ids[ack_id] = time.time()
        # Update stored message
        for msg in self._messages:
            if (
                msg["direction"] == "tx"
                and msg.get("message_id") == ack_id
                and msg["to"].upper() == from_call
            ):
                msg["acked"] = True
                break
        logger.info(f"ACK received from {from_call} for message #{ack_id}")
        # Notify frontend
        asyncio.ensure_future(self.ws.broadcast({
            "type": "message_ack",
            "data": {"from": from_call, "message_id": ack_id},
        }))

    def _handle_rej(self, from_call: str, rej_id: str):
        """Handle a rejected message."""
        for msg in self._messages:
            if (
                msg["direction"] == "tx"
                and msg.get("message_id") == rej_id
                and msg["to"].upper() == from_call
            ):
                msg["rejected"] = True
                break
        logger.info(f"REJ received from {from_call} for message #{rej_id}")
        asyncio.ensure_future(self.ws.broadcast({
            "type": "message_rej",
            "data": {"from": from_call, "message_id": rej_id},
        }))

    async def _send_ack(self, to_call: str, message_id: str):
        """Send an ACK for a received message."""
        ack_info = make_ack_packet(to_call, message_id)
        await self._send_aprs_message_raw(to_call, ack_info)

    async def send_message(self, to_call: str, text: str) -> Dict[str, Any]:
        """Send an APRS message to another station. Returns the message record."""
        msg_id = str(self._msg_id_counter)
        self._msg_id_counter += 1

        info = make_message_packet(to_call, text, msg_id)

        msg_record = {
            "id": len(self._messages) + 1,
            "timestamp": time.time(),
            "from": self.config.station.full_callsign,
            "to": to_call.strip(),
            "text": text,
            "message_id": msg_id,
            "source": "local",
            "direction": "tx",
            "acked": False,
        }

        self._messages.appendleft(msg_record)
        self.stats["messages_tx"] += 1

        # Send on both RF and APRS-IS
        await self._send_aprs_message_raw(to_call, info)

        logger.info(f"Message TX: {self.config.station.full_callsign} → {to_call}: {text}")

        # Broadcast to web clients
        await self.ws.broadcast({
            "type": "message",
            "data": msg_record,
        })

        return msg_record

    async def _send_aprs_message_raw(self, to_call: str, info: str):
        """Send an APRS info field on RF and APRS-IS."""
        my_call = self.config.station.full_callsign

        # Send on RF
        if self.rf_interfaces:
            from server.ax25 import AX25Address

            frame = AX25Frame()
            frame.source = AX25Address.from_string(my_call)
            frame.destination = AX25Address.from_string("APRSPV")
            frame.digipeaters = [AX25Address.from_string("WIDE1-1")]
            frame.info = info.encode("ascii", errors="replace")
            await self._transmit_rf(frame)

        # Send on APRS-IS
        if self.aprs_is and self.aprs_is.connected:
            is_packet = f"{my_call}>APRSPV,TCPIP*:{info}"
            await self.aprs_is.send(is_packet)
            self.stats["is_tx"] += 1

    def get_messages(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Return recent messages (newest first)."""
        return list(self._messages)[:limit]

    def clear_messages(self):
        """Clear all stored messages."""
        self._messages.clear()
        self._acked_ids.clear()

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
                    logger.debug("Beaconing disabled (interval=0)")
                    await asyncio.sleep(60)
                    continue

                # APRS-IS policy: enforce minimum beacon interval (10 minutes)
                if interval < 600:
                    logger.warning(
                        f"Beacon interval {interval}s is below APRS-IS minimum (600s). "
                        "Clamping to 600 seconds."
                    )
                    interval = 600

                logger.info(f"Sending beacon (next in {interval}s / {interval // 60}min)")
                await self._send_beacon()
                await asyncio.sleep(interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Beacon error: {e}", exc_info=True)
                await asyncio.sleep(60)

    async def _send_beacon(self):
        """Send our position beacon on RF and APRS-IS."""
        cfg = self.config.station
        if cfg.latitude == 0.0 and cfg.longitude == 0.0:
            logger.debug("Beacon skipped — no position set (0,0)")
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

            # Build digipeater path from config (e.g. "WIDE1-1,WIDE2-1")
            path_str = (cfg.beacon_path or "").strip()
            if path_str:
                frame.digipeaters = [
                    AX25Address.from_string(hop.strip())
                    for hop in path_str.split(",")
                    if hop.strip()
                ]
            else:
                frame.digipeaters = []

            frame.info = info.encode("ascii")
            await self._transmit_rf(frame)
            logger.info(f"Beacon RF TX: {cfg.full_callsign}>APRSPV via {path_str or 'DIRECT'}")

        # Beacon on APRS-IS
        if self.aprs_is and self.aprs_is.connected:
            await self.aprs_is.send_position()
            logger.info("Beacon APRS-IS TX")

        if not self.rf_interfaces and not (self.aprs_is and self.aprs_is.connected):
            logger.warning("Beacon: no RF or APRS-IS interfaces available")

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
