"""The APRS-IS connect loop, driven against a real socket on 127.0.0.1."""
import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from starlette.requests import Request

from server.app import create_app
from server.aprs_is import APRSISClient
from server.config import Config


class FakeServer:
    """Answers each login, then keeps the socket open unless told otherwise."""

    def __init__(self, close_after_login=False, send_comments=True):
        self.close_after_login = close_after_login
        self.send_comments = send_comments
        self.logins = []
        self.login_times = []
        self.server = None
        self.port = 0
        self.writers = []

    async def start(self, port=0):
        self.server = await asyncio.start_server(self.handle, '127.0.0.1', port)
        self.port = self.server.sockets[0].getsockname()[1]
        return self

    async def handle(self, reader, writer):
        self.writers.append(writer)
        if self.send_comments:
            writer.write(b'# fake-aprsis 0.1\r\n')
            await writer.drain()
        login = await reader.readline()
        loop = asyncio.get_running_loop()
        self.logins.append(login.decode('ascii').strip())
        self.login_times.append(loop.time())
        if self.send_comments:
            writer.write(b'# logresp W1AW unverified, server FAKE\r\n')
            await writer.drain()
        if self.close_after_login:
            writer.close()
            return
        await reader.read()
        writer.close()

    async def stop(self):
        self.server.close()
        for writer in self.writers:
            writer.close()
        await self.server.wait_closed()

    async def wait_for_logins(self, count, timeout=2):
        async def poll():
            while len(self.logins) < count:
                await asyncio.sleep(.01)
        await asyncio.wait_for(poll(), timeout)


def make_config(port, callsign='W1AW'):
    config = Config()
    config.station.callsign = callsign
    config.aprs_is.server = '127.0.0.1'
    config.aprs_is.port = port
    return config


class ConnectLoopCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.task = None
        self.server = None

    async def asyncTearDown(self):
        if self.task:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
        if self.server:
            await self.server.stop()

    def start(self, config):
        client = APRSISClient(config, AsyncMock())
        client._handshake_timeout = .05
        self.task = asyncio.create_task(client.connect())
        return client


class SettingsChangeTests(ConnectLoopCase):
    async def test_placeholder_callsign_connects_once_a_callsign_is_saved(self):
        self.server = await FakeServer().start()
        config = make_config(self.server.port, 'N0CALL')
        client = self.start(config)
        await asyncio.sleep(.05)
        self.assertEqual(self.server.logins, [])
        self.assertFalse(self.task.done())

        config.station.callsign = 'W1AW'
        await client.reconnect()
        await self.server.wait_for_logins(1)
        self.assertIn('user W1AW ', self.server.logins[0])

    async def test_placeholder_callsign_is_never_sent_after_a_change_back(self):
        self.server = await FakeServer().start()
        config = make_config(self.server.port)
        client = self.start(config)
        await self.server.wait_for_logins(1)

        config.station.callsign = 'N0CALL'
        await client.reconnect()
        await asyncio.sleep(.05)
        self.assertEqual(len(self.server.logins), 1)
        self.assertFalse(client.connected)

    async def test_disabling_disconnects_and_stays_down_until_enabled(self):
        self.server = await FakeServer().start()
        config = make_config(self.server.port)
        client = self.start(config)
        await self.server.wait_for_logins(1)

        config.aprs_is.enabled = False
        await client.reconnect()
        await asyncio.sleep(.05)
        self.assertEqual(len(self.server.logins), 1)
        self.assertFalse(client.connected)

        config.aprs_is.enabled = True
        await client.reconnect()
        await self.server.wait_for_logins(2)

    async def test_saved_settings_cut_a_backoff_wait_short(self):
        idle = await FakeServer().start()
        port = idle.port
        await idle.stop()
        config = make_config(port)
        client = self.start(config)
        client._reconnect_delay = 30
        await asyncio.sleep(.05)

        self.server = await FakeServer().start()
        config.aprs_is.port = self.server.port
        await client.reconnect()
        await self.server.wait_for_logins(1)


class SaveRouteTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addAsyncCleanup(self.cleanup)
        self.path = Path(self.temp.name) / 'config.toml'
        self.config = make_config(14580)

    async def cleanup(self):
        self.temp.cleanup()

    async def save(self, client, payload):
        app = create_app(self.config, MagicMock(), MagicMock(), MagicMock(), MagicMock(),
                         aprs_is=client, config_path=self.path)
        endpoint = next(r.endpoint for r in app.routes if getattr(r, 'path', '') == '/api/config/save')

        async def receive():
            return {'type': 'http.request', 'body': json.dumps(payload).encode()}
        return await endpoint(Request(
            {'type': 'http', 'method': 'POST', 'path': '/api/config/save', 'headers': []}, receive))

    async def test_callsign_change_reconnects(self):
        client = MagicMock(reconnect=AsyncMock())
        result = await self.save(client, {'station': {'callsign': 'K5ABC', 'latitude': 36, 'longitude': -91}})
        self.assertTrue(result['success'])
        client.reconnect.assert_awaited_once()

    async def test_ssid_change_reconnects(self):
        client = MagicMock(reconnect=AsyncMock())
        await self.save(client, {'station': {'callsign': 'W1AW', 'ssid': 10, 'latitude': 36, 'longitude': -91}})
        client.reconnect.assert_awaited_once()

    async def test_unrelated_save_leaves_the_connection_alone(self):
        client = MagicMock(reconnect=AsyncMock())
        await self.save(client, {'station': {'callsign': 'W1AW', 'latitude': 36, 'longitude': -91}})
        client.reconnect.assert_not_awaited()

    async def test_enabling_with_no_client_reports_restart_required(self):
        self.config.aprs_is.enabled = False
        result = await self.save(None, {'aprs_is': {'enabled': True}})
        self.assertTrue(result['success'])
        self.assertIn('APRS-IS', result['applicationRestartReasons'])


class BackoffTests(ConnectLoopCase):
    async def test_server_that_closes_after_login_is_not_hammered(self):
        self.server = await FakeServer(close_after_login=True).start()
        client = APRSISClient(make_config(self.server.port), AsyncMock())
        client._handshake_timeout = .05
        client._reconnect_delay = .1
        self.task = asyncio.create_task(client.connect())
        await asyncio.sleep(.45)

        times = self.server.login_times
        gaps = [later - earlier for earlier, later in zip(times, times[1:])]
        self.assertLessEqual(len(times), 3)
        self.assertGreaterEqual(len(gaps), 1)
        self.assertGreaterEqual(gaps[0], .09)
        if len(gaps) > 1:
            self.assertGreaterEqual(gaps[1], .18)

    async def test_lasting_session_resets_the_backoff(self):
        self.server = await FakeServer(close_after_login=True).start()
        client = APRSISClient(make_config(self.server.port), AsyncMock())
        client._handshake_timeout = .05
        client._reconnect_delay = .1
        client._stable_session = 0
        self.task = asyncio.create_task(client.connect())
        await self.server.wait_for_logins(4)

        times = self.server.login_times
        gaps = [later - earlier for earlier, later in zip(times, times[1:])]
        self.assertLess(max(gaps), .19)

    async def test_settings_change_on_a_live_session_redials_at_once(self):
        self.server = await FakeServer().start()
        client = APRSISClient(make_config(self.server.port), AsyncMock())
        client._handshake_timeout = .05
        client._reconnect_delay = 30
        self.task = asyncio.create_task(client.connect())
        await self.server.wait_for_logins(1)

        await client.reconnect()
        await self.server.wait_for_logins(2)
