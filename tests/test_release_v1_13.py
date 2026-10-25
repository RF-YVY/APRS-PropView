import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from server.config import Config
from server.release_notes import ReleaseNotes, migrate_network_settings


class ReleaseTests(unittest.TestCase):
    def test_network_defaults_and_one_time_dev_migration(self):
        config = Config()
        self.assertEqual((config.web.host, config.web.port), ('0.0.0.0', 14501))
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'config.toml'
            config.web.host, config.web.port = '127.0.0.1', 14502
            config.save(path)
            migrate_network_settings(config, path, '1.13.0')
            self.assertEqual((config.web.host, config.web.port), ('0.0.0.0', 14501))
            ReleaseNotes(path.with_name('release-state.json'), '1.13.0')
            config.web.host, config.web.port = '127.0.0.1', 14502
            migrate_network_settings(config, path, '1.13.0')
            self.assertEqual((config.web.host, config.web.port), ('127.0.0.1', 14502))

    def test_new_install_shows_full_changelog_once(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'release-state.json'
            release = ReleaseNotes(path, '1.13.0')
            self.assertFalse(release.snapshot(False)['should_show'])
            self.assertTrue(release.snapshot(True)['should_show'])
            self.assertEqual(release.snapshot(True)['changelog_url'], '/static/releases/v1.13.0.html')
            self.assertTrue(release.acknowledge('1.13.0'))
            self.assertFalse(ReleaseNotes(path, '1.13.0').snapshot(True)['should_show'])

    def test_release_bundles_full_notes_and_modem_disclaimer(self):
        root = Path(__file__).resolve().parents[1]
        text = (root / 'CHANGELOG.md').read_text(encoding='utf-8')
        self.assertEqual(text, (root / 'docs/release-v1.14.1.md').read_text(encoding='utf-8'))
        html = (root / 'static/releases/v1.14.1.html').read_text(encoding='utf-8')
        self.assertIn('changes since v1.11.1', html)
        self.assertIn('Further radio and hardware testing is needed', html)
        modem = (root / 'static/js/software-modem.js').read_text(encoding='utf-8')
        self.assertIn('Experimental modem:', modem)
        self.assertIn('placeholder="W1AW"', (root / 'static/js/aprs-spot.js').read_text())
        self.assertNotIn('>K5YVY</text>', (root / 'static/index.html').read_text(encoding='utf-8'))


class ReleaseWebTests(unittest.IsolatedAsyncioTestCase):
    async def test_stable_release_has_modem_desktop_mobile_and_notes(self):
        from server.app import create_app
        from tests.test_operator_auth import Browser
        with tempfile.TemporaryDirectory() as temp:
            handler = MagicMock()
            handler.rf_interfaces = []
            path = Path(temp) / 'config.toml'
            app = create_app(Config(), MagicMock(), MagicMock(), MagicMock(), handler,
                             app_version='1.13.0', config_path=path)
            self.assertIsNotNone(app.state.software_modem)
            self.assertEqual(len(handler.rf_interfaces), 1)
            browser = Browser(app)
            for endpoint, expected in [('/', 'v1.13.0'), ('/mobile', 'APRS'),
                                       ('/static/releases/v1.13.0.html', 'changes since v1.11.1')]:
                code, content = await browser.request('GET', endpoint)
                self.assertEqual(code, 200)
                self.assertIn(expected, content)
