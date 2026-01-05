"""Unit tests for the API layer (parser and commands)."""

from unittest.mock import MagicMock, PropertyMock, patch

from custom_components.robovac_mqtt.api.commands import (
    build_command,
    build_room_clean_command,
    build_scene_clean_command,
    build_set_auto_action_cfg_command,
    build_set_clean_speed_command,
)
from custom_components.robovac_mqtt.api.parser import update_state
from custom_components.robovac_mqtt.const import DPS_MAP, EUFY_CLEAN_CONTROL
from custom_components.robovac_mqtt.models import VacuumState
from custom_components.robovac_mqtt.proto.cloud.error_code_pb2 import ErrorCode
from custom_components.robovac_mqtt.proto.cloud.work_status_pb2 import WorkStatus


def test_update_state_battery():
    """Test updating battery level."""
    state = VacuumState()
    dps = {DPS_MAP["BATTERY_LEVEL"]: "85"}
    new_state, _ = update_state(state, dps)
    assert new_state.battery_level == 85


@patch("custom_components.robovac_mqtt.api.parser.decode")
def test_update_state_work_status(mock_decode):
    """Test updating work status."""
    state = VacuumState()

    # Mock WorkStatus
    mock_status = MagicMock(spec=WorkStatus)
    mock_status.state = 4  # Cleaning
    mock_status.go_wash = "None"
    mock_decode.return_value = mock_status

    dps = {DPS_MAP["WORK_STATUS"]: "some_encoded_string"}
    new_state, _ = update_state(state, dps)

    assert new_state.activity == "cleaning"
    assert new_state.status_code == 4


@patch("custom_components.robovac_mqtt.api.parser.decode")
def test_update_state_error_code(mock_decode):
    """Test updating error code."""
    state = VacuumState()

    # Mock ErrorCode
    mock_error = MagicMock(spec=ErrorCode)
    mock_error.warn = [1]  # CRASH BUFFER STUCK
    mock_decode.return_value = mock_error

    dps = {DPS_MAP["ERROR_CODE"]: "some_encoded_string"}
    new_state, _ = update_state(state, dps)

    assert new_state.error_code == 1
    assert new_state.error_message == "CRASH BUFFER STUCK"


@patch("custom_components.robovac_mqtt.api.parser.decode")
def test_update_state_station_status(mock_decode):
    """Test updating station status."""
    state = VacuumState()

    # Mock StationResponse
    mock_station = MagicMock()
    # Configure the status object
    type(mock_station.status).collecting_dust = PropertyMock(return_value=True)
    mock_station.status.collecting_dust = True

    # Also need to make sure other checks don't fail if they are accessed
    mock_station.status.clear_water_adding = False
    mock_station.status.waste_water_recycling = False
    mock_station.status.disinfectant_making = False
    mock_station.status.cutting_hair = False

    mock_decode.return_value = mock_station

    dps = {DPS_MAP["STATION_STATUS"]: "some_encoded_string"}
    new_state, _ = update_state(state, dps)

    assert new_state.dock_status == "Emptying dust"


@patch("custom_components.robovac_mqtt.api.commands.encode")
def test_build_set_clean_speed(mock_encode):
    """Test building set clean speed command."""
    # This one doesn't use encode, it sends raw index
    cmd = build_set_clean_speed_command("Standard")
    assert cmd == {DPS_MAP["CLEAN_SPEED"]: "1"}

    cmd = build_command("set_fan_speed", fan_speed="Max")
    assert cmd == {DPS_MAP["CLEAN_SPEED"]: "3"}


@patch("custom_components.robovac_mqtt.api.commands.encode")
def test_build_scene_clean_command(mock_encode):
    """Test building scene clean command."""
    mock_encode.return_value = "encoded_scene_cmd"

    cmd = build_scene_clean_command(1)
    assert cmd == {DPS_MAP["PLAY_PAUSE"]: "encoded_scene_cmd"}

    # Verify what was encoded
    args, _ = mock_encode.call_args
    # args[1] is the data dict
    assert args[1]["method"] == EUFY_CLEAN_CONTROL.START_SCENE_CLEAN
    assert args[1]["scene_clean"]["scene_id"] == 1


@patch("custom_components.robovac_mqtt.api.commands.encode_message")
def test_build_room_clean_command(mock_encode_message):
    """Test building room clean command."""
    mock_encode_message.return_value = "encoded_room_cmd"

    cmd = build_room_clean_command([10, 11])
    assert cmd == {DPS_MAP["PLAY_PAUSE"]: "encoded_room_cmd"}

    # Verify protobuf construction would be complex to check fully against the mock,
    # but we checked that encode_message was called.
    assert mock_encode_message.called


@patch("custom_components.robovac_mqtt.api.commands.encode")
def test_build_set_auto_cfg(mock_encode):
    """Test building auto config command."""
    mock_encode.return_value = "encoded_auto_cfg"

    cfg = {"some": "config"}
    cmd = build_set_auto_action_cfg_command(cfg)
    assert cmd == {DPS_MAP["GO_HOME"]: "encoded_auto_cfg"}

    args, _ = mock_encode.call_args
    assert args[1]["auto_cfg"] == cfg
