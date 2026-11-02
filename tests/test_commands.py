"""Unit tests for api/commands.py: invalid command edge cases."""

import base64
import logging


import pytest

from custom_components.robovac_mqtt.api.commands import (
    _build_off_peak_sub_bytes,
    build_command,
    build_map_load_command,
    build_room_clean_command,
    build_set_boost_iq_command,
    build_set_child_lock_command,
    build_set_cleaning_intensity_command,
    build_set_cleaning_mode_command,
    build_set_cleaning_pattern_command,
    build_set_off_peak_charging_command,
    build_set_room_custom_command,
    build_set_voice_command,
    build_set_volume_command,
    build_set_volume_novel_command,
    build_set_water_level_command,
    build_zone_clean_command,
)
from custom_components.robovac_mqtt.api.parser import (
    _decode_raw_varints,
    _extract_off_peak_charging,
)
from custom_components.robovac_mqtt.const import (
    DPS_MAP,
    EUFY_CLEAN_CONTROL,
    SCALAR_DPS,
)
from custom_components.robovac_mqtt.proto.cloud.control_pb2 import (
    ModeCtrlRequest,
    RemoteCtrl,
    SelectRoomsClean,
)
from custom_components.robovac_mqtt.proto.cloud.map_edit_pb2 import MapEditRequest
from custom_components.robovac_mqtt.proto.cloud.multi_maps_pb2 import (
    MultiMapsManageRequest,
)
from custom_components.robovac_mqtt.proto.cloud.unisetting_pb2 import UnisettingRequest
from custom_components.robovac_mqtt.utils import (
    decode,
    decode_varint,
    encode,
    encode_varint,
)


def _build_fake_response_b64(
    enabled: bool,
    begin_hour: int,
    begin_minute: int,
    end_hour: int,
    end_minute: int,
    extra_padding: bytes = b"",
) -> str:
    """Build a fake UnisettingResponse base64 with OffPeakCharging at field 23."""
    sub = _build_off_peak_sub_bytes(enabled, begin_hour, begin_minute, end_hour, end_minute)
    tag23 = encode_varint((23 << 3) | 2)
    field23 = tag23 + encode_varint(len(sub)) + sub
    body = field23 + extra_padding
    prefixed = encode_varint(len(body)) + body
    return base64.b64encode(prefixed).decode()


def test_set_cleaning_mode_invalid():
    """Invalid cleaning mode should return empty dict."""
    result = build_set_cleaning_mode_command("nonexistent_mode")
    assert not result


def test_set_water_level_invalid():
    """Invalid water level should return empty dict."""
    result = build_set_water_level_command("super_high")
    assert not result


def test_set_cleaning_intensity_invalid():
    """Invalid cleaning intensity should return empty dict."""
    result = build_set_cleaning_intensity_command("ultra_deep")
    assert not result


def test_build_command_unknown_returns_empty():
    """Test build_command with unknown command returns empty dict."""
    assert not build_command("nonexistent_command")


def test_start_auto_default_payload():
    """Default auto clean preserves the original single-pass payload."""
    result = build_command("start_auto")
    expected = encode(
        ModeCtrlRequest,
        {
            "method": EUFY_CLEAN_CONTROL.START_AUTO_CLEAN,
            "auto_clean": {"clean_times": 1, "force_mapping": False},
        },
    )
    assert result == {DPS_MAP["PLAY_PAUSE"]: expected}
    decoded = decode(ModeCtrlRequest, result[DPS_MAP["PLAY_PAUSE"]])
    assert decoded.method == EUFY_CLEAN_CONTROL.START_AUTO_CLEAN
    assert decoded.auto_clean.clean_times == 1


@pytest.mark.parametrize(("clean_times", "expected"), [(2, 2), ("2", 2)])
def test_start_auto_clean_times(clean_times, expected, caplog):
    """Auto clean accepts an in-range repeat count and coerces strings."""
    with caplog.at_level(logging.WARNING):
        result = build_command("start_auto", clean_times=clean_times)
    decoded = decode(ModeCtrlRequest, result[DPS_MAP["PLAY_PAUSE"]])
    assert decoded.method == EUFY_CLEAN_CONTROL.START_AUTO_CLEAN
    assert decoded.WhichOneof("Param") == "auto_clean"
    assert decoded.auto_clean.clean_times == expected
    assert decoded.auto_clean.force_mapping is False
    assert "out of range" not in caplog.text


