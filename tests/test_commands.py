"""Unit tests for api/commands.py: invalid command edge cases."""

from custom_components.robovac_mqtt.api.commands import (
    build_command,
    build_set_boost_iq_command,
    build_set_child_lock_command,
    build_set_cleaning_intensity_command,
    build_set_cleaning_mode_command,
    build_set_cleaning_pattern_command,
    build_set_volume_command,
    build_set_water_level_command,
)
from custom_components.robovac_mqtt.const import DPS_MAP, SCALAR_DPS
from custom_components.robovac_mqtt.proto.cloud.unisetting_pb2 import UnisettingRequest
from custom_components.robovac_mqtt.utils import decode


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
    assert build_command("set_volume", volume=70) == {SCALAR_DPS["VOLUME"]: 7}
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
