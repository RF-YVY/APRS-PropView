from server.ax25 import AX25Frame
from server.aprs_parser import parse_packet
from server.kiss import KISSFrameParser, make_kiss_frame


def test_kiss_round_trip_all_channels_and_chunk_boundaries():
    frame = AX25Frame.from_aprs_string(
        "N0TEST-1>APRS,WIDE1-1:!3430.00N/08900.00W>test"
    )
    frame.info += bytes([0xC0, 0xDB])
    encoded = frame.encode()
    for port in range(16):
        wire = make_kiss_frame(encoded, port)
        for split in range(len(wire) + 1):
            parser = KISSFrameParser()
            frames = parser.feed(wire[:split]) + parser.feed(wire[split:])
            assert frames == [encoded], (port, split)
            packet = parse_packet(AX25Frame.decode(frames[0]).to_aprs_string())
            assert packet.has_position
            assert packet.from_call == "N0TEST-1"
