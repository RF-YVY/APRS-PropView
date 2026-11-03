import asyncio
import re
import tempfile
import unittest
from html.parser import HTMLParser
from pathlib import Path
from unittest.mock import MagicMock

from server.app import create_app
from server.config import Config

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / 'static'

# An inline handler written into markup built by script, quoted or not, e.g.
# `<button onclick="pvWeather.toggle(${i})">` or `<a onclick=${call}>`, and one
# set through setAttribute. Property assignments such as `button.onclick = fn`
# are allowed under CSP and do not match.
TEMPLATE_HANDLER = re.compile(r'(?<![\w.$])on[a-z]+\s*=\s*(?:\\?["\']|\$\{)')
SET_ATTRIBUTE_HANDLER = re.compile(r'setAttribute\(\s*["\'`]on', re.IGNORECASE)
JAVASCRIPT_URL = re.compile(r'javascript\s*:', re.IGNORECASE)


async def _get(app, path):
    scope = {
        'type': 'http', 'asgi': {'version': '3.0'}, 'http_version': '1.1', 'method': 'GET',
        'scheme': 'http', 'path': path, 'raw_path': path.encode(), 'query_string': b'',
        'root_path': '', 'headers': [(b'host', b'127.0.0.1')],
        'client': ('127.0.0.1', 50000), 'server': ('127.0.0.1', 14501),
    }
    pending = [{'type': 'http.request', 'body': b'', 'more_body': False}]
    sent = []

    async def receive():
        if pending:
            return pending.pop()
        await asyncio.Event().wait()

    async def send(message):
        sent.append(message)

    await app(scope, receive, send)
    start = next(m for m in sent if m['type'] == 'http.response.start')
    headers = {k.decode().lower(): v.decode() for k, v in start['headers']}
    return start['status'], headers


def _directives(policy):
    out = {}
    for part in policy.split(';'):
        tokens = part.split()
        if tokens:
            out[tokens[0].lower()] = tokens[1:]
    return out


class _InlineScriptFinder(HTMLParser):
    def __init__(self):
        super().__init__()
        self.inline_scripts = []
        self.handlers = []
        self._in_inline = False

    def handle_starttag(self, tag, attrs):
        names = {name.lower() for name, _ in attrs}
        for name, value in attrs:
            name = name.lower()
            if (name.startswith('on') or name == 'srcdoc'
                    or JAVASCRIPT_URL.match((value or '').strip())):
                self.handlers.append((self.getpos()[0], tag, name))
        if tag == 'script' and 'src' not in names:
            self._in_inline = True
            self.inline_scripts.append(self.getpos()[0])

    def handle_endtag(self, tag):
        if tag == 'script':
            self._in_inline = False


class ContentSecurityPolicyHeaderTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.app = create_app(Config(), MagicMock(), MagicMock(), MagicMock(), MagicMock(),
                              config_path=Path(self.temp.name) / 'config.toml')

    async def test_pages_forbid_inline_script(self):
        for path in ('/', '/kiosk', '/mobile', '/static/documentation.html'):
            with self.subTest(path=path):
                status, headers = await _get(self.app, path)
                self.assertEqual(status, 200)
                self.assertIn('content-security-policy', headers)
                policy = _directives(headers['content-security-policy'])
                self.assertEqual(policy.get('script-src'), ["'self'"])
                self.assertEqual(policy.get('object-src'), ["'none'"])
                self.assertEqual(policy.get('base-uri'), ["'self'"])

    async def test_policy_leaves_images_styles_and_connections_alone(self):
        # Map tiles, radar overlays and inline style attributes come from many
        # places; this policy is about script only.
        _, headers = await _get(self.app, '/')
        policy = _directives(headers['content-security-policy'])
        for directive in ('default-src', 'img-src', 'style-src', 'connect-src'):
            self.assertNotIn(directive, policy)


class NoInlineScriptInPagesTests(unittest.TestCase):
    def test_served_pages_have_no_inline_script_or_handlers(self):
        pages = sorted(STATIC.rglob('*.html'))
        self.assertIn(STATIC / 'index.html', pages)
        self.assertIn(STATIC / 'mobile.html', pages)
        for page in pages:
            with self.subTest(page=str(page.relative_to(ROOT))):
                finder = _InlineScriptFinder()
                finder.feed(page.read_text(encoding='utf-8'))
                self.assertEqual(finder.inline_scripts, [], 'inline <script> at these lines')
                self.assertEqual(finder.handlers, [], 'inline event handlers')

    def test_scripts_do_not_build_inline_handlers(self):
        for script in sorted((STATIC / 'js').glob('*.js')):
            with self.subTest(script=script.name):
                text = script.read_text(encoding='utf-8')
                hits = [text.count('\n', 0, m.start()) + 1
                        for pattern in (TEMPLATE_HANDLER, SET_ATTRIBUTE_HANDLER, JAVASCRIPT_URL)
                        for m in pattern.finditer(text)]
                self.assertEqual(hits, [], 'inline handler or javascript: URL at these lines')

    def test_patterns_catch_the_forms_csp_blocks(self):
        for sample in ('`<button onclick="go(${i})">`', '`<a onclick=${call}>`',
                       "'<img onerror=\\'x()\\'>'"):
            self.assertRegex(sample, TEMPLATE_HANDLER)
        self.assertNotRegex('button.onclick = () => go();', TEMPLATE_HANDLER)
        self.assertRegex("el.setAttribute('onclick', code)", SET_ATTRIBUTE_HANDLER)
        self.assertRegex('<a href="javascript:void(0)">', JAVASCRIPT_URL)


class MobilePageCachingTests(unittest.IsolatedAsyncioTestCase):
    """The mobile script lives in its own file now, so the page must never be
    served stale beside it, and its script URLs must change when the files do."""

    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.app = create_app(Config(), MagicMock(), MagicMock(), MagicMock(), MagicMock(),
                              config_path=Path(self.temp.name) / 'config.toml')
        self.endpoint = next(route.endpoint for route in self.app.routes
                             if getattr(route, 'path', '') == '/mobile')

    async def test_mobile_page_is_not_cached(self):
        _, headers = await _get(self.app, '/mobile')
        self.assertIn('no-store', headers.get('cache-control', ''))

    async def test_mobile_scripts_carry_the_asset_fingerprint(self):
        body = (await self.endpoint()).body.decode('utf-8')
        self.assertNotIn('__ASSET_VERSION__', body)
        versions = set(re.findall(r'src="/static/js/[\w.-]+\.js\?v=([^"]+)"', body))
        for name in ('mobile.js', 'mobile-theme-boot.js', 'operator-auth.js', 'heard-me.js'):
            self.assertRegex(body, rf'/static/js/{re.escape(name)}\?v=')
        self.assertEqual(len(versions), 1, versions)
        self.assertRegex(versions.pop(), r'-[0-9a-f]+$')


if __name__ == '__main__':
    unittest.main()
