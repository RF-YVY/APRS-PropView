import unittest

from server.aprs_is import APRSISClient
from server.ax25 import AX25Address, AX25Frame
from server.config import Config
from server.igate import IGate


def gate_config():
    config = Config()
    config.station.callsign = "W1AW"
    config.station.ssid = 10
    config.igate.enabled = True
    config.igate.rf_to_is = True
    return config


class FakeWriter:
    def __init__(self):
        self.data = b""

    def write(self, data):
        self.data += data

    async def drain(self):
        pass


class IGateLineInjectionTests(unittest.TestCase):
    def test_rf_payload_is_cut_at_first_crlf(self):
        gate = IGate(gate_config())
        raw = "K1ABC>APRS,WIDE1-1:>test\r\nN0FAKE>APRS,TCPIP*:!4903.50N/07201.75W-forged"
        self.assertEqual(
            gate.should_gate_rf_to_is(raw, "K1ABC"),
            "K1ABC>APRS,WIDE1-1,qAR,W1AW-10:>test",
        )

    def test_bare_cr_and_bare_lf_both_end_the_line(self):
        gate = IGate(gate_config())
        for sep in ("\r", "\n"):
            gated = gate.should_gate_rf_to_is(f"K1ABC>APRS:>one{sep}two", "K1ABC")
            self.assertEqual(gated, "K1ABC>APRS,qAR,W1AW-10:>one")

    def test_third_party_inner_packet_is_cut_too(self):
        gate = IGate(gate_config())
        raw = "K1ABC>APRS,WIDE2-1:}K2XYZ>APRS,K1ABC*:>inner\rN0FAKE>APRS:>forged"
        self.assertEqual(
            gate.should_gate_rf_to_is(raw, "K1ABC"),
            "K2XYZ>APRS,K1ABC*,qAR,W1AW-10:>inner",
        )

    def test_newline_before_info_cannot_supply_a_later_header(self):
        gate = IGate(gate_config())
        for raw in ('\rK1ABC>APRS:>test', 'K1ABC>APRS\nN0FAKE>APRS:>test',
                    'K1ABC>APRS:}K2XYZ>APRS\r:>inner'):
            with self.subTest(raw=raw):
                self.assertIsNone(gate.should_gate_rf_to_is(raw, 'K1ABC'))

    def test_payload_without_crlf_is_unchanged(self):
        gate = IGate(gate_config())
        info = ">trailing spaces and \x1c Mic-E bytes stay   "
        self.assertEqual(
            gate.should_gate_rf_to_is(f"K1ABC>APRS:{info}", "K1ABC"),
            f"K1ABC>APRS,qAR,W1AW-10:{info}",
        )

    def test_decoded_rf_frame_gates_as_one_line(self):
        gate = IGate(gate_config())
        frame = AX25Frame(
            destination=AX25Address.from_string("APRS"),
            source=AX25Address.from_string("K1ABC"),
            info=b">test\r\nN0FAKE>APRS,TCPIP*:>forged",
        )
        decoded = AX25Frame.decode(frame.encode())
        gated = gate.should_gate_rf_to_is(decoded.to_aprs_string(), decoded.from_call)
        self.assertEqual(gated, "K1ABC>APRS,qAR,W1AW-10:>test")


class APRSISSendTests(unittest.IsolatedAsyncioTestCase):
    def connected_client(self):
        client = APRSISClient(gate_config(), on_packet=None)
        client.connected = True
        client.verified = True
        client.writer = FakeWriter()
        return client

    async def test_send_refuses_embedded_crlf(self):
        client = self.connected_client()
        for packet in ("A>B:x\r\nN0FAKE>APRS:y", "A>B:x\ry", "A>B:x\ny"):
            self.assertFalse(await client.send(packet))
        self.assertEqual(client.writer.data, b"")

    async def test_send_writes_one_terminated_line(self):
        client = self.connected_client()
        self.assertTrue(await client.send("A>B:x"))
        self.assertEqual(client.writer.data, b"A>B:x\r\n")


if __name__ == "__main__":
    unittest.main()
