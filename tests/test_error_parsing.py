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
    # The full warn list is now captured too (not just [0]).
    assert new_state.warn_codes == [6011]


def test_full_error_capture():
    """The whole ErrorCode proto is mined: error[] (previously NEVER read), the
    full warn[], timestamp, new_code, obstacle/poop reminder, and battery swap."""
    state = VacuumState()
    error = ErrorCode()
    error.error.extend([101, 102])        # real errors — the old parser ignored these
    error.warn.extend([6011, 6012])       # multiple warnings
    error.last_time = 123456789
    error.new_code.error.append(101)
    error.new_code.warn.append(6011)
    error.battery.restored = True
    ob = error.obstacle_reminder.add()
    ob.type = 0                           # POOP
    ob.photo_id = "photo123"
    ob.accuracy = 88
    ob.map_id = 3
    ob.point.x = 150
    ob.point.y = -200
    dps = {DPS_MAP["ERROR_CODE"]: encode_message(error)}

    new_state, _ = update_state(state, dps)
    # A real error[] takes priority over a warn[] for the primary code.
    assert new_state.error_code == 101
    assert new_state.error_codes == [101, 102]
    assert new_state.warn_codes == [6011, 6012]
    assert new_state.last_error_time == 123456789
    assert new_state.new_error_codes == [101]
    assert new_state.new_warn_codes == [6011]
    assert new_state.battery_restored is True
    assert len(new_state.obstacle_reminders) == 1
    ob0 = new_state.obstacle_reminders[0]
    assert ob0["type_name"] == "poop"
    assert ob0["photo_id"] == "photo123"
    assert ob0["accuracy"] == 88
    assert ob0["map_id"] == 3
    assert ob0["x"] == 150 and ob0["y"] == -200


def test_error_clears_to_empty():
    """An empty ErrorCode clears the primary code and the lists."""
    state = VacuumState(error_code=101, error_codes=[101], warn_codes=[6011])
    dps = {DPS_MAP["ERROR_CODE"]: encode_message(ErrorCode())}
    new_state, _ = update_state(state, dps)
    assert new_state.error_code == 0
    assert new_state.error_message == ""
    assert new_state.error_codes == []
    assert new_state.warn_codes == []
