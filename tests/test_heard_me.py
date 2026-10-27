import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from server.aprs_is import APRSISClient
from server.aprs_parser import parse_packet
from server.ax25 import AX25Frame
from server.config import Config
from server.heard_me import HeardMe
from server.packet_handler import PacketHandler
from server.app import create_app
from tests.test_operator_auth import Browser


def setup():
    config = Config()
    config.station.callsign = 'K5ABC'
    config.station.ssid = 1
    config.station.latitude, config.station.longitude = 34, -89
    now = [1000.0]
    tracker = HeardMe(config, clock=lambda: now[0])
    tracker.transmitted('K5ABC-1>APPRPV,WIDE1-1:>test', 34, -89)
    return config, now, tracker


def test_direct_gate_report_requires_matching_actual_rf_packet():
    _, _, tracker = setup()
    assert tracker.observe('K5ABC-1>APPRPV,WIDE1-1,qAR,W1GATE:>test', 'aprs_is')['direct']
    observation = tracker.snapshot()['observations'][0]
    assert observation['route_calls'] == ['W1GATE']
    assert observation['latitude'] == 34
    assert 'raw' not in observation and '_transmission' not in observation
    assert tracker.observe('K5ABC-1>APPRPV,qAR,W1GATE:>different', 'aprs_is') is None
    assert tracker.observe('K5ABC-2>APPRPV,qAR,W1GATE:>test', 'aprs_is') is None


def test_h_bit_prefix_is_a_relay_route_not_direct_gate_reception():
    _, _, tracker = setup()
    result = tracker.observe('K5ABC-1>APPRPV,DIGI1,DIGI2*,WIDE2-1,qAO,W1GATE:>test', 'aprs_is')
    assert result['route_calls'] == ['DIGI1', 'DIGI2', 'W1GATE']
    assert not result['direct'] and result['path_known']


def test_internet_and_own_gateway_reports_and_local_echoes_do_not_count():
    _, _, tracker = setup()
    for path in ('TCPIP*,qAC,SERVER', 'TCPIP*,qAR,W1GATE', 'TCPXX*,qAO,W1GATE',
                 'qAR,K5ABC-10', 'qAX,W1GATE', 'qAR,INVALID<script>'):
        assert tracker.observe(f'K5ABC-1>APPRPV,{path}:>test', 'aprs_is') is None
    assert tracker.observe('K5ABC-1>APPRPV:>test', 'rf') is None
    assert tracker.snapshot()['observations'] == []


def test_rf_repeated_copy_counts_without_aprs_is_and_deduplicates_reports():
    _, _, tracker = setup()
    raw = 'K5ABC-1>APPRPV,DIGI1*:>test'
    result = tracker.observe(raw, 'rf')
    assert result['route_calls'] == ['DIGI1']
    tracker.observe(raw, 'rf')
    tracker.observe('K5ABC-1>APPRPV,DIGI1*,qAR,DIGI1:>test', 'aprs_is')
    observations = tracker.snapshot()['observations']
    assert len(observations) == 1
    assert observations[0]['packet_count'] == 1
    assert observations[0]['transports'] == ['aprs_is', 'rf']


def test_unknown_aliases_stay_unresolved_and_positions_can_arrive_later():
    _, _, tracker = setup()
    result = tracker.observe('K5ABC-1>APPRPV,WIDE1*:>test', 'rf')
    assert result is None
    result = tracker.observe('K5ABC-1>APPRPV,WIDE1*,qAR,W1GATE:>test', 'aprs_is')
    assert not result['path_known'] and not result['direct']
    assert tracker.snapshot()['observations'][0]['hops'][0]['latitude'] is None
    tracker.observe('W1GATE>APRS:!3500.00N/09000.00W>gateway', 'aprs_is',
                    parse_packet('W1GATE>APRS:!3500.00N/09000.00W>gateway', source='aprs_is'))
    assert tracker.snapshot()['observations'][0]['hops'][0]['latitude'] == 35


def test_expiry_mismatch_private_messages_and_callsign_change():
    config, now, tracker = setup()
    now[0] += 181
    assert tracker.observe('K5ABC-1>APPRPV,qAR,W1GATE:>test', 'aprs_is') is None
    tracker.transmitted('K5ABC-1>APPRPV::OTHER    :secret', 34, -89)
    assert not tracker.transmissions
    tracker.transmitted('K5ABC-1>APPRPV:>new', 34, -89)
    tracker.observe('K5ABC-1>APPRPV,qAR,W1GATE:>new', 'aprs_is')
    config.station.callsign = 'N1NEW'
    assert not tracker.snapshot()['observations']
    config.station.callsign = 'K5ABC'
    now[0] += 3601
    assert not tracker.snapshot()['observations']


def test_storage_is_bounded_and_untrusted_unicode_is_ignored():
    _, _, tracker = setup()
    for i in range(600):
        raw = f'K5ABC-1>APPRPV:>test{i}'
        tracker.transmitted(raw, 34, -89)
        tracker.observe(f'K5ABC-1>APPRPV,qAR,G{i}:>test{i}', 'aprs_is')
    assert len(tracker.transmissions) == 512
    assert len(tracker.observations) == 128
    assert tracker.observe('K5ABC-1>APPRPV:>\u2603', 'aprs_is') is None


def test_successful_rf_send_is_recorded_but_failed_or_other_station_is_not():
    async def run():
        config, _, _ = setup()
        handler = PacketHandler(config, SimpleNamespace(my_lat=34, my_lon=-89), None, None, MagicMock())
        interface = SimpleNamespace(connected=True, can_transmit=True, name='test', send=AsyncMock(return_value=False))
        handler.rf_interfaces = [interface]
        frame = AX25Frame.from_aprs_string('K5ABC-1>APPRPV:>test')
        assert await handler._transmit_rf(frame) == 0
        assert not handler.heard_me.transmissions
        interface.send.return_value = None
        assert await handler._transmit_rf(frame) == 1
        assert len(handler.heard_me.transmissions) == 1
    asyncio.run(run())


def test_subscription_keeps_existing_filters_and_bounds_remote_calls():
    async def run():
        config, _, _ = setup()
        config.aprs_is.filter = 'r/34/-89/200'
        client = APRSISClient(config, None)
        client._message_recipients.add('N1TEST')
        assert 'r/34/-89/200' in client._effective_filter()
        assert 'b/K5ABC/K5ABC-*' in client._effective_filter()
        assert 'g/K5ABC-1/N1TEST' in client._effective_filter()
        await client.register_heard_me_stations([f'G{i}' for i in range(100)] + ['BAD\r\nfilter b/*'])
        assert len(client._heard_me_calls) == 32
        assert '\n' not in client._effective_filter()
    asyncio.run(run())


def test_public_endpoint_exposes_only_non_message_reception_metadata(tmp_path):
    async def run():
        config, _, heard = setup()
        heard.observe('K5ABC-1>APPRPV,qAR,W1GATE:>test', 'aprs_is')
        handler = MagicMock()
        handler.heard_me = heard
        app = create_app(config, MagicMock(), MagicMock(), MagicMock(), handler, config_path=tmp_path / 'config.toml')
        viewer = Browser(app)
        code, data = await viewer.request('GET', '/api/heard-me')
        assert code == 200
        assert data['observations'][0]['receiver'] == 'W1GATE'
        assert 'raw' not in json.dumps(data) and '>test' not in json.dumps(data)
    asyncio.run(run())
