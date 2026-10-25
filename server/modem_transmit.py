"""Original AFSK transmit audio and bounded PTT control for the development modem."""
import asyncio
import ctypes
import math
import re
import random
import threading
import time

from server.ax25 import AX25Frame
from server.aprs_spot import operator_callsign
from server.modem_library import load_modem_library
import sys


def encode_audio(frame,rate=48000,gain=.2,delay_ms=300,tail_ms=50,channel=0):
    if channel not in (0,1):raise ValueError('Choose left/mono or right output.')
    library=load_modem_library()
    library.pv_encode.argtypes=[ctypes.POINTER(ctypes.c_uint8),ctypes.c_int,ctypes.c_int,ctypes.c_float,
                               ctypes.c_int,ctypes.c_int,ctypes.POINTER(ctypes.c_float),ctypes.c_int]
    raw=(ctypes.c_uint8*len(frame)).from_buffer_copy(frame)
    size=library.pv_encode(raw,len(frame),rate,gain,delay_ms,tail_ms,None,0)
    if size<=0:raise ValueError('Invalid APRS frame or audio/timing settings.')
    audio=(ctypes.c_float*size)()
    if library.pv_encode(raw,len(frame),rate,gain,delay_ms,tail_ms,audio,size)!=size:
        raise ValueError('Could not encode transmit audio.')
    if channel==0:return bytes(audio)
    stereo=(ctypes.c_float*(size*2))()
    stereo[1::2]=audio[:]
    return bytes(stereo)


