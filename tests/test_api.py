"""Unit tests for the API layer (parser and commands)."""

from unittest.mock import MagicMock, PropertyMock, patch

from custom_components.robovac_mqtt.api.commands import (
    build_command,
    build_find_robot_command,
    build_room_clean_command,
    build_scene_clean_command,
    build_set_auto_action_cfg_command,
    build_set_clean_speed_command,
    build_set_cleaning_intensity_command,
    build_set_cleaning_mode_command,
    build_set_undisturbed_command,
    build_set_water_level_command,
)
from custom_components.robovac_mqtt.api.parser import update_state
from custom_components.robovac_mqtt.const import DPS_MAP, EUFY_CLEAN_CONTROL
from custom_components.robovac_mqtt.models import VacuumState
from custom_components.robovac_mqtt.proto.cloud.error_code_pb2 import ErrorCode
from custom_components.robovac_mqtt.proto.cloud.unisetting_pb2 import (
    UnisettingResponse,
)
from custom_components.robovac_mqtt.proto.cloud.work_status_pb2 import WorkStatus
from custom_components.robovac_mqtt.utils import encode


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
def test_update_state_work_mode(mock_decode):
    """Test updating work mode through parser."""
    # Case 1: Mode field present (1 = SELECT_ROOM)
    state = VacuumState()
    mock_status = MagicMock()
    mock_status.state = 5  # Cleaning
    mock_status.mode.value = 1
    mock_status.trigger.source = 0
    mock_status.HasField.side_effect = lambda f: f in ["mode", "trigger"]
    mock_decode.return_value = mock_status

    dps = {DPS_MAP["WORK_STATUS"]: "encoded"}
    new_state, _ = update_state(state, dps)
    assert new_state.work_mode == "Room"

    # Case 2: Mode field missing but cleaning
    state = VacuumState()
    mock_status.HasField.side_effect = None
    mock_status.HasField.return_value = False
    new_state, _ = update_state(state, dps)
    assert new_state.work_mode == "Auto"

    # Case 3: Mode field missing and not cleaning
    state = VacuumState()
    mock_status.state = 0  # Standby
    new_state, _ = update_state(state, dps)
    assert new_state.work_mode == "unknown"


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
    assert cmd == {DPS_MAP["CLEAN_SPEED"]: 1}

    cmd = build_command("set_fan_speed", fan_speed="Max")
    assert cmd == {DPS_MAP["CLEAN_SPEED"]: 3}


@patch("custom_components.robovac_mqtt.api.commands.encode")
def test_build_spot_clean_command(mock_encode):
    """Test building spot clean command."""
    build_command("clean_spot")
    mock_encode.assert_called()
    # The first argument is ModeCtrlRequest, second is the data dict
    args, _ = mock_encode.call_args
    assert args[1]["method"] == EUFY_CLEAN_CONTROL.START_SPOT_CLEAN
    assert args[1]["spot_clean"] == {"clean_times": 1}


@patch("custom_components.robovac_mqtt.api.commands.encode_message")
def test_build_set_cleaning_mode_command(mock_encode_message):
    """Test building global cleaning mode command."""
    mock_encode_message.return_value = "encoded_clean_mode"

    cmd = build_set_cleaning_mode_command("Vacuum and mop")
    assert cmd == {DPS_MAP["CLEANING_PARAMETERS"]: "encoded_clean_mode"}

    cmd = build_command("set_cleaning_mode", clean_mode="Mop")
    assert cmd == {DPS_MAP["CLEANING_PARAMETERS"]: "encoded_clean_mode"}
    assert mock_encode_message.call_count == 2


@patch("custom_components.robovac_mqtt.api.commands.encode_message")
def test_build_set_water_level_command(mock_encode_message):
    """Test building global water level command."""
    mock_encode_message.return_value = "encoded_water_level"

    cmd = build_set_water_level_command("High")
    assert cmd == {DPS_MAP["CLEANING_PARAMETERS"]: "encoded_water_level"}

    cmd = build_command("set_water_level", water_level="Medium")
    assert cmd == {DPS_MAP["CLEANING_PARAMETERS"]: "encoded_water_level"}
    assert mock_encode_message.call_count == 2


