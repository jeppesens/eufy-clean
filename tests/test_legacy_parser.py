"""Unit tests for api/legacy_parser.py: legacy DPS -> VacuumState mapping."""

import pytest

from custom_components.robovac_mqtt.api.legacy_parser import update_state_legacy
from custom_components.robovac_mqtt.models import VacuumState


# ── Work Status (DPS 15) ───────────────────────────────────────────


@pytest.mark.parametrize(
    "status_str, expected_activity",
    [
        ("Running", "cleaning"),
        ("Cleaning", "cleaning"),
        ("cleaning", "cleaning"),
        ("Spot", "cleaning"),
        ("Charging", "docked"),
        ("charging", "docked"),
        ("standby", "idle"),
        ("Standby", "idle"),
        ("Sleeping", "idle"),
        ("Sleep", "idle"),
        ("Recharge", "returning"),
        ("recharge", "returning"),
        ("Completed", "docked"),
        ("completed", "docked"),
        ("Fault", "error"),
        ("fault", "error"),
        ("Go Home", "returning"),
        ("Go_Home", "returning"),
        ("go_home", "returning"),
    ],
)
def test_work_status_mapping(status_str, expected_activity):
    """Each legacy work status string maps to the correct activity."""
    state = VacuumState()
    new_state, changes = update_state_legacy(state, {"15": status_str})

    assert new_state.activity == expected_activity
    assert changes["activity"] == expected_activity
    assert "activity" in new_state.received_fields


def test_work_status_unknown():
    """Unknown work status should not crash; activity remains default."""
    state = VacuumState()
    new_state, changes = update_state_legacy(state, {"15": "SomeUnknownStatus"})

    assert new_state.activity == "idle"  # default
    assert "activity" not in changes


def test_work_status_sets_task_status():
    """Work status should also set task_status to the raw status string."""
    state = VacuumState()
    new_state, _ = update_state_legacy(state, {"15": "Running"})

    assert new_state.task_status == "Running"


def test_work_status_charging_flag():
    """Charging flag derived from docked + charging/completed status."""
    state = VacuumState()

    # Charging -> docked + charging=True
    new_state, _ = update_state_legacy(state, {"15": "Charging"})
    assert new_state.charging is True

    # Completed -> docked + charging=True (completed means done charging at dock)
    new_state, _ = update_state_legacy(state, {"15": "Completed"})
    assert new_state.charging is True

    # Running -> cleaning + charging=False
    new_state, _ = update_state_legacy(state, {"15": "Running"})
    assert new_state.charging is False

    # Standby -> idle + charging=False
    new_state, _ = update_state_legacy(state, {"15": "Standby"})
    assert new_state.charging is False


# ── Battery Level (DPS 104) ────────────────────────────────────────


def test_battery_level():
    """Battery level is parsed as int."""
    state = VacuumState()
    new_state, changes = update_state_legacy(state, {"104": 85})

    assert new_state.battery_level == 85
    assert changes["battery_level"] == 85
    assert "battery_level" in new_state.received_fields


def test_battery_level_string():
    """Battery level should handle string values."""
    state = VacuumState()
    new_state, _ = update_state_legacy(state, {"104": "72"})

    assert new_state.battery_level == 72


def test_battery_level_invalid():
    """Invalid battery value should not crash."""
    state = VacuumState()
    new_state, changes = update_state_legacy(state, {"104": "invalid"})

    assert new_state.battery_level == 0  # default
    assert "battery_level" not in changes


# ── Clean Speed (DPS 102) ──────────────────────────────────────────


def test_clean_speed():
    """Clean speed is stored as-is."""
    state = VacuumState()
    new_state, changes = update_state_legacy(state, {"102": "Turbo"})

    assert new_state.fan_speed == "Turbo"
    assert "fan_speed" in new_state.received_fields


@pytest.mark.parametrize("speed", ["Standard", "Quiet", "Turbo", "Max", "Boost_IQ", "No_suction"])
def test_clean_speed_all_values(speed):
    """All known legacy clean speeds are accepted."""
    state = VacuumState()
    new_state, _ = update_state_legacy(state, {"102": speed})

    assert new_state.fan_speed == speed


