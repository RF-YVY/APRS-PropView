import asyncio
import base64
import io
import os
import hashlib
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
            'installer_url': 'https://github.com/RF-YVY/APRS-PropView/releases/download/v2/APRSPropViewSetup-2.exe',
            'installer_name': 'APRSPropViewSetup-2.exe',
            'installer_sha256': hashlib.sha256(b'x' * 2 * 1024 * 1024).hexdigest(),
            'installer_size': 2 * 1024 * 1024,
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
        response.geturl.return_value = checker.get_status.return_value['installer_url']
        with patch('server.app._sys.platform', 'win32'), patch('server.update_install.create_staging_directory', return_value=tmp_path), patch('server.update_install.release_opener') as opener, patch('server.app.subprocess.Popen') as spawn:
            opener.return_value.open.return_value = response
            tasks = BackgroundTasks()
            result = await install(tasks)
            assert result['success']
            progress = await state()
            assert progress['phase'] == 'installing'
            assert progress['downloaded_bytes'] == progress['total_bytes'] == 2 * 1024 * 1024
            assert spawn.call_args.kwargs['env']['PYINSTALLER_RESET_ENVIRONMENT'] == '1'
            script = base64.b64decode(spawn.call_args.args[0][-1]).decode('utf-16le')
            assert 'Wait-Process' in script and '/PROPVIEWINAPPUPDATE=1' in script
            assert 'Get-FileHash -LiteralPath' in script and 'integrity check failed' in script
            assert len(tasks.tasks) == 1  # Shutdown scheduled only after helper starts.
            assert (await install(BackgroundTasks())).status_code == 409
    asyncio.run(run())


def test_installer_rejects_missing_digest_before_staging(tmp_path):
    from server.update_install import download_installer
    import pytest
    with patch('server.update_install.create_staging_directory') as staging:
        with pytest.raises(ValueError, match='SHA-256'):
            download_installer('https://github.com/RF-YVY/APRS-PropView/releases/download/v2/APRSPropViewSetup.exe',
                               'APRSPropViewSetup.exe', '', 2 * 1024 * 1024, {})
        staging.assert_not_called()


def test_installer_digest_and_streaming_size_fail_closed(tmp_path):
    from server.update_install import download_installer
    import pytest
    url = 'https://github.com/RF-YVY/APRS-PropView/releases/download/v2/APRSPropViewSetup.exe'
    data = b'x' * 1024 * 1024
    for case in ('digest', 'overflow', 'truncated', 'length'):
        directory = tmp_path / case
        directory.mkdir()
        response = MagicMock()
        response.__enter__.return_value = response
        response.geturl.return_value = 'https://release-assets.githubusercontent.com/github-production-release-asset/test'
        response.headers = {} if case != 'length' else {'Content-Length': '999999999'}
        response.read = io.BytesIO(data + b'x' if case == 'overflow' else data).read
        digest = '0' * 64 if case == 'digest' else hashlib.sha256(data).hexdigest()
        size = len(data) + 1 if case == 'truncated' else len(data)
        with patch('server.update_install.create_staging_directory', return_value=directory), patch('server.update_install.release_opener') as opener:
            opener.return_value.open.return_value = response
            with pytest.raises(ValueError):
                download_installer(url, 'APRSPropViewSetup.exe', digest, size, {})
        assert not directory.exists()


def test_updater_redirects_and_project_origin_are_restricted():
    from server.update_install import validate_download_url, TrustedReleaseRedirects
    import urllib.request
    import pytest
    for url in ('http://github.com/RF-YVY/APRS-PropView/releases/download/v2/a.exe',
                'https://github.com/attacker/repo/releases/download/v2/a.exe',
                'https://github.com.evil.example/RF-YVY/APRS-PropView/releases/download/v2/a.exe'):
        with pytest.raises(ValueError):
            validate_download_url(url, initial=True)
    request = urllib.request.Request('https://github.com/RF-YVY/APRS-PropView/releases/download/v2/a.exe')
    for url in ('http://objects.githubusercontent.com/a', 'https://evil.example/a'):
        with pytest.raises(ValueError):
            TrustedReleaseRedirects().redirect_request(request, None, 302, 'Found', {}, url)


def test_github_asset_digest_is_carried_to_update_status():
    from server.update_checker import UpdateChecker
    digest = 'ab' * 32
    result = UpdateChecker._installer_asset_from_release({'assets': [{
        'name': 'APRSPropViewSetup-2.exe', 'browser_download_url': 'https://github.com/test',
        'digest': 'sha256:' + digest, 'size': 1234567}]})
    assert result['installer_sha256'] == digest
    assert result['installer_size'] == 1234567


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
