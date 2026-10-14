import json
import ssl
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import certifi

from server.app import _merge_secret_value
from server.config import Config
from server.weather import _sync_http_get, _weather_ssl_context


class ReportedRegressionTests(unittest.TestCase):
    def test_mqtt_password_survives_unrelated_save_and_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.toml'
            config = Config()
            config.mqtt.password = 'broker-secret'
            config.save(path)
            restarted = Config.load(path)
            restarted.mqtt.password = _merge_secret_value(
                restarted.mqtt.password, '', submitted_present=False,
            )
            restarted.save(path)
            self.assertEqual(Config.load(path).mqtt.password, 'broker-secret')

    def test_weather_context_adds_bundle_to_system_roots(self):
        with patch('server.weather.ssl.create_default_context') as create:
            context = _weather_ssl_context()
            create.assert_called_once_with()
            context.load_verify_locations.assert_called_once_with(cafile=certifi.where())

    def test_weather_request_uses_verified_context(self):
        context = _weather_ssl_context()
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(context.check_hostname)
        response = MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps({'ok': True}).encode()
        with patch('server.weather._weather_ssl_context', return_value=context), patch(
            'server.weather.urllib.request.urlopen', return_value=response,
        ) as urlopen:
            self.assertEqual(_sync_http_get('https://example.com/weather'), {'ok': True})
            self.assertIs(urlopen.call_args.kwargs['context'], context)
