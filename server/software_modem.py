"""Original native Bell 202 modem adapter. Development release: soundcard receive and opt-in transmit."""
import asyncio
import ctypes
import io
import json
import math
import queue
import struct
import sys
import threading
import time
import wave
from pathlib import Path

from server.ax25 import AX25Frame
from server.config_io import atomic_write

from server.modem_library import ROOT, load_modem_library
CALLBACK = ctypes.CFUNCTYPE(None, ctypes.POINTER(ctypes.c_uint8), ctypes.c_int, ctypes.c_void_p)


class AudioDecoder:
    def __init__(self, rate=48000):
        self.frames = []
        self.lib = load_modem_library()
        self.callback = CALLBACK(lambda data, size, _: self.frames.append(ctypes.string_at(data, size)))
        self.lib.pv_create.argtypes = [ctypes.c_int, CALLBACK, ctypes.c_void_p]
        self.lib.pv_create.restype = ctypes.c_void_p
        self.lib.pv_destroy.argtypes = [ctypes.c_void_p]
        self.lib.pv_push.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_float), ctypes.c_int, ctypes.c_int, ctypes.c_int]
        self.lib.pv_stats.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_double)]
        self.ctx = self.lib.pv_create(rate, self.callback, None)
        if not self.ctx: raise ValueError('Unsupported sample rate or modem initialization failure.')

    def feed(self, data, channels=1, channel=0):
        if not self.ctx: raise RuntimeError('Decoder is closed.')
        if channels not in (1,2) or not 0 <= channel < channels or len(data) % (4*channels):
            raise ValueError('Invalid float32 audio buffer.')
        samples = (ctypes.c_float * (len(data)//4)).from_buffer_copy(data)
        self.frames.clear()
        self.lib.pv_push(self.ctx, samples, len(data)//(4*channels), channels, channel)
        return list(self.frames)

    def stats(self):
        values = (ctypes.c_double * 7)()
        self.lib.pv_stats(self.ctx, values)
        return dict(zip(('samples','decoded_frames','crc_failures','peak','rms','clipped_samples','carrier_detected'), values))

    def resync(self):
        self.lib.pv_resync.argtypes=[ctypes.c_void_p]
        self.lib.pv_resync(self.ctx)

    def close(self):
        if self.ctx:
            self.lib.pv_destroy(self.ctx); self.ctx = None


def generate_test_wav(frame, rate=48000, noise=0, gain=.6, offset=0):
    """Generate independent NRZI/HDLC test audio; no playback or RF transmission."""
    import random
    crc=0xffff
    for value in frame:
        crc ^= value
        for _ in range(8): crc=(crc>>1)^0x8408 if crc&1 else crc>>1
    crc ^= 0xffff
    raw=frame+struct.pack('<H',crc)
    bits=[]
    for _ in range(35): bits.extend((0,1,1,1,1,1,1,0))
    ones=0
    for value in raw:
        for index in range(8):
            bit=(value>>index)&1;bits.append(bit)
            ones=ones+1 if bit else 0
            if ones==5:bits.append(0);ones=0
    for _ in range(8):bits.extend((0,1,1,1,1,1,1,0))
    rng=random.Random(810);phase=0;previous=0; samples=bytearray(); elapsed=0
    for index,bit in enumerate(bits):
        if bit==0:previous ^= 1
        frequency=(1200 if previous else 2200)+offset
        target=round((index+1)*rate/1200)
        while elapsed<target:
            value=gain*math.sin(phase)+rng.gauss(0,noise)
            samples.extend(struct.pack('<h',round(max(-1,min(1,value))*32767)))
            phase=(phase+2*math.pi*frequency/rate)%(2*math.pi);elapsed+=1
    out=io.BytesIO()
    with wave.open(out,'wb') as wav:
        wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(rate);wav.writeframes(samples)
    return out.getvalue()


def decode_wav(data, channel=0):
    """Decode PCM WAV without injecting test recordings into the RF station map."""
    with wave.open(io.BytesIO(data),'rb') as wav:
        rate,channels,width=wav.getframerate(),wav.getnchannels(),wav.getsampwidth()
        if channels not in (1,2) or width!=2 or not 8000<=rate<=96000 or not 0<=channel<channels:
            raise ValueError('Use 16-bit PCM WAV, mono/stereo, 8-96 kHz, with a valid channel.')
        if wav.getnframes()/rate>300: raise ValueError('Use a recording of five minutes or less.')
        decoder=AudioDecoder(rate); result=[];started=time.perf_counter()
        try:
            while True:
                raw=wav.readframes(4096)
                if not raw:break
                values=struct.unpack('<'+'h'*(len(raw)//2),raw)
                floats=struct.pack('<'+'f'*len(values),*(v/32768 for v in values))
                for frame in decoder.feed(floats,channels,channel):
                    parsed=AX25Frame.decode(frame)
                    if parsed:result.append(parsed.to_aprs_string())
            return {'packets':result[:1000], 'decoded_frames':len(result), 'stats':decoder.stats(),
                    'audio_seconds':wav.getnframes()/rate,'processing_seconds':time.perf_counter()-started}
        finally:decoder.close()


class SoftwareModem:
    name='Built-in modem (experimental)'

    @property
    def can_transmit(self):return self.transmitter.enabled

    @property
    def rx_only_rf(self):return not self.transmitter.enabled
    rx_only_is=True

    def __init__(self, handler, path):
        self.handler,self.path=handler,Path(path)
        from server.modem_transmit import ModemTransmitter
        self.transmitter=ModemTransmitter(self)
        self._closed=False
        self.connected=False;self.last_error='';self.stream=None;self.worker=None;self.consumer=None
        self.stop_event=threading.Event();self.audio=queue.Queue(maxsize=50)
        self.metrics={};self.dropped_blocks=0;self.overflows=0;self.frames_dropped=0
        self.lock=asyncio.Lock()
        try:self.settings=json.loads(self.path.read_text(encoding='utf-8'))
        except (OSError,ValueError):self.settings={}
        if not isinstance(self.settings,dict):self.settings={}
        try:
            saved_tx=json.loads(self.path.with_name('modem-transmit.json').read_text(encoding='utf-8'))
            if isinstance(saved_tx.get('settings'),dict):self.transmitter.settings=saved_tx['settings']
        except (OSError,ValueError,AttributeError):pass

    def persist_transmit(self):
        atomic_write(self.path.with_name('modem-transmit.json'),json.dumps({'enabled':self.transmitter.enabled,'settings':self.transmitter.settings}))

    async def restore_startup(self):
        if not self.settings.get('auto_start'):return
        try:
            saved=dict(self.settings)
            devices=await asyncio.to_thread(self.devices)
            device=next((d for d in devices if d['name']==saved.get('device_name') and d['host_api']==saved.get('host_api')),None)
            if not device:raise ValueError('Saved modem input is unavailable. Refresh devices and select the radio interface.')
            await self.start({'device':device['id'],'channel':saved.get('channel',0)})
            path=self.path.with_name('modem-transmit.json')
            if path.exists():
                tx=json.loads(path.read_text(encoding='utf-8'))
                settings=tx.get('settings',{})
                self.transmitter.settings=dict(settings)
                if tx.get('enabled') is True:
                    outputs=await asyncio.to_thread(self.transmitter.outputs)
                    output=next((d for d in outputs if d['name']==settings.get('device_name') and d['host_api']==settings.get('host_api')),None)
                    if not output:raise ValueError('Saved modem output is unavailable. Apply transmit settings again.')
                    await self.transmitter.configure({**settings,'device':output['id'],'enabled':True})
        except Exception as exc:
            self.transmitter.enabled=False
            self.last_error='Modem automatic startup: '+str(exc)

    def status(self):
        if self.connected and self.stream and not self.stream.active:
            self.connected=False;self.last_error='Audio input stopped. Reconnect the interface, refresh devices and start again.'
        return {'connected':self.connected,'running':bool(self.stream and self.stream.active),
                'receive_only':not self.transmitter.enabled,'transmit':self.transmitter.status(),'last_error':self.last_error,'metrics':dict(self.metrics),
                'dropped_blocks':self.dropped_blocks,'audio_overflows':self.overflows,
                'frames_dropped':self.frames_dropped,'settings':self.settings,
                'engine':'Original PropView Bell 202 / 1200 baud / four decoder lanes'}

    def devices(self):
        import sounddevice as sd
        hosts=sd.query_hostapis();result=[]
        for index,item in enumerate(sd.query_devices()):
            if item['max_input_channels']:
                result.append({'id':index,'name':item['name'],'host_api':hosts[item['hostapi']]['name'],
                               'channels':item['max_input_channels'],'default_rate':item['default_samplerate']})
        return result

    async def start(self, settings):
        async with self.lock:
            await self._stop()
            import sounddevice as sd
            if not isinstance(settings,dict):raise ValueError('Invalid modem settings.')
            device=settings.get('device'); channel=settings.get('channel',0)
            if type(device) is not int or type(channel) is not int or channel not in (0,1):
                raise ValueError('Select an input device and left/mono or right audio channel.')
            devices=await asyncio.to_thread(self.devices)
            selected=next((d for d in devices if d['id']==device),None)
            if not selected or selected['channels']<=channel:raise ValueError('The selected input/channel is unavailable. Refresh audio devices.')
            rate=48000;channels=channel+1
            try:sd.check_input_settings(device=device,channels=channels,dtype='float32',samplerate=rate)
            except sd.PortAudioError:
                rate=44100;sd.check_input_settings(device=device,channels=channels,dtype='float32',samplerate=rate)
            decoder=AudioDecoder(rate)
            self.settings={'device':device,'device_name':selected['name'],'host_api':selected['host_api'],
                           'channel':channel,'sample_rate':rate,'auto_start':True}
            self.metrics={};self.dropped_blocks=self.overflows=self.frames_dropped=0
            self.last_error='';self.stop_event.clear();self.audio=queue.Queue(maxsize=50)
            loop=asyncio.get_running_loop();frames=asyncio.Queue(maxsize=100)
            def enqueue(frame):
                if frames.full():self.frames_dropped+=1
                else:frames.put_nowait(frame)
            def callback(indata,count,timing,status):
                if status.input_overflow:self.overflows+=1
                try:self.audio.put_nowait(bytes(indata))
                except queue.Full:self.dropped_blocks+=1
            def worker():
                was_transmitting=False
                try:
                    while not self.stop_event.is_set():
                        try:raw=self.audio.get(timeout=.2)
                        except queue.Empty:continue
                        if self.transmitter.active:
                            was_transmitting=True;continue
                        if was_transmitting:
                            decoder.resync();was_transmitting=False
                        started=time.perf_counter()
                        for frame in decoder.feed(raw,channels,channel):loop.call_soon_threadsafe(enqueue,frame)
                        self.metrics={**decoder.stats(),'processing_ms':(time.perf_counter()-started)*1000}
                except Exception as exc:
                    self.last_error=str(exc);self.connected=False
                finally:decoder.close()
            async def consume():
                while True:
                    frame=await frames.get()
                    try:await self.handler.handle_rf_packet(frame,interface=self)
                    except Exception as exc:self.last_error='Decoded packet handling failed: '+str(exc)
            try:
                self.stream=sd.RawInputStream(device=device,samplerate=rate,channels=channels,dtype='float32',
                                              blocksize=round(rate*.02),callback=callback,latency='high')
                self.worker=threading.Thread(target=worker,name='PropView modem DSP',daemon=True)
                self.worker.start();self.consumer=asyncio.create_task(consume())
                await asyncio.to_thread(self.stream.start)
                self.connected=True
                atomic_write(self.path,json.dumps(self.settings))
                return self.status()
            except Exception:
                if not self.worker:decoder.close()
                await self._stop();raise

    async def _stop(self):
        self.connected=False
        await self.transmitter.stop()
        if self.stream:
            stream,self.stream=self.stream,None
            try:await asyncio.to_thread(stream.stop)
            except Exception as exc:self.last_error='Audio stop: '+str(exc)
            try:await asyncio.to_thread(stream.close)
            except Exception as exc:self.last_error='Audio close: '+str(exc)
        self.stop_event.set()
        if self.worker:
            await asyncio.to_thread(self.worker.join,3);self.worker=None
        if self.consumer:
            self.consumer.cancel()
            try:await self.consumer
            except asyncio.CancelledError:pass
            self.consumer=None

    async def stop(self):
        self.settings['auto_start']=False
        atomic_write(self.path,json.dumps(self.settings))
        async with self.lock:await self._stop()
        self.persist_transmit()
        return self.status()

    async def connect(self):
        await self.restore_startup()
        # Monitor connection/capability changes independently of incoming packets.
        # Quiet channels, TX disable/failures and lost audio must update the UI too.
        previous = None
        while not self._closed:
            status = self.status()
            signature = (status['connected'], self.can_transmit, self.last_error)
            if signature != previous:
                await self.handler.broadcast_status()
                previous = signature
            await asyncio.sleep(.25)

    async def close(self):
        self._closed=True
        async with self.lock:await self._stop()

    async def send(self, data):
        await self.transmitter.send(data)