@pytest.mark.parametrize(("clean_times", "expected"), [(0, 1), (-1, 1), (5, 2)])
def test_start_auto_clean_times_clamped(clean_times, expected, caplog):
    """Out-of-range repeat counts are clamped to the app's x1/x2 with a warning."""
    with caplog.at_level(logging.WARNING):
        result = build_command("start_auto", clean_times=clean_times)
    decoded = decode(ModeCtrlRequest, result[DPS_MAP["PLAY_PAUSE"]])
    assert decoded.auto_clean.clean_times == expected
    assert f"clean_times {clean_times} out of range" in caplog.text


def test_set_child_lock_command():
    """Child lock command should encode a writable UnisettingRequest."""
    result = build_set_child_lock_command(True)

    assert DPS_MAP["UNSETTING"] in result
    decoded = decode(UnisettingRequest, result[DPS_MAP["UNSETTING"]])
    assert decoded.children_lock.value is True


@pytest.mark.parametrize("room_ids", [[8], [6, 2], [0], [2, 0, 6]])
@pytest.mark.parametrize("mode", ["GENERAL", "CUSTOMIZE"])
@pytest.mark.parametrize("tuya_transport", [False, True])
def test_s1_pro_room_clean_uses_zero_based_slots(room_ids, mode, tuya_transport):
    """T2080A uses order as a slot; leaving slot zero empty selects room zero."""
    command = build_command(
        "room_clean", model="T2080A", tuya_transport=tuya_transport,
        room_ids=room_ids, map_id=7, mode=mode,
    )
    request = decode(ModeCtrlRequest, command[DPS_MAP["PLAY_PAUSE"]])
    assert request.method == EUFY_CLEAN_CONTROL.START_SELECT_ROOMS_CLEAN
    rooms_clean = request.select_rooms_clean
    assert rooms_clean.map_id == 7
    assert rooms_clean.clean_times == 1
    assert rooms_clean.mode == (SelectRoomsClean.CUSTOMIZE if mode == "CUSTOMIZE" else SelectRoomsClean.GENERAL)
    assert [(room.id, room.order) for room in rooms_clean.rooms] == [
        (room_id, slot) for slot, room_id in enumerate(room_ids)
    ]


@pytest.mark.parametrize("model", ["", "T2351", "T2080"])
@pytest.mark.parametrize("tuya_transport", [False, True])
def test_other_models_keep_one_based_room_order(model, tuya_transport):
    """The verified T2080A fix must not change other models or unknown callers."""
    command = build_command(
        "room_clean", model=model, tuya_transport=tuya_transport,
        room_ids=[6, 0, 2], map_id=4,
    )
    rooms = decode(ModeCtrlRequest, command[DPS_MAP["PLAY_PAUSE"]]).select_rooms_clean.rooms
    assert [(room.id, room.order) for room in rooms] == [(6, 1), (0, 2), (2, 3)]


# ── zone (select-zones) clean ────────────────────────────────────────


def test_build_zone_clean_command():
    """Zone clean encodes a SelectZonesClean ModeCtrlRequest on DPS 152."""
    quad = [(100, 200), (500, 200), (500, 600), (100, 600)]
    result = build_zone_clean_command([quad], map_id=3, clean_times=2)

    assert DPS_MAP["PLAY_PAUSE"] in result
    decoded = decode(ModeCtrlRequest, result[DPS_MAP["PLAY_PAUSE"]])
    assert decoded.method == EUFY_CLEAN_CONTROL.START_SELECT_ZONES_CLEAN
    assert decoded.WhichOneof("Param") == "select_zones_clean"
    szc = decoded.select_zones_clean
    assert szc.map_id == 3
    assert len(szc.zones) == 1
    zone = szc.zones[0]
    assert zone.clean_times == 2
    q = zone.quadrangle
    got = [(q.p0.x, q.p0.y), (q.p1.x, q.p1.y), (q.p2.x, q.p2.y), (q.p3.x, q.p3.y)]
    assert got == quad


def test_build_zone_clean_command_empty():
    """No zones -> empty dict (nothing dispatched)."""
    assert not build_zone_clean_command([])


def test_build_zone_clean_command_skips_bad_quad():
    """A quad without exactly four corners is skipped (no zones left -> empty)."""
    assert not build_zone_clean_command([[(0, 0), (1, 1)]])


def test_build_command_zone_clean_dispatch():
    """build_command routes 'zone_clean' to the zone builder."""
    quad = [(0, 0), (10, 0), (10, 10), (0, 10)]
    result = build_command("zone_clean", zones_cm=[quad], map_id=1)

    assert DPS_MAP["PLAY_PAUSE"] in result
    decoded = decode(ModeCtrlRequest, result[DPS_MAP["PLAY_PAUSE"]])
    assert decoded.method == EUFY_CLEAN_CONTROL.START_SELECT_ZONES_CLEAN
    assert decoded.select_zones_clean.map_id == 1


