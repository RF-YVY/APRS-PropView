import asyncio
import threading
import time
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI

from server.operator_auth import OperatorAuth, install_access_control
from server.resource_limits import PublicRequestLimits, TileCacheBudget
from server.app import create_app
from server.config import Config
from tests.test_operator_auth import Browser


def test_public_buckets_refill_and_peer_storage_stays_bounded():
    now = [0]
    limiter = PublicRequestLimits(clock=lambda: now[0])
    for _ in range(12):
        assert limiter.acquire('peer', '/api/analytics/anomaly') is None
        limiter.release()
    assert limiter.acquire('peer', '/api/analytics/anomaly') == 429
    now[0] += 2
    assert limiter.acquire('peer', '/api/analytics/anomaly') is None
    limiter.release()
    limiter.MAX_PEERS = 4
    for i in range(10):
        limiter.acquire(str(i), '/api/status')
        limiter.release()
    assert len(limiter.peers) == 4


def test_public_concurrency_and_rate_errors_have_retry_headers(tmp_path):
    async def run():
        app = FastAPI()
        install_access_control(app, OperatorAuth(tmp_path / 'missing.json'))
        entered = asyncio.Event()
        finish = asyncio.Event()
        count = 0

        @app.get('/api/analytics/anomaly')
        async def slow():
            nonlocal count
            count += 1
            if count == 16:
                entered.set()
            await finish.wait()
            return {'ok': True}

        tasks = [asyncio.create_task(Browser(app, ip=str(i)).request('GET', '/api/analytics/anomaly')) for i in range(16)]
        try:
            await asyncio.wait_for(entered.wait(), 5)
            viewer = Browser(app, ip='extra')
            assert (await viewer.request('GET', '/api/analytics/anomaly'))[0] == 503
            assert viewer.last_headers['retry-after'] == '5'
        finally:
            finish.set()
            await asyncio.gather(*tasks)
        assert app.state.public_limits.active == 0
        viewer = Browser(app, ip='rate')
        for _ in range(12):
            assert (await viewer.request('GET', '/api/analytics/anomaly'))[0] == 200
        assert (await viewer.request('GET', '/api/analytics/anomaly'))[0] == 429
    asyncio.run(run())


def test_tile_cache_eviction_spans_sources_and_caps_files(tmp_path):
    cache = TileCacheBudget(tmp_path, max_bytes=10, max_files=2)
    first = tmp_path / 'source-a/0/0/0.png'
    second = tmp_path / 'source-b/0/0/0.png'
    assert cache.store(first, b'123456') == first
    cache.store(second, b'abcdef')
    assert not first.exists()
    assert second.read_bytes() == b'abcdef'
    assert cache.size == 6
    assert cache.store(first, b'x' * 11) is None
    cache.store(first, b'a')
    third = tmp_path / 'source-c/0/0/0.png'
    cache.store(third, b'b')
    assert len(cache.entries) == 2
    assert not second.exists()
    assert not list(tmp_path.rglob('*.tmp'))


def test_tile_workers_share_four_download_slots(tmp_path):
    async def run():
        handler = MagicMock()
        app = create_app(Config(), MagicMock(), MagicMock(), MagicMock(), handler, config_path=tmp_path / 'config.toml')
        lock = threading.Lock()
        active = peak = 0

        def download(url, z, x, y):
            nonlocal active, peak
            with lock:
                active += 1
                peak = max(active, peak)
            time.sleep(0.03)
            path = tmp_path / f'{x}.png'
            path.write_bytes(b'tile')
            with lock:
                active -= 1
            return path

        with patch('server.app._download_tile', side_effect=download), patch('server.app._tile_cache_path', side_effect=lambda url,z,x,y: tmp_path / f'{x}.png'):
            results = await asyncio.gather(*(Browser(app).request('GET', f'/api/map-tiles/5/{i}/0') for i in range(12)))
        assert all(code == 200 for code, _ in results)
        assert peak == 4
    asyncio.run(run())


