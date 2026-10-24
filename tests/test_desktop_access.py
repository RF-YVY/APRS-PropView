import json
import tempfile
import types
from pathlib import Path
from unittest.mock import patch

from server.desktop_access import show_password_dialog
from server.desktop_launch import register_desktop_launcher, open_existing_dashboard
from server.release_notes import ReleaseNotes, RELEASES


def test_fresh_install_no_popup_upgrade_shown_once_and_survives_restart():
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / 'release-state.json'
        initial = ReleaseNotes(path, '1.11.1')
        assert not initial.pending
        upgrade = ReleaseNotes(path, '1.12.0')
        assert upgrade.snapshot(True)['should_show']
        assert not upgrade.snapshot(False)['should_show']
        assert not upgrade.acknowledge('1.11.1')
        assert ReleaseNotes(path, '1.12.0').pending
        assert upgrade.acknowledge('1.12.0')
        assert not ReleaseNotes(path, '1.12.0').pending
        assert RELEASES['1.12.0']


def test_existing_install_migration_gets_notes_without_previous_state_file():
    with tempfile.TemporaryDirectory() as directory:
        assert ReleaseNotes(Path(directory) / 'release-state.json', '1.12.0', True).pending


def test_headless_password_setup_leaves_credentials_untouched():
    with tempfile.TemporaryDirectory() as directory, patch('server.desktop_access.sys.platform', 'linux'), patch.dict('os.environ', {}, clear=True):
        path = Path(directory) / 'operator-auth.json'
        assert not show_password_dialog(path)
        assert not path.exists()


def test_shortcut_capability_is_written_locally_and_bypasses_http_proxies():
    with tempfile.TemporaryDirectory() as directory:
        config = Path(directory) / 'config.toml'
        secret = register_desktop_launcher(config, 'http://127.0.0.1:14501')
        data = json.loads(config.with_name('operator-desktop.json').read_text())
        assert data['secret'] == secret
        with patch('server.desktop_launch.urllib.request.build_opener') as build:
            build.return_value.open.return_value.__enter__.return_value.status = 200
            assert open_existing_dashboard(config)
            request = build.return_value.open.call_args.args[0]
            assert request.full_url == 'http://127.0.0.1:14501/api/auth/desktop-open'
            assert json.loads(request.data)['secret'] == secret
            assert request.method == 'POST'


def test_missing_shortcut_record_fails_safely():
    with tempfile.TemporaryDirectory() as directory:
        assert not open_existing_dashboard(Path(directory) / 'config.toml')


def test_password_window_validates_confirmation_and_saves_local_preference():
    """Drive the GUI's real Save callback with fake widgets, without opening a desktop."""
    from server.operator_auth import OperatorAuth
    strings, booleans, buttons = [], [], {}

    class Variable:
        def __init__(self, value=''): self.value = value
        def get(self): return self.value
        def set(self, value): self.value = value

    def variable(collection, value=''):
        result = Variable(value)
        collection.append(result)
        return result

    class Widget:
        def __init__(self, *args, **kwargs):
            if 'command' in kwargs:
                buttons[kwargs['text']] = kwargs['command']
        def grid(self, **kwargs): pass
        def pack(self, **kwargs): pass
        def focus_set(self): pass

    class Window:
        def title(self, value): pass
        def resizable(self, *args): pass
        def bind(self, *args): pass
        def destroy(self): pass
        def mainloop(self):
            strings[0].set('a long test operator password')
            strings[1].set('different confirmation')
            buttons['Save password']()
            assert 'do not match' in strings[2].get()
            assert not path.exists()
            strings[1].set(strings[0].get())
            booleans[0].set(False)
            buttons['Save password']()

    ttk = types.SimpleNamespace(**{name: Widget for name in ('Frame', 'Label', 'Entry', 'Checkbutton', 'Button')})
    tk = types.SimpleNamespace(Tk=Window, ttk=ttk,
        StringVar=lambda: variable(strings), BooleanVar=lambda value: variable(booleans, value))
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / 'operator-auth.json'
        with patch('server.desktop_access.sys.platform', 'win32'), patch.dict('sys.modules', {'tkinter': tk}):
            assert show_password_dialog(path)
        auth = OperatorAuth(path)
        auth.reload()
        assert auth.verify('a long test operator password', auth.record)
        assert auth.record['local_auto_login'] is False
