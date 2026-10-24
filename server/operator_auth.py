"""Local credentials and independent, expiring browser operator sessions.

There is deliberately no network password setup/reset endpoint and no trusted
IP, localhost, VPN, or proxy-header shortcut to operator privileges.
"""
import asyncio
import hashlib
import hmac
import json
import logging
import secrets
import time
from collections import defaultdict, deque
from dataclasses import asdict
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import Request
from starlette.responses import JSONResponse

from server.config_io import atomic_write

COOKIE = 'pv_operator_session'
DURATIONS = (900, 3600, 28800)
ITERATIONS = 600_000
logger = logging.getLogger('propview.operator')


def set_password(path, password, local_auto_login=True):
    if not isinstance(password, str) or not 6 <= len(password) <= 256:
        raise ValueError('Use an operator password between 6 and 256 characters.')
    salt = secrets.token_hex(32)
    digest = hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), ITERATIONS).hex()
    atomic_write(path, json.dumps({'algorithm': 'pbkdf2-sha256', 'iterations': ITERATIONS,
                                 'salt': salt, 'digest': digest,
                                 'local_auto_login': bool(local_auto_login)}))
    Path(path).chmod(0o600)


class OperatorAuth:
    def __init__(self, path):
        self.path = Path(path)
        self.sessions = {}
        self.local_launches = {}
        self.update_restored = False
        self.fingerprint = None
        self.record = None
        self.attempts = defaultdict(deque)
        self.global_attempts = deque()
        self.login_lock = asyncio.Lock()

    def reload(self):
        try:
            raw = self.path.read_bytes()
        except OSError:
            raw = b''
        fingerprint = hashlib.sha256(raw).digest()
        if fingerprint == self.fingerprint:
            return
        self.fingerprint = fingerprint
        self.sessions.clear()
        self.local_launches.clear()
        self.record = None
        try:
            record = json.loads(raw)
            if (record['algorithm'] == 'pbkdf2-sha256' and
                    record['iterations'] == ITERATIONS and
                    len(bytes.fromhex(record['salt'])) == 32 and
                    len(bytes.fromhex(record['digest'])) == 32):
                self.record = record
        except (ValueError, KeyError, TypeError):
            pass  # Missing/corrupt credentials always leave the server read-only.

    def session(self, token):
        self.reload()
        if not self.update_restored:
            self.update_restored = True
            self._restore_update_session()
        now = time.time()
        self.sessions = {key: value for key, value in self.sessions.items() if value['expires_at'] > now}
        return self.sessions.get(hashlib.sha256(token.encode()).hexdigest()) if token else None

    def preserve_local_update_session(self, token):
        """Only an intentional in-app update may continue this exact local browser."""
        session = self.session(token)
        if not session or not session.get('local'):
            return
        path = self.path.with_name('operator-update-session.json')
        atomic_write(path, json.dumps({'key': hashlib.sha256(token.encode()).hexdigest(),
            'session': session, 'fingerprint': self.fingerprint.hex(), 'handoff_until': time.time() + 900}))
        path.chmod(0o600)

    def _restore_update_session(self):
        path = self.path.with_name('operator-update-session.json')
        try:
            data = json.loads(path.read_text(encoding='utf-8'))
            path.unlink()  # One handoff, not general persistent authentication.
            session, key = data['session'], data['key']
            if (self.record and data['fingerprint'] == self.fingerprint.hex() and
                    data['handoff_until'] > time.time() and session['expires_at'] > time.time() and
                    session.get('local') is True and isinstance(session.get('csrf'), str) and
                    len(key) == 64 and all(char in '0123456789abcdef' for char in key)):
                self.sessions[key] = session
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            pass

    def verify(self, password, record):
        digest = hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(record['salt']), ITERATIONS)
        return hmac.compare_digest(digest.hex(), record['digest'])

    def status(self, token):
        session = self.session(token)
        return {'authenticated': bool(session), 'configured': self.record is not None,
                'expires_at': session['expires_at'] if session else None,
                'csrf_token': session['csrf'] if session else None,
                'local_session': bool(session and session.get('local')),
                'durations': list(DURATIONS)}

    def create_session(self, request, duration, local=False):
        self.logout(request.cookies.get(COOKIE, ''))
        if len(self.sessions) >= 128:
            self.sessions.pop(next(iter(self.sessions)))
        token = secrets.token_urlsafe(32)
        self.sessions[hashlib.sha256(token.encode()).hexdigest()] = {
            'expires_at': time.time() + duration, 'csrf': secrets.token_urlsafe(32), 'local': local}
        response = JSONResponse(self.status(token))
        response.set_cookie(COOKIE, token, max_age=duration, httponly=True,
                            secure=request.url.scheme == 'https', samesite='strict', path='/')
        return response

    def local_dashboard_url(self, url):
        """Host process/tray only. There is no HTTP endpoint to mint these."""
        self.reload()
        if not self.record or not self.record.get('local_auto_login', True):
            return url
        now = time.time()
        self.local_launches = {key: value for key, value in self.local_launches.items() if value[0] > now}
        if len(self.local_launches) >= 20:
            self.local_launches.pop(next(iter(self.local_launches)))
        token = secrets.token_urlsafe(32)
        origin = urlsplit(url)
        self.local_launches[hashlib.sha256(token.encode()).hexdigest()] = (now + 90, f'{origin.scheme}://{origin.netloc}')
        # A fragment is never sent in HTTP requests, access logs or Referer.
        return f'{url}#propview-local={token}'

    async def local_login(self, request):
        if request.headers.get('x-propview-login') != '1' or not same_origin(request):
            return JSONResponse({'message': 'Same-origin login required.'}, status_code=403)
        try:
            raw = bytearray()
            async for chunk in request.stream():
                raw.extend(chunk)
                if len(raw) > 4096:
                    raise ValueError()
            body = json.loads(raw)
            token = body.get('token', '')
            if not isinstance(token, str) or not 1 <= len(token) <= 128:
                raise ValueError()
        except (ValueError, TypeError, AttributeError):
            return JSONResponse({'message': 'Invalid local launch.'}, status_code=400)
        self.reload()
        launch = self.local_launches.pop(hashlib.sha256(token.encode()).hexdigest(), None)
        origin = f'{request.url.scheme}://{request.url.netloc}'
        if not launch or launch[0] <= time.time() or launch[1] != origin:
            return JSONResponse({'message': 'Local launch expired. Reopen PropView from its tray menu.'}, status_code=401)
        logger.info('Local application browser signed in')
        return self.create_session(request, 28800, local=True)

    async def login(self, request):
        # Custom header plus JSON prevents cross-site form login requests.
        if request.headers.get('x-propview-login') != '1' or not same_origin(request):
            return JSONResponse({'message': 'Same-origin login required.'}, status_code=403)
        raw = bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw) > 4096:
                return JSONResponse({'message': 'Login request too large.'}, status_code=413)
        try:
            body = json.loads(raw)
            password, duration = body['password'], body.get('duration', 3600)
            if (not isinstance(password, str) or not 1 <= len(password) <= 256 or
                    type(duration) is not int or duration not in DURATIONS):
                raise ValueError()
        except (ValueError, KeyError, TypeError):
            return JSONResponse({'message': 'Invalid password or session duration.'}, status_code=400)
        async with self.login_lock:
            self.reload()
            if not self.record:
                return JSONResponse({'message': 'Set the operator password using the host computer first.'}, status_code=403)
            now = time.time()
            self.attempts = defaultdict(deque, {key: deque(t for t in values if now-t < 60)
                                               for key, values in self.attempts.items() if values and now-values[-1] < 60})
            peer = request.client.host if request.client else 'unknown'
            attempts = self.attempts[peer]
            while self.global_attempts and now-self.global_attempts[0] >= 60:
                self.global_attempts.popleft()
            if len(attempts) >= 5 or len(self.global_attempts) >= 30:
                return JSONResponse({'message': 'Too many login attempts. Wait a minute.'}, status_code=429,
                                    headers={'Retry-After': '60'})
            attempts.append(now)
            self.global_attempts.append(now)
            record = self.record.copy()
            verified = await asyncio.to_thread(self.verify, password, record)
            self.reload()
            if not verified or record != self.record:
                logger.warning('Operator login rejected from %s', peer)
                return JSONResponse({'message': 'Incorrect operator password.'}, status_code=401)
            # Only this browser's old session is replaced. No global unlock flag.
            response = self.create_session(request, duration)
            logger.info('Operator login from %s for %s seconds', peer, duration)
            return response

    def logout(self, token):
        key = hashlib.sha256(token.encode()).hexdigest()
        self.sessions.pop(key, None)
        path = self.path.with_name('operator-update-session.json')
        try:
            if json.loads(path.read_text(encoding='utf-8')).get('key') == key:
                path.unlink()
        except (OSError, ValueError, AttributeError):
            pass


