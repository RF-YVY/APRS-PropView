"""Independent distorted Bell 202 fixtures for the production receiver."""
import math
import random
import struct
import unittest
from server.ax25 import AX25Frame
from server.software_modem import AudioDecoder


def samples(frame, rate, offset=0, twist=-12, noise=.04):
    crc=0xffff
    for byte in frame:
        crc ^= byte
        for _ in range(8):crc=(crc>>1)^(0x8408 if crc&1 else 0)
    data=frame+struct.pack('<H',crc^0xffff)
    flag=[(0x7e>>bit)&1 for bit in range(8)]
    bits=flag*35;ones=0
    for byte in data:
        for bit in range(8):
            value=(byte>>bit)&1;bits.append(value);ones=ones+1 if value else 0
            if ones==5:bits.append(0);ones=0
    bits+=flag*8
    rng=random.Random(17);phase=0;tone=False;position=0
    output=bytearray()
    for index,bit in enumerate(bits):
        if not bit:tone=not tone
        frequency=(1200 if tone else 2200)+offset
        amplitude=.35 if tone else .35*10**(twist/20)
        end=round((index+1)*rate/1200)
        while position<end:
            output.extend(struct.pack('<f',amplitude*math.sin(phase)+rng.gauss(0,noise)))
            phase=(phase+2*math.pi*frequency/rate)%(2*math.pi);position+=1
    output.extend(b'\0'*4*(rate//4))
    return output


class EnhancedReceiverTests(unittest.TestCase):
    def test_tone_imbalance_offsets_and_sample_rates(self):
        frame=AX25Frame.from_aprs_string('W1AW>APTEST:>Independent distorted receive test 0123456789').encode()
        for rate,offset,twist in [(48000,-150,-12),(44100,100,-8),(12000,0,-8),(48000,100,8)]:
            with self.subTest(rate=rate,offset=offset,twist=twist):
                decoder=AudioDecoder(rate);packets=[]
                try:
                    raw=samples(frame,rate,offset,twist)
                    for i in range(0,len(raw),4*997):packets+=decoder.feed(raw[i:i+4*997])
                    self.assertEqual(packets,[frame])
                finally:decoder.close()

    def test_resync_discards_partial_frame_and_accepts_next_packet(self):
        frame=AX25Frame.from_aprs_string('W1AW>APTEST:>After transmit resynchronization').encode()
        raw=samples(frame,48000,twist=0,noise=0)
        decoder=AudioDecoder()
        try:
            decoder.feed(raw[:8000]);decoder.resync()
            self.assertEqual(decoder.feed(raw),[frame])
        finally:decoder.close()

    def test_noise_is_not_accepted_as_a_packet(self):
        rng=random.Random(84)
        decoder=AudioDecoder()
        try:
            for _ in range(100):
                raw=b''.join(struct.pack('<f',rng.gauss(0,.15)) for _ in range(960))
                self.assertEqual(decoder.feed(raw),[])
        finally:decoder.close()
