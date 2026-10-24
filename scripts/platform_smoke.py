"""Exercise a real headless deployment without radio, browser or Internet feeds."""
import argparse
from contextlib import contextmanager
import json
import os
import socket
import signal
import secrets
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from server.config import Config


@contextmanager
def smoke_workspace():
    workspace = tempfile.TemporaryDirectory()
    try:
        yield workspace.name
    finally:
        # Windows may release a killed child's SQLite handles after its parent
        # exits. Retry only this test's freshly created temporary directory.
        assert Path(workspace.name).resolve().parent == Path(tempfile.gettempdir()).resolve()
        for attempt in range(20):
            try:
                workspace.cleanup()
                break
            except (PermissionError, NotADirectoryError):
                if attempt == 19:
                    raise
                time.sleep(.25)


def run(executable=None, verify_address=None):
    with smoke_workspace() as temp:
        data = Path(temp)
        config = Config()
        config.aprs_is.enabled = False
        config.weather.space_weather_enabled = False
        config.propagation.psk_reporter_enabled = False
        config.station.beacon_interval = 0
        config.save(data / 'config.toml')
        from server.operator_auth import set_password
        set_password(data / 'operator-auth.json', secrets.token_urlsafe(24))
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        env = dict(os.environ, PROPVIEW_DEPLOYMENT='1', PROPVIEW_DATA_DIR=str(data),
                   PROPVIEW_CONFIG=str(data / 'config.toml'), PROPVIEW_DB=str(data / 'smoke.db'),
                   PROPVIEW_HOST='0.0.0.0', PROPVIEW_PORT=str(port), PROPVIEW_LAUNCH_BROWSER='none')
        command = [str(Path(executable).resolve())] if executable else [sys.executable, str(ROOT / 'main.py')]
        with (data / 'startup.log').open('w+') as log:
            process = subprocess.Popen(command, env=env, stdout=log, stderr=subprocess.STDOUT,
                                       start_new_session=os.name != 'nt')
            try:
                opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                for _ in range(150):
                    if process.poll() is not None:
                        raise RuntimeError('Application exited before becoming healthy.')
                    try:
                        with opener.open(f'http://127.0.0.1:{port}/api/health', timeout=1) as response:
                            result = json.load(response)
                        if result.get('ok'):
                            break
                    except OSError:
                        pass
                    time.sleep(.2)
                else:
                    raise RuntimeError('Application did not become healthy.')
                with opener.open(f'http://127.0.0.1:{port}/', timeout=2) as response:
                    assert 'APRS PropView' in response.read().decode()
                with opener.open(f'http://127.0.0.1:{port}/mobile', timeout=2) as response:
                    assert 'APRS' in response.read().decode()
                if verify_address:
                    for suffix in ('/api/health', '/mobile'):
                        with opener.open(f'http://{verify_address}:{port}{suffix}', timeout=3) as response:
                            assert response.status == 200
                assert (data / 'smoke.db').is_file(), 'Deployment data directory was ignored.'
                assert not (data / 'propview-development.db').exists(), 'Explicit DB override was ignored.'
                print('PASS: headless startup, configured port, desktop/mobile pages, health and persistent data path')
                if verify_address:
                    print('PASS: desktop health and mobile access through interface '+verify_address)
            except Exception:
                log.flush()
                log.seek(0)
                print(log.read())
                raise
            finally:
                if os.name == 'nt':
                    # PyInstaller one-file executables have a bootloader child.
                    subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                else:
                    try:
                        os.killpg(process.pid, signal.SIGTERM)
                    except ProcessLookupError:
                        pass
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--executable')
    parser.add_argument('--verify-address')
    options = parser.parse_args()
    run(options.executable, options.verify_address)
