"""Unit tests for task status sensor logic."""

# pylint: disable=redefined-outer-name

from unittest.mock import MagicMock

import pytest

from custom_components.robovac_mqtt.api.parser import update_state
from custom_components.robovac_mqtt.const import DPS_MAP
from custom_components.robovac_mqtt.models import VacuumState
from custom_components.robovac_mqtt.proto.cloud.work_status_pb2 import WorkStatus
from custom_components.robovac_mqtt.sensor import RoboVacSensor
from custom_components.robovac_mqtt.utils import encode_message


@pytest.fixture
def mock_coordinator():
    """Mock the coordinator."""
    coordinator = MagicMock()
    coordinator.device_id = "test_id"
    coordinator.device_name = "Test Vac"
    coordinator.device_model = "T2118"
    coordinator.data = VacuumState()
    return coordinator


def test_task_status_mapping():
    """Test mapping of WorkStatus to task_status string."""
    state = VacuumState()

    # Case 1: Cleaning
    ws = WorkStatus()
    ws.state = 5  # Cleaning
    dps = {DPS_MAP["WORK_STATUS"]: encode_message(ws)}
    new_state = update_state(state, dps)
    assert new_state.task_status == "Cleaning"

    # Case 2: Washing Mop
    ws = WorkStatus()
    ws.state = 5
    ws.go_wash.mode = 1  # Washing
    dps = {DPS_MAP["WORK_STATUS"]: encode_message(ws)}
    new_state = update_state(state, dps)
    assert new_state.task_status == "Washing Mop"

    # Case 3: Drying Mop
    ws = WorkStatus()
    ws.state = 5
    ws.go_wash.mode = 2  # Drying
    dps = {DPS_MAP["WORK_STATUS"]: encode_message(ws)}
    new_state = update_state(state, dps)
    assert new_state.task_status == "Drying Mop"

    # Case 4: Returning to Wash
    ws = WorkStatus()
    ws.state = 5
    ws.go_wash.mode = 0  # Navigation
    dps = {DPS_MAP["WORK_STATUS"]: encode_message(ws)}
    new_state = update_state(state, dps)
    assert new_state.task_status == "Returning to Wash"

    # Case 5: Recharge & Resume (Returning)
    ws = WorkStatus()
    ws.state = 7  # Go Home
    ws.breakpoint.state = 0  # Doing (Resumable)
    dps = {DPS_MAP["WORK_STATUS"]: encode_message(ws)}
    new_state = update_state(state, dps)
    assert new_state.task_status == "Returning to Charge"

    # Case 6: Recharge & Resume (Charging)
    ws = WorkStatus()
    ws.state = 3  # Charging
    ws.breakpoint.state = 0  # Resumable
    dps = {DPS_MAP["WORK_STATUS"]: encode_message(ws)}
    new_state = update_state(state, dps)
    assert new_state.task_status == "Charging (Resume)"

    # Case 7: Normal Charging
    ws = WorkStatus()
    ws.state = 3
    # No breakpoint
    dps = {DPS_MAP["WORK_STATUS"]: encode_message(ws)}
    new_state = update_state(state, dps)
    assert new_state.task_status == "Charging"

    # Case 8: Returning to Empty Dust
    ws = WorkStatus()
    ws.state = 7
    ws.go_home.mode = 1  # COLLECT_DUST
    dps = {DPS_MAP["WORK_STATUS"]: encode_message(ws)}
    new_state = update_state(state, dps)
    assert new_state.task_status == "Returning to Empty"

    # Case 9: Positioning
    ws = WorkStatus()
    ws.state = 4
    dps = {DPS_MAP["WORK_STATUS"]: encode_message(ws)}
    new_state = update_state(state, dps)
    assert new_state.task_status == "Positioning"

    # Case 10: Error
    ws = WorkStatus()
    ws.state = 2
    dps = {DPS_MAP["WORK_STATUS"]: encode_message(ws)}
    new_state = update_state(state, dps)
    assert new_state.task_status == "Error"


def test_task_status_sensor(mock_coordinator):
    """Test task status sensor entity."""
    mock_coordinator.data.task_status = "Washing Mop"

    sensor = RoboVacSensor(
        mock_coordinator,
        "task_status",
        "Task Status",
        lambda s: s.task_status,
        category=None,
    )
    assert sensor.native_value == "Washing Mop"
