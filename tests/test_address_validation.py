"""Malformed addresses never reach tracking, gating, or digipeating."""
import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock

from server.aprs_parser import parse_packet
from server.ax25 import AX25Frame
from server.config import Config
from server.packet_handler import PacketHandler


def address(call, ssid=0, last=False):
    """Encode an address byte by byte, so invalid callsigns can be built."""
    padded = call.ljust(6).encode("latin-1")
    return bytes(b << 1 for b in padded) + bytes([0x60 | (ssid << 1) | int(last)])


def frame_bytes(source="N0CALL", dest="APRS", digis=()):
    data = address(dest) + address(source, last=not digis)
    for index, digi in enumerate(digis):
        data += address(digi, last=index == len(digis) - 1)
    return data + b"\x03\xf0>status"


class AX25AddressValidationTests(unittest.TestCase):
    def test_valid_frame_decodes(self):
        frame = AX25Frame.decode(frame_bytes(digis=("WIDE1",)))
        self.assertEqual(frame.from_call, "N0CALL")
        self.assertEqual(frame.digipeaters[0].callsign, "WIDE1")

    def test_invalid_characters_are_rejected_in_every_address(self):
        for bad in ("N0,CAL", "N0:CAL", 'N0"X', "n0call", "N0>X", "N0 X"):
            with self.subTest(bad=bad):
                self.assertIsNone(AX25Frame.decode(frame_bytes(source=bad)))
                self.assertIsNone(AX25Frame.decode(frame_bytes(dest=bad)))
                self.assertIsNone(AX25Frame.decode(frame_bytes(digis=(bad,))))

    def test_blank_address_is_rejected(self):
        self.assertIsNone(AX25Frame.decode(frame_bytes(source="")))


class ParserAddressValidationTests(unittest.TestCase):
    def test_accepts_addresses_seen_on_rf_and_aprs_is(self):
        for raw in (
            "N0CALL-9>APRS,WIDE1-1,WIDE2*:>ok",
            "CW0003>APRS,TCPIP*,qAC,T2FINLAND:>ok",
            "EL-123456>APRS,qAS,N0CALL-10:>ok",
            "KD8JNT-VS>APDG01,TCPIP*,qAC,KD8JNT-VS:>ok",
            "N0CALL>APRS,qAI,C0A80001,N0CALL:>ok",
            "N0CALL>APRS:>no path",
        ):
            with self.subTest(raw=raw):
                self.assertTrue(parse_packet(raw, source="aprs_is").valid)

    def test_rejects_invalid_source_destination_and_path(self):
        for raw in (
            'N0X" onmouseover="alert(1)>APRS:>x',
            "N0X<b>>APRS:>x",
            "N0CALL>AP RS:>x",
            'N0CALL>APRS,WIDE1-1":>x',
            "N0CALL>APRS,,WIDE1-1:>x",
            ">APRS:>x",
            "N0CALL>:>x",
            "TOOLONGCALL>APRS:>x",
        ):
            with self.subTest(raw=raw):
                self.assertFalse(parse_packet(raw, source="aprs_is").valid)

    def test_rejects_invalid_third_party_header(self):
        packet = parse_packet('N0CALL>APRS:}N0X">APRS,TCPIP,N0CALL*:>x', source="rf")
        self.assertFalse(packet.valid)

    def test_accepts_valid_third_party_header(self):
        packet = parse_packet("N0CALL>APRS:}CW0003>APRS,TCPIP,N0CALL*:>x", source="rf")
        self.assertTrue(packet.valid)
        self.assertEqual(packet.from_call, "CW0003")


class HandlerDropsMalformedPacketsTests(unittest.TestCase):
    def setUp(self):
        self.tracker = MagicMock()
        self.tracker.is_blocked_callsign.return_value = False
        self.tracker.track_packet = AsyncMock()
        self.igate = MagicMock()
        self.handler = PacketHandler(Config(), self.tracker, None, self.igate, AsyncMock())
        self.handler.aprs_is = AsyncMock()

    def assert_dropped(self):
        self.tracker.track_packet.assert_not_awaited()
        self.igate.should_gate_rf_to_is.assert_not_called()
        self.igate.should_gate_is_to_rf.assert_not_called()

    def test_rf_text_packet(self):
        asyncio.run(self.handler.handle_rf_aprs_packet('N0X"bad>APRS,WIDE1-1:>x'))
        self.assert_dropped()

    def test_aprs_is_packet(self):
        asyncio.run(self.handler.handle_is_packet('N0X"bad>APRS,TCPIP*:>x'))
        self.assert_dropped()

    def test_rf_frame_with_valid_addresses_and_bad_third_party_header(self):
        data = frame_bytes()[:-len(">status")] + b'}N0X">APRS,TCPIP,N0CALL*:>x'
        asyncio.run(self.handler.handle_rf_packet(data))
        self.assert_dropped()

    def test_valid_packet_is_tracked(self):
        asyncio.run(self.handler.handle_rf_aprs_packet("N0CALL>APRS,WIDE1-1:>x"))
        self.tracker.track_packet.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