def test_build_map_load_command():
    """Map load encodes a MAP_LOAD MultiMapsManageRequest on DPS 172."""
    result = build_map_load_command(7, seq=5)

    assert DPS_MAP["MULTI_MAP_MANAGE"] in result
    decoded = decode(MultiMapsManageRequest, result[DPS_MAP["MULTI_MAP_MANAGE"]])
    assert decoded.method == MultiMapsManageRequest.MAP_LOAD
    assert decoded.seq == 5
    assert decoded.common.cloud_mapid == 7


def test_build_map_load_command_invalid_id():
    """A non-positive cloud_mapid dispatches nothing."""
    assert not build_map_load_command(0)
    assert not build_map_load_command(-1)


def test_build_command_map_load_dispatch():
    """build_command routes 'map_load' to the map-load builder."""
    result = build_command("map_load", cloud_mapid=6, seq=2)

    assert DPS_MAP["MULTI_MAP_MANAGE"] in result
    decoded = decode(MultiMapsManageRequest, result[DPS_MAP["MULTI_MAP_MANAGE"]])
    assert decoded.method == MultiMapsManageRequest.MAP_LOAD
    assert decoded.common.cloud_mapid == 6
    assert decoded.seq == 2


# ── G-series scalar command builders (T2210/G50) ─────────────────────


def test_set_boost_iq_command():
    """BoostIQ writes a plain int to DPS 118."""
    assert build_set_boost_iq_command(True) == {SCALAR_DPS["BOOST_IQ"]: 1}
    assert build_set_boost_iq_command(False) == {SCALAR_DPS["BOOST_IQ"]: 0}


def test_set_cleaning_pattern_command():
    """Cleaning pattern maps Arranged->1, Random->2 on DPS 154."""
    assert build_set_cleaning_pattern_command("Arranged") == {
        SCALAR_DPS["CLEAN_PATTERN"]: 1
    }
    assert build_set_cleaning_pattern_command("Random") == {
        SCALAR_DPS["CLEAN_PATTERN"]: 2
    }


def test_set_volume_command():
    """Volume percent maps to a 0-10 step on DPS 111."""
    assert build_set_volume_command(0) == {SCALAR_DPS["VOLUME"]: 0}
    assert build_set_volume_command(50) == {SCALAR_DPS["VOLUME"]: 5}
    assert build_set_volume_command(100) == {SCALAR_DPS["VOLUME"]: 10}
    # Out-of-range clamps
    assert build_set_volume_command(140) == {SCALAR_DPS["VOLUME"]: 10}


def test_g_series_commands_via_dispatch():
    """build_command dispatches the G-series command names."""
    assert build_command("set_boost_iq", active=True) == {SCALAR_DPS["BOOST_IQ"]: 1}
    assert build_command("set_cleaning_pattern", pattern="Random") == {
        SCALAR_DPS["CLEAN_PATTERN"]: 2
    }
    assert build_command("set_volume", api_type="scalar", volume=70) == {
        SCALAR_DPS["VOLUME"]: 7
    }
    assert build_command("set_auto_return", active=True) == {
        SCALAR_DPS["AUTO_RETURN"]: 1
    }
    assert build_command("set_activity_log", active=False) == {
        SCALAR_DPS["ACTIVITY_LOG"]: 0
    }
    assert build_command("detangle_brush") == {SCALAR_DPS["DETANGLE"]: 1}
    # Accessory reset = DPS 150 JSON with the counter zeroed
    assert build_command(
        "reset_accessory", api_type="scalar", scalar_key="sensors"
    ) == {SCALAR_DPS["ACCESSORIES"]: '{"sensors": 0}'}


def test_scalar_movement_commands():
    """G50 movement (captured from the app's /req): start/home via DPS 5,
    pause/resume via DPS 122. (DPS 2/101 are ignored by the firmware.)"""
    assert build_command("start_auto", api_type="scalar") == {
        SCALAR_DPS["WORK_MODE"]: 1
    }
    assert build_command("return_to_base", api_type="scalar") == {
        SCALAR_DPS["WORK_MODE"]: 3
    }
    assert build_command("pause", api_type="scalar") == {SCALAR_DPS["PAUSE"]: 1}
    assert build_command("stop", api_type="scalar") == {SCALAR_DPS["PAUSE"]: 1}
    assert build_command("play", api_type="scalar") == {SCALAR_DPS["PAUSE"]: 2}
    # Novel devices still get protobuf movement payloads (unchanged)
    assert build_command("start_auto", api_type="novel") != {SCALAR_DPS["WORK_MODE"]: 1}
    # Scalar SETTINGS remain real scalar writes (unaffected)
    assert build_command("set_fan_speed", api_type="scalar", fan_speed="Max") == {
        "102": 3
    }


