"""Server age survives independent public browser sessions and socket filtering."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from server.app import create_app
from server.config import Config
from server.operator_auth import public_socket_message
from server.packet_handler import PacketHandler
from tests.test_operator_auth import Browser


class ServerUptimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_public_browsers_receive_existing_server_age(self):
        with tempfile.TemporaryDirectory() as temp:
            handler = PacketHandler(Config(), MagicMock(), None, None, MagicMock())
            app = create_app(handler.config, MagicMock(), MagicMock(), MagicMock(), handler,
                             config_path=Path(temp) / 'config.toml')
            started = handler.stats['start_time']
            with patch('server.packet_handler.time.time', return_value=started + 7200):
                first_status, first = await Browser(app).request('GET', '/api/status')
            with patch('server.packet_handler.time.time', return_value=started + 7210):
                next_status, reopened = await Browser(app).request('GET', '/api/status')
                socket = public_socket_message({'type': 'status', 'data': handler.get_status()})
            self.assertEqual((first_status, next_status), (200, 200))
            self.assertEqual(first['uptime_seconds'], 7200)
            self.assertEqual(reopened['uptime_seconds'], 7210)
            self.assertEqual(socket['data']['uptime_seconds'], 7210)
            self.assertEqual(handler.stats['start_time'], started)
            with patch('server.packet_handler.time.time', return_value=started + 8000):
                restarted = PacketHandler(Config(), MagicMock(), None, None, MagicMock())
                self.assertEqual(restarted.get_status()['uptime_seconds'], 0)
