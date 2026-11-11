import pytest

from custom_components.robovac_mqtt.api.parser import _obstacle_type_name, update_state
from custom_components.robovac_mqtt.const import DPS_MAP
from custom_components.robovac_mqtt.errors import (
    error_attributes,
    error_sensor_value,
    screen_error_code,
)
from custom_components.robovac_mqtt.models import VacuumState
from custom_components.robovac_mqtt.proto.cloud.error_code_pb2 import ErrorCode
from custom_components.robovac_mqtt.proto.cloud.work_status_pb2 import WorkStatus
from custom_components.robovac_mqtt.utils import encode_message


def test_error_code_mapping():
    """Test mapping of error codes."""
    state = VacuumState()

    # Test 6011
    error = ErrorCode()
    error.warn.append(6011)
    dps = {DPS_MAP["ERROR_CODE"]: encode_message(error)}

    new_state, _ = update_state(state, dps)
    assert new_state.error_code == 6011
    assert new_state.error_message == "STATION LOW CLEAN WATER"


def _apply(state, **lists):
    dps = {DPS_MAP["ERROR_CODE"]: encode_message(ErrorCode(**lists))}
    new_state, _ = update_state(state, dps)
    return new_state


def test_error_list_takes_priority_over_standing_warning():
    """A fault in `error` must not be hidden by a warning already in `warn`."""
    state = _apply(VacuumState(), warn=[6112])
    assert state.error_code == 6112

    state = _apply(state, error=[7002], warn=[6112])
    assert state.error_code == 7002
    assert state.error_codes == [7002]
    assert state.warn_codes == [6112]

    # Fault clears, warning remains
    state = _apply(state, warn=[6112])
    assert state.error_code == 6112
    assert state.error_codes == []
    assert state.warn_codes == [6112]


def test_error_list_only():
    """A fault reported only in `error` is surfaced (was previously code 0)."""
    state = _apply(VacuumState(), error=[7002])
    assert state.error_code == 7002
    assert state.error_message != ""
    assert state.warn_codes == []


def test_all_lists_empty_clears():
    state = _apply(VacuumState(), error=[7002], warn=[6112])
    state = _apply(state)
    assert state.error_code == 0
    assert state.error_message == ""
    assert state.error_codes == []
    assert state.warn_codes == []


# S1 Pro uses the app's packed integer codes, not the older t2080 proto enum.


def _report(*codes, new=False):
    error = ErrorCode()
    (error.new_code.error if new else error.error).extend(codes)
    return {DPS_MAP["ERROR_CODE"]: encode_message(error)}


def test_s1_screen_codes_preserve_raw_numbers_and_all_faults():
    state, _ = update_state(VacuumState(device_model="T2080A", activity="error"), _report(19924741, 19923712))
    attrs = error_attributes(state)
    assert error_sensor_value(state) == "E75"
    assert attrs["error_code"] == "E75" and attrs["error_code_raw"] == 19924741
    assert attrs["error_codes"] == ["E75", "E30"]
    assert attrs["error_codes_raw"] == [19924741, 19923712]
    assert attrs["error_active"] is True
    assert "route blocked" in state.error_message
    assert screen_error_code(19924741, "T2351") == 19924741
    assert screen_error_code(75, "T2080A") == 75
    assert screen_error_code(123456789, "T2080A") == 123456789


def test_confirmed_recovery_clears_the_active_fault_and_keeps_history():
    state, _ = update_state(VacuumState(device_model="T2080A", activity="error"), _report(19924741))
    healthy = WorkStatus(state=9)
    healthy.go_wash.mode = 1
    recovered, changes = update_state(state, {DPS_MAP["WORK_STATUS"]: encode_message(healthy)})
    assert recovered.error_code == 0 and recovered.error_codes == []
    assert recovered.error_message == "" and changes["error_code"] == 0
    assert error_sensor_value(recovered) == "None"
    assert error_attributes(recovered)["last_error_code"] == "E75"
    assert recovered.last_error_code == 19924741
    assert recovered.activity == "docked"


def test_standby_pause_manual_and_partial_updates_do_not_claim_recovery():
    state, _ = update_state(VacuumState(device_model="T2080A", activity="error"), _report(19924741))
    for status in [0, 1, 2, 6, 15, 100]:
        updated, _ = update_state(state, {DPS_MAP["WORK_STATUS"]: encode_message(WorkStatus(state=status))})
        assert updated.error_code == 19924741
    updated, _ = update_state(state, {DPS_MAP["BATTERY_LEVEL"]: 75})
    assert updated.error_code == 19924741


def test_fresh_fault_and_abnormal_charging_win_over_a_healthy_snapshot():
    state = VacuumState(device_model="T2080A")
    report = _report(19924741, new=True)
    report[DPS_MAP["WORK_STATUS"]] = encode_message(WorkStatus(state=7))
    updated, _ = update_state(state, report)
    assert updated.error_code == 19924741
    charging = WorkStatus(state=3)
    charging.charging.state = 2
    report = _report(19924741)
    report[DPS_MAP["WORK_STATUS"]] = encode_message(charging)
    updated, _ = update_state(state, report)
    assert updated.error_code == 19924741


def test_a_healthy_full_snapshot_does_not_reactivate_a_latched_fault():
    report = _report(19924741)
    report[DPS_MAP["WORK_STATUS"]] = encode_message(WorkStatus(state=9))
    updated, _ = update_state(VacuumState(device_model="T2080A"), report)
    assert updated.error_code == 0 and updated.last_error_code == 19924741


def test_a_paused_subtask_does_not_claim_recovery():
    state, _ = update_state(VacuumState(device_model="T2080A", activity="error"), _report(19924741))
    paused = WorkStatus(state=7)
    paused.go_home.state = 1
    updated, _ = update_state(state, {DPS_MAP["WORK_STATUS"]: encode_message(paused)})
    assert updated.error_code == 19924741


