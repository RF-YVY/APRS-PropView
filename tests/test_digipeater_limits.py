"""The digipeater emits valid AX.25 and repeats UI frames only."""
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from server.ax25 import AX25Address, AX25Frame
from server.config import Config
from server.digipeater import Digipeater
from server.packet_handler import PacketHandler

USED = ["N0AAA", "N0AAB", "N0AAC", "N0AAD", "N0AAE", "N0AAF", "N0AAG"]


def frame(digis, control=0x03, pid=0xF0, info=b">status"):
    addresses = []
    for call in digis:
        address = AX25Address.from_string(call.rstrip("*"))
        address.h_bit = call.endswith("*")
        addresses.append(address)
    return AX25Frame(
        destination=AX25Address.from_string("APRS"),
        source=AX25Address.from_string("K1ABC"),
        digipeaters=addresses,
        control=control,
        pid=pid,
        info=info,
    )


class PathCapTests(unittest.TestCase):
    def setUp(self):
        self.config = Config()
        self.config.station.callsign = "K5ABC"
        self.config.digipeater.enabled = True
        self.digi = Digipeater(self.config)

    def test_declines_a_wide_hop_that_would_make_nine_digipeaters(self):
        full = frame([call + "*" for call in USED] + ["WIDE1-1"])
        self.assertIsNone(self.digi.should_digipeat(full))

    def test_repeats_a_wide_hop_that_makes_eight_digipeaters(self):
        result = self.digi.should_digipeat(frame([call + "*" for call in USED[:6]] + ["WIDE1-1"]))
        self.assertEqual(len(result.digipeaters), 8)

    def test_direct_address_in_an_eight_digipeater_frame_still_repeats(self):
        full = frame([call + "*" for call in USED] + ["K5ABC"])
        self.assertEqual(len(self.digi.should_digipeat(full).digipeaters), 8)

    def test_every_emitted_frame_has_a_valid_address_field(self):
        result = self.digi.should_digipeat(frame([call + "*" for call in USED[:6]] + ["WIDE1-1"]))
        self.assertIsNotNone(AX25Frame.decode(result.encode()))


class UIFramesOnlyTests(unittest.IsolatedAsyncioTestCase):
    def handler(self):
        config = Config()
        config.station.callsign = "K5ABC"
        config.digipeater.enabled = True
        tracker = SimpleNamespace(is_blocked_callsign=lambda call: False, track_packet=AsyncMock())
        handler = PacketHandler(config, tracker, None, None, AsyncMock())
        handler._check_incoming_message = AsyncMock()
        handler._record_tx_packet = AsyncMock()
        handler._broadcast_stats = AsyncMock()
        interface = SimpleNamespace(name="TNC", connected=True, send=AsyncMock())
        handler.rf_interfaces = [interface]
        return handler, interface

    async def test_ui_frame_is_repeated(self):
        handler, interface = self.handler()
        await handler.handle_rf_packet(frame(["WIDE1-1"]).encode(), interface)
        interface.send.assert_awaited()

    async def test_i_frame_is_not_repeated(self):
        handler, interface = self.handler()
        await handler.handle_rf_packet(frame(["WIDE1-1"], control=0x00).encode(), interface)
        interface.send.assert_not_awaited()

    async def test_ui_frame_with_another_pid_is_not_repeated(self):
        handler, interface = self.handler()
        await handler.handle_rf_packet(frame(["WIDE1-1"], pid=0xCF).encode(), interface)
        interface.send.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
