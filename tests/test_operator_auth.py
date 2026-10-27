"""Exercise the real ASGI middleware with independent browser cookie jars.

Transmit handlers are mocks; these tests never open RF/APRS-IS connections.
"""
import asyncio
import json
import tempfile
import unittest
from http.cookies import SimpleCookie
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from server.app import create_app
from server.config import Config
from server.operator_auth import COOKIE, set_password, public_socket_message, same_origin
from server.websocket_manager import WebSocketManager
from starlette.websockets import WebSocket

PASSWORD = 'local test operator passphrase'


class Browser:
    def __init__(self, app, host='public.example', scheme='https', ip='198.51.100.10'):
        self.app, self.host, self.scheme, self.ip = app, host, scheme, ip
        self.cookie = ''
        self.csrf = ''
        self.last_headers = {}

    async def request(self, method, path, body=None, headers=None):
        raw = json.dumps(body or {}).encode()
        outgoing = {'host': self.host, 'content-type': 'application/json',
                    'content-length': str(len(raw))}
        if self.cookie:
            outgoing['cookie'] = self.cookie
        outgoing.update(headers or {})
        scope = {'type': 'http', 'asgi': {'version': '3.0'}, 'http_version': '1.1',
                 'method': method, 'scheme': self.scheme, 'path': path,
                 'raw_path': path.encode(), 'query_string': b'', 'root_path': '',
                 'headers': [(k.encode(), v.encode()) for k, v in outgoing.items()],
                 'client': (self.ip, 50000), 'server': ('127.0.0.1', 14501)}
        sent, delivered = [], False

        async def receive():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {'type': 'http.request', 'body': raw, 'more_body': False}
            await asyncio.Event().wait()

        async def send(message):
            sent.append(message)

        await self.app(scope, receive, send)
        start = next(item for item in sent if item['type'] == 'http.response.start')
        self.last_headers = {k.decode(): v.decode() for k, v in start['headers']}
        cookie = self.last_headers.get('set-cookie')
        if cookie:
            jar = SimpleCookie(cookie)
            self.cookie = f'{COOKIE}={jar[COOKIE].value}'
        data = b''.join(item.get('body', b'') for item in sent)
        try:
            data = json.loads(data)
        except ValueError:
            data = data.decode()
        return start['status'], data

    async def login(self, password=PASSWORD, duration=3600):
        status, data = await self.request('POST', '/api/auth/login',
                                          {'password': password, 'duration': duration},
                                          {'x-propview-login': '1', 'origin': f'{self.scheme}://{self.host}'})
        self.csrf = data.get('csrf_token', '')
        return status, data

    async def beacon(self, **headers):
        return await self.request('POST', '/api/beacon/transmit', {'mode': 'rf'},
                                  {'x-propview-csrf': self.csrf, **headers})


class OperatorAccessTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'config.toml'
        self.auth_path = self.path.with_name('operator-auth.json')
        self.config = Config()
        self.config.alerts.discord_webhook_url = 'private-webhook-secret'
        self.config.web.mobile_pin = 'private-pin'
        self.config.web.map_tile_source = 'custom'
        self.config.web.map_tile_url = 'https://tiles.example/{z}/{x}/{y}?key=private-key'
        self.config.save(self.path)
        self.handler = MagicMock()
        self.handler.transmit_beacon_now = AsyncMock(return_value={'sent': True})
        self.handler.get_status.return_value = {'station': 'N0TEST', 'rf_connected': True,
                                               'gps': {'secret': 'private GPS'}, 'rf_interfaces': ['private port']}
        self.weather = MagicMock()
        self.weather.get_all = AsyncMock(return_value={'enabled': True, 'configured': True,
            'map_overlays': {'radar_provider': 'custom_xyz', 'radar_enabled': True,
                             'radar_custom_api_key': 'private-radar-key',
                             'radar_custom_url': 'https://radar.example/private-radar-key'}})
        self.ws = MagicMock()
        self.app = create_app(self.config, MagicMock(), MagicMock(), self.ws,
                              self.handler, weather_manager=self.weather, config_path=self.path)
        self.auth = self.app.state.operator_auth
        self.operator = Browser(self.app)
        self.viewer = Browser(self.app)  # Deliberately the SAME IP as the operator.

    async def asyncTearDown(self):
        self.temp.cleanup()

    async def test_no_localhost_vpn_or_header_bypass_before_setup(self):
        for ip in ['127.0.0.1', '::1', '100.71.11.34', '198.51.100.10']:
            browser = Browser(self.app, ip=ip)
            status, _ = await browser.beacon(**{'x-forwarded-for': '127.0.0.1'})
            self.assertEqual(status, 401)
        status, data = await self.viewer.request('GET', '/api/auth/status')
        self.assertEqual(status, 200)
        self.assertFalse(data['configured'])
        self.assertEqual((await self.viewer.login())[0], 403)
        self.assertEqual((await self.viewer.request('POST', '/api/auth/reset'))[0], 401)
        self.handler.transmit_beacon_now.assert_not_awaited()

    async def test_only_the_browser_that_logged_in_can_operate_repeatedly(self):
        set_password(self.auth_path, PASSWORD)
        self.assertEqual((await self.operator.login())[0], 200)
        cookie = self.operator.last_headers['set-cookie'].lower()
        for attribute in ['httponly', 'secure', 'samesite=strict', 'max-age=3600', 'path=/']:
            self.assertIn(attribute, cookie)
        self.assertNotIn('domain=', cookie)
        for _ in range(3):
            self.assertEqual((await self.operator.beacon())[0], 200)
            self.assertEqual((await self.viewer.beacon())[0], 401)
        _, public = await self.viewer.request('GET', '/api/auth/status')
        self.assertFalse(public['authenticated'])
        self.assertIsNone(public['csrf_token'])
        self.assertEqual((await self.viewer.beacon(**{'x-propview-csrf': self.operator.csrf}))[0], 401)
        self.assertEqual(self.handler.transmit_beacon_now.await_count, 3)

    async def test_sessions_expire_without_any_new_login_prompt_per_action(self):
        set_password(self.auth_path, PASSWORD)
        _, data = await self.operator.login(duration=900)
        self.assertGreater(data['expires_at'], 0)
        self.assertEqual((await self.operator.beacon())[0], 200)
        for session in self.auth.sessions.values():
            session['expires_at'] = 1
        self.assertEqual((await self.operator.beacon())[0], 401)
        self.assertEqual((await self.operator.request('GET', '/api/config/export'))[0], 401)

    async def test_logout_revokes_only_this_browser(self):
        set_password(self.auth_path, PASSWORD)
        await self.operator.login()
        await self.viewer.login()
        self.assertNotEqual(self.operator.cookie, self.viewer.cookie)
        old_cookie = self.operator.cookie
        self.assertEqual((await self.operator.request('POST', '/api/auth/logout',
            headers={'x-propview-csrf': self.operator.csrf}))[0], 200)
        self.operator.cookie = old_cookie
        self.assertEqual((await self.operator.beacon())[0], 401)
        self.assertEqual((await self.viewer.beacon())[0], 200)

    async def test_local_reset_revokes_all_browsers_while_server_is_running(self):
        set_password(self.auth_path, PASSWORD)
        await self.operator.login()
        await self.viewer.login()
        set_password(self.auth_path, 'replacement operator passphrase')
        self.assertEqual((await self.operator.beacon())[0], 401)
        self.assertEqual((await self.viewer.beacon())[0], 401)
        self.assertEqual((await self.operator.login())[0], 401)
        self.assertEqual((await self.operator.login('replacement operator passphrase'))[0], 200)
        self.assertNotIn('replacement operator passphrase', self.auth_path.read_text())

    async def test_missing_or_cross_origin_csrf_cannot_transmit(self):
        set_password(self.auth_path, PASSWORD)
        await self.operator.login()
        self.assertEqual((await self.operator.beacon(**{'x-propview-csrf': ''}))[0], 403)
        self.assertEqual((await self.operator.beacon(origin='https://evil.example'))[0], 403)
        self.assertEqual((await self.operator.beacon(origin='https://sibling.public.example'))[0], 403)
        self.assertEqual((await self.operator.beacon(origin='https://public.example'))[0], 200)
        self.assertEqual((await self.viewer.request('POST', '/api/auth/login',
            {'password': PASSWORD}, {'origin': 'https://evil.example', 'x-propview-login': '1'}))[0], 403)

    async def test_existing_and_future_privileged_routes_are_denied_by_default(self):
        @self.app.get('/api/new-sensitive-route')
        async def new_route():
            return {'secret': 'do not publish'}
        for route in self.app.routes:
            path = getattr(route, 'path', '')
            if not path.startswith('/api/') or path in {'/api/auth/login', '/api/auth/local-login'}:
                continue
            for method in (getattr(route, 'methods', set()) or set()) & {'POST', 'PUT', 'PATCH', 'DELETE'}:
                with self.subTest(path=path, method=method):
                    self.assertEqual((await self.viewer.request(method, path))[0], 401)
        for path in ['/api/config/export', '/api/messages', '/api/messages/contacts',
                     '/api/diagnostics', '/api/storage', '/api/browsers', '/api/weather/refresh',
                     '/api/transmit/history', '/api/update-status', '/api/new-sensitive-route']:
            self.assertEqual((await self.viewer.request('GET', path))[0], 401, path)

    async def test_public_display_is_sanitized_and_never_cached(self):
        for path in ['/api/config', '/api/weather', '/api/status', '/api/health']:
            status, data = await self.viewer.request('GET', path)
            self.assertEqual(status, 200)
            self.assertNotIn('private-', json.dumps(data))
            self.assertEqual(self.viewer.last_headers['cache-control'], 'no-store')
            self.assertIn('cookie', {value.strip().lower() for value in self.viewer.last_headers['vary'].split(',')})
        _, config = await self.viewer.request('GET', '/api/config')
        self.assertEqual(config['web']['map_tile_url'], '/api/map-tiles/{z}/{x}/{y}')
        set_password(self.auth_path, PASSWORD)
        await self.operator.login()
        _, operator_config = await self.operator.request('GET', '/api/config')
        self.assertEqual(operator_config['web']['mobile_pin'], 'private-pin')
        self.assertEqual((await self.operator.request('GET', '/api/config/export'))[0], 200)
        self.assertNotIn('digest', json.dumps(operator_config))

    async def test_watched_paths_are_private_over_http(self):
        tracker = AsyncMock()
        tracker.get_propagation_data.return_value = {'score': 12}
        tracker.evaluate_watched_paths.return_value = {'opportunities': [{'callsign': 'PRIVATE-TARGET'}]}
        app = create_app(self.config, MagicMock(), tracker, MagicMock(), self.handler, config_path=self.path)
        viewer = Browser(app)
        status, data = await viewer.request('GET', '/api/propagation')
        self.assertEqual(status, 200)
        self.assertEqual(data['watched_paths']['opportunities'], [])
        set_password(self.auth_path, PASSWORD)
        await viewer.login()
        _, data = await viewer.request('GET', '/api/propagation')
        self.assertEqual(data['watched_paths']['opportunities'][0]['callsign'], 'PRIVATE-TARGET')

    async def test_host_cannot_hide_a_protected_route(self):
        for host in ('public.example/not-api?', 'public.example#', 'public.example@evil.example',
                     'public.example\\not-api'):
            with self.subTest(host=host):
                browser = Browser(self.app, host=host)
                self.assertEqual((await browser.request('GET', '/api/config/export'))[0], 400)
                self.assertEqual((await browser.beacon())[0], 400)
        self.handler.transmit_beacon_now.assert_not_awaited()

    async def test_unc_path_is_rejected_before_static_resolution(self):
        from unittest.mock import patch
        with patch('starlette.staticfiles.os.path.realpath', side_effect=AssertionError('must not resolve UNC')):
            self.assertEqual((await self.viewer.request('GET', '/static/\\\\audit.invalid\\share'))[0], 400)

    async def test_websocket_permissions_follow_each_browser_and_expiry(self):
        set_password(self.auth_path, PASSWORD)
        await self.operator.login()
        token = self.operator.cookie.split('=', 1)[1]
        operator_socket = MagicMock(cookies={COOKIE: token})
        public_socket = MagicMock(cookies={})
        message = {'type': 'message', 'data': {'text': 'private message'}}
        gate = self.ws.message_filter
        self.assertEqual(gate(operator_socket, message), message)
        self.assertIsNone(gate(public_socket, message))
        for session in self.auth.sessions.values():
            session['expires_at'] = 1
        self.assertIsNone(gate(operator_socket, message))
        self.assertIsNone(public_socket_message({'type': 'gps_location', 'data': {}}))
        self.assertIsNone(public_socket_message({'type': 'packet', 'data': {'packet_type': 'message'}}))
        self.assertEqual(public_socket_message({'type': 'stats', 'data': {'rf_rx': 4}})['data']['rf_rx'], 4)

    async def test_login_rate_limit_and_invalid_duration(self):
        set_password(self.auth_path, PASSWORD)
        self.assertEqual((await self.operator.login(duration=99999999))[0], 400)
        for _ in range(5):
            self.assertEqual((await self.operator.login(password='wrong'))[0], 401)
        self.assertEqual((await self.operator.login())[0], 429)

    async def test_corrupt_or_deleted_credentials_fail_closed(self):
        set_password(self.auth_path, PASSWORD)
        await self.operator.login()
        self.auth_path.write_text('{}')
        self.assertEqual((await self.operator.beacon())[0], 401)
        self.assertEqual((await self.operator.login())[0], 403)
        self.auth_path.unlink()
        self.assertEqual((await self.viewer.beacon())[0], 401)

    async def test_websocket_origin_accepts_matching_http_origin_only(self):
        for scheme, origin, expected in [('ws', 'http://public.example', True),
                                         ('wss', 'https://public.example', True),
                                         ('wss', 'https://evil.example', False),
                                         ('wss', 'http://public.example', False)]:
            socket = WebSocket({'type': 'websocket', 'scheme': scheme, 'path': '/ws',
                'query_string': b'', 'headers': [(b'host', b'public.example'), (b'origin', origin.encode())]},
                receive=AsyncMock(), send=AsyncMock())
            self.assertEqual(same_origin(socket), expected)

    async def test_queued_private_websocket_data_is_filtered_after_expiry(self):
        set_password(self.auth_path, PASSWORD)
        await self.operator.login()

        class Socket:
            cookies = {COOKIE: self.operator.cookie.split('=', 1)[1]}
            sent = []

            async def accept(self): pass
            async def close(self, **kwargs): pass
            async def send_text(self, text): self.sent.append(json.loads(text))

        manager, socket = WebSocketManager(), Socket()
        manager.message_filter = self.ws.message_filter
        await manager.connect(socket)
        await manager.broadcast({'type': 'message', 'data': {'text': 'private message'}})
        for session in self.auth.sessions.values():
            session['expires_at'] = 1
        await manager.broadcast({'type': 'stats', 'data': {'rf_rx': 5}})
        for _ in range(10):
            await asyncio.sleep(0)
        await manager.close()
        self.assertEqual(socket.sent, [{'type': 'stats', 'data': {'rf_rx': 5}}])

    async def test_station_snapshots_do_not_disclose_last_message_raw(self):
        station = {'callsign': 'N0TEST', 'last_raw': 'private-message-text', 'last_port_name': 'private-port'}
        snapshot = {'type': 'initial_stations', 'rf': [station], 'aprs_is': []}
        update = {'type': 'station_update', 'station': station}
        self.assertNotIn('private-', json.dumps(public_socket_message(snapshot)))
        self.assertNotIn('private-', json.dumps(public_socket_message(update)))

    async def test_new_backend_restart_identity_is_public_for_update_refresh(self):
        status, data = await self.viewer.request('GET', '/api/update-install-status')
        self.assertEqual(status, 200)
        self.assertIn('instance', data)
        self.assertNotIn('installer_path', data)
        self.assertNotIn('csrf_token', data)

    async def test_host_launch_is_single_use_and_never_unlocks_public_browser(self):
        from urllib.parse import urlsplit, parse_qs
        set_password(self.auth_path, PASSWORD)
        url = self.auth.local_dashboard_url('https://public.example')
        token = parse_qs(urlsplit(url).fragment)['propview-local'][0]
        self.assertNotIn(token, urlsplit(url).query)
        status, data = await self.operator.request('POST', '/api/auth/local-login', {'token': token},
            {'x-propview-login': '1', 'origin': 'https://public.example'})
        self.operator.csrf = data['csrf_token']
        self.assertEqual(status, 200)
        self.assertTrue(data['local_session'])
        self.assertEqual((await self.operator.beacon())[0], 200)
        self.assertEqual((await self.viewer.beacon())[0], 401)
        self.assertEqual((await self.viewer.request('POST', '/api/auth/local-login', {'token': token},
            {'x-propview-login': '1'}))[0], 401)

    async def test_local_launch_rejects_expired_wrong_origin_and_reset_tokens(self):
        from urllib.parse import urlsplit, parse_qs
        set_password(self.auth_path, PASSWORD)
        token = parse_qs(urlsplit(self.auth.local_dashboard_url('https://other.example')).fragment)['propview-local'][0]
        self.assertEqual((await self.operator.request('POST', '/api/auth/local-login', {'token': token},
            {'x-propview-login': '1'}))[0], 401)
        token = parse_qs(urlsplit(self.auth.local_dashboard_url('https://public.example')).fragment)['propview-local'][0]
        for key, value in list(self.auth.local_launches.items()):
            self.auth.local_launches[key] = (1, value[1])
        self.assertEqual((await self.operator.request('POST', '/api/auth/local-login', {'token': token},
            {'x-propview-login': '1'}))[0], 401)
        token = parse_qs(urlsplit(self.auth.local_dashboard_url('https://public.example')).fragment)['propview-local'][0]
        set_password(self.auth_path, 'reset local password passphrase')
        self.assertEqual((await self.operator.request('POST', '/api/auth/local-login', {'token': token},
            {'x-propview-login': '1'}))[0], 401)

    async def test_local_automatic_sign_in_can_be_disabled_on_host(self):
        set_password(self.auth_path, PASSWORD, local_auto_login=False)
        self.assertEqual(self.auth.local_dashboard_url('http://localhost:14501'), 'http://localhost:14501')
        self.assertEqual((await self.operator.login())[0], 200)

    async def test_desktop_shortcut_handoff_requires_local_file_secret_even_when_logged_in(self):
        opener = MagicMock()
        self.app.state.desktop_open = opener
        self.app.state.desktop_secret = 'local-file-only-secret'
        self.assertEqual((await self.viewer.request('POST', '/api/auth/desktop-open'))[0], 401)
        set_password(self.auth_path, PASSWORD)
        await self.operator.login()
        self.assertEqual((await self.operator.request('POST', '/api/auth/desktop-open', {'secret': 'wrong'}))[0], 401)
        status, data = await self.viewer.request('POST', '/api/auth/desktop-open', {'secret': 'local-file-only-secret'})
        self.assertEqual(status, 200)
        self.assertEqual(data, {'success': True})
        await asyncio.sleep(0)
        opener.assert_called_once_with()
        self.assertFalse((await self.viewer.request('GET', '/api/auth/status'))[1]['authenticated'])

    async def test_public_viewers_cannot_consume_upgrade_notice(self):
        from server.release_notes import ReleaseNotes
        release = ReleaseNotes(self.path.with_name('release-state.json'), '1.12.0', existing_installation=True)
        app = create_app(self.config, MagicMock(), MagicMock(), MagicMock(), self.handler,
                         config_path=self.path, release_notes=release)
        viewer = Browser(app)
        self.assertFalse((await viewer.request('GET', '/api/whats-new'))[1]['should_show'])
        self.assertEqual((await viewer.request('POST', '/api/whats-new/acknowledge', {'version': '1.12.0'}))[0], 401)
        self.assertTrue(release.pending)
        set_password(self.auth_path, PASSWORD)
        await viewer.login()
        self.assertTrue((await viewer.request('GET', '/api/whats-new'))[1]['should_show'])
        self.assertEqual((await viewer.request('POST', '/api/whats-new/acknowledge', {'version': '1.12.0'},
            {'x-propview-csrf': viewer.csrf}))[0], 200)
        self.assertFalse((await viewer.request('GET', '/api/whats-new'))[1]['should_show'])

    async def test_local_update_continues_only_the_same_browser_and_only_once(self):
        from urllib.parse import urlsplit, parse_qs
        from server.operator_auth import OperatorAuth
        set_password(self.auth_path, PASSWORD)
        token = parse_qs(urlsplit(self.auth.local_dashboard_url('https://public.example')).fragment)['propview-local'][0]
        _, data = await self.operator.request('POST', '/api/auth/local-login', {'token': token}, {'x-propview-login': '1'})
        cookie_token = self.operator.cookie.split('=', 1)[1]
        self.auth.preserve_local_update_session(cookie_token)
        restarted = OperatorAuth(self.auth_path)
        self.assertFalse(restarted.status('')['authenticated'])  # A public visitor may arrive first.
        self.assertTrue(restarted.status(cookie_token)['authenticated'])
        self.assertEqual(restarted.status(cookie_token)['expires_at'], data['expires_at'])
        self.assertFalse(OperatorAuth(self.auth_path).status(cookie_token)['authenticated'])

    async def test_password_sessions_are_not_carried_over_updates(self):
        set_password(self.auth_path, PASSWORD)
        await self.operator.login()
        self.auth.preserve_local_update_session(self.operator.cookie.split('=', 1)[1])
        self.assertFalse(self.path.with_name('operator-update-session.json').exists())
