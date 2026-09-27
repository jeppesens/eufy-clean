"""Unit tests for api/legacy_parser.py: legacy DPS -> VacuumState mapping."""

import base64
import dataclasses
import json

import pytest

from custom_components.robovac_mqtt import profiles
from custom_components.robovac_mqtt.api.legacy_parser import (
    encode_legacy_loops,
    parse_legacy_schedules,
    update_state_legacy,
)
from custom_components.robovac_mqtt.const import LEGACY_DPS_MAP
from custom_components.robovac_mqtt.models import VacuumState
from custom_components.robovac_mqtt.profiles import LEGACY_DUSTBAG_50H, DeviceProfile

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
    new_state, _ = update_state_legacy(state, {"102": "Turbo"})

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
    new_state, _ = update_state_legacy(state, {"106": 1})

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
    _, changes = update_state_legacy(state, {"106": "bad"})

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
    new_state, _ = update_state_legacy(state, {"5": mode_str})

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


# ── Pause control (DPS 122) ────────────────────────────────────────


def test_pause_control_outranks_a_running_work_status():
    """DPS 15 keeps reading "Running" for a paused job; 122 is the truth."""
    state = VacuumState()
    new_state, _ = update_state_legacy(state, {"15": "Running", "122": "Pause"})

    assert new_state.activity == "paused"


def test_continue_resumes_a_job_the_pause_control_paused():
    """...and it has to work in the other direction too.

    Because 15 never leaves "Running", only 122 can undo what 122 did. Without
    this the entity stayed Paused for the rest of a clean resumed from the eufy
    app — nothing else was ever going to move it back.
    """
    paused, _ = update_state_legacy(VacuumState(), {"15": "Running", "122": "Pause"})
    assert paused.activity == "paused"

    resumed, changes = update_state_legacy(paused, {"122": "Continue"})
    assert resumed.activity == "cleaning"
    assert changes["activity"] == "cleaning"


def test_nosweep_is_not_read_as_a_resume():
    """The control's idle position is ambiguous — a stopped job sits there too."""
    paused, _ = update_state_legacy(VacuumState(), {"15": "Running", "122": "Pause"})
    unchanged, _ = update_state_legacy(paused, {"122": "Nosweep"})

    assert unchanged.activity == "paused"


def test_continue_does_not_override_a_work_status_in_the_same_frame():
    """A frame that also docks the robot wins: docked is not "resumed"."""
    paused, _ = update_state_legacy(VacuumState(), {"15": "Running", "122": "Pause"})
    docked, _ = update_state_legacy(paused, {"15": "Charging", "122": "Continue"})

    assert docked.activity == "docked"


def test_continue_while_docked_changes_nothing():
    """Only a PAUSED job resumes; the work status owns every other state."""
    docked, _ = update_state_legacy(VacuumState(), {"15": "Charging"})
    still_docked, _ = update_state_legacy(docked, {"122": "Continue"})

    assert still_docked.activity == "docked"


# ── Multiple DPS in one update ──────────────────────────────────────


def test_multiple_dps_combined():
    """Multiple DPS keys in a single update are all processed."""
    state = VacuumState()
    new_state, _ = update_state_legacy(
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
    new_state, _ = update_state_legacy(state, {"999": "whatever"})

    assert new_state.activity == "idle"  # unchanged


def test_received_fields_accumulate():
    """received_fields should grow across multiple updates."""
    state = VacuumState()
    state1, _ = update_state_legacy(state, {"104": 80})
    state2, _ = update_state_legacy(state1, {"15": "Running"})

    assert "battery_level" in state2.received_fields
    assert "activity" in state2.received_fields


# ── Consumables (DPS 116) ──────────────────────────────────────────


def _consumables(durations: dict[str, int]) -> dict[str, str]:
    doc = {"consumable": {"duration": durations}}
    return {LEGACY_DPS_MAP["CONSUMABLES"]: base64.b64encode(json.dumps(doc).encode()).decode()}


def test_consumable_hours_map_onto_the_profile_fields():
    state, _ = update_state_legacy(
        VacuumState(), _consumables({"SB": 50, "RB": 40, "FM": 29, "DB": 3, "TR": 9})
    )
    assert state.accessories.side_brush_usage == 50
    assert state.accessories.main_brush_usage == 40
    assert state.accessories.filter_usage == 29
    assert state.accessories.dustbag_usage == 3


def test_a_spec_with_a_new_legacy_key_is_parsed(monkeypatch):
    """A profile spec alone wires a DPS 116 key; no second table to edit."""
    spec = dataclasses.replace(LEGACY_DUSTBAG_50H, attr_name="mop_usage", legacy_key="MP")
    monkeypatch.setitem(
        profiles.MODEL_PROFILES,
        "T9999",
        DeviceProfile(model="T9999", api_type="legacy", accessories={"mop_usage": spec}),
    )
    state, _ = update_state_legacy(VacuumState(), _consumables({"MP": 12}))
    assert state.accessories.mop_usage == 12


@pytest.mark.parametrize(
    ("days", "expected"),
    [
        ("Mon, Sun", "1100000"),
        (["Weekdays"], "0111110"),
        ("Every day", "1111111"),
        ("0010010", "0010010"),
        (None, "0000000"),
    ],
)
def test_loops_mask_is_sunday_first(days, expected):
    assert encode_legacy_loops(days) == expected


def test_loops_mask_rejects_an_unknown_day():
    with pytest.raises(ValueError):
        encode_legacy_loops("Tue, Xday")


def _timer(doc: dict) -> dict:
    encoded = base64.b64encode(json.dumps(doc).encode()).decode()
    return {"timerId": 7, "status": 0, "time": "09:15", "loops": "0100010",
            "dps": {"124": encoded}}


def test_app_schedule_shows_its_rooms_and_levels():
    """property[].roomId carries the rooms; levels read in any case and spelling."""
    (entry,) = parse_legacy_schedules({"result": [_timer({
        "method": "scheduleRoomsClean",
        "data": {"mapId": 3, "cleanMode": "customize", "cleanLevel": "max",
                 "waterMode": "medium", "property": [{"roomId": 0}, {"roomId": 2}],
                 "cleanTimes": 1},
        "timestamp": 1_700_000_000_000,
    })]})
    assert entry == {
        "id": 7, "enabled": False, "time": "09:15", "days": "Mon, Fri",
        "loops": "0100010", "action": "scheduleRoomsClean", "map_id": 3,
        "suction": "Max", "water": "Mid", "mode": "customize", "clean_times": 1,
        "rooms": [0, 2],
    }


def test_schedule_room_ids_list_is_still_read():
    (entry,) = parse_legacy_schedules(
        [_timer({"method": "scheduleRoomsClean", "data": {"roomIds": [4, 5]}})]
    )
    assert entry["rooms"] == [4, 5]