def same_origin(request):
    origin = request.headers.get('origin')
    if not origin:
        return request.headers.get('sec-fetch-site') not in {'cross-site', 'same-site'}
    try:
        parsed = urlsplit(origin)
    except ValueError:
        return False
    scheme = {'ws': 'http', 'wss': 'https'}.get(request.url.scheme, request.url.scheme)
    return parsed.scheme == scheme and parsed.netloc.lower() == request.url.netloc.lower()


# Explicit allowlist. New endpoints and all non-GET actions require a session.
PUBLIC_GET = {
    '/api/header-image',
    '/api/auth/status', '/api/whats-new', '/api/config', '/api/health', '/api/version', '/api/status',
    '/api/update-install-status',  # Safe restart identity/progress; no paths or credentials.
    '/api/stations/rf', '/api/stations/is', '/api/stations/all', '/api/packets',
    '/api/propagation', '/api/propagation/history', '/api/stats', '/api/source-health',
    '/api/weather', '/api/lightning', '/api/space-weather', '/api/external-propagation',
    '/api/first-heard', '/api/ducting',
    '/api/analytics/longest-paths', '/api/analytics/heatmap', '/api/analytics/reliability',
    '/api/analytics/best-times', '/api/analytics/anomaly', '/api/analytics/bearing-sectors',
    '/api/analytics/historical', '/api/analytics/sporadic-e', '/api/analytics/observed-range',
    '/api/analytics/weather', '/api/analytics/weather-mesh',
}


