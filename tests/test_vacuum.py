"""Unit tests for the RoboVacMQTTEntity."""

# pylint: disable=redefined-outer-name, unused-argument

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.components.vacuum import VacuumActivity

from custom_components.robovac_mqtt.const import (
    EUFY_CLEAN_CLEAN_SPEED,
    EUFY_CLEAN_VACUUMCLEANER_STATE,
)
from custom_components.robovac_mqtt.models import VacuumState
from custom_components.robovac_mqtt.vacuum import RoboVacMQTTEntity


@pytest.fixture
def mock_coordinator():
    """Mock the coordinator."""
    coordinator = MagicMock()
    coordinator.device_id = "test_id"
    coordinator.device_name = "Test Vac"
    coordinator.device_model = "T2118"
    coordinator.data = VacuumState()
    coordinator.async_send_command = AsyncMock()
    return coordinator


def test_vacuum_properties(mock_coordinator):
    """Test vacuum properties."""
    entity = RoboVacMQTTEntity(mock_coordinator)
    entity.hass = MagicMock()

    assert entity.unique_id == "test_id"
    # assert entity.name is None  # has_entity_name is True

    # Test Activity Mapping
    mock_coordinator.data.activity = EUFY_CLEAN_VACUUMCLEANER_STATE.CLEANING
    assert entity.activity == VacuumActivity.CLEANING

    mock_coordinator.data.activity = EUFY_CLEAN_VACUUMCLEANER_STATE.DOCKED
    assert entity.activity == VacuumActivity.DOCKED

    mock_coordinator.data.activity = "error"
    assert entity.activity == VacuumActivity.ERROR

    mock_coordinator.data.activity = "idle"
    assert entity.activity == VacuumActivity.IDLE


def test_vacuum_attributes(mock_coordinator):
    """Test vacuum attributes."""
    entity = RoboVacMQTTEntity(mock_coordinator)

    mock_coordinator.data.battery_level = 80
    mock_coordinator.data.fan_speed = EUFY_CLEAN_CLEAN_SPEED.STANDARD
    mock_coordinator.data.error_code = 0
    mock_coordinator.data.task_status = "Cleaning"

    attrs = entity.extra_state_attributes
    assert attrs["battery_level"] == 80
    assert attrs["fan_speed"] == EUFY_CLEAN_CLEAN_SPEED.STANDARD
    assert attrs["task_status"] == "Cleaning"


@pytest.mark.asyncio
async def test_vacuum_commands(mock_coordinator):
    """Test vacuum commands."""
    entity = RoboVacMQTTEntity(mock_coordinator)

    with patch("custom_components.robovac_mqtt.vacuum.build_command") as mock_build:
        mock_build.return_value = {"cmd": "val"}

        # Start (Default/Docked)
        await entity.async_start()
        mock_build.assert_called_with("start_auto")
        mock_coordinator.async_send_command.assert_called_with({"cmd": "val"})

        # Start (Paused -> Resume)
        mock_coordinator.data.activity = "paused"
        await entity.async_start()
        mock_build.assert_called_with("play")

        # Stop
        await entity.async_stop()
        mock_build.assert_called_with("stop")

        # Pause
        await entity.async_pause()
        mock_build.assert_called_with("pause")

        # Return to base
        await entity.async_return_to_base()
        mock_build.assert_called_with("return_to_base")

        # Spot Clean
        await entity.async_clean_spot()
        mock_build.assert_called_with("clean_spot")

        # Locate
        await entity.async_locate()
        mock_build.assert_called_with("find_robot", active=True)


@pytest.mark.asyncio
async def test_set_fan_speed(mock_coordinator):
    """Test setting fan speed."""
    entity = RoboVacMQTTEntity(mock_coordinator)

    # Supported speeds (Mocking list if needed, but defaults are used)
    # entity._attr_fan_speed_list is set in init

    with patch("custom_components.robovac_mqtt.vacuum.build_command") as mock_build:
        mock_build.return_value = {"cmd": "speed"}

        speed_max = EUFY_CLEAN_CLEAN_SPEED.MAX.value
        await entity.async_set_fan_speed(speed_max)
        mock_build.assert_called_with("set_fan_speed", fan_speed=speed_max)
        mock_coordinator.async_send_command.assert_called_with({"cmd": "speed"})

        # Invalid speed
        with pytest.raises(ValueError):
            await entity.async_set_fan_speed("InvalidSpeed")


@pytest.mark.asyncio
async def test_async_send_command_raw(mock_coordinator):
    """Test sending raw commands."""
    entity = RoboVacMQTTEntity(mock_coordinator)

    with patch("custom_components.robovac_mqtt.vacuum.build_command") as mock_build:
        mock_build.return_value = {"cmd": "raw"}

        # Test scene_clean
        await entity.async_send_command("scene_clean", params={"scene_id": 5})
        mock_build.assert_called_with("scene_clean", scene_id=5)

        # Test room_clean
        mock_coordinator.data.map_id = 9
        await entity.async_send_command("room_clean", params={"room_ids": [1]})
        mock_build.assert_called_with("room_clean", room_ids=[1], map_id=9)
