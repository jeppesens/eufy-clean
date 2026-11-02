from custom_components.robovac_mqtt.api.parser import (
    _obstacle_type_name,
    update_state,
)
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
