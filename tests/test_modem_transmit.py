import asyncio
import ctypes
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock,patch

from server.ax25 import AX25Frame
from server.software_modem import AudioDecoder
from server.modem_transmit import ModemTransmitter,encode_audio

FRAME=AX25Frame.from_aprs_string('K5YVY-7>APPRPV:>Transmit unit test').encode()

class NativeTransmitTests(unittest.TestCase):
    def test_audio_round_trip_and_stereo(self):
        for rate in (44100,48000):
            for channel in (0,1):
                with self.subTest(rate=rate,channel=channel):
                    audio=encode_audio(FRAME,rate=rate,channel=channel)
                    d=AudioDecoder(rate)
                    try:self.assertEqual(d.feed(audio,channel+1,channel),[FRAME])
                    finally:d.close()
                    if channel:
                        samples=(ctypes.c_float*(len(audio)//4)).from_buffer_copy(audio)
                        self.assertTrue(all(value==0 for value in samples[::2]))

    def test_invalid_levels_and_timing(self):
        for settings in [dict(gain=0),dict(gain=1),dict(delay_ms=0),dict(tail_ms=501)]:
            with self.subTest(settings=settings),self.assertRaises(ValueError):encode_audio(FRAME,**settings)


class FakeSerial:
    instances=[]
    def __init__(self,**kwargs):
        self.rts=True;self.dtr=True;self.open_state=None;self.closed=False;self.asserted=[]
        self.__class__.instances.append(self)
    def __setattr__(self,name,value):
        if name in ('rts','dtr') and value and 'asserted' in self.__dict__:self.asserted.append(name)
        object.__setattr__(self,name,value)
    def open(self):self.open_state=(self.rts,self.dtr)
    def close(self):self.closed=True


class FakeOutput:
    instances=[];fail_start=False;hang=False;underflow=False
    def __init__(self,**kwargs):self.args=kwargs;self.closed=False;self.aborted=False;self.__class__.instances.append(self)
    def start(self):
        import sounddevice as sd
        if self.__class__.fail_start:raise RuntimeError('Output start failed')
        if self.__class__.hang:return
        try:
            for _ in range(1000):
                self.args['callback'](bytearray(960*4*self.args['channels']),960,None,SimpleNamespace(output_underflow=self.__class__.underflow))
        except (sd.CallbackStop,sd.CallbackAbort):pass
        self.args['finished_callback']()
    def abort(self):self.aborted=True;self.args['finished_callback']()
    def close(self):self.closed=True


class TransmitControlTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.modem=SimpleNamespace(connected=True,stream=SimpleNamespace(active=True),metrics={},handler=SimpleNamespace(rf_interfaces=[]))
        self.tx=ModemTransmitter(self.modem)
        FakeSerial.instances=[];FakeOutput.instances=[];FakeOutput.fail_start=FakeOutput.hang=FakeOutput.underflow=False
        self.patches=[patch('sounddevice.RawOutputStream',FakeOutput),patch('serial.Serial',FakeSerial),
          patch('sounddevice.query_devices',return_value={'name':'Radio output'}),patch('sounddevice.check_output_settings'),
          patch.object(self.tx,'outputs',return_value=[{'id':1,'name':'Radio output','host_api':'Test','channels':2}]),
          patch.object(self.tx,'ports',return_value=[{'device':'COM9','description':'NOMIC test'}])]
        for item in self.patches:item.start()
        self.settings={'enabled':True,'device':1,'ptt':'nomic_rts','port':'COM9'}

    async def asyncTearDown(self):
        await self.tx.stop()
        for item in reversed(self.patches):item.stop()

    async def test_configure_does_not_open_audio_or_ptt_and_transmit_unkeys(self):
        await self.tx.configure(self.settings)
        self.assertEqual(FakeSerial.instances,[]);self.assertEqual(FakeOutput.instances,[])
        await self.tx.send(FRAME)
        port=FakeSerial.instances[0]
        self.assertEqual(port.open_state,(False,False))
        self.assertEqual(port.asserted,['rts'])
        self.assertFalse(port.rts);self.assertFalse(port.dtr);self.assertTrue(port.closed)
        self.assertTrue(FakeOutput.instances[0].closed)
        self.assertEqual(self.tx.sent,1);self.assertFalse(self.tx.active)

    async def test_dtr_and_vox_methods(self):
        for method in ('serial_dtr','vox'):
            await self.tx.configure({**self.settings,'ptt':method})
            FakeSerial.instances=[]
            await self.tx.send(FRAME)
            if method=='vox':self.assertEqual(FakeSerial.instances,[])
            else:self.assertEqual(FakeSerial.instances[0].asserted,['dtr'])

    async def test_gated_transmit_is_explicit_opt_in_and_requires_tx(self):
        from server.software_modem import SoftwareModem
        from server.packet_handler import PacketHandler
        modem=SimpleNamespace(transmitter=self.tx,connected=True,can_transmit=True)
        def permitted():
            modem.rx_only_is=SoftwareModem.rx_only_is.fget(modem)
            return PacketHandler._iface_can_transmit(None,modem,'is')
        await self.tx.configure(self.settings)
        self.assertFalse(permitted())
        for value in ['true',1,None]:
            with self.assertRaises(ValueError):
                await self.tx.configure({**self.settings,'allow_is_to_rf':value})
        await self.tx.configure({**self.settings,'allow_is_to_rf':True})
        self.assertTrue(permitted())
        modem.can_transmit=False
        self.assertFalse(permitted())
        modem.can_transmit=True
        await self.tx.configure({**self.settings,'allow_is_to_rf':False})
        self.assertFalse(permitted())
        self.assertEqual(FakeSerial.instances,[])
        self.assertEqual(FakeOutput.instances,[])

    async def test_transmit_delay_milliseconds_reach_audio_encoder(self):
        await self.tx.configure({**self.settings,'delay_ms':725,'wait_for_clear_channel':False})
        self.assertEqual(self.tx.status()['settings']['delay_ms'],725)
        with patch('server.modem_transmit.encode_audio', wraps=encode_audio) as encoder:
            await self.tx.send(FRAME)
        self.assertEqual(encoder.call_args.args[3],725)


    async def test_audio_failure_releases_both_lines(self):
        await self.tx.configure(self.settings);FakeOutput.fail_start=True
        with self.assertRaisesRegex(RuntimeError,'Output start'):await self.tx.send(FRAME)
        port=FakeSerial.instances[0]
        self.assertFalse(port.rts);self.assertFalse(port.dtr);self.assertTrue(port.closed)
        self.assertTrue(FakeOutput.instances[0].closed)
        self.assertFalse(self.tx.active);self.assertEqual(self.tx.sent,0)

    async def test_output_underrun_not_reported_successful(self):
        await self.tx.configure(self.settings);FakeOutput.underflow=True
        with self.assertRaisesRegex(ValueError,'underrun'):await self.tx.send(FRAME)
        self.assertEqual(self.tx.sent,0);self.assertGreater(self.tx.underflows,0)
        self.assertTrue(FakeSerial.instances[0].closed)

    async def test_watchdog_unkeys_stalled_audio(self):
        await self.tx.configure(self.settings);FakeOutput.hang=True;self.tx.MAX_KEY_SECONDS=2
        with self.assertRaisesRegex(ValueError,'stopped|timed out'):await self.tx.send(FRAME)
        self.assertTrue(FakeOutput.instances[0].aborted)
        self.assertFalse(FakeSerial.instances[0].rts);self.assertFalse(FakeSerial.instances[0].dtr)
        self.assertFalse(self.tx.active)

    async def test_stop_aborts_active_packet_and_disables_tx(self):
        await self.tx.configure(self.settings);FakeOutput.hang=True
        sending=asyncio.create_task(self.tx.send(FRAME))
        for _ in range(100):
            if self.tx.active:break
            await asyncio.sleep(.01)
        self.assertTrue(self.tx.active)
        await self.tx.stop()
        with self.assertRaises(ValueError):await sending
        self.assertFalse(self.tx.enabled);self.assertFalse(FakeSerial.instances[0].rts)

    async def test_busy_channel_can_be_cancelled_without_keying(self):
        await self.tx.configure(self.settings);self.modem.metrics={'carrier_detected':1}
        sending=asyncio.create_task(self.tx.send(FRAME));await asyncio.sleep(.02);await self.tx.stop()
        with self.assertRaises(ValueError):await sending
        self.assertEqual(FakeSerial.instances,[]);self.assertEqual(FakeOutput.instances,[])

    async def test_busy_channel_bypass_and_default_validation(self):
        await self.tx.configure(self.settings)
        self.assertTrue(self.tx.settings['wait_for_clear_channel'])
        with self.assertRaises(ValueError):
            await self.tx.configure({**self.settings,'wait_for_clear_channel':'false'})
        await self.tx.configure({**self.settings,'wait_for_clear_channel':False})
        self.modem.metrics={'carrier_detected':1}
        await self.tx.send(FRAME)
        self.assertEqual(self.tx.sent,1)
        self.assertTrue(FakeOutput.instances[0].closed)
        self.assertFalse(FakeSerial.instances[0].rts)
        self.assertFalse(FakeSerial.instances[0].dtr)

    async def test_placeholder_and_disabled_tx_are_rejected(self):
        with self.assertRaises(ValueError):await self.tx.send(FRAME)
        await self.tx.configure(self.settings)
        invalid=AX25Frame.from_aprs_string('N0CALL>APRS:>Bad identity').encode()
        with self.assertRaises(ValueError):await self.tx.send(invalid)
        self.assertEqual(FakeSerial.instances,[])


class RequestedSettingsTests(unittest.TestCase):
    def test_six_character_password_and_reject_five(self):
        from server.operator_auth import set_password,OperatorAuth
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'auth.json'
            with self.assertRaises(ValueError):set_password(path,'abcde')
            set_password(path,'abcdef');auth=OperatorAuth(path);auth.reload()
            self.assertTrue(auth.verify('abcdef',auth.record))
            self.assertFalse(auth.verify('abcdeg',auth.record))

    def test_noaa_default_fits_html_step(self):
        import re
        from decimal import Decimal
        from server.config import Config
        text=(Path(__file__).resolve().parents[1]/'static/index.html').read_text(encoding='utf-8')
        element=re.search(r'<input[^>]+id="cfg-space-weather-min-kp"[^>]+>',text).group()
        attrs=dict(re.findall(r'(\w+)="([^"]*)"',element))
        value=Decimal(str(Config().weather.space_weather_alert_min_kp))
        self.assertTrue(Decimal(attrs['min'])<=value<=Decimal(attrs['max']))
        self.assertEqual((value-Decimal(attrs['min']))%Decimal(attrs['step']),0)


class TransmitApiTests(unittest.IsolatedAsyncioTestCase):
    async def test_operator_can_configure_and_disable_without_keying(self):
        from server.app import create_app
        from server.config import Config
        from server.operator_auth import set_password
        from tests.test_operator_auth import Browser
        with tempfile.TemporaryDirectory() as temp:
            config=Config();config.station.callsign='K5YVY'
            path=Path(temp)/'config.toml';set_password(path.with_name('operator-auth.json'),'abcdef')
            handler=MagicMock();handler.rf_interfaces=[]
            app=create_app(config,MagicMock(),MagicMock(),MagicMock(),handler,app_version='1.13.0-dev.3',config_path=path)
            modem=app.state.software_modem;modem.connected=True;modem.stream=MagicMock(active=True)
            browser=Browser(app);self.assertEqual((await browser.login('abcdef'))[0],200)
            body={'enabled':True,'device':1,'port':'COM9','ptt':'nomic_rts'}
            # Authenticated writes still need this browser's CSRF token.
            self.assertEqual((await browser.request('POST','/api/modem/transmit-settings',body))[0],403)
            headers={'x-propview-csrf':browser.csrf,'origin':'https://public.example'}
            with patch.object(modem.transmitter,'outputs',return_value=[{'id':1,'name':'Test radio','host_api':'Test','channels':2}]),patch.object(modem.transmitter,'ports',return_value=[{'device':'COM9'}]),patch('sounddevice.check_output_settings'),patch('serial.Serial') as serial,patch('sounddevice.RawOutputStream') as output:
                code,data=await browser.request('POST','/api/modem/transmit-settings',body,headers)
                self.assertEqual(code,200);self.assertFalse(data['receive_only'])
                serial.assert_not_called();output.assert_not_called()
                code,data=await browser.request('POST','/api/modem/channel-wait',{'wait_for_clear_channel':False},headers)
                self.assertEqual(code,200);self.assertFalse(data['transmit']['settings']['wait_for_clear_channel'])
                saved=__import__('json').loads(path.with_name('modem-transmit.json').read_text())
                self.assertFalse(saved['settings']['wait_for_clear_channel'])
                self.assertTrue(saved['enabled'])
                code,data=await browser.request('POST','/api/modem/stop-transmit',{},headers)
                self.assertEqual(code,200);self.assertTrue(data['receive_only'])
                self.assertFalse(modem.transmitter.enabled)
                serial.assert_not_called();output.assert_not_called()
