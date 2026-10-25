import unittest
from server.ax25 import AX25Frame
from server.software_modem import decode_wav,generate_test_wav,AudioDecoder

class ModemTests(unittest.TestCase):
    def test_exact_packet_across_sample_rates_and_noise(self):
        packet=AX25Frame.from_aprs_string('N2UGS-7>APRS,WIDE1-1:!3500.00N/07900.00W-Test modem')
        for rate,noise in [(48000,0),(44100,0),(48000,.08),(48000,.16)]:
            with self.subTest(rate=rate,noise=noise):
                result=decode_wav(generate_test_wav(packet.encode(),rate=rate,noise=noise))
                self.assertEqual(result['packets'],[packet.to_aprs_string()])

    def test_silence_does_not_decode(self):
        decoder=AudioDecoder()
        try:self.assertEqual(decoder.feed(bytes(48000*4)),[])
        finally:decoder.close()


# Independent reference transmitter: a separate CRC construction, cosine
# oscillator and fractional symbol clock, not the production test generator.
def reference_audio(payload, rate=48000, baud=1200, corrupt=False, mark_gain=.6, space_gain=.6):
    import binascii, math, struct
    def reflect(value,width):return int(f'{value:0{width}b}'[::-1],2)
    crc=reflect(binascii.crc_hqx(bytes(reflect(b,8) for b in payload),0xffff),16)^0xffff
    if corrupt:crc^=0x01
    data=payload+struct.pack('<H',crc)
    bits=[0,1,1,1,1,1,1,0]*40
    ones=0
    for value in data:
        for index in range(8):
            bit=(value>>index)&1;bits.append(bit);ones=ones+1 if bit else 0
            if ones==5:bits.append(0);ones=0
    bits += [0,1,1,1,1,1,1,0]*8
    samples=[];phase=.73;tone=False;position=0
    for index,bit in enumerate(bits):
        if not bit:tone=not tone
        frequency=1200 if tone else 2200
        gain=mark_gain if tone else space_gain
        end=int((index+1)*rate/baud)
        while position<end:
            samples.append(gain*math.cos(phase));phase+=2*math.pi*frequency/rate;position+=1
    return struct.pack('<'+'f'*len(samples),*samples)


