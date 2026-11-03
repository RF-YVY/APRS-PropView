import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock

from server.websocket_manager import WebSocketManager


def _socket():
    return MagicMock(accept=AsyncMock(), close=AsyncMock(), send_text=AsyncMock())


class WebSocketFairnessTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.manager = WebSocketManager()
        self.addAsyncCleanup(self.manager.close)

    async def fill(self, peers, per_peer):
        sockets = {}
        for peer in peers:
            sockets[peer] = []
            for _ in range(per_peer):
                socket = _socket()
                self.assertTrue(await self.manager.connect(socket, peer=peer))
                sockets[peer].append(socket)
        return sockets

    async def test_new_browser_gets_in_when_four_addresses_hold_every_public_slot(self):
        held = await self.fill([f'203.0.113.{n}' for n in range(1, 5)], 4)
        newcomer = _socket()
        self.assertTrue(await self.manager.connect(newcomer, peer='198.51.100.7'))
        self.assertIn(newcomer, self.manager.active_connections)
        evicted = [s for group in held.values() for s in group if s not in self.manager.active_connections]
        self.assertEqual(evicted, [held['203.0.113.1'][0]])
        await asyncio.sleep(0.05)
        evicted[0].close.assert_awaited()

    async def test_twenty_idle_anonymous_sockets_admit_four_new_browsers(self):
        for n in range(1, 6):
            for _ in range(4):
                await self.manager.connect(_socket(), peer=f'203.0.113.{n}')
        for n in range(4):
            self.assertTrue(await self.manager.connect(_socket(), peer=f'198.51.100.{n}'))
        self.assertEqual(len(self.manager._public_peers), self.manager.MAX_PUBLIC_CONNECTIONS)

    async def test_an_address_never_evicts_itself_or_an_equal(self):
        await self.fill([f'203.0.113.{n}' for n in range(1, 17)], 1)
        late = _socket()
        self.assertFalse(await self.manager.connect(late, peer='198.51.100.7'))
        late.close.assert_awaited_with(code=1013, reason='Too many connections')

    async def test_evictions_stop_once_holdings_are_level(self):
        await self.fill(['203.0.113.1'], 4)
        await self.fill([f'198.51.100.{n}' for n in range(1, 13)], 1)
        for n in range(20, 23):
            self.assertTrue(await self.manager.connect(_socket(), peer=f'192.0.2.{n}'))
        self.assertEqual(list(self.manager._public_peers.values()).count('203.0.113.1'), 1)
        self.assertFalse(await self.manager.connect(_socket(), peer='192.0.2.99'))

    async def test_operators_keep_their_reserved_slots(self):
        await self.fill([f'203.0.113.{n}' for n in range(1, 5)], 4)
        for _ in range(4):
            self.assertTrue(await self.manager.connect(_socket(), operator=True, peer='203.0.113.1'))

    async def test_socket_evicted_during_its_handshake_is_not_started(self):
        self.manager.MAX_PUBLIC_CONNECTIONS = 2
        release = asyncio.Event()
        slow = _socket()
        slow.accept = AsyncMock(side_effect=release.wait)
        first = asyncio.create_task(self.manager.connect(slow, peer='203.0.113.1'))
        await asyncio.sleep(0)
        self.assertTrue(await self.manager.connect(_socket(), peer='203.0.113.1'))
        self.assertTrue(await self.manager.connect(_socket(), peer='198.51.100.7'))
        release.set()
        self.assertFalse(await first)
        self.assertNotIn(slow, self.manager._queues)
        self.assertNotIn(slow, self.manager._senders)

    async def test_handshake_broken_by_eviction_returns_false(self):
        self.manager.MAX_PUBLIC_CONNECTIONS = 2
        release = asyncio.Event()
        slow = _socket()

        async def accept():
            await release.wait()
            raise RuntimeError('Cannot call "send" once a close message has been sent.')

        slow.accept = AsyncMock(side_effect=accept)
        first = asyncio.create_task(self.manager.connect(slow, peer='203.0.113.1'))
        await asyncio.sleep(0)
        self.assertTrue(await self.manager.connect(_socket(), peer='203.0.113.1'))
        self.assertTrue(await self.manager.connect(_socket(), peer='198.51.100.7'))
        release.set()
        self.assertFalse(await first)
        self.assertNotIn(slow, self.manager.active_connections)

    async def test_handshake_failure_without_eviction_still_raises(self):
        broken = _socket()
        broken.accept = AsyncMock(side_effect=RuntimeError('boom'))
        with self.assertRaises(RuntimeError):
            await self.manager.connect(broken, peer='203.0.113.1')
        self.assertNotIn(broken, self.manager.active_connections)


if __name__ == '__main__':
    unittest.main()
