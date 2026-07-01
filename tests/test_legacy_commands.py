"""Unit tests for api/legacy_commands.py: legacy command building."""

import logging

import pytest

from custom_components.robovac_mqtt.api.legacy_commands import build_legacy_command

# ── Basic commands ──────────────────────────────────────────────────


def test_start_auto():
    result = build_legacy_command("start_auto")
    assert result == {"2": True, "5": "auto"}


def test_play():
    result = build_legacy_command("play")
    assert result == {"2": True}


def test_resume():
    result = build_legacy_command("resume")
    assert result == {"2": True}


def test_pause():
    result = build_legacy_command("pause")
    assert result == {"2": False}


def test_stop():
    result = build_legacy_command("stop")
    assert result == {"2": False}


def test_return_to_base():
    result = build_legacy_command("return_to_base")
    assert result == {"101": True}


def test_go_home():
    result = build_legacy_command("go_home")
    assert result == {"101": True}


# ── Find robot ──────────────────────────────────────────────────────


def test_find_robot_active():
    result = build_legacy_command("find_robot", active=True)
    assert result == {"103": True}


def test_find_robot_inactive():
    result = build_legacy_command("find_robot", active=False)
    assert result == {"103": False}


def test_find_robot_default_active():
    result = build_legacy_command("find_robot")
    assert result == {"103": True}


# ── Fan speed ───────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "speed",
    ["No_suction", "Standard", "Quiet", "Turbo", "Boost_IQ", "Max"],
)
def test_set_fan_speed_valid(speed):
    result = build_legacy_command("set_fan_speed", fan_speed=speed)
    assert result == {"102": speed}


def test_set_fan_speed_invalid():
    result = build_legacy_command("set_fan_speed", fan_speed="SuperMax")
    assert result == {}


def test_set_fan_speed_missing():
    result = build_legacy_command("set_fan_speed")
    assert result == {}


# ── Cleaning modes ──────────────────────────────────────────────────


def test_clean_spot():
    result = build_legacy_command("clean_spot")
    assert result == {"2": True, "5": "Spot"}


def test_room_clean():
    result = build_legacy_command("room_clean")
    assert result == {"2": True, "5": "room"}


def test_edge_clean():
    result = build_legacy_command("edge_clean")
    assert result == {"2": True, "5": "Edge"}


# ── Room clean with room_ids warning ──────────────────────────────


def test_room_clean_with_room_ids_logs_warning(caplog):
    """room_clean should warn when room_ids are passed (unsupported on legacy)."""
    with caplog.at_level(logging.WARNING):
        result = build_legacy_command("room_clean", room_ids=[1, 2, 3])

    # Command should still work (full room clean)
    assert result == {"2": True, "5": "room"}
    assert "room_ids parameter is not supported on legacy devices" in caplog.text


def test_room_clean_without_room_ids_no_warning(caplog):
    """room_clean without room_ids should not warn."""
    with caplog.at_level(logging.WARNING):
        result = build_legacy_command("room_clean")

    assert result == {"2": True, "5": "room"}
    assert "room_ids" not in caplog.text


# ── Unsupported commands ────────────────────────────────────────────


@pytest.mark.parametrize(
    "command",
    [
        "scene_clean",
        "set_room_custom",
        "set_auto_cfg",
        "go_dry",
        "go_selfcleaning",
        "collect_dust",
        "set_cleaning_mode",
        "set_water_level",
        "set_cleaning_intensity",
        "reset_accessory",
        "nonexistent_command",
    ],
)
def test_unsupported_commands_return_empty(command):
    """Unsupported commands should return empty dict."""
    result = build_legacy_command(command)
    assert result == {}


# ── DPS key correctness ────────────────────────────────────────────


def test_dps_keys_are_strings():
    """All DPS keys in output should be string type."""
    result = build_legacy_command("start_auto")
    for key in result:
        assert isinstance(key, str), f"DPS key {key!r} should be a string"
