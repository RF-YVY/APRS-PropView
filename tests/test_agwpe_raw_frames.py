from server.ax25 import AX25Frame
from server.kiss import _agwpe_raw_payload_to_ax25


def test_agwpe_raw_k_frame_strips_leading_tnc_byte():
    frame = AX25Frame.from_aprs_string(
        "KR4CWL-4>APPRPV,WIDE1-1,WIDE2-1:>APRS PropView 1-5-4-2"
    )
    encoded = frame.encode()

    decoded = AX25Frame.decode(_agwpe_raw_payload_to_ax25(b"\x00" + encoded, port=0))

    assert decoded is not None
    assert decoded.from_call == "KR4CWL-4"
    assert decoded.to_call == "APPRPV"
    assert decoded.path_str == "WIDE1-1,WIDE2-1"


def test_agwpe_raw_k_frame_accepts_already_stripped_ax25():
    frame = AX25Frame.from_aprs_string(
        "N4JJ-15>APRRTE,KE4KDY-5*,KX4NC-4*,NC4CD-1*:!3647.52N/07607.25Wk307/014"
    )
    encoded = frame.encode()

    assert _agwpe_raw_payload_to_ax25(encoded, port=0) == encoded
