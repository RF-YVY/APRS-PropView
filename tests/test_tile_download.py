import ssl
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock, patch

from server.app import _download_tile


class TileDownloadTests(unittest.TestCase):
    def test_download_trusts_system_and_bundled_certificates(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'tile.png'
            response = MagicMock()
            response.status = 200
            response.read.return_value = b'tile'
            with patch('server.app._tile_cache_path', return_value=path), \
                    patch('server.app.ssl.create_default_context', wraps=ssl.create_default_context) as create, \
                    patch('server.app.urllib.request.urlopen') as open_url, \
                    patch('server.app.TILE_CACHE_BUDGET.store', return_value=path) as store:
                open_url.return_value.__enter__.return_value = response
                self.assertEqual(_download_tile('https://tiles.example/{z}/{x}/{y}.png', 8, 139, 85), path)
                create.assert_called_once_with()
                context = open_url.call_args.kwargs['context']
                self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
                self.assertTrue(context.check_hostname)
                self.assertGreater(context.cert_store_stats()['x509_ca'], 0)
                store.assert_called_once_with(path, b'tile')

    def test_failed_download_logs_tls_reason_without_custom_url_credentials(self):
        with tempfile.TemporaryDirectory() as temp:
            error = ssl.SSLCertVerificationError(1, 'certificate verify failed')
            error.verify_message = 'unable to get local issuer certificate'
            with patch('server.app._tile_cache_path', return_value=Path(temp) / 'tile.png'), \
                    patch('server.app.urllib.request.urlopen', side_effect=urllib.error.URLError(error)), \
                    self.assertLogs('propview.app', level='WARNING') as logs:
                self.assertIsNone(_download_tile('https://tiles.example/{z}/{x}/{y}?key=secret', 8, 139, 85))
            self.assertIn('unable to get local issuer certificate', logs.output[0])
            self.assertNotIn('secret', logs.output[0])

    def test_cached_tile_needs_no_network_or_certificate_setup(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'tile.png'
            path.write_bytes(b'cached')
            with patch('server.app._tile_cache_path', return_value=path), \
                    patch('server.app.urllib.request.urlopen') as open_url, \
                    patch('server.app.ssl.create_default_context') as context:
                self.assertEqual(_download_tile('https://tiles.example/{z}/{x}/{y}.png', 8, 139, 85), path)
                open_url.assert_not_called()
                context.assert_not_called()
