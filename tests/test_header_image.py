import base64
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from PIL import Image
from server.header_image import normalize_header_image, save_header_image


def picture(size=(1200, 600)):
    output = io.BytesIO()
    Image.new('RGBA', size, (20, 100, 200, 127)).save(output, format='PNG')
    return output.getvalue()


class HeaderImageTests(unittest.TestCase):
    def test_large_image_preserves_aspect_and_transparency(self):
        result = normalize_header_image(picture())
        with Image.open(io.BytesIO(result)) as image:
            self.assertEqual(image.size, (192, 96))
            self.assertEqual(image.mode, 'RGBA')
            self.assertEqual(image.getpixel((50, 50))[3], 127)

    def test_invalid_upload_preserves_previous_image(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'header-image.png'
            save_header_image(path, picture())
            previous = path.read_bytes()
            with self.assertRaises(ValueError):
                save_header_image(path, b'not an image')
            self.assertEqual(path.read_bytes(), previous)


class HeaderImageApiTests(unittest.IsolatedAsyncioTestCase):
    async def test_authenticated_upload_persists_and_reset_restores_default(self):
        from server.app import create_app
        from server.config import Config
        from server.operator_auth import set_password
        from tests.test_operator_auth import Browser
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'config.toml'
            set_password(path.with_name('operator-auth.json'), 'abcdef')
            app = create_app(Config(), MagicMock(), MagicMock(), MagicMock(), MagicMock(), config_path=path)
            browser = Browser(app)
            payload = {'data': base64.b64encode(picture()).decode()}
            self.assertEqual((await browser.request('POST', '/api/header-image', payload))[0], 401)
            await browser.login('abcdef')
            self.assertEqual((await browser.request('POST', '/api/header-image', payload))[0], 403)
            headers = {'x-propview-csrf': browser.csrf, 'origin': 'https://public.example'}
            self.assertEqual((await browser.request('POST', '/api/header-image', payload, headers))[0], 200)
            stored = path.with_name('header-image.png')
            self.assertTrue(stored.is_file())
            # A new app instance resolves the same saved image after restart.
            from server.header_image import register_header_image_routes
            from fastapi import FastAPI
            restarted = FastAPI()
            register_header_image_routes(restarted, path, Path(__file__).resolve().parents[1] / 'static')
            route = next(r for r in restarted.routes if r.path == '/api/header-image' and 'GET' in r.methods)
            response = await route.endpoint()
            self.assertEqual(Path(response.path), stored)
            self.assertEqual(response.headers['cache-control'], 'no-store')
            self.assertEqual((await browser.request('POST', '/api/header-image', {'data': 'invalid!'}, headers))[0], 400)
            self.assertTrue(stored.is_file())
            self.assertEqual((await browser.request('DELETE', '/api/header-image', headers=headers))[0], 200)
            self.assertFalse(stored.exists())
            response = await route.endpoint()
            self.assertEqual(Path(response.path).name, 'app-icon.webp')
