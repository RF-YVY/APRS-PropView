import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from server.app import create_app
from server.config import Config


class TileProxyBoundsTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.tmp = Path(self.temp.name)
        self.config = Config()
        self.downloads = []

        def download(url, z, x, y):
            self.downloads.append((z, x, y))
            path = self.tmp / f'{z}-{x}-{y}.png'
            path.write_bytes(b'tile')
            return path

        for target, fake in (
            ('server.app._download_tile', download),
            ('server.app._tile_cache_path', lambda url, z, x, y: self.tmp / f'{z}-{x}-{y}.png'),
        ):
            patcher = patch(target, side_effect=fake)
            patcher.start()
            self.addCleanup(patcher.stop)

    def endpoint(self):
        app = create_app(self.config, MagicMock(), MagicMock(), MagicMock(), MagicMock(),
                         config_path=self.tmp / 'config.toml')
        return next(route.endpoint for route in app.routes
                    if getattr(route, 'path', '') == '/api/map-tiles/{z}/{x}/{y}')

    def request(self, ip='198.51.100.7', operator=False):
        request = MagicMock()
        request.state.operator_session = operator
        request.client.host = ip
        return request

    async def test_zoom_above_the_source_maximum_is_not_fetched(self):
        get_tile = self.endpoint()
        response = await get_tile(20, 0, 0, self.request())
        self.assertEqual(response.status_code, 404)
        self.assertEqual(self.downloads, [])

    async def test_operators_are_held_to_the_source_maximum_too(self):
        get_tile = self.endpoint()
        response = await get_tile(22, 0, 0, self.request(operator=True))
        self.assertEqual(response.status_code, 404)
        self.assertEqual(self.downloads, [])

    async def test_custom_source_maximum_is_honoured(self):
        self.config.web.map_tile_source = 'custom'
        self.config.web.map_tile_url = 'https://tiles.example/{z}/{x}/{y}.png'
        self.config.web.map_tile_max_zoom = 21
        get_tile = self.endpoint()
        self.assertEqual((await get_tile(21, 0, 0, self.request())).status_code, 200)
        self.assertEqual((await get_tile(22, 0, 0, self.request())).status_code, 404)
        self.assertEqual(self.downloads, [(21, 0, 0)])

    async def test_cached_tiles_above_the_source_maximum_are_still_served(self):
        (self.tmp / '20-0-0.png').write_bytes(b'tile')
        get_tile = self.endpoint()
        response = await get_tile(20, 0, 0, self.request())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.downloads, [])

    async def test_ipv6_addresses_in_one_64_share_the_miss_limit(self):
        get_tile = self.endpoint()
        statuses = []
        for n in range(60):
            response = await get_tile(10, n, 0, self.request(ip=f'2001:db8:5:6::{n + 1:x}'))
            statuses.append(response.status_code)
        self.assertIn(429, statuses)


if __name__ == '__main__':
    unittest.main()