# ── Error Code (DPS 106) ───────────────────────────────────────────


def test_error_code_known():
    """Known error codes map to error messages."""
    state = VacuumState()
    new_state, changes = update_state_legacy(state, {"106": 1})

    assert new_state.error_code == 1
    assert "CRASH BUFFER STUCK" in new_state.error_message.upper()
    assert "error_code" in new_state.received_fields


def test_error_code_zero():
    """Error code 0 means no error."""
    state = VacuumState()
    new_state, _ = update_state_legacy(state, {"106": 0})

    assert new_state.error_code == 0


def test_error_code_unknown():
    """Unknown error code should include code in message."""
    state = VacuumState()
    new_state, _ = update_state_legacy(state, {"106": 99999})

    assert new_state.error_code == 99999
    assert "99999" in new_state.error_message


def test_error_code_invalid():
    """Non-numeric error code should not crash."""
    state = VacuumState()
    new_state, changes = update_state_legacy(state, {"106": "bad"})

    assert "error_code" not in changes


# ── Find Robot (DPS 103) ───────────────────────────────────────────


def test_find_robot_true():
    state = VacuumState()
    new_state, _ = update_state_legacy(state, {"103": True})

    assert new_state.find_robot is True
    assert "find_robot" in new_state.received_fields


def test_find_robot_false():
    state = VacuumState()
    new_state, _ = update_state_legacy(state, {"103": False})

    assert new_state.find_robot is False


# ── Work Mode (DPS 5) ──────────────────────────────────────────────


@pytest.mark.parametrize(
    "mode_str, expected_display",
    [
        ("auto", "Auto"),
        ("room", "Room"),
        ("SmallRoom", "Small Room"),
        ("Spot", "Spot"),
        ("Edge", "Edge"),
        ("Nosweep", "No Sweep"),
        ("zone", "Zone"),
    ],
)
def test_work_mode_mapping(mode_str, expected_display):
    """Work mode strings map to display names."""
    state = VacuumState()
    new_state, changes = update_state_legacy(state, {"5": mode_str})

    assert new_state.work_mode == expected_display
    assert "work_mode" in new_state.received_fields


def test_work_mode_unknown():
    """Unknown work mode is stored as-is."""
    state = VacuumState()
    new_state, _ = update_state_legacy(state, {"5": "custom_mode"})

    assert new_state.work_mode == "custom_mode"


# ── Play/Pause (DPS 2) ─────────────────────────────────────────────


def test_play_pause_tracked():
    """Play/pause should be tracked in received_fields."""
    state = VacuumState()
    new_state, _ = update_state_legacy(state, {"2": True})

    assert "play_pause" in new_state.received_fields


# ── Multiple DPS in one update ──────────────────────────────────────


def test_multiple_dps_combined():
    """Multiple DPS keys in a single update are all processed."""
    state = VacuumState()
    new_state, changes = update_state_legacy(
        state,
        {
            "15": "Running",
            "104": 65,
            "102": "Turbo",
            "5": "auto",
        },
    )

    assert new_state.activity == "cleaning"
    assert new_state.battery_level == 65
    assert new_state.fan_speed == "Turbo"
    assert new_state.work_mode == "Auto"


def test_raw_dps_stored():
    """Raw DPS dict is accumulated across updates."""
    state = VacuumState()
    state1, _ = update_state_legacy(state, {"104": 50})
    state2, _ = update_state_legacy(state1, {"102": "Max"})

    assert state2.raw_dps["104"] == 50
    assert state2.raw_dps["102"] == "Max"


def test_unknown_dps_keys_ignored():
    """DPS keys not in legacy map should not crash."""
    state = VacuumState()
    new_state, changes = update_state_legacy(state, {"999": "whatever"})

    # Only raw_dps and received_fields should be in changes
    assert new_state.activity == "idle"  # unchanged


def test_received_fields_accumulate():
    """received_fields should grow across multiple updates."""
    state = VacuumState()
    state1, _ = update_state_legacy(state, {"104": 80})
    state2, _ = update_state_legacy(state1, {"15": "Running"})

    assert "battery_level" in state2.received_fields
    assert "activity" in state2.received_fields
