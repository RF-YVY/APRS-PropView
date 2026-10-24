import asyncio
import base64
import io
import os
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import BackgroundTasks

from server.app import create_app
from server.config import Config
from server.update_install import installer_environment


def test_installer_environment_is_independent():
    with patch.dict(os.environ, {'_PYI_APPLICATION_HOME_DIR': 'deleted-temp',
                                 '_PYI_PARENT_PROCESS_LEVEL': '1',
                                 '_MEIPASS2': 'deleted-temp', 'PROPVIEW_PORT': '8080'}):
        env = installer_environment()
        assert not any(key.startswith(('_PYI_', '_MEIPASS')) for key in env)
        assert env['PYINSTALLER_RESET_ENVIRONMENT'] == '1'
        assert env['PROPVIEW_PORT'] == '8080'
        assert os.environ['_PYI_APPLICATION_HOME_DIR'] == 'deleted-temp'


def test_update_handoff_progress_and_duplicate_guard(tmp_path):
    async def run():
        checker = MagicMock()
        checker.get_status = AsyncMock(return_value={
            'update_available': True,
            'installer_url': 'https://github.com/test/setup.exe',
            'installer_name': 'setup.exe',
        })
        app = create_app(Config(), MagicMock(), MagicMock(), MagicMock(),
                         MagicMock(), update_checker=checker)
        endpoints = {route.path: route.endpoint for route in app.routes if hasattr(route, 'endpoint')}
        install = endpoints['/api/update-install']
        state = endpoints['/api/update-install-status']
        assert (await state())['phase'] == 'idle'
        response = MagicMock()
        response.headers = {'Content-Length': str(2 * 1024 * 1024)}
        response.read = io.BytesIO(b'x' * 2 * 1024 * 1024).read
        response.__enter__.return_value = response
        with patch('server.app._sys.platform', 'win32'), patch('server.app.tempfile.gettempdir', return_value=str(tmp_path)), patch('server.app.urllib.request.urlopen', return_value=response), patch('server.app.subprocess.Popen') as spawn:
            tasks = BackgroundTasks()
            result = await install(tasks)
            assert result['success']
            progress = await state()
            assert progress['phase'] == 'installing'
            assert progress['downloaded_bytes'] == progress['total_bytes'] == 2 * 1024 * 1024
            assert spawn.call_args.kwargs['env']['PYINSTALLER_RESET_ENVIRONMENT'] == '1'
            script = base64.b64decode(spawn.call_args.args[0][-1]).decode('utf-16le')
            assert 'Wait-Process' in script and '/PROPVIEWINAPPUPDATE=1' in script
            assert len(tasks.tasks) == 1  # Shutdown scheduled only after helper starts.
            assert (await install(BackgroundTasks())).status_code == 409
    asyncio.run(run())


def test_failed_download_can_be_retried():
    async def run():
        checker = MagicMock()
        checker.get_status = AsyncMock(return_value={
            'update_available': True, 'installer_url': 'https://untrusted.example/setup.exe',
        })
        app = create_app(Config(), MagicMock(), MagicMock(), MagicMock(), MagicMock(), update_checker=checker)
        routes = {route.path: route.endpoint for route in app.routes if hasattr(route, 'endpoint')}
        with patch('server.app._sys.platform', 'win32'), patch('server.app.subprocess.Popen') as spawn:
            for _ in range(2):
                tasks = BackgroundTasks()
                assert (await routes['/api/update-install'](tasks)).status_code == 502
                assert (await routes['/api/update-install-status']())['phase'] == 'failed'
                assert not tasks.tasks
            spawn.assert_not_called()
    asyncio.run(run())
