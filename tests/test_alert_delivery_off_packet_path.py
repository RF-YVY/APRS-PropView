"""A slow notification service never holds up packet handling."""
import asyncio
import logging
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from server.alerts import AlertConfig, AlertManager
from server.ax25 import AX25Address, AX25Frame
from server.config import Config
from server.database import Database
from server.digipeater import Digipeater
from server.packet_handler import PacketHandler
from server.station_tracker import StationTracker
from server.websocket_manager import WebSocketManager

GUARD = 5  # A timeout here means the path is still waiting on delivery.


def position_frame() -> bytes:
    """A direct RF position report roughly 150 km north of the station."""
    return AX25Frame(
        destination=AX25Address("APRS"),
        source=AX25Address("W1AW", 9),
        digipeaters=[AX25Address("WIDE1", 1)],
        info=b"!3530.00N/09730.00W-first heard",
    ).encode()


def discord_manager() -> AlertManager:
    return AlertManager(
        AlertConfig(
            enabled=True,
            discord_enabled=True,
            discord_webhook_url="https://discord.invalid/webhook",
            quiet_start="",
            quiet_end="",
        ),
        station_callsign="K5ABC",
    )


class PacketPathTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.config = Config()
        self.config.station.callsign = "K5ABC"
        self.config.station.latitude = 34.0
        self.config.station.longitude = -97.5
        self.config.digipeater.enabled = True
        self.db = Database(f"{self.tmp.name}/test.db")
        await self.db.initialize()
        self.addAsyncCleanup(self.db.close)
        self.tracker = StationTracker(self.db, self.config, WebSocketManager())
        self.alerts = discord_manager()
        self.tracker.set_alert_manager(self.alerts)
        self.handler = PacketHandler(
            self.config, self.tracker, Digipeater(self.config), None, WebSocketManager()
        )
        self.interface = SimpleNamespace(name="TNC", connected=True, send=AsyncMock())
        self.handler.rf_interfaces = [self.interface]

    async def test_stalled_discord_does_not_hold_the_digipeat(self):
        release = asyncio.Event()
        started = asyncio.Event()

        async def stalled(alert):
            started.set()
            await release.wait()

        self.alerts._send_discord = stalled
        await asyncio.wait_for(
            self.handler.handle_rf_packet(position_frame(), self.interface), GUARD
        )
        self.interface.send.assert_awaited_once()
        await asyncio.wait_for(started.wait(), GUARD)
        self.assertEqual(len(self.alerts._delivery_tasks), 1)

        release.set()
        await asyncio.wait_for(asyncio.gather(*self.alerts._delivery_tasks), GUARD)
        await asyncio.sleep(0)
        self.assertEqual(len(self.alerts._delivery_tasks), 0)

    async def test_stalled_discord_does_not_hold_the_mqtt_alert(self):
        release = asyncio.Event()

        async def stalled(alert):
            await release.wait()

        self.alerts._send_discord = stalled
        publisher = SimpleNamespace(
            watched_callsigns=[],
            publish_event=AsyncMock(),
            publish_alert=AsyncMock(),
            publish_status_snapshot=AsyncMock(),
            publish_propagation=AsyncMock(),
            publish_watched_station=AsyncMock(),
        )
        self.tracker.set_mqtt_publisher(publisher)
        await asyncio.wait_for(
            self.handler.handle_rf_packet(position_frame(), self.interface), GUARD
        )
        publisher.publish_alert.assert_awaited_once()
        release.set()
        await asyncio.gather(*self.alerts._delivery_tasks)


class DeliveryTaskTests(unittest.IsolatedAsyncioTestCase):
    async def first_heard(self, manager):
        return await asyncio.wait_for(
            manager.check_first_heard("W1AW-9", 150.0, 0.0), GUARD
        )

    async def test_channel_failure_is_logged(self):
        manager = discord_manager()
        manager._send_discord = AsyncMock(side_effect=OSError("webhook unreachable"))
        with self.assertLogs("propview.alerts", logging.ERROR) as logs:
            await self.first_heard(manager)
            await asyncio.gather(*manager._delivery_tasks)
        self.assertIn("webhook unreachable", "\n".join(logs.output))

    async def test_failure_outside_the_channels_is_logged(self):
        manager = discord_manager()
        manager.send_alert = AsyncMock(side_effect=ValueError("bad alert"))
        with self.assertLogs("propview.alerts", logging.ERROR) as logs:
            await self.first_heard(manager)
            await asyncio.gather(*manager._delivery_tasks, return_exceptions=True)
            await asyncio.sleep(0)
        self.assertIn("bad alert", "\n".join(logs.output))
        self.assertEqual(len(manager._delivery_tasks), 0)

    async def test_cancelling_a_delivery_at_shutdown_is_silent(self):
        manager = discord_manager()

        async def stalled(alert):
            await asyncio.Event().wait()

        manager._send_discord = stalled
        with self.assertNoLogs("propview.alerts", logging.ERROR):
            await self.first_heard(manager)
            await asyncio.sleep(0)
            for task in list(manager._delivery_tasks):
                task.cancel()
            await asyncio.gather(*manager._delivery_tasks, return_exceptions=True)
            await asyncio.sleep(0)
        self.assertEqual(len(manager._delivery_tasks), 0)

    async def test_alert_is_returned_with_its_message(self):
        manager = discord_manager()
        manager._send_discord = AsyncMock()
        alert = await self.first_heard(manager)
        self.assertEqual(alert["type"], "first_heard")
        await asyncio.gather(*manager._delivery_tasks)
        manager._send_discord.assert_awaited_once_with(alert)


if __name__ == "__main__":
    unittest.main()
