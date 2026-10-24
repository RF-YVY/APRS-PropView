import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from server.ax25 import AX25Address, AX25Frame
from server.config import Config
from server.digipeater import Digipeater
from server.packet_handler import PacketHandler


def packet(path="WIDE1-1", info=b"!3530.00N/09745.00W-Test"):
    return AX25Frame(
        destination=AX25Address.from_string("APRS"),
        source=AX25Address.from_string("K1ABC"),
        digipeaters=[AX25Address.from_string(path)],
        info=info,
    )


class LiveDigipeaterTests(unittest.IsolatedAsyncioTestCase):
    async def test_handheld_and_mobile_paths_from_field_report(self):
        config = Config()
        config.station.callsign = "K5YVY"
        config.station.ssid = 0
        digi = Digipeater(config)
        handheld = AX25Frame.from_aprs_string("K5YVY-7>S4RT7U,WIDE1-1,WIDE2-1:>handheld")
        mobile = AX25Frame.from_aprs_string("K5YVY-9>DECT7P,WIDE2-2:>mobile")
        self.assertIsNotNone(digi.should_digipeat(handheld))
        self.assertIsNone(digi.should_digipeat(mobile))
        config.digipeater.aliases.append("WIDE2-2")
        # Use a new payload outside duplicate suppression for the next beacon.
        mobile.info = b">next mobile beacon"
        repeated = digi.should_digipeat(mobile)
        self.assertIsNotNone(repeated)
        self.assertEqual(repeated.digipeaters[0].full_call, "K5YVY")
        self.assertTrue(repeated.digipeaters[0].h_bit)
        self.assertEqual(repeated.digipeaters[1].full_call, "WIDE2-1")
        self.assertFalse(repeated.digipeaters[1].h_bit)

    async def test_enable_after_startup_transmits_received_rf_and_records_it(self):
        config = Config()
        config.station.callsign = "K5ABC"
        config.digipeater.enabled = False
        tracker = SimpleNamespace(
            is_blocked_callsign=lambda call: False,
            track_packet=AsyncMock(),
        )
        handler = PacketHandler(config, tracker, None, None, AsyncMock())
        handler._check_incoming_message = AsyncMock()
        handler._record_tx_packet = AsyncMock()
        handler._broadcast_stats = AsyncMock()
        interface = SimpleNamespace(name="TNC", connected=True, send=AsyncMock())
        handler.rf_interfaces = [interface]
        raw = packet().encode()

        await handler.handle_rf_packet(raw, interface)
        interface.send.assert_not_awaited()
        config.digipeater.enabled = True
        await handler.handle_rf_packet(raw, interface)

        interface.send.assert_awaited_once()
        repeated = AX25Frame.decode(interface.send.call_args.args[0])
        self.assertEqual(repeated.digipeaters[0].full_call, config.station.full_callsign)
        self.assertTrue(repeated.digipeaters[0].h_bit)
        self.assertEqual(handler.stats["digipeated"], 1)
        handler._record_tx_packet.assert_awaited_once()
        await handler.handle_rf_packet(raw, interface)
        self.assertEqual(interface.send.await_count, 1)
        config.digipeater.enabled = False
        await handler.handle_rf_packet(packet(info=b"new packet").encode(), interface)
        self.assertEqual(interface.send.await_count, 1)
        config.digipeater.enabled = True
        interface.rx_only_rf = True
        await handler.handle_rf_packet(packet(info=b"receive only").encode(), interface)
        self.assertEqual(interface.send.await_count, 1)

    async def test_live_identity_alias_and_dedupe_settings(self):
        config = Config()
        config.station.callsign = "K5ABC"
        config.digipeater.aliases = ["WIDE1-1"]
        digi = Digipeater(config)
        config.station.callsign = "K5XYZ"
        config.station.ssid = 3
        config.digipeater.aliases = [" wide2-1 "]
        config.digipeater.dedupe_interval = 7

        self.assertIsNone(digi.should_digipeat(packet()))
        repeated = digi.should_digipeat(packet("WIDE2-1", b"second packet"))
        self.assertIsNotNone(repeated)
        self.assertEqual(repeated.digipeaters[0].full_call, "K5XYZ-3")
        self.assertEqual(digi.dedupe.max_age, 7)
        direct = digi.should_digipeat(packet("K5XYZ-3", b"direct packet"))
        self.assertIsNotNone(direct)
        own = packet("WIDE2-1", b"own packet")
        own.source = AX25Address.from_string("K5XYZ-3")
        self.assertIsNone(digi.should_digipeat(own))
