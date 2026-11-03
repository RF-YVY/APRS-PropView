import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import server.operator_auth as operator_auth
from server.app import create_app
from server.config import Config
from server.operator_auth import set_password
from tests.test_operator_auth import PASSWORD, Browser


class LoginLockoutTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        path = Path(self.temp.name) / 'config.toml'
        config = Config()
        config.save(path)
        set_password(path.with_name('operator-auth.json'), PASSWORD)
        self.app = create_app(config, MagicMock(), MagicMock(), MagicMock(), MagicMock(), config_path=path)
        self.auth = self.app.state.operator_auth
        # The limits count attempts in a one-minute window. Freeze the clock so
        # a flood stays inside one window on a slow runner, and swap PBKDF2 for
        # a plain comparison so hundreds of checks don't take minutes.
        # test_operator_auth.py covers the real hash.
        clock = patch.object(operator_auth, 'time', types.SimpleNamespace(time=lambda: 1_900_000_000.0))
        clock.start()
        self.addCleanup(clock.stop)
        self.auth.verify = lambda password, record: password == PASSWORD

    async def flood(self, addresses):
        statuses = []
        for ip in addresses:
            browser = Browser(self.app, ip=ip)
            for _ in range(6):
                status, _ = await browser.login(password='wrong')
                statuses.append(status)
        return statuses

    async def test_operator_signs_in_while_ten_addresses_flood_bad_logins(self):
        statuses = await self.flood([f'203.0.113.{n}' for n in range(1, 11)])
        self.assertIn(429, statuses)
        status, _ = await Browser(self.app, ip='198.51.100.77').login()
        self.assertEqual(status, 200)

    async def test_flooding_addresses_stay_limited_under_pressure(self):
        await self.flood([f'203.0.113.{n}' for n in range(1, 11)])
        for n in range(1, 11):
            status, _ = await Browser(self.app, ip=f'203.0.113.{n}').login()
            self.assertEqual(status, 429, n)

    async def test_global_ceiling_caps_guesses_however_many_addresses(self):
        statuses = await self.flood([f'10.0.{n // 256}.{n % 256}' for n in range(200)])
        self.assertEqual(statuses.count(401), 120)

    async def test_public_request_limits_group_ipv6_by_64(self):
        from server.resource_limits import PublicRequestLimits
        limits = PublicRequestLimits()
        results = []
        for n in range(1, 80):
            results.append(limits.acquire(f'2001:db8:7:8::{n:x}', '/api/status'))
            limits.release()
        self.assertIn(429, results)
        self.assertIsNone(limits.acquire('2001:db8:7:9::1', '/api/status'))

    async def test_ipv6_addresses_in_one_64_share_a_bucket(self):
        for n in range(1, 6):
            status, _ = await Browser(self.app, ip=f'2001:db8:1:2::{n}').login(password='wrong')
            self.assertEqual(status, 401)
        status, _ = await Browser(self.app, ip='2001:db8:1:2::99').login()
        self.assertEqual(status, 429)
        status, _ = await Browser(self.app, ip='2001:db8:1:3::1').login()
        self.assertEqual(status, 200)

    async def test_full_verification_queue_answers_429_without_hashing(self):
        self.auth.login_waiting = self.auth.MAX_LOGIN_WAITING
        status, data = await Browser(self.app, ip='198.51.100.77').login()
        self.assertEqual(status, 429)
        self.assertIn('busy', data['message'])


if __name__ == '__main__':
    unittest.main()