@patch("custom_components.robovac_mqtt.api.commands.encode_message")
def test_build_set_cleaning_intensity_command(mock_encode_message):
    """Test building global cleaning intensity command."""
    mock_encode_message.return_value = "encoded_clean_intensity"

    cmd = build_set_cleaning_intensity_command("Quick")
    assert cmd == {DPS_MAP["CLEANING_PARAMETERS"]: "encoded_clean_intensity"}

    cmd = build_command("set_cleaning_intensity", cleaning_intensity="Normal")
    assert cmd == {DPS_MAP["CLEANING_PARAMETERS"]: "encoded_clean_intensity"}
    assert mock_encode_message.call_count == 2


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


def test_build_find_robot_command():
    """Test building find robot command."""
    cmd = build_find_robot_command(True)
    assert cmd == {DPS_MAP["FIND_ROBOT"]: True}

    cmd = build_find_robot_command(False)
    assert cmd == {DPS_MAP["FIND_ROBOT"]: False}


def test_update_state_find_robot():
    """Test updating find robot state."""
    state = VacuumState()

    # Test True
    dps = {DPS_MAP["FIND_ROBOT"]: True}
    new_state, changes = update_state(state, dps)
    assert new_state.find_robot is True
    assert changes["find_robot"] is True

    # Test False string
    dps = {DPS_MAP["FIND_ROBOT"]: "false"}
    new_state, changes = update_state(state, dps)
    assert new_state.find_robot is False


def test_build_set_undisturbed_command():
    """Test building a Do Not Disturb command."""
    cmd = build_set_undisturbed_command(True, 22, 0, 8, 0)
    assert DPS_MAP["UNDISTURBED"] in cmd


def test_update_state_undisturbed():
    """Test parsing Do Not Disturb state from DPS 157."""
    state = VacuumState()
    dps = {DPS_MAP["UNDISTURBED"]: "EAoAEgwKAggBEgIIFhoCCAg="}

    new_state, changes = update_state(state, dps)

    assert new_state.dnd_enabled is True
    assert new_state.dnd_start_hour == 22
    assert new_state.dnd_start_minute == 0
    assert new_state.dnd_end_hour == 8
    assert new_state.dnd_end_minute == 0
    assert "do_not_disturb" in changes["received_fields"]


def test_completed_docked_refresh_keeps_cleared_targets():
    """Test repeated completed docked updates keep targets cleared."""
    state = VacuumState(
        activity="docked",
        task_status="Completed",
        active_room_ids=[],
        active_room_names="",
    )

    dps = {DPS_MAP["WORK_STATUS"]: "ChADGgByAiIAegA="}
    new_state, _ = update_state(state, dps)

    assert new_state.activity == "docked"
    assert new_state.task_status == "Completed"
    assert new_state.active_room_ids == []
    assert new_state.active_room_names == ""


@patch("custom_components.robovac_mqtt.api.parser.decode")
def test_mid_clean_washing_does_not_clear_active_targets(mock_decode):
    """Test dock-side washing preserves the active room target."""
    state = VacuumState(
        activity="cleaning",
        active_room_ids=[1],
        active_room_names="Kitchen1",
    )

    mock_status = MagicMock()
    mock_status.state = 5
    mock_status.cleaning.state = 1
    mock_status.go_wash.mode = 1
    mock_status.mode.value = 1
    mock_status.HasField.side_effect = lambda field: field in {
        "mode",
        "charging",
        "cleaning",
        "go_wash",
        "station",
    }
    mock_status.station.HasField.return_value = True
    mock_decode.return_value = mock_status

    dps = {DPS_MAP["WORK_STATUS"]: "encoded"}
    new_state, _ = update_state(state, dps)

    assert new_state.activity == "docked"
    assert new_state.task_status == "Washing Mop"
    assert new_state.active_room_ids == [1]
    assert new_state.active_room_names == "Kitchen1"


@patch("custom_components.robovac_mqtt.api.parser.decode")
def test_charging_paused_state_does_not_clear_active_targets(mock_decode):
    """Test paused charging during wash preparation does not clear target."""
    state = VacuumState(
        activity="cleaning",
        active_room_ids=[1],
        active_room_names="Kitchen1",
    )

    mock_status = MagicMock()
    mock_status.state = 3
    mock_status.cleaning.state = 1
    mock_status.HasField.side_effect = lambda field: field in {
        "charging",
        "cleaning",
        "station",
        "mode",
    }
    mock_status.mode.value = 1
    mock_status.station.HasField.return_value = False
    mock_decode.return_value = mock_status

    dps = {DPS_MAP["WORK_STATUS"]: "encoded"}
    new_state, _ = update_state(state, dps)

    assert new_state.activity == "docked"
    assert new_state.task_status == "Paused"
    assert new_state.active_room_ids == [1]
    assert new_state.active_room_names == "Kitchen1"