def test_oversize_tile_is_rejected_before_cache_write():
    import server.app as module
    response = MagicMock()
    response.__enter__.return_value = response
    response.status = 200
    response.read.return_value = b'x' * (module.MAX_TILE_BYTES + 1)
    with patch('server.app.urllib.request.urlopen', return_value=response), patch('server.app._tile_cache_path') as path, patch.object(module.TILE_CACHE_BUDGET, 'store') as store:
        path.return_value.exists.return_value = False
        assert module._download_tile('https://tiles.example/{z}/{x}/{y}', 0, 0, 0) is None
        store.assert_not_called()


def test_websocket_viewers_cannot_take_operator_reserve():
    from server.websocket_manager import WebSocketManager

    async def run():
        manager = WebSocketManager()
        sockets = []
        try:
            for i in range(16):
                socket = MagicMock(accept=AsyncMock(), close=AsyncMock())
                assert await manager.connect(socket, peer=str(i // 4))
                sockets.append(socket)
            extra = MagicMock(accept=AsyncMock(), close=AsyncMock())
            assert not await manager.connect(extra, peer='new')
            operator = MagicMock(accept=AsyncMock(), close=AsyncMock())
            assert await manager.connect(operator, operator=True)
            assert not await manager.connect(extra, peer='0')
            manager.disconnect(sockets[0])
            assert await manager.connect(extra, peer='new')
        finally:
            await manager.close()
        assert not manager._public_peers
    asyncio.run(run())


def test_cancelled_tile_requests_hold_slots_until_threads_finish(tmp_path):
    async def run():
        app = create_app(Config(), MagicMock(), MagicMock(), MagicMock(), MagicMock(), config_path=tmp_path / 'config.toml')
        endpoint = next(route.endpoint for route in app.routes if getattr(route, 'path', '') == '/api/map-tiles/{z}/{x}/{y}')
        request = MagicMock()
        request.state.operator_session = True
        release = threading.Event()
        started = 0
        lock = threading.Lock()

        def download(url, z, x, y):
            nonlocal started
            with lock:
                started += 1
            assert release.wait(5)
            path = tmp_path / f'{x}.png'
            path.write_bytes(b'tile')
            return path

        with patch('server.app._download_tile', side_effect=download), patch('server.app._tile_cache_path', side_effect=lambda url,z,x,y: tmp_path / f'{x}.png'):
            first = [asyncio.create_task(endpoint(5, i, 0, request)) for i in range(4)]
            second = []
            try:
                async with asyncio.timeout(5):
                    while started < 4:
                        await asyncio.sleep(0.01)
                for task in first:
                    task.cancel()
                second = [asyncio.create_task(endpoint(5, i, 0, request)) for i in range(4, 8)]
                await asyncio.sleep(0.05)
                assert started == 4
            finally:
                release.set()
                await asyncio.gather(*first, *second, return_exceptions=True)
            assert started == 8
    asyncio.run(run())


def test_concurrent_websocket_handshakes_cannot_overbook_slots():
    from server.websocket_manager import WebSocketManager

    async def run():
        manager = WebSocketManager()
        manager.MAX_PUBLIC_CONNECTIONS = 2
        finish = asyncio.Event()
        entered = 0

        async def accept():
            nonlocal entered
            entered += 1
            await finish.wait()

        sockets = [MagicMock(accept=AsyncMock(side_effect=accept), close=AsyncMock()) for _ in range(8)]
        tasks = [asyncio.create_task(manager.connect(socket, peer='same-peer')) for socket in sockets]
        try:
            await asyncio.sleep(0.03)
            assert entered == 2
            assert len(manager.active_connections) == 2
        finally:
            finish.set()
            results = await asyncio.gather(*tasks)
            await manager.close()
        assert results.count(True) == 2
    asyncio.run(run())
