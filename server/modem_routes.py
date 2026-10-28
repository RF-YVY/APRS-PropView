"""Operator-only development modem endpoints; default-deny API middleware applies."""
import asyncio
import logging
import wave
from fastapi import Request
from fastapi.responses import JSONResponse, Response
from server.ax25 import AX25Frame
from server.software_modem import decode_wav, generate_test_wav


logger = logging.getLogger(__name__)

def register_modem_routes(app, modem):
    offline_lock = asyncio.Lock()

    @app.get('/api/modem/status')
    async def status(): return modem.status()

    @app.get('/api/modem/devices')
    async def devices():
        try:return {'devices':await asyncio.to_thread(modem.devices)}
        except Exception:
            logger.exception('Listing modem input devices failed')
            return JSONResponse({'message':'Unable to list audio input devices. Check the audio interface connection.'},status_code=400)

    @app.post('/api/modem/start')
    async def start(request:Request):
        try:return await modem.start(await request.json())
        except Exception:
            logger.exception('Starting modem failed')
            modem.last_error='Unable to start the modem. Check the selected input device and settings.'
            return JSONResponse({'message':modem.last_error},status_code=400)

    @app.post('/api/modem/stop')
    async def stop():return await modem.stop()

    @app.get('/api/modem/transmit-devices')
    async def transmit_devices():
        try:
            outputs,ports=await asyncio.gather(asyncio.to_thread(modem.transmitter.outputs),asyncio.to_thread(modem.transmitter.ports))
            return {'outputs':outputs,'ports':ports}
        except Exception:
            logger.exception('Listing modem transmit devices failed')
            return JSONResponse({'message':'Unable to list transmit devices. Check the audio and serial connections.'},status_code=400)

    @app.post('/api/modem/transmit-settings')
    async def transmit_settings(request:Request):
        try:
            await modem.transmitter.configure(await request.json())
            modem.persist_transmit()
            return modem.status()
        except Exception:
            logger.exception('Applying modem transmit settings failed')
            return JSONResponse({'message':'Unable to apply transmit settings. Check the selected devices and settings.'},status_code=400)

    @app.post('/api/modem/stop-transmit')
    async def stop_transmit():
        await modem.transmitter.stop()
        modem.persist_transmit()
        return modem.status()

    @app.post('/api/modem/channel-wait')
    async def channel_wait(request:Request):
        body=await request.json()
        value=body.get('wait_for_clear_channel') if isinstance(body,dict) else None
        if type(value) is not bool:return JSONResponse({'message':'Choose enabled or disabled.'},status_code=400)
        async with modem.transmitter.lock:
            modem.transmitter.settings['wait_for_clear_channel']=value
            modem.persist_transmit()
        return modem.status()

    @app.post('/api/modem/transmit-test')
    async def transmit_test():
        try:
            from server.aprs_spot import operator_callsign
            call=modem.handler.config.station.full_callsign
            operator_callsign(modem.handler.config.station.callsign)
            frame=AX25Frame.from_aprs_string(f'{call}>APPRPV:>PropView development modem TX test')
            await modem.send(frame.encode())
            modem.handler.stats['rf_tx']+=1
            await modem.handler._record_tx_packet(frame.to_aprs_string(),'Built-in modem TX')
            return {'success':True,'message':'Test packet transmitted. Check reception on another station.'}
        except Exception:
            logger.exception('Modem test transmission failed')
            return JSONResponse({'message':'Unable to transmit the test packet. Check your callsign, modem settings and radio connection.'},status_code=400)

    @app.post('/api/modem/decode-wav')
    async def decode(request:Request):
        if offline_lock.locked():return JSONResponse({'message':'A recording is already being decoded.'},status_code=409)
        async with offline_lock:
            data=bytearray()
            async for chunk in request.stream():
                data.extend(chunk)
                if len(data)>32*1024*1024:
                    return JSONResponse({'message':'Choose a WAV recording smaller than 32 MB.'},status_code=413)
            try:
                return await asyncio.to_thread(decode_wav,bytes(data),int(request.query_params.get('channel','0')))
            except (ValueError,wave.Error,EOFError):
                return JSONResponse({'message':'Unable to decode recording. Use a valid 16-bit PCM WAV, mono/stereo, '
                                               '8-96 kHz, five minutes or less, with a valid channel.'},status_code=400)

    @app.get('/api/modem/test-wav')
    async def test_wav():
        frame=AX25Frame.from_aprs_string('N0CALL>APRS:>PropView development modem offline test')
        return Response(generate_test_wav(frame.encode()),media_type='audio/wav',
                        headers={'Content-Disposition':'attachment; filename="propview-modem-test.wav"'})

    @app.on_event('shutdown')
    async def shutdown():await modem.close()
