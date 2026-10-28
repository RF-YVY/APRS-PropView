import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from server.aprs_spot import build_spot, select_spot_route, ACTIVITY_PROFILES
from server.app import create_app
from server.config import Config
from server.operator_auth import set_password
from server.packet_handler import PacketHandler
from tests.test_operator_auth import Browser, PASSWORD

FORM = dict(activity='POTA', reference='US-1234', frequency='14.310', mode='SSB', comment='CQ', source='rf')

class SpotFormatTests(unittest.TestCase):
    def test_command_and_sender(self):
        result = build_spot({**FORM, 'callsign':'k5yvy'}, 'N2UGS-7')
        self.assertEqual(result['text'], '! POTA US-1234 14.31 SSB CQ')
        self.assertEqual(result['callsign'], 'K5YVY')
        self.assertEqual(result['to'], 'APSPOT')

    def test_supported_activities(self):
        for activity, ref in [('POTA','US-1234'),('SOTA','W4C/CM-001'),('WWFF','VKFF-1929'),('SIOTA','VK-0001')]:
            self.assertIn(activity, build_spot({**FORM,'activity':activity,'reference':ref}, 'N2UGS')['text'])

    def test_invalid_fields(self):
        for change in [dict(frequency='14310'), dict(frequency='nan'),dict(reference='US-1 extra'),
                       dict(mode='FT8',activity='SOTA'),dict(comment='hello{12'),dict(comment='x'*67),
                       dict(comment='line\nbreak'),dict(source='both'),dict(test='yes'), dict(callsign='N2UGS-7'), dict(callsign='BAD>CALL'), dict(callsign='N0CALL')]:
            with self.subTest(change=change), self.assertRaises(ValueError):
                build_spot({**FORM,**change},'N2UGS')
        with self.assertRaises(ValueError): build_spot(FORM, 'N0CALL-1')

    def test_reference_segments_and_numeric_suffix(self):
        for reference in ('US-1234', 'W4C/CM-001', 'A-1/B2-C3-004'):
            with self.subTest(reference=reference):
                self.assertIn(reference, build_spot({**FORM, 'reference': reference}, 'N2UGS')['text'])
        for reference in ('', 'US', '-123', 'US-', 'US--123', 'US/-123',
                          'US-12A', 'US-\u0661', 'US_1-123', 'US-123\nX',
                          '0' * 100000, '0-' * 50000 + 'X', '0/' * 50000 + '0-1X'):
            with self.subTest(reference=reference[:40]), self.assertRaisesRegex(ValueError, 'Enter a reference'):
                build_spot({**FORM, 'reference': reference}, 'N2UGS')

    def test_test_and_length(self):
        self.assertTrue(build_spot({**FORM,'test':True},'N2UGS')['text'].endswith('aptest'))
        self.assertTrue(build_spot({**FORM,'comment':'contest'},'N2UGS')['test'])
        prefix = build_spot({**FORM,'comment':''},'N2UGS')['text']
        self.assertEqual(build_spot({**FORM,'comment':'x'*(66-len(prefix))},'N2UGS')['characters'],67)

class SpotDeliveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_strict_send_once_and_failed_transport_not_recorded(self):
        config=Config(); config.station.callsign='N2UGS'
        tracker=MagicMock(); tracker._mqtt_publisher=None; tracker.db.add_message=AsyncMock(return_value=None)
        tracker.db.upsert_message_contact=AsyncMock()
        ws=MagicMock(); ws.broadcast=AsyncMock()
        handler=PacketHandler(config,tracker,None,None,ws)
        handler._resolve_message_source=MagicMock(return_value='rf')
        handler._send_aprs_message_raw=AsyncMock(return_value=False)
        with self.assertRaises(ValueError):
            await handler.send_message('APSPOT','command',preferred_source='rf',require_delivery=True,sender_call='N2UGS')
        tracker.db.add_message.assert_not_awaited()
        handler._send_aprs_message_raw.reset_mock(return_value=True)
        await handler.send_message('APSPOT','command',preferred_source='rf',require_delivery=True,sender_call='N2UGS')
        handler._send_aprs_message_raw.assert_awaited_once()
        tracker.db.add_message.assert_awaited_once()

    async def test_api_auth_preview_and_send(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'config.toml'; set_password(path.with_name('operator-auth.json'),PASSWORD)
            config=Config(); config.station.callsign='N2UGS'; config.station.ssid=7
            handler=MagicMock(); handler.send_message=AsyncMock()
            app=create_app(config,MagicMock(),MagicMock(),MagicMock(),handler,config_path=path)
            browser=Browser(app)
            self.assertEqual((await browser.request('GET','/api/spot/options'))[0],401)
            for route in ('preview','send'):
                self.assertEqual((await browser.request('POST','/api/spot/'+route,FORM))[0],401)
            await browser.login()
            options_status, options = await browser.request('GET','/api/spot/options')
            self.assertEqual(options_status,200)
            self.assertEqual(options['callsign'],'N2UGS')
            headers={'x-propview-csrf':browser.csrf,'origin':'https://public.example'}
            status,data=await browser.request('POST','/api/spot/preview',FORM,headers)
            self.assertEqual(status,200); handler.send_message.assert_not_awaited()
            self.assertEqual(data['spot']['callsign'],'N2UGS')
            status,_=await browser.request('POST','/api/spot/send',FORM,headers)
            self.assertEqual(status,200)
            handler.send_message.assert_awaited_once_with('APSPOT','! POTA US-1234 14.31 SSB CQ',preferred_source='rf',require_delivery=True,sender_call='N2UGS')


            # Another operator changes only this request's APRS sender.
            handler.send_message.reset_mock()
            status,_=await browser.request('POST','/api/spot/send',{**FORM,'callsign':'K5YVY'},headers)
            self.assertEqual(status,200)
            self.assertEqual(handler.send_message.await_args.kwargs['sender_call'],'K5YVY')
            self.assertEqual(config.station.full_callsign,'N2UGS-7')
            # Delivery ValueErrors may contain internal information.
            handler.send_message.side_effect=ValueError('PRIVATE /server/config secret')
            with self.assertLogs('propview.app',level='ERROR') as logs:
                status,data=await browser.request('POST','/api/spot/send',FORM,headers)
            self.assertEqual(status,400)
            self.assertFalse(data['success'])
            self.assertNotIn('PRIVATE',data['message'])
            self.assertIn('PRIVATE',' '.join(logs.output))
            handler.send_message.side_effect=None
            # Lookup/help do not require any activation-only fields.
            status,data=await browser.request('POST','/api/spot/preview',{'action':'usage'},headers)
            self.assertEqual(status,200); self.assertEqual(data['spot']['text'],'usage')
            handler._can_send_via.return_value=False
            handler.aprs_is.verified=False
            handler.send_message.reset_mock()
            status,data=await browser.request('POST','/api/spot/preview',FORM,headers)
            self.assertEqual(status,200); self.assertFalse(data['spot']['can_send'])
            status,_=await browser.request('POST','/api/spot/send',FORM,headers)
            self.assertEqual(status,400); handler.send_message.assert_not_awaited()


class SpotCommandTests(unittest.TestCase):
    def test_default_callsign_and_route(self):
        form = {key: value for key, value in FORM.items() if key != 'source'}
        result = build_spot(form,'N2UGS-7')
        self.assertEqual(result['callsign'],'N2UGS')
        self.assertEqual(result['source'],'auto')

    def test_lookup_filters_and_service_help(self):
        for form, expected in [
            ({'action':'spots','activity':'POTA'}, 'spots POTA'),
            ({'action':'spots','activity':'POTA','filter_mode':'cw'}, 'spots POTA CW'),
            ({'action':'spots','activity':'WWFF','count':'5'}, 'spots WWFF 5'),
            ({'action':'spots','activity':'WWFF','filter_mode':'ssb','count':'5'}, 'spots WWFF SSB 5'),
            ({'action':'usage'}, 'usage'),
            ({'action':'usage','help_type':'sms'}, 'usage sms'),
            ({'action':'usage','help_type':'winlink','help_activity':'SOTA'}, 'usage winlink SOTA'),
            ({'action':'usage','help_type':'aprs','help_activity':'POTA'}, 'usage aprs POTA')]:
            with self.subTest(form=form): self.assertEqual(build_spot(form,'N2UGS')['text'],expected)

    def test_invalid_queries(self):
        for form in [dict(action='spots',activity='SIOTA'),dict(action='spots',activity='POTA',count='0'),
                     dict(action='spots',activity='POTA',count='5 CW'),dict(action='spots',activity='SOTA',filter_mode='FT8'),
                     dict(action='usage',help_type='other'),dict(action='usage',help_activity='POTA'),dict(action='raw')]:
            with self.subTest(form=form), self.assertRaises(ValueError): build_spot(form,'N2UGS')

    def test_activity_modes_and_routes(self):
        self.assertIn('FT8', ACTIVITY_PROFILES['POTA']['modes'])
        for activity in ('SOTA','WWFF','SIOTA'): self.assertNotIn('FT8',ACTIVITY_PROFILES[activity]['modes'])
        handler=MagicMock(); handler._can_send_via.return_value=True
        handler.aprs_is.connected=handler.aprs_is.verified=True
        self.assertEqual(select_spot_route(handler,'auto'),'rf')
        handler._can_send_via.return_value=False
        self.assertIsNone(select_spot_route(handler,'rf'))
        self.assertEqual(select_spot_route(handler,'auto'),'aprs_is')
        handler.aprs_is.verified=False
        self.assertIsNone(select_spot_route(handler,'auto'))
        self.assertIsNone(select_spot_route(handler,'aprs_is'))


class OperatorPacketTests(unittest.IsolatedAsyncioTestCase):
    def make_handler(self):
        config=Config(); config.station.callsign='N2UGS'; config.station.ssid=7
        tracker=MagicMock(); tracker._mqtt_publisher=None; tracker.db.add_message=AsyncMock(return_value=None)
        tracker.db.upsert_message_contact=AsyncMock()
        ws=MagicMock(); ws.broadcast=AsyncMock()
        handler=PacketHandler(config,tracker,None,None,ws)
        handler.rf_interfaces=[MagicMock(connected=True, can_transmit=True, rx_only_rf=False)]
        handler._record_tx_packet=AsyncMock()
        handler._transmit_rf=AsyncMock(return_value=1)
        handler.aprs_is=MagicMock(connected=True,verified=True)
        handler.aprs_is.send=AsyncMock(return_value=True)
        handler.aprs_is.register_message_recipient=AsyncMock(return_value=True)
        return handler

    async def test_operator_is_actual_sender_on_each_transport(self):
        for source in ('rf','aprs_is'):
            with self.subTest(source=source):
                handler=self.make_handler()
                msg=await handler.send_message('APSPOT','! POTA US-1234 14.31 SSB',preferred_source=source,
                                               require_delivery=True,sender_call='K5YVY')
                self.assertEqual(msg['from'],'K5YVY')
                self.assertEqual(handler.config.station.full_callsign,'N2UGS-7')
                if source == 'rf':
                    frame=handler._transmit_rf.await_args.args[0]
                    self.assertEqual(frame.source.full_call,'K5YVY')
                    self.assertTrue(frame.info.startswith(b':APSPOT   :! POTA'))
                    handler.aprs_is.send.assert_not_awaited()
                else:
                    self.assertTrue(handler.aprs_is.send.await_args.args[0].startswith('K5YVY>APPRPV,TCPIP*::APSPOT   :! POTA'))
                    handler.aprs_is.register_message_recipient.assert_awaited_once_with('K5YVY')
                    handler._transmit_rf.assert_not_awaited()

    async def test_reply_to_other_operator_is_stored_and_acked_from_that_operator(self):
        import time
        from server.aprs_parser import parse_packet
        handler=self.make_handler()
        handler._messages.append({'direction':'tx','to':'APSPOT','from':'K5YVY','timestamp':time.time()})
        handler.tracker.db.add_message.return_value={'direction':'rx','from':'APSPOT','to':'K5YVY','text':'Posted','timestamp':time.time()}
        packet=parse_packet('APSPOT>APRS::K5YVY    :Posted{42',source='rf')
        await handler._check_incoming_message(packet,'rf')
        handler.tracker.db.add_message.assert_awaited_once()
        self.assertEqual(handler._transmit_rf.await_args.args[0].source.full_call,'K5YVY')
        handler.tracker.db.add_message.reset_mock()
        packet=parse_packet('APSPOT>APRS::K9XYZ    :Unrelated{43',source='rf')
        await handler._check_incoming_message(packet,'rf')
        handler.tracker.db.add_message.assert_not_awaited()

    async def test_recipient_filter_and_reconnect(self):
        from server.aprs_is import APRSISClient
        config=Config(); config.station.callsign='N2UGS'; config.station.ssid=7
        config.aprs_is.filter='r/35/-79/80'
        client=APRSISClient(config,AsyncMock()); client.connected=client.verified=True
        client.writer=MagicMock(); client.writer.drain=AsyncMock()
        self.assertTrue(await client.register_message_recipient('K5YVY'))
        command=client.writer.write.call_args.args[0]
        self.assertIn(b'r/35/-79/80',command)
        self.assertIn(b'g/K5YVY/N2UGS-7',command)
        self.assertTrue(command.endswith(b'\r\n'))
        self.assertIn('g/K5YVY/N2UGS-7',client._build_login())
        self.assertEqual(config.aprs_is.filter,'r/35/-79/80')
        self.assertTrue(await client.register_message_recipient('K5YVY'))
        client.writer.write.assert_called_once()
