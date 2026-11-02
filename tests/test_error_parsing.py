from custom_components.robovac_mqtt.api.parser import update_state
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