# ── Novel voice / volume command builders ────────────────────────────


def test_build_set_volume_novel_command():
    """Novel-protocol volume writes a plain 0-100 int to DPS 161."""
    assert build_set_volume_novel_command(0) == {DPS_MAP["VOLUME"]: 0}
    assert build_set_volume_novel_command(50) == {DPS_MAP["VOLUME"]: 50}
    assert build_set_volume_novel_command(100) == {DPS_MAP["VOLUME"]: 100}
    assert build_set_volume_novel_command(150) == {DPS_MAP["VOLUME"]: 100}
    assert build_set_volume_novel_command(-10) == {DPS_MAP["VOLUME"]: 0}


def test_build_set_voice_command_known():
    """Voice command returns a non-empty DPS 162 payload for a known set_id."""
    result = build_set_voice_command(1201)  # English (Female)
    assert DPS_MAP["VOICE_LANGUAGE"] in result
    assert result[DPS_MAP["VOICE_LANGUAGE"]]


def test_build_set_voice_command_unknown():
    """Unknown voice set_id returns an empty dict (no command sent)."""
    assert not build_set_voice_command(9999)


def test_build_command_volume_novel_dispatch():
    """build_command dispatches set_volume for novel api_type to DPS 161."""
    result = build_command("set_volume", api_type="novel", volume=70)
    assert result == {DPS_MAP["VOLUME"]: 70}


def test_build_command_set_voice_dispatch():
    """build_command dispatches set_voice to DPS 162."""
    result = build_command("set_voice", set_id=1200)
    assert DPS_MAP["VOICE_LANGUAGE"] in result


# ── Off-peak charging command + parser round-trip ────────────────────


def test_off_peak_command_encodes_valid_prefix():
    """build_set_off_peak_charging_command produces a length-prefixed DPS 176 value."""
    cmd = build_set_off_peak_charging_command(
        enabled=True, begin_hour=22, begin_minute=0, end_hour=6, end_minute=30
    )
    assert DPS_MAP["UNSETTING"] in cmd
    raw = base64.b64decode(cmd[DPS_MAP["UNSETTING"]])
    body_len, start = decode_varint(raw, 0)
    assert start + body_len == len(raw), "Varint prefix must equal remaining byte count"


def test_off_peak_round_trip_small_payload():
    """Off-peak encode/decode round-trip with body < 128 bytes (single-byte varint prefix)."""
    b64 = _build_fake_response_b64(
        enabled=True, begin_hour=22, begin_minute=0, end_hour=6, end_minute=30
    )
    result = _extract_off_peak_charging(b64)
    assert result is not None
    assert result["enabled"] is True
    assert result["begin_hour"] == 22
    assert result["begin_minute"] == 0
    assert result["end_hour"] == 6
    assert result["end_minute"] == 30


def test_off_peak_round_trip_large_payload():
    """Off-peak decode round-trip with body > 127 bytes (multi-byte varint prefix).

    Regression for H1: the original heuristic (raw[0] == len(raw) - 1) silently
    failed when the encoded body exceeded 127 bytes, causing the off-peak switch
    and time entities to go permanently unavailable with no error logged.
    """
    dummy_tag = encode_varint((99 << 3) | 2)
    dummy_payload = b"x" * 150
    dummy_field = dummy_tag + encode_varint(len(dummy_payload)) + dummy_payload

    b64 = _build_fake_response_b64(
        enabled=False,
        begin_hour=0,
        begin_minute=30,
        end_hour=8,
        end_minute=0,
        extra_padding=dummy_field,
    )
    # Confirm the test precondition: body length must exceed 127 bytes.
    raw = base64.b64decode(b64)
    body_len, _ = decode_varint(raw, 0)
    assert body_len > 127, "Test precondition: body must be > 127 bytes to exercise multi-byte varint"

    result = _extract_off_peak_charging(b64)
    assert result is not None
    assert result["enabled"] is False
    assert result["begin_hour"] == 0
    assert result["begin_minute"] == 30
    assert result["end_hour"] == 8
    assert result["end_minute"] == 0


