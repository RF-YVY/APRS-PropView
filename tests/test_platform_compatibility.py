import os
import plistlib
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from server.modem_library import library_name


class DeploymentTests(unittest.TestCase):
    def test_macos_bundle_keeps_other_artifacts_and_declares_microphone(self):
        import build_macos
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            unrelated = root / 'dist' / 'existing-installer.exe'
            unrelated.parent.mkdir()
            unrelated.write_bytes(b'keep')
            app = root / 'dist' / f'{build_macos.APP_NAME}.app'

            def package(*args, **kwargs):
                info = app / 'Contents' / 'Info.plist'
                info.parent.mkdir(parents=True)
                info.write_bytes(plistlib.dumps({'CFBundleIdentifier': build_macos.BUNDLE_ID}))
                return SimpleNamespace(returncode=0)

            with patch.object(build_macos, 'PROJECT_ROOT', root), \
                 patch.object(build_macos, 'check_macos'), \
                 patch.object(build_macos, 'ensure_pyinstaller'), \
                 patch.object(build_macos, 'ensure_runtime_dependencies'), \
                 patch.object(build_macos, 'build_icns', return_value=None), \
                 patch('build_macos.subprocess.run', side_effect=package), \
                 patch('build_macos.subprocess.check_call') as commands:
                build_macos.build()
            self.assertEqual(unrelated.read_bytes(), b'keep')
            info = plistlib.loads((app / 'Contents' / 'Info.plist').read_bytes())
            self.assertTrue(info['NSMicrophoneUsageDescription'])
            self.assertEqual(info['CFBundleIdentifier'], 'com.wickermade.aprspropview')
            entitlements = plistlib.loads((root / 'build/macos/entitlements.plist').read_bytes())
            self.assertTrue(entitlements['com.apple.security.device.audio-input'])
            self.assertEqual(commands.call_args.args[0][-1], str(app))
            self.assertEqual(commands.call_args.args[0][0], 'codesign')

    def test_deployment_preserves_container_overrides_and_data(self):
        from main import _runtime_environment
        original = Path.cwd()
        try:
            with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {
                'PROPVIEW_DEPLOYMENT': '1', 'PROPVIEW_DATA_DIR': temp,
                'PROPVIEW_HOST': '0.0.0.0', 'PROPVIEW_PORT': '14501',
                'PROPVIEW_DB': str(Path(temp) / 'custom.db'),
            }, clear=True):
                _runtime_environment()
                working = Path.cwd()
                os.chdir(original)
                self.assertEqual(working, Path(temp).resolve())
                self.assertEqual(os.environ['PROPVIEW_HOST'], '0.0.0.0')
                self.assertEqual(os.environ['PROPVIEW_PORT'], '14501')
                self.assertEqual(os.environ['PROPVIEW_DB'], str(Path(temp) / 'custom.db'))
                self.assertEqual(os.environ['PROPVIEW_LAUNCH_BROWSER'], 'none')
                self.assertEqual(Path(os.environ['PROPVIEW_CONFIG']), Path(temp).resolve() / 'config.toml')
                os.chdir(original)
        finally:
            os.chdir(original)

    def test_platform_names(self):
        self.assertEqual(library_name('linux'), 'libpropview_modem.so')
        self.assertEqual(library_name('darwin'), 'libpropview_modem.dylib')
        self.assertEqual(library_name('win32'), 'propview_modem.dll')

    def test_tray_is_not_started_on_mac_or_headless_linux(self):
        from main import _start_tray
        for platform in ('darwin', 'linux'):
            with patch('main.sys.platform', platform), patch.dict(os.environ, {}, clear=True):
                self.assertIsNone(_start_tray('', None, None, None))

    def test_headless_password_confirmation(self):
        from server.desktop_access import set_console_password
        from server.operator_auth import OperatorAuth
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'operator-auth.json'
            with patch('getpass.getpass', side_effect=['abcdef', 'different']):
                with self.assertRaises(ValueError):
                    set_console_password(path)
            self.assertFalse(path.exists())
            with patch('getpass.getpass', side_effect=['abcdef', 'abcdef']):
                set_console_password(path)
            auth = OperatorAuth(path)
            auth.reload()
            self.assertIsNotNone(auth.record)


class UnixPttTests(unittest.IsolatedAsyncioTestCase):
    async def test_unix_serial_device_paths_are_preserved_and_conflicts_blocked(self):
        import sounddevice  # Load the real host backend before simulating other OS names.
        from server.modem_transmit import ModemTransmitter
        modem = SimpleNamespace(connected=True, stream=SimpleNamespace(active=True), handler=SimpleNamespace(rf_interfaces=[]))
        tx = ModemTransmitter(modem)
        for platform, port in [('linux', '/dev/ttyUSB0'), ('darwin', '/dev/cu.usbserial-AbC')]:
            with patch('server.modem_transmit.sys.platform', platform), \
                 patch.object(tx, 'outputs', return_value=[{'id': 1, 'name': 'Radio', 'host_api': 'Test', 'channels': 2}]), \
                 patch.object(tx, 'ports', return_value=[{'device': port}]), \
                 patch('sounddevice.check_output_settings'):
                body = {'enabled': True, 'device': 1, 'port': port, 'ptt': 'serial_rts'}
                await tx.configure(body)
                self.assertEqual(tx.settings['port'], port)
                with self.assertRaises(ValueError):
                    await tx.configure({**body, 'port': port.upper()})
                modem.handler.rf_interfaces = [SimpleNamespace(port=port)]
                with self.assertRaisesRegex(ValueError, 'already assigned'):
                    await tx.configure(body)
                modem.handler.rf_interfaces = []