@patch("custom_components.robovac_mqtt.api.parser.decode")
def test_completed_docked_state_clears_active_targets(mock_decode):
    """Test completed docked states clear the active room target."""
    state = VacuumState(
        activity="docked",
        task_status="Washing Mop",
        active_room_ids=[1],
        active_room_names="Kitchen1",
    )

    mock_status = MagicMock()
    mock_status.state = 3
    mock_status.HasField.side_effect = lambda field: field in {"charging"}
    mock_decode.return_value = mock_status

    dps = {DPS_MAP["WORK_STATUS"]: "encoded"}
    new_state, _ = update_state(state, dps)

    assert new_state.activity == "docked"
    assert new_state.task_status == "Completed"
    assert new_state.active_room_ids == []
    assert new_state.active_room_names == ""


def test_empty_room_clean_echo_preserves_existing_active_rooms():
    """Test empty room-clean echoes do not wipe optimistic target state."""
    state = VacuumState(
        active_room_ids=[1],
        active_room_names="Kitchen1",
        rooms=[{"id": 1, "name": "Kitchen1"}],
    )

    dps = {DPS_MAP["PLAY_PAUSE"]: "AggB"}
    new_state, changes = update_state(state, dps)

    assert new_state.active_room_ids == [1]
    assert new_state.active_room_names == "Kitchen1"
    assert "active_room_ids" not in changes


def test_update_state_device_info_dps169():
    """Test parsing DPS 169 (DeviceInfo) for MAC, WiFi SSID, and WiFi IP."""
    state = VacuumState()
    # Real DPS 169 payload from a T2351 (X10 Pro Omni)
    dps = {
        DPS_MAP["MAP_MANAGE"]: "vgEKF2V1ZnkgQ2xlYW4gWDEwIFBybyBPbW5pGhFjMDo"
        "4YTo2MDoyMzo4MzpkOSIGMy40Ljg1KAMyCkx1ZnRIYW1uZW06CjEwLjEuMC4xMDZCKD"
        "A5OTM2ZDFkNjdhZjE2YWJlYzJiNDdhOTZjYmU5M2RiNTY4NmM2YzhaCgoGMS4yLjI3EA"
        "hiLQgBEgQIAhADGgQIAhAPIgQIARABMgQIARADOgQIARABQgQIARADUgUIARCzJGoJVDI"
        "zNTFfb3Rh"
    }
    new_state, _ = update_state(state, dps)
    assert new_state.device_mac == "c0:8a:60:23:83:d9"
    assert new_state.wifi_ssid == "LuftHamnen"
    assert new_state.wifi_ip == "10.1.0.106"
    assert "wifi_ssid" in new_state.received_fields
    assert "wifi_ip" in new_state.received_fields


def test_update_state_wifi_signal_dps176():
    """Test parsing WiFi signal strength from DPS 176 (UnisettingResponse)."""
    # Build a UnisettingResponse with ap_signal_strength=80 (i.e. -60 dBm)
    encoded = encode(UnisettingResponse, {"ap_signal_strength": 80})

    state = VacuumState()
    dps = {DPS_MAP["UNSETTING"]: encoded}
    new_state, _ = update_state(state, dps)
    assert new_state.wifi_signal == -60.0
    assert "wifi_signal" in new_state.received_fields


def test_update_state_robot_position_dps179():
    """Test parsing robot position from DPS 179 telemetry."""
    state = VacuumState()
    # Real DPS 179 payload from active cleaning session
    dps = {"179": "HBIaOhgIlrujzgYQYxhiIPx9KIcOMgbO3QKg6gI="}
    new_state, changes = update_state(state, dps)
    assert "robot_position_x" in changes
    assert "robot_position_y" in changes
    # Raw unsigned varint values from undocumented telemetry format
    assert isinstance(new_state.robot_position_x, int)
    assert isinstance(new_state.robot_position_y, int)
    assert "robot_position" in new_state.received_fields


def test_known_unprocessed_dps_does_not_crash():
    """Test that known-but-unprocessed DPS keys are handled gracefully."""
    state = VacuumState()
    # DPS 155 (DIRECTION), 156 (MULTI_MAP_SW), 161 (unknown) are in KNOWN_UNPROCESSED_DPS
    dps = {"155": None, "156": True, "161": 80}
    new_state, _ = update_state(state, dps)
    # Should not crash and state should be unchanged (except raw_dps)
    assert new_state.activity == "idle"
