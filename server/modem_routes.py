"""Operator-only development modem endpoints; default-deny API middleware applies."""
import asyncio
import wave
from fastapi import Request
from fastapi.responses import JSONResponse, Response
from server.ax25 import AX25Frame
from server.software_modem import decode_wav, generate_test_wav


def register_modem_routes(app, modem):
    offline_lock = asyncio.Lock()

    @app.get('/api/modem/status')
    async def status(): return modem.status()

    @app.get('/api/modem/devices')
    async def devices():
        try:return {'devices':await asyncio.to_thread(modem.devices)}
        except Exception as exc:return JSONResponse({'message':str(exc)},status_code=400)

    @app.post('/api/modem/start')
    async def start(request:Request):
        try:return await modem.start(await request.json())
        except Exception as exc:
            modem.last_error=str(exc)
            return JSONResponse({'message':str(exc)},status_code=400)

    @app.post('/api/modem/stop')
    async def stop():return await modem.stop()

    @app.get('/api/modem/transmit-devices')
    async def transmit_devices():
        try:
            outputs,ports=await asyncio.gather(asyncio.to_thread(modem.transmitter.outputs),asyncio.to_thread(modem.transmitter.ports))
            return {'outputs':outputs,'ports':ports}
        except Exception as exc:return JSONResponse({'message':str(exc)},status_code=400)

    @app.post('/api/modem/transmit-settings')
    async def transmit_settings(request:Request):
        try:
            await modem.transmitter.configure(await request.json())
            modem.persist_transmit()
            return modem.status()
        except Exception as exc:return JSONResponse({'message':str(exc)},status_code=400)

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
        except Exception as exc:return JSONResponse({'message':str(exc)},status_code=400)

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
            except (ValueError,wave.Error,EOFError) as exc:return JSONResponse({'message':str(exc)},status_code=400)

    @app.get('/api/modem/test-wav')
    async def test_wav():
        frame=AX25Frame.from_aprs_string('N0CALL>APRS:>PropView development modem offline test')
        return Response(generate_test_wav(frame.encode()),media_type='audio/wav',
                        headers={'Content-Disposition':'attachment; filename="propview-modem-test.wav"'})

    @app.on_event('shutdown')
    async def shutdown():await modem.close()
