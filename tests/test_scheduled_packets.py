from server.scheduled_packets import build_bulletin_info, build_object_info, object_transmit_mode


def test_build_bulletin_info_uses_bln_addressee():
    assert build_bulletin_info({"id": "1", "text": "Club net 7PM"}) == ":BLN1     :Club net 7PM"


def test_build_object_info_contains_padded_name_and_position():
    info = build_object_info({
        "name": "NETCTRL",
        "latitude": 35.1234,
        "longitude": -79.1234,
        "symbol_table": "/",
        "symbol_code": "r",
        "comment": "Net control",
    })

    assert info.startswith(";NETCTRL  *")
    assert "3507.40N/07907.40WrNet control" in info


def test_build_object_info_supports_permanent_item_and_motion_metadata():
    info = build_object_info({
        "name": "SAG1",
        "latitude": 35.5,
        "longitude": -79.25,
        "symbol_table": "\\",
        "symbol_code": ">",
        "permanent": True,
        "speed_mph": 42,
        "course_deg": 271,
        "frequency": "146.520",
        "tone": "100.0",
        "comment": "Moving object",
    })

    assert info.startswith(")SAG1!")
    assert "3530.00N\\07915.00W>" in info
    assert "271/042" in info
    assert "146.520MHz" in info
    assert "T100.0" in info


def test_object_transmit_mode_respects_scope_and_enabled_state():
    assert object_transmit_mode({"enabled": False}, "both") is None
    assert object_transmit_mode({"scope": "private"}, "both") is None
    assert object_transmit_mode({"scope": "local"}, "both") == "rf"
    assert object_transmit_mode({"scope": "global", "mode": "aprs_is"}, "both") == "aprs_is"