@pytest.mark.parametrize("code", [19988737, 19988739])  # EB11 clean water low, EB13 dirty tank full
def test_a_healthy_work_status_does_not_clear_station_codes(code):
    """The robot stays healthy while a base-station advisory is up, so it must not clear it."""
    state, _ = update_state(VacuumState(device_model="T2080A", activity="docked"), _report(code))
    healthy = WorkStatus(state=9)
    healthy.go_wash.mode = 1
    after, _ = update_state(state, {DPS_MAP["WORK_STATUS"]: encode_message(healthy)})
    assert after.error_code == code


def _recover(state):
    healthy = WorkStatus(state=9)
    healthy.go_wash.mode = 1
    after, _ = update_state(state, {DPS_MAP["WORK_STATUS"]: encode_message(healthy)})
    return after


def _docked_with(*, error=(), warn=()):
    report = ErrorCode()
    report.error.extend(error)
    report.warn.extend(warn)
    state, _ = update_state(
        VacuumState(device_model="T2080A", activity="docked"), {DPS_MAP["ERROR_CODE"]: encode_message(report)}
    )
    return state


def test_a_healthy_work_status_does_not_clear_a_warning():
    assert _recover(_docked_with(warn=[19923712])).error_code == 19923712  # E30 in warn[]


def test_a_docking_fault_is_cleared_even_when_listed_in_warn():
    assert _recover(_docked_with(warn=[19924741])).error_code == 0  # E75


def test_recovery_clears_the_movement_fault_but_keeps_a_station_code_that_is_still_up():
    for order in ([19988739, 19924741], [19924741, 19988739]):  # EB13 and E75, either order
        after = _recover(_docked_with(error=order))
        assert after.error_codes == [19988739] and after.error_code == 19988739
        assert "dirty water" in after.error_message.lower()
        assert after.last_error_code == 19924741  # the cleared E75, not the kept EB13


def test_a_zero_entry_in_error_does_not_defeat_the_station_exemption():
    assert _recover(_docked_with(error=[0], warn=[19988739])).error_code == 19988739


def test_an_unmapped_warning_is_kept():
    assert _recover(_docked_with(warn=[12345])).error_code == 12345


@pytest.mark.parametrize("warn", [19923712, 19988739])  # E30, EB13
def test_a_warning_that_outlives_the_fault_becomes_the_headline(warn):
    after = _recover(_docked_with(error=[19924741], warn=[warn]))  # E75 cleared
    assert after.error_code == warn and after.last_error_code == 19924741


def test_extra_proto_fields_are_captured():
    """The fields #194 does not read: timestamp, new_code, battery, obstacle.

    error[]/warn[] priority and clearing are covered above; this covers only
    what this PR adds on top of them.
    """
    state = _apply(
        VacuumState(),
        error=[101],
        last_time=123456789,
        new_code={"error": [101], "warn": [6011]},
        battery={"restored": True},
        obstacle_reminder=[
            {
                "type": 0,  # POOP
                "photo_id": "photo123",
                "accuracy": 88,
                "map_id": 3,
                "point": {"x": 150, "y": -200},
            }
        ],
    )
    assert state.last_error_time == 123456789
    assert state.new_error_codes == [101]
    assert state.new_warn_codes == [6011]
    assert state.battery_restored is True
    assert len(state.obstacle_reminders) == 1
    ob0 = state.obstacle_reminders[0]
    assert ob0["type_name"] == "poop"
    assert ob0["photo_id"] == "photo123"
    assert ob0["accuracy"] == 88
    assert ob0["map_id"] == 3
    assert ob0["x"] == 150 and ob0["y"] == -200


def test_battery_and_obstacles_clear_as_snapshot():
    """battery_restored and obstacle_reminders are SNAPSHOT fields, like the lists.

    Each ErrorCode frame reports the robot's whole current error picture, and
    update_state applies changes through dataclasses.replace() -- so a field only
    written when present carries its old value forward for the life of the
    config entry. Before this was fixed, one battery swap left battery_restored
    True on every later state (and so in every later error_log entry), and the
    last obstacle reminder stuck forever.
    """
    stale = {"type": 0, "type_name": "poop", "photo_id": "old",
             "accuracy": 90, "map_id": 1, "x": 1, "y": 2}
    state = VacuumState(battery_restored=True, obstacle_reminders=[stale])

    dps = {DPS_MAP["ERROR_CODE"]: encode_message(ErrorCode())}
    new_state, changes = update_state(state, dps)

    assert new_state.battery_restored is False
    assert new_state.obstacle_reminders == []
    # Written on EVERY frame, not only when set -- the coordinator relies on
    # that to tell a genuine swap from a carried-forward flag.
    assert changes["battery_restored"] is False
    assert changes["obstacle_reminders"] == []


def test_obstacle_type_name_falls_back_to_the_number():
    """An obstacle type our compiled proto does not know names itself numerically.

    The device can be ahead of the proto we ship; a bare number is still a
    usable label and must not raise.
    """
    assert _obstacle_type_name(7) == "7"


def test_every_obstacle_type_in_the_proto_has_a_name():
    """Every value of the proto enum resolves to a word, not a number.

    RATCHET, not a bite: ErrorCode.ObstacleReminder.Type currently holds only
    POOP = 0, so this cannot fail today -- it fails the day a new obstacle type
    is added to error_code.proto and nothing else is updated, which is exactly
    what deriving the name from the enum is for.
    """
    for value in ErrorCode.ObstacleReminder.Type.values():
        assert _obstacle_type_name(value) != str(value)