def public_get(path):
    if path in PUBLIC_GET:
        return True
    parts = path.strip('/').split('/')
    if len(parts) == 5 and parts[:2] == ['api', 'map-tiles']:
        return all(part.isdigit() for part in parts[2:])
    return len(parts) == 4 and parts[:3] == ['api', 'analytics', 'path-quality']


def public_config(config):
    web = asdict(config.web)
    web = {key: value for key, value in web.items() if key.startswith(('visual_', 'club_display_')) or key in {
        'font_family', 'unit_system', 'ghost_after_minutes', 'expire_after_minutes',
        'map_tile_source', 'map_tile_attribution', 'map_tile_max_zoom'}}
    # Custom base tile credentials stay on the host behind the existing proxy.
    web['map_tile_url'] = '/api/map-tiles/{z}/{x}/{y}'
    return {'station': {key: value for key, value in asdict(config.station).items() if key in {
                'callsign', 'ssid', 'latitude', 'longitude', 'symbol_table', 'symbol_code', 'phg', 'comment'}},
            'web': web, 'weather': {'enabled': config.weather.enabled},
            'watched_paths': [], 'alerts': {}, 'gps': {'enabled': False}}


def public_status(data):
    return {key: value for key, value in data.items() if key in {
        'station', 'station_info', 'latitude', 'longitude', 'symbol_table', 'symbol_code',
        'rf_connected', 'aprs_is_connected', 'stats'}}


def public_packet(packet):
    return packet.get('packet_type') != 'message'


def public_station(station):
    # last_raw may be a message even when the station still has a map position.
    return {key: value for key, value in station.items() if key not in {'last_raw', 'last_port_name'}}


def public_weather(data):
    data = dict(data)
    overlays = dict(data.get('map_overlays') or {})
    for key in ('radar_custom_url', 'radar_custom_api_key'):
        overlays.pop(key, None)
    if overlays.get('radar_provider') in {'custom_xyz', 'custom_wms'}:
        overlays['radar_enabled'] = False
    data['map_overlays'] = overlays
    data.pop('error', None)
    return data


def public_socket_message(message):
    kind = message.get('type')
    if kind not in {'status', 'stats', 'propagation', 'initial_stations', 'station_update', 'station_removed', 'packet'}:
        return None
    if kind == 'status':
        return {**message, 'data': public_status(message.get('data', {}))}
    if kind == 'packet' and not public_packet(message.get('data', {})):
        return None
    if kind == 'station_update':
        return {**message, 'station': public_station(message.get('station', {}))}
    if kind == 'initial_stations':
        return {**message, **{key: [public_station(station) for station in message.get(key, [])]
                              for key in ('rf', 'aprs_is')}}
    return message


def install_access_control(app, auth):
    app.state.operator_auth = auth

    @app.middleware('http')
    async def enforce_operator_access(request: Request, call_next):
        path = request.url.path
        token = request.cookies.get(COOKIE, '')
        session = auth.session(token)
        request.state.operator_session = session
        is_api = path.startswith('/api/')
        public = request.method in {'GET', 'HEAD'} and public_get(path)
        login = path in {'/api/auth/login', '/api/auth/local-login', '/api/auth/desktop-open'} and request.method == 'POST'
        if is_api and not public and not login:
            if not session:
                return JSONResponse({'success': False, 'message': 'Operator login required.'}, status_code=401)
            if request.method not in {'GET', 'HEAD', 'OPTIONS'}:
                if not same_origin(request) or not hmac.compare_digest(request.headers.get('x-propview-csrf', ''), session['csrf']):
                    return JSONResponse({'success': False, 'message': 'Invalid operator request token.'}, status_code=403)
                logger.info('Operator action %s %s from %s', request.method, path, request.client.host if request.client else 'unknown')
        response = await call_next(request)
        if is_api:
            response.headers['Cache-Control'] = 'no-store'
            response.headers['Vary'] = 'Cookie'
        return response

    @app.get('/api/auth/status')
    async def status(request: Request):
        return auth.status(request.cookies.get(COOKIE, ''))

    @app.post('/api/auth/login')
    async def login(request: Request):
        return await auth.login(request)

    @app.post('/api/auth/local-login')
    async def local_login(request: Request):
        return await auth.local_login(request)

    @app.post('/api/auth/logout')
    async def logout(request: Request):
        auth.logout(request.cookies.get(COOKIE, ''))
        response = JSONResponse({'success': True})
        response.delete_cookie(COOKIE, path='/')
        return response
