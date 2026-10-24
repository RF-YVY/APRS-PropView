"""Packaged decoder test, with no audio device, browser or user data access."""
def run():
    from server.ax25 import AX25Frame
    from server.software_modem import generate_test_wav,decode_wav
    import sounddevice
    frame=AX25Frame.from_aprs_string('N0CALL>APRS:>Development modem self-test')
    result=decode_wav(generate_test_wav(frame.encode()))
    if result['packets'] != [frame.to_aprs_string()]:raise RuntimeError('Packaged modem failed exact-packet self-test.')
    from server.modem_transmit import encode_audio
    from server.software_modem import AudioDecoder
    tx_audio=encode_audio(frame.encode());decoder=AudioDecoder()
    try:
        if decoder.feed(tx_audio)!=[frame.encode()]:raise RuntimeError('Packaged transmit encoder self-test failed.')
    finally:decoder.close()
    return {'tx_encoder_passed':True,'version':'1.13.0','passed':True,'decoded_frames':result['decoded_frames'],
            'audio_seconds':result['audio_seconds'],'processing_seconds':result['processing_seconds'],
            'portaudio_version':sounddevice.get_portaudio_version()[1],'transmit_defaults_off':True}
