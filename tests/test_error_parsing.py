from custom_components.robovac_mqtt.api.parser import update_state
from custom_components.robovac_mqtt.const import DPS_MAP
from custom_components.robovac_mqtt.models import VacuumState
from custom_components.robovac_mqtt.proto.cloud.error_code_pb2 import ErrorCode
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
