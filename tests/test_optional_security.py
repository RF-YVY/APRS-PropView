"""Real middleware coverage for optional login and headless browser setup."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from server.app import create_app
from server.config import Config
from server.operator_auth import OperatorAuth, set_password
from tests.test_operator_auth import Browser


class OptionalSecurityTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'config.toml'
        self.auth_path = self.path.with_name('operator-auth.json')
        self.config = Config()
        self.handler = MagicMock()
        self.handler.transmit_beacon_now = AsyncMock(return_value={'sent': True})
        self.ws = MagicMock()
        self.app = create_app(self.config, MagicMock(), MagicMock(), self.ws,
                              self.handler, config_path=self.path)
        self.auth = self.app.state.operator_auth
        self.owner = Browser(self.app)
        self.viewer = Browser(self.app)

    async def asyncTearDown(self):
        self.temp.cleanup()

    async def status(self, browser):
        code, data = await browser.request('GET', '/api/auth/status')
        self.assertEqual(code, 200)
        browser.csrf = data['csrf_token'] or ''
        return data

    async def security(self, browser, enabled, password=None, headers=None):
        return await browser.request('POST', '/api/auth/security',
            {'enabled': enabled, 'password': password},
            {'x-propview-csrf': browser.csrf, **(headers or {})})

    async def test_default_unlocked_and_csrf_still_required(self):
        data = await self.status(self.owner)
        self.assertFalse(data['enabled'])
        self.assertTrue(data['authenticated'])
        self.assertIsNone(data['expires_at'])
        self.assertEqual((await self.owner.beacon())[0], 200)
        self.assertEqual((await self.viewer.beacon())[0], 403)
        self.assertEqual((await self.owner.beacon(origin='https://evil.example'))[0], 403)
        self.assertFalse(self.auth_path.exists())

    async def test_headless_enable_is_atomic_and_isolates_viewers(self):
        await self.status(self.owner)
        await self.status(self.viewer)
        for password in [None, '', 'short', 'x' * 257]:
            self.assertEqual((await self.security(self.owner, True, password))[0], 400)
            self.assertFalse((await self.status(self.owner))['enabled'])
        code, data = await self.security(self.owner, True, 'my new password')
        self.assertEqual(code, 200)
        self.owner.csrf = data['csrf_token']
        self.assertTrue(data['enabled'])
        self.assertTrue(data['authenticated'])
        self.assertEqual((await self.owner.beacon())[0], 200)
        self.assertEqual((await self.viewer.beacon())[0], 401)
        self.assertEqual((await self.security(self.viewer, False))[0], 401)
        self.assertEqual((await self.security(self.viewer, True, 'attacker password'))[0], 401)
        self.assertNotIn('my new password', self.auth_path.read_text())
        self.assertTrue(OperatorAuth(self.auth_path).status('')['enabled'])
        self.assertEqual((await self.viewer.login('my new password'))[0], 200)

    async def test_disable_persists_and_reenable_requires_new_password(self):
        set_password(self.auth_path, 'existing password')
        await self.owner.login('existing password')
        code, data = await self.security(self.owner, False)
        self.assertEqual(code, 200)
        self.assertFalse(data['enabled'])
        self.assertFalse(OperatorAuth(self.auth_path).status('')['enabled'])
        await self.status(self.viewer)
        self.assertEqual((await self.viewer.beacon())[0], 200)
        self.assertEqual((await self.security(self.viewer, True))[0], 400)
        code, data = await self.security(self.viewer, True, 'replacement password')
        self.assertEqual(code, 200)
        self.assertEqual((await self.owner.beacon())[0], 401)
        self.assertEqual((await self.owner.login('existing password'))[0], 401)

    async def test_setup_rejects_cross_origin_missing_csrf_and_invalid_types(self):
        await self.status(self.owner)
        self.assertEqual((await self.security(self.owner, True, 'safe password',
            {'origin': 'https://evil.example'}))[0], 403)
        self.assertEqual((await self.security(self.owner, True, 'safe password',
            {'x-propview-csrf': ''}))[0], 403)
        for enabled in ['true', 1, None, {}]:
            self.assertEqual((await self.security(self.owner, enabled, 'safe password'))[0], 400)
        self.assertFalse(self.auth_path.exists())

    async def test_legacy_password_keeps_protection(self):
        set_password(self.auth_path, 'legacy password')
        record = json.loads(self.auth_path.read_text())
        record.pop('enabled')
        self.auth_path.write_text(json.dumps(record))
        self.assertTrue((await self.status(self.viewer))['enabled'])
        self.assertEqual((await self.viewer.beacon())[0], 401)
        self.assertEqual((await self.owner.login('legacy password'))[0], 200)

    async def test_existing_websocket_loses_operator_data_when_enabled(self):
        message = {'type': 'private-message', 'data': {'secret': 'private'}}
        socket = MagicMock()
        socket.cookies = {}
        # The app installs a delivery-time filter on the manager.
        manager_filter = self.ws.message_filter
        self.assertEqual(manager_filter(socket, message), message)
        await self.status(self.owner)
        await self.security(self.owner, True, 'new password')
        self.assertIsNone(manager_filter(socket, message))