def test_off_peak_command_dispatch():
    """build_command dispatches set_off_peak_charging to DPS 176."""
    result = build_command(
        "set_off_peak_charging",
        enabled=True,
        begin_hour=22,
        begin_minute=0,
        end_hour=6,
        end_minute=30,
    )
    assert DPS_MAP["UNSETTING"] in result


def test_build_room_clean_command_keeps_room_zero():
    """Room id 0 is a real id on some maps (T2080A after room merges) and must
    reach SelectRoomsClean alongside the requested map id."""
    result = build_room_clean_command([0, 5], map_id=1)
    decoded = decode(ModeCtrlRequest, result[DPS_MAP["PLAY_PAUSE"]])
    assert decoded.method == EUFY_CLEAN_CONTROL.START_SELECT_ROOMS_CLEAN
    src = decoded.select_rooms_clean
    assert src.map_id == 1
    assert src.clean_times == 1
    assert [(r.id, r.order) for r in src.rooms] == [(0, 1), (5, 2)]


def test_set_room_custom_keeps_room_zero():
    """Room id 0 is a real id on some maps (T2080A after room merges) and must
    not be dropped from the SET_ROOMS_CUSTOM payload by a falsy check."""
    result = build_set_room_custom_command([0, 2], map_id=1, fan_speed="Turbo")
    assert DPS_MAP["MAP_EDIT_REQUEST"] in result
    decoded = decode(MapEditRequest, result[DPS_MAP["MAP_EDIT_REQUEST"]])
    assert decoded.method == MapEditRequest.SET_ROOMS_CUSTOM
    assert decoded.map_id == 1
    assert [r.id for r in decoded.rooms_custom.rooms_parm.rooms] == [0, 2]


def test_tuya_transport_suction_is_the_level_name():
    """Over Tuya (S1 Pro) DPS 158 is an enum string, not the MQTT index."""
    assert build_command("set_fan_speed", tuya_transport=True, fan_speed="quiet") == {"158": "Quiet"}
    assert build_command("set_fan_speed", tuya_transport=True, fan_speed="Max") == {"158": "Max"}
    assert build_command("set_fan_speed", tuya_transport=True, fan_speed="Boost_IQ") == {"159": True}
    assert build_command("set_fan_speed", tuya_transport=True, fan_speed="nope") == {}
    # MQTT robots keep the index.
    assert build_command("set_fan_speed", fan_speed="Quiet") == {"158": 0}


def test_tuya_transport_boost_iq_is_dps_159():
    assert build_command("set_boost_iq", tuya_transport=True, active=False) == {"159": False}


def test_remote_move_commands():
    """Manual drive writes a RemoteCtrl on DPS 155; unknown directions build nothing."""
    for name, value in (("brake", 0), ("forward", 1), ("back", 2), ("left", 3), ("right", 4)):
        command = build_command("remote_move", direction=name)
        assert list(command) == ["155"]
        assert decode(RemoteCtrl, command["155"]).direction == value
    assert build_command("remote_move", direction="sideways") == {}


def test_remote_mode_enter_and_exit():
    assert decode(ModeCtrlRequest, build_command("start_remote")["152"]).method == 5
    assert decode(ModeCtrlRequest, build_command("stop_remote")["152"]).method == 16


def test_set_height_detection_matches_the_app_payloads():
    """Byte-for-byte what was written to a real S1 Pro (field 107, length-prefixed)."""
    assert build_command("set_height_detection", mode="Safe") == {"176": "A9gGAQ=="}
    assert build_command("set_height_detection", mode="medium") == {"176": "A9gGAg=="}
    assert build_command("set_height_detection", mode="FREE") == {"176": "A9gGAw=="}
    assert build_command("set_height_detection", mode="nope") == {}


@pytest.mark.parametrize(("direction", "value"), [("brake", 0), ("forward", 1), ("back", 2), ("left", 3), ("right", 4)])
def test_s1_pro_remote_direction_uses_the_v2_normal_envelope(direction, value):
    """Decode method=NORMAL and its nested value, including a present BRAKE parameter."""
    command = build_command("remote_move", model="T2080A", direction=direction)
    raw = base64.b64decode(command["155"])
    length, pos = decode_varint(raw, 0)
    assert length == len(raw) - pos
    request = _decode_raw_varints(raw[pos:])
    assert request.get(1, 0) == 0  # NORMAL, not ROCKER
    assert set(request) == {2}  # normal remains present even with default value 0
    assert _decode_raw_varints(request[2]).get(1, 0) == value
    assert build_command("remote_move", model="T2351", direction=direction) == build_command("remote_move", direction=direction)
