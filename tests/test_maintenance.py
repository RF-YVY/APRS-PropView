"""Regression cases for the 1.10 maintenance release (no real radio/network)."""
import asyncio
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from starlette.requests import Request
from server.config import Config
from server.database import Database
from server.station_tracker import StationTracker
from server.websocket_manager import WebSocketManager
from server.aprs_parser import parse_packet
from server.analytics import AnalyticsEngine
from server.app import create_app
from server.packet_handler import PacketHandler
from server.rf_evidence import valid_position, grade_position_observations


class EvidenceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.db = Database(':memory:')
        await self.db.initialize()
        self.config = Config()
        self.config.station.callsign = 'K5ABC'
        self.config.station.latitude = 35
        self.config.station.longitude = -90
        self.ws = WebSocketManager()
        self.tracker = StationTracker(self.db, self.config, self.ws)

    async def asyncTearDown(self):
        await self.ws.close()
        await self.db.close()

    async def test_direct_evidence_survives_relay_and_nonposition_packet(self):
        for raw in ['W1ABC>APRS:!3600.00N/09000.00W-Test',
                    'W1ABC>APRS,W2DIGI*:!3700.00N/09000.00W-Test',
                    'W1ABC>APRS:>Status without position']:
            await self.tracker.track_packet(parse_packet(raw, source='rf'))
        result = await self.tracker.get_propagation_data()
        self.assertEqual(result['my_stations_1h'], 1)
        self.assertAlmostEqual(result['my_max_distance_km'], 111.2, places=1)
        self.assertEqual(result['regional_stations_1h'], 1)
        self.assertGreater(result['max_distance_km'], 220)

    async def test_history_survives_movement_and_station_cleanup(self):
        await self.db.log_path_event('W1ABC', 450, 0, is_direct=True, port_name='2m')
        await self.db.log_path_event('W1ABC', 30, 180, is_direct=True, port_name='2m')
        await self.db.log_path_event('W2ABC', 900, 90, is_direct=False, port_name='6m')
        await self.db.delete_old_stations(0)
        engine = AnalyticsEngine(self.db)
        best = await engine.get_longest_paths(path_type='direct', port='2m')
        self.assertEqual(best[0]['distance_km'], 450)
        ring = await engine.get_observed_range(path_type='direct', port='2m')
        self.assertEqual(max(r['historical_max_km'] for r in ring['ring']), 450)
        sectors = await engine.get_bearing_sectors(path_type='relayed', port='6m')
        self.assertEqual(sectors['total_stations'], 1)
        self.assertEqual(sectors['sectors'][2]['max_distance_km'], 900)

    async def test_longest_path_holds_out_isolated_extreme_position(self):
        await self.db.log_path_event('W1BAD', 6500, 20, is_direct=True, latitude=10, longitude=10)
        await self.db.log_path_event('W1GOOD', 1200, 40, is_direct=True, latitude=45, longitude=-100)
        await self.db.log_path_event('W1GOOD', 1195, 41, is_direct=True, latitude=45.1, longitude=-100.1)
        engine = AnalyticsEngine(self.db)
        report = await engine.get_longest_paths_report()
        self.assertEqual([row['callsign'] for row in report['paths']], ['W1GOOD'])
        self.assertEqual(report['excluded_count'], 1)
        shown = await engine.get_longest_paths(include_suspect=True)
        self.assertEqual(shown[0]['callsign'], 'W1BAD')
        self.assertEqual(shown[0]['quality_status'], 'suspect')

    def test_repeated_position_cluster_rejects_distant_conflict(self):
        rows = [
            {'callsign': 'W1MOVE', 'distance_km': 100, 'latitude': 35, 'longitude': -90},
            {'callsign': 'W1MOVE', 'distance_km': 102, 'latitude': 35.1, 'longitude': -90.1},
            {'callsign': 'W1MOVE', 'distance_km': 700, 'latitude': 42, 'longitude': -75},
        ]
        accepted, rejected = grade_position_observations(rows)
        self.assertEqual(len(accepted), 2)
        self.assertEqual(rejected[0]['quality_reason'], "Position conflicts with this station's repeated location")

    def test_legacy_coordinate_less_row_survives_new_position_cluster(self):
        rows = [
            {'callsign': 'W1LEGACY', 'distance_km': 100, 'latitude': None, 'longitude': None},
            {'callsign': 'W1LEGACY', 'distance_km': 102, 'latitude': 35, 'longitude': -90},
            {'callsign': 'W1LEGACY', 'distance_km': 103, 'latitude': 35.1, 'longitude': -90.1},
        ]
        accepted, rejected = grade_position_observations(rows)
        self.assertEqual(len(accepted), 3)
        self.assertEqual(rejected, [])
        self.assertEqual(accepted[0]['quality_status'], 'plausible')

    async def test_es_does_not_join_near_direct_with_distant_relay(self):
        await self.db.log_path_event('W1ABC', 20, 0, is_direct=True)
        await self.db.log_path_event('W1ABC', 900, 90, is_direct=False, hop_count=3)
        result = await AnalyticsEngine(self.db).detect_sporadic_e()
        candidates = result['candidates'] + result['near_misses']
        self.assertEqual(candidates[0]['path_tier'], 'multi_hop_rf')
        self.assertEqual(candidates[0]['path_confidence'], 0.3)
        self.assertIn('hypothesis', result['interpretation'])

    async def test_atomic_station_count_with_concurrent_receivers(self):
        await asyncio.gather(*(self.db.upsert_station('W1ABC', 'rf', port_name=str(i % 2)) for i in range(80)))
        station = await self.db.get_station('W1ABC', 'rf')
        self.assertEqual(station['packet_count'], 80)

    async def test_retention_rollup_is_idempotent_and_preserves_identity(self):
        await self.db.log_path_event('W1ABC', 450, 0, is_direct=True)
        await self.db.log_first_heard('W1ABC', 'rf', 450, 0, 35, -90)
        await self.db.db.execute('UPDATE path_history SET timestamp=?', (time.time()-40*86400,))
        await self.db.maintain_history(history_days=30)
        await self.db.maintain_history(history_days=30)
        row = await (await self.db.db.execute('SELECT packet_count FROM rf_daily_summary')).fetchone()
        self.assertEqual(row[0], 1)
        self.assertTrue(await self.db.is_station_known('W1ABC','rf'))
        self.assertEqual(await self.db.rf_observations(24*60), [])

    async def test_failed_save_does_not_modify_runtime_or_position(self):
        handler = PacketHandler(self.config, self.tracker, None, None, self.ws)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'config.toml'
            self.config.save(path)
            original = path.read_bytes()
            app = create_app(self.config, self.db, self.tracker, self.ws, handler, config_path=path)
            endpoint = next(r.endpoint for r in app.routes if getattr(r,'path','') == '/api/config/save')
            payload = {'station': {'callsign':'K5ABC', 'latitude': 36, 'longitude': -91}}
            async def receive():
                return {'type':'http.request', 'body':json.dumps(payload).encode()}
            request = Request({'type':'http','method':'POST','path':'/api/config/save','headers':[]}, receive)
            with patch('server.config.atomic_write', side_effect=OSError('disk full')):
                response = await endpoint(request)
            self.assertEqual(response.status_code, 500)
            self.assertEqual(self.config.station.latitude,35)
            self.assertEqual(self.tracker.my_lat,35)
            self.assertEqual(path.read_bytes(), original)

    async def test_successful_save_preserves_references_and_backup(self):
        handler = PacketHandler(self.config, self.tracker, None, None, self.ws)
        reference = self.config.station
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'config.toml'
            self.config.save(path)
            app = create_app(self.config, self.db, self.tracker, self.ws, handler, config_path=path)
            endpoint = next(r.endpoint for r in app.routes if getattr(r,'path','') == '/api/config/save')
            async def receive():
                return {'type':'http.request','body':b'{"station":{"callsign":"K5ABC","latitude":36,"longitude":-91}}'}
            result = await endpoint(Request({'type':'http','method':'POST','path':'/api/config/save','headers':[]},receive))
            self.assertTrue(result['success'])
            self.assertIs(reference,self.config.station)
            self.assertEqual(reference.latitude,36)
            self.assertEqual(Config.load(path).station.latitude,36)
            self.assertEqual(Config.load(path.with_suffix('.toml.bak')).station.latitude,35)

    def test_zero_coordinates_valid_but_nonfinite_invalid(self):
        self.assertTrue(valid_position(0, -90))
        self.assertTrue(valid_position(35, 0))
        self.assertFalse(valid_position(float('nan'), 0))
        self.assertFalse(valid_position(None, 0))


class BrowserDeliveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_slow_browser_does_not_block_other_clients(self):
        class Socket:
            def __init__(self, slow=False): self.slow=slow; self.messages=[]
            async def accept(self): pass
            async def close(self, **kwargs): pass
            async def send_text(self, text):
                if self.slow: await asyncio.sleep(10)
                self.messages.append(json.loads(text))
        manager = WebSocketManager()
        manager.SEND_TIMEOUT = .03
        slow, fast = Socket(True), Socket()
        await manager.connect(slow)
        await manager.connect(fast)
        await asyncio.wait_for(manager.broadcast({'type':'message','data':'hello'}), .02)
        await asyncio.sleep(.08)
        self.assertEqual(fast.messages[0]['data'],'hello')
        self.assertNotIn(slow, manager.active_connections)
        await manager.close()

    async def test_replaceable_updates_coalesce_without_losing_messages(self):
        class Socket:
            async def accept(self): pass
            async def close(self, **kwargs): pass
            async def send_text(self, text): pass
        manager = WebSocketManager()
        socket = Socket()
        await manager.connect(socket)
        for i in range(100):
            await manager.broadcast({'type':'status','data':i})
        await manager.broadcast({'type':'message','data':'preserve me'})
        self.assertEqual(manager._queues[socket].qsize(),2)
        manager.disconnect(socket)
        await manager.close()

    async def test_overflow_closes_socket_before_sender_starts(self):
        class Socket:
            closed = False
            async def accept(self): pass
            async def close(self, **kwargs): self.closed = True
            async def send_text(self, text): pass
        manager = WebSocketManager()
        manager.QUEUE_LIMIT = 1
        socket = Socket()
        await manager.connect(socket)
        await manager.broadcast({'type': 'message', 'data': 'first'})
        await manager.broadcast({'type': 'message', 'data': 'overflow'})
        await manager.close()
        self.assertTrue(socket.closed)
        self.assertEqual(manager.client_count, 0)
