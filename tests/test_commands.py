"""Unit tests for api/commands.py: invalid command edge cases."""

import base64

from custom_components.robovac_mqtt.api.commands import (
    _build_off_peak_sub_bytes,
    build_command,
    build_set_boost_iq_command,
    build_set_child_lock_command,
    build_set_cleaning_intensity_command,
    build_set_cleaning_mode_command,
    build_set_cleaning_pattern_command,
    build_set_off_peak_charging_command,
    build_set_voice_command,
    build_set_volume_command,
    build_set_volume_novel_command,
    build_set_water_level_command,
)
from custom_components.robovac_mqtt.api.parser import _extract_off_peak_charging
from custom_components.robovac_mqtt.const import DPS_MAP, SCALAR_DPS
from custom_components.robovac_mqtt.proto.cloud.unisetting_pb2 import UnisettingRequest
from custom_components.robovac_mqtt.utils import decode, decode_varint, encode_varint


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


def test_set_child_lock_command():
    """Child lock command should encode a writable UnisettingRequest."""
    result = build_set_child_lock_command(True)

    assert DPS_MAP["UNSETTING"] in result
    decoded = decode(UnisettingRequest, result[DPS_MAP["UNSETTING"]])
    assert decoded.children_lock.value is True


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
