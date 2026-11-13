import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from server.packet_handler import PacketHandler


def make_handler(ifaces, aprs_is=None):
    handler = object.__new__(PacketHandler)
    handler.config = SimpleNamespace(
        station=SimpleNamespace(
            full_callsign="N0CALL",
            latitude=37.8,
            longitude=-122.1,
            comment="test",
            phg="",
            equipment="",
            beacon_path="WIDE1-1",
        )
    )
    handler.rf_interfaces = ifaces
    handler.aprs_is = aprs_is
    handler.stats = {"rf_tx": 0}
    handler.heard_me = MagicMock()
    handler.tracker = SimpleNamespace(my_lat=37.8, my_lon=-122.1)
    handler._station_symbol_for_beacon = lambda: {"symbol_table": "/", "symbol_code": "-"}
    handler._record_tx_packet = AsyncMock()
    handler.record_transmit_history = MagicMock()
    return handler


def iface(rx_only_rf):
    return SimpleNamespace(
        name="Direwolf", connected=True, can_transmit=True,
        rx_only_rf=rx_only_rf, rx_only_is=True, send=AsyncMock(return_value=True),
    )


class BeaconRxOnlyTests(unittest.IsolatedAsyncioTestCase):
    async def test_rx_only_port_skips_beacon_and_does_not_log_tx(self):
        port = iface(rx_only_rf=True)
        handler = make_handler([port])
        with self.assertLogs("propview.handler", level="INFO") as logs:
            await handler._send_beacon("rf")
        port.send.assert_not_called()
        handler._record_tx_packet.assert_not_called()
        output = "\n".join(logs.output)
        self.assertNotIn("Beacon RF TX:", output)
        self.assertIn("Beacon RF skipped", output)

    async def test_tx_capable_port_logs_tx(self):
        port = iface(rx_only_rf=False)
        handler = make_handler([port])
        with self.assertLogs("propview.handler", level="INFO") as logs:
            await handler._send_beacon("rf")
        port.send.assert_awaited_once()
        self.assertIn("Beacon RF TX: N0CALL>APPRPV via WIDE1-1", "\n".join(logs.output))

    async def test_rejected_send_logs_failure_not_tx(self):
        port = iface(rx_only_rf=False)
        port.send = AsyncMock(return_value=False)
        handler = make_handler([port])
        with self.assertLogs("propview.handler", level="INFO") as logs:
            await handler._send_beacon("rf")
        output = "\n".join(logs.output)
        self.assertNotIn("Beacon RF TX:", output)
        self.assertIn("Beacon RF TX failed", output)


if __name__ == "__main__":
    unittest.main()