class IndependentSignalTests(unittest.TestCase):
    def test_reference_signal_timing_and_chunk_boundaries(self):
        packet=AX25Frame.from_aprs_string('K5YVY>APRS:>Independent reference ~~~~~')
        for rate,baud,mark,space in [(48000,1200,.6,.6),(44100,1188,.6,.6),(48000,1212,.6,.6),(48000,1200,.3,.7)]:
            with self.subTest(rate=rate,baud=baud,mark=mark):
                samples=reference_audio(packet.encode(),rate,baud,mark_gain=mark,space_gain=space)
                decoder=AudioDecoder(rate);frames=[]
                try:
                    for start in range(0,len(samples),788):frames.extend(decoder.feed(samples[start:start+788]))
                    self.assertEqual(frames,[packet.encode()])
                finally:decoder.close()

    def test_crc_failure_and_noise_are_not_packets(self):
        import random,struct
        packet=AX25Frame.from_aprs_string('K5YVY>APRS:>Bad checksum')
        decoder=AudioDecoder()
        try:
            self.assertEqual(decoder.feed(reference_audio(packet.encode(),corrupt=True)),[])
            self.assertGreater(decoder.stats()['crc_failures'],0)
            rng=random.Random(105)
            raw=struct.pack('<'+'f'*48000,*(rng.gauss(0,.2) for _ in range(48000)))
            self.assertEqual(decoder.feed(raw),[])
        finally:decoder.close()

    def test_stereo_channel_selection(self):
        import struct
        packet=AX25Frame.from_aprs_string('K5YVY>APRS:>Stereo test')
        raw=reference_audio(packet.encode())
        mono=struct.unpack('<'+'f'*(len(raw)//4),raw)
        stereo=struct.pack('<'+'f'*(len(mono)*2),*(v for sample in mono for v in (0,sample)))
        for channel in (0,1):
            decoder=AudioDecoder()
            try:self.assertEqual(decoder.feed(stereo,2,channel),[] if channel==0 else [packet.encode()])
            finally:decoder.close()


class ModemLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_mock_stream_feeds_packet_handler_and_stops(self):
        import asyncio,tempfile
        from pathlib import Path
        from unittest.mock import AsyncMock,MagicMock,patch
        from server.software_modem import SoftwareModem
        handler=MagicMock();handler.handle_rf_packet=AsyncMock()
        with tempfile.TemporaryDirectory() as temp:
            modem=SoftwareModem(handler,Path(temp)/'modem.json')
            stream=MagicMock();stream.active=True
            with patch('sounddevice.RawInputStream',return_value=stream) as factory,patch('sounddevice.check_input_settings'),patch.object(modem,'devices',return_value=[dict(id=0,name='Test input',host_api='Test',channels=1)]):
                await modem.start({'device':0,'channel':0})
                callback=factory.call_args.kwargs['callback']
                payload=AX25Frame.from_aprs_string('K5YVY>APRS:>Live mocked stream').encode()
                status=MagicMock(input_overflow=False)
                callback(reference_audio(payload),0,None,status)
                for _ in range(100):
                    if handler.handle_rf_packet.await_count:break
                    await asyncio.sleep(.01)
                handler.handle_rf_packet.assert_awaited_once_with(payload,interface=modem)
                self.assertFalse(modem.can_transmit)
                await modem.stop();stream.close.assert_called_once()
                self.assertIsNone(modem.worker)
                self.assertFalse(modem.connected)

    async def test_development_routes_block_public_browser(self):
        import tempfile
        from pathlib import Path
        from unittest.mock import MagicMock
        from server.app import create_app
        from server.config import Config
        from tests.test_operator_auth import Browser
        with tempfile.TemporaryDirectory() as temp:
            handler=MagicMock();handler.rf_interfaces=[]
            app=create_app(Config(),MagicMock(),MagicMock(),MagicMock(),handler,
                           app_version='1.13.0-dev.1',config_path=Path(temp)/'config.toml')
            browser=Browser(app)
            for method,path in [('GET','status'),('GET','devices'),('GET','test-wav'),('GET','transmit-devices'),('POST','transmit-settings'),('POST','transmit-test'),('POST','stop-transmit'),('POST','start'),('POST','stop'),('POST','decode-wav')]:
                self.assertEqual((await browser.request(method,'/api/modem/'+path))[0],401)
            self.assertFalse(app.state.software_modem.can_transmit)


class ReleaseIdentityTests(unittest.TestCase):
    def test_release_version_and_installer_identity(self):
        from pathlib import Path
        from main import APP_VERSION
        self.assertEqual(APP_VERSION, '1.14.0')
        root=Path(__file__).resolve().parents[1]
        script=(root/'deploy/APRSPropView.iss').read_text(encoding='utf-8')
        self.assertIn('8F56D489-53F5-4E9E-89B0-BA55762CDE37',script)
        self.assertIn('APRSPropView.exe',script)
        self.assertNotIn('APRSPropViewDev.exe',script)


class OfflineRouteTests(unittest.IsolatedAsyncioTestCase):
    async def test_wav_route_decodes_without_touching_rf_handler(self):
        import tempfile
        from pathlib import Path
        from unittest.mock import MagicMock
        from starlette.requests import Request
        from server.app import create_app
        from server.config import Config
        with tempfile.TemporaryDirectory() as temp:
            handler=MagicMock();handler.rf_interfaces=[]
            app=create_app(Config(),MagicMock(),MagicMock(),MagicMock(),handler,
                           app_version='1.13.0-dev.1',config_path=Path(temp)/'config.toml')
            endpoint=next(route.endpoint for route in app.routes if getattr(route,'path','')=='/api/modem/decode-wav')
            payload=AX25Frame.from_aprs_string('N0CALL>APRS:>Offline route test').encode()
            raw=generate_test_wav(payload)
            async def receive():return {'type':'http.request','body':raw,'more_body':False}
            request=Request({'type':'http','method':'POST','path':'/api/modem/decode-wav','query_string':b'channel=0','headers':[]},receive)
            data=await endpoint(request)
            self.assertEqual(data['decoded_frames'],1)
            handler.handle_rf_packet.assert_not_called()


class ModemDashboardTests(unittest.IsolatedAsyncioTestCase):
    async def test_modem_only_dashboard_updates_without_packets(self):
        import asyncio, tempfile
        from pathlib import Path
        from unittest.mock import AsyncMock, MagicMock
        from server.config import Config
        from server.packet_handler import PacketHandler
        from server.software_modem import SoftwareModem
        config=Config();config.station.latitude=35;config.station.longitude=-79
        ws=MagicMock();ws.broadcast=AsyncMock()
        handler=PacketHandler(config,MagicMock(),None,None,ws)
        with tempfile.TemporaryDirectory() as temp:
            modem=SoftwareModem(handler,Path(temp)/'modem.json');handler.add_rf_interface(modem)
            task=asyncio.create_task(modem.connect())
            try:
                await asyncio.sleep(.02)
                modem.connected=True;modem.stream=MagicMock(active=True)
                await asyncio.sleep(.3)
                status=ws.broadcast.call_args.args[0]['data']
                self.assertTrue(status['rf_connected']);self.assertFalse(status['beacon']['rf_tx_available'])
                modem.transmitter.enabled=True
                await asyncio.sleep(.3)
                status=ws.broadcast.call_args.args[0]['data']
                self.assertTrue(status['beacon']['can_transmit']);self.assertTrue(status['beacon']['rf_tx_available'])
                modem.stream.active=False
                await asyncio.sleep(.3)
                self.assertFalse(ws.broadcast.call_args.args[0]['data']['rf_connected'])
                self.assertEqual(config.rf_ports,[])
            finally:
                task.cancel()
                try:await task
                except asyncio.CancelledError:pass

class CarrierTests(unittest.TestCase):
    def test_noise_clear_tone_busy_and_silence_releases(self):
        import random,struct,math
        rng=random.Random(83)
        for rate in (8000,44100,48000):
            decoder=AudioDecoder(rate)
            try:
                busy=0
                for _ in range(100):
                    samples=[rng.gauss(0,.08) for i in range(rate//50)]
                    decoder.feed(struct.pack('<'+'f'*len(samples),*samples))
                    busy+=bool(decoder.stats()['carrier_detected'])
                self.assertEqual(busy,0,rate)
                samples=[.2*math.sin(2*math.pi*1200*i/rate) for i in range(rate//10)]
                decoder.feed(struct.pack('<'+'f'*len(samples),*samples))
                self.assertTrue(decoder.stats()['carrier_detected'])
                decoder.feed(bytes(rate*4//2));self.assertFalse(decoder.stats()['carrier_detected'])
            finally:decoder.close()


class ModemAutostartTests(unittest.IsolatedAsyncioTestCase):
    async def test_restart_restores_saved_devices_tx_and_bypass(self):
        import json,tempfile
        from pathlib import Path
        from unittest.mock import MagicMock,AsyncMock,patch
        from server.software_modem import SoftwareModem
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'modem.json'
            path.write_text(json.dumps({'device':1,'device_name':'Radio in','host_api':'Test','channel':0,'auto_start':True}))
            path.with_name('modem-transmit.json').write_text(json.dumps({'enabled':True,'settings':{'device':2,'device_name':'Radio out','host_api':'Test','channel':0,'ptt':'vox','wait_for_clear_channel':False}}))
            handler=MagicMock();handler.rf_interfaces=[]
            modem=SoftwareModem(handler,path)
            async def start(settings):
                self.assertEqual(settings['device'],7)
                modem.connected=True;modem.stream=MagicMock(active=True)
            modem.start=AsyncMock(side_effect=start)
            with patch.object(modem,'devices',return_value=[{'id':7,'name':'Radio in','host_api':'Test'}]),patch.object(modem.transmitter,'outputs',return_value=[{'id':8,'name':'Radio out','host_api':'Test','channels':2}]),patch('sounddevice.check_output_settings'),patch('sounddevice.RawOutputStream') as output,patch('serial.Serial') as serial:
                await modem.restore_startup()
                self.assertTrue(modem.transmitter.enabled)
                self.assertEqual(modem.transmitter.settings['device'],8)
                self.assertFalse(modem.transmitter.settings['wait_for_clear_channel'])
                output.assert_not_called();serial.assert_not_called()
                await modem.close()
                self.assertTrue(json.loads(path.read_text())['auto_start'])
                self.assertTrue(json.loads(path.with_name('modem-transmit.json').read_text())['enabled'])
                await modem.stop()
                self.assertFalse(json.loads(path.read_text())['auto_start'])
                self.assertFalse(json.loads(path.with_name('modem-transmit.json').read_text())['enabled'])

    async def test_missing_input_does_not_fall_back(self):
        import tempfile
        from pathlib import Path
        from unittest.mock import MagicMock,AsyncMock,patch
        from server.software_modem import SoftwareModem
        with tempfile.TemporaryDirectory() as temp:
            modem=SoftwareModem(MagicMock(),Path(temp)/'modem.json')
            modem.settings={'auto_start':True,'device_name':'Missing radio','host_api':'Test'}
            modem.start=AsyncMock()
            with patch.object(modem,'devices',return_value=[{'id':1,'name':'Speakers','host_api':'Test'}]):await modem.restore_startup()
            modem.start.assert_not_called();self.assertFalse(modem.transmitter.enabled)
            self.assertIn('unavailable',modem.last_error)
