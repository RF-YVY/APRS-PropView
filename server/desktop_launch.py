"""Local shortcut-to-running-app handoff, protected by an owner-only capability."""
import json
import secrets
import urllib.request
from pathlib import Path

from server.config_io import atomic_write


def register_desktop_launcher(config_path, url):
    path = Path(config_path).with_name('operator-desktop.json')
    secret = secrets.token_urlsafe(32)
    atomic_write(path, json.dumps({'url': url, 'secret': secret}))
    path.chmod(0o600)
    return secret


def open_existing_dashboard(config_path):
    """A second local launch never receives an operator token over HTTP."""
    try:
        data = json.loads(Path(config_path).with_name('operator-desktop.json').read_text(encoding='utf-8'))
        request = urllib.request.Request(data['url'] + '/api/auth/desktop-open',
            data=json.dumps({'secret': data['secret']}).encode(),
            headers={'Content-Type': 'application/json'}, method='POST')
        # Do not leak a local capability to a system-configured HTTP proxy.
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(request, timeout=5) as response:
            return response.status == 200
    except (OSError, ValueError, KeyError, TypeError):
        return False