class ModemTransmitter:
    MAX_KEY_SECONDS=10

    def __init__(self,modem):
        self.modem=modem;self.enabled=False;self.active=False;self.settings={}
        self.lock=asyncio.Lock();self.cancel=threading.Event()
        self.port=None;self.output=None;self.task=None
        self.sent=0;self.failed=0;self.last_error='';self.last_sent_at=0;self.underflows=0

    def receiver_ready(self):
        stream=getattr(self.modem,'stream',None)
        return bool(self.modem.connected and stream and stream.active)

    def status(self):
        return {'enabled':self.enabled,'active':self.active,'settings':dict(self.settings),
                'sent':self.sent,'failed':self.failed,'last_error':self.last_error,
                'last_sent_at':self.last_sent_at,'output_underflows':self.underflows,
                'max_key_seconds':self.MAX_KEY_SECONDS}

    @staticmethod
    def ports():
        from serial.tools.list_ports import comports
        return [{'device':p.device,'description':p.description} for p in comports()]

    @staticmethod
    def outputs():
        import sounddevice as sd
        hosts=sd.query_hostapis()
        return [{'id':i,'name':d['name'],'host_api':hosts[d['hostapi']]['name'],'channels':d['max_output_channels']}
                for i,d in enumerate(sd.query_devices()) if d['max_output_channels']]

    async def configure(self,body):
        if not isinstance(body,dict) or type(body.get('enabled')) is not bool:raise ValueError('Invalid transmit settings.')
        if not body['enabled']:
            await self.stop()
            return self.status()
        if not self.receiver_ready():raise ValueError('Start receiving before enabling transmission.')
        async with self.lock:
            wait_clear=body.get('wait_for_clear_channel',True)
            if type(wait_clear) is not bool:raise ValueError('Wait for clear channel must be true or false.')
            device=body.get('device');channel=body.get('channel',0)
            if type(device) is not int or type(channel) is not int or channel not in (0,1):raise ValueError('Select an output device and audio channel.')
            output=next((d for d in await asyncio.to_thread(self.outputs) if d['id']==device),None)
            if not output or output['channels']<=channel:raise ValueError('Selected output/channel is unavailable.')
            method=body.get('ptt','nomic_rts');port=body.get('port','')
            if method=='vox':port=''
            if method not in ('nomic_rts','serial_rts','serial_dtr','vox'):raise ValueError('Unsupported PTT method.')
            if method!='vox':
                if not isinstance(port,str) or not port:raise ValueError('Select the PTT serial port.')
                available=await asyncio.to_thread(self.ports)
                normalize = str.upper if sys.platform == 'win32' else str
                selected=next((p['device'] for p in available if normalize(p['device'])==normalize(port)),None)
                if selected is None:raise ValueError('PTT serial port is unavailable.')
                port=selected
                for iface in self.modem.handler.rf_interfaces:
                    if iface is not self.modem and normalize(str(getattr(iface,'port','')))==normalize(port):raise ValueError('That serial port is already assigned to an RF interface.')
            def number(key,default,minimum,maximum):
                value=body.get(key,default)
                if type(value) not in (int,float) or not math.isfinite(value) or not minimum<=value<=maximum:raise ValueError(f'Invalid {key}.')
                return value
            gain=number('gain',.2,.01,.9);delay=int(number('delay_ms',300,50,1500));tail=int(number('tail_ms',50,0,500))
            import sounddevice as sd
            rate=48000
            try:sd.check_output_settings(device=device,channels=channel+1,dtype='float32',samplerate=rate)
            except sd.PortAudioError:
                rate=44100;sd.check_output_settings(device=device,channels=channel+1,dtype='float32',samplerate=rate)
            self.settings={'device':device,'device_name':output['name'],'host_api':output['host_api'],'channel':channel,
                           'ptt':method,'port':port,'gain':gain,'delay_ms':delay,'tail_ms':tail,'rate':rate,'wait_for_clear_channel':wait_clear}
            self.enabled=True;self.last_error=''
            return self.status()

    async def send(self,frame):
        async with self.lock:
            if not self.enabled or not self.receiver_ready():raise ValueError('Start receiving and enable modem transmission first.')
            parsed=AX25Frame.decode(frame)
            if not parsed or parsed.control!=0x03 or parsed.pid!=0xf0:raise ValueError('Only APRS UI frames can be transmitted.')
            operator_callsign(parsed.source.callsign)
            # No queue survives a stop, restart or reconfiguration.
            settings=dict(self.settings);deadline=time.monotonic()+5
            while settings.get('wait_for_clear_channel',True) and self.modem.metrics.get('carrier_detected'):
                if not self.enabled or not self.receiver_ready():raise ValueError('Transmission was disabled.')
                if time.monotonic()>deadline:raise ValueError('Channel stayed busy; packet was not transmitted. Check local radio input, squelch and noise levels; retry when Channel shows clear.')
                await asyncio.sleep(.1)
            if settings.get('wait_for_clear_channel',True):await asyncio.sleep(.1+random.random()*.2)
            if not self.enabled or not self.receiver_ready():raise ValueError('Transmission was disabled.')
            if settings.get('wait_for_clear_channel',True) and self.modem.metrics.get('carrier_detected'):raise ValueError('Channel became busy; retry when clear.')
            self.cancel.clear()
            self.task=asyncio.create_task(asyncio.to_thread(self._play,frame,settings))
            try:
                await asyncio.shield(self.task);self.sent+=1;self.last_sent_at=time.time();self.last_error=''
            except asyncio.CancelledError:
                self.abort()
                try:await asyncio.shield(self.task)
                except Exception:pass
                raise
            except Exception as exc:
                self.failed+=1;self.enabled=False;self.last_error=str(exc);raise
            finally:self.task=None

    def abort(self):
        self.cancel.set()
        port=self.port
        if port:
            for name in ('rts','dtr'):
                try:setattr(port,name,False)
                except Exception:pass
        output=self.output
        if output:
            try:output.abort()
            except Exception:pass

    def _play(self,frame,settings):
        import sounddevice as sd
        # Resolve the chosen device again; never silently fall back to a speaker.
        device=sd.query_devices(settings['device'])
        if device['name']!=settings['device_name']:raise ValueError('Audio devices changed. Apply transmit settings again.')
        audio=encode_audio(frame,settings['rate'],settings['gain'],settings['delay_ms'],settings['tail_ms'],settings['channel'])
        if len(audio)/(4*(settings['channel']+1)*settings['rate'])>self.MAX_KEY_SECONDS-1:
            raise ValueError('Encoded packet exceeds the transmit time limit.')
        position=0;done=threading.Event();underflows=[];failure=[]
        def callback(outdata,frames,timing,status):
            nonlocal position
            if status.output_underflow:underflows.append(True)
            if self.cancel.is_set():raise sd.CallbackAbort
            count=len(outdata);remaining=len(audio)-position
            if remaining>=count:outdata[:]=audio[position:position+count];position+=count
            else:
                outdata[:]=audio[position:]+bytes(count-remaining);position=len(audio)
            if position>=len(audio):raise sd.CallbackStop
        timer=None
        try:
            timer=threading.Timer(self.MAX_KEY_SECONDS,self.abort);timer.daemon=True;timer.start()
            self.output=sd.RawOutputStream(device=settings['device'],samplerate=settings['rate'],channels=settings['channel']+1,
                 dtype='float32',blocksize=round(settings['rate']*.02),latency='high',callback=callback,finished_callback=done.set)
            if self.cancel.is_set():raise ValueError('Transmission stopped.')
            if settings['ptt']!='vox':
                import serial
                port=serial.Serial(port=None,baudrate=9600,timeout=0,write_timeout=1)
                self.port=port;port.rts=False;port.dtr=False;port.port=settings['port'];port.open()
                # NOMIC keys on either line: always hold the unused line low.
                port.rts=False;port.dtr=False
            if self.cancel.is_set():raise ValueError('Transmission stopped.')
            self.active=True
            if self.cancel.is_set():raise ValueError('Transmission stopped.')
            if self.port:
                if settings['ptt']=='serial_dtr':self.port.dtr=True
                else:self.port.rts=True
            if self.cancel.is_set() or not self.receiver_ready():raise ValueError('Transmission stopped or receive input closed.')
            self.output.start()
            end=time.monotonic()+self.MAX_KEY_SECONDS
            while not done.wait(.05):
                if self.cancel.is_set() or time.monotonic()>end:
                    self.abort()
                    raise ValueError('Transmission stopped or timed out.')
            if self.cancel.is_set():raise ValueError('Transmission stopped or timed out.')
            self.underflows+=len(underflows)
            if underflows:raise ValueError('Output audio underrun; the transmitted packet may be incomplete.')
        finally:
            cleanup_errors=[]
            port=self.port
            if port:
                for name in ('rts','dtr'):
                    try:setattr(port,name,False)
                    except Exception as exc:cleanup_errors.append(str(exc))
                try:port.close()
                except Exception as exc:cleanup_errors.append(str(exc))
                self.port=None
            output=self.output;self.output=None
            if output:
                try:output.close()
                except Exception as exc:cleanup_errors.append(str(exc))
            self.active=False
            if timer:timer.cancel()
            if cleanup_errors:raise ValueError('Transmit cleanup failed: '+'; '.join(cleanup_errors))

    async def stop(self):
        self.enabled=False
        self.abort()
        if self.task:
            try:await asyncio.wait_for(asyncio.shield(self.task),3)
            except (Exception,asyncio.CancelledError):pass
