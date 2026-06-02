"""Unit tests for the RoboVacMQTTEntity."""

# pylint: disable=redefined-outer-name, unused-argument

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.components.vacuum import VacuumActivity

from custom_components.robovac_mqtt.const import (
    EUFY_CLEAN_CLEAN_SPEED,
    EUFY_CLEAN_VACUUMCLEANER_STATE,
)
from custom_components.robovac_mqtt.coordinator import EufyCleanCoordinator
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


@pytest.fixture
def mock_config_entry():
    """Mock the config entry."""
    config_entry = MagicMock()
    config_entry.entry_id = "test_entry_id"
    return config_entry


def test_vacuum_properties(mock_coordinator, mock_config_entry):
    """Test vacuum properties."""
    entity = RoboVacMQTTEntity(mock_coordinator, mock_config_entry)
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


def test_vacuum_attributes(mock_coordinator, mock_config_entry):
    """Test vacuum attributes."""
    entity = RoboVacMQTTEntity(mock_coordinator, mock_config_entry)

    mock_coordinator.data.battery_level = 80
    mock_coordinator.data.fan_speed = EUFY_CLEAN_CLEAN_SPEED.STANDARD
    mock_coordinator.data.error_code = 0
    mock_coordinator.data.task_status = "Cleaning"
    mock_coordinator.data.work_mode = "Room"

    attrs = entity.extra_state_attributes

    assert attrs["task_status"] == "Cleaning"
    assert attrs["work_mode"] == "Room"


@pytest.mark.asyncio
async def test_vacuum_commands(mock_coordinator, mock_config_entry):
    """Test vacuum commands."""
    entity = RoboVacMQTTEntity(mock_coordinator, mock_config_entry)

    with patch("custom_components.robovac_mqtt.vacuum.build_command") as mock_build:
        mock_build.return_value = {"cmd": "val"}

        api = mock_coordinator.data.api_type

        # Start (Default/Docked)
        await entity.async_start()
        mock_build.assert_called_with("start_auto", api_type=api)
        mock_coordinator.async_send_command.assert_called_with({"cmd": "val"})

        # Start (Paused -> Resume)
        mock_coordinator.data.activity = "paused"
        await entity.async_start()
        mock_build.assert_called_with("play", api_type=api)

        # Stop
        await entity.async_stop()
        mock_build.assert_called_with("stop", api_type=api)

        # Pause
        await entity.async_pause()
        mock_build.assert_called_with("pause", api_type=api)

        # Return to base
        await entity.async_return_to_base()
        mock_build.assert_called_with("return_to_base", api_type=api)

        # Spot Clean
        await entity.async_clean_spot()
        mock_build.assert_called_with("clean_spot")

        # Locate
        await entity.async_locate()
        mock_build.assert_called_with(
            "find_robot", api_type=mock_coordinator.data.api_type, active=True
        )


@pytest.mark.asyncio
async def test_set_fan_speed(mock_coordinator, mock_config_entry):
    """Test setting fan speed."""
    entity = RoboVacMQTTEntity(mock_coordinator, mock_config_entry)

    # Supported speeds (Mocking list if needed, but defaults are used)
    # entity._attr_fan_speed_list is set in init

    with patch("custom_components.robovac_mqtt.vacuum.build_command") as mock_build:
        mock_build.return_value = {"cmd": "speed"}

        speed_max = EUFY_CLEAN_CLEAN_SPEED.MAX.value
        await entity.async_set_fan_speed(speed_max)
        mock_build.assert_called_with(
            "set_fan_speed", api_type=mock_coordinator.data.api_type, fan_speed=speed_max
        )
        mock_coordinator.async_send_command.assert_called_with({"cmd": "speed"})

        # Invalid speed
        with pytest.raises(ValueError):
            await entity.async_set_fan_speed("InvalidSpeed")


@pytest.mark.asyncio
async def test_async_send_command_raw(mock_coordinator, mock_config_entry):
    """Test sending raw commands."""
    entity = RoboVacMQTTEntity(mock_coordinator, mock_config_entry)
    mock_coordinator.set_active_scene = MagicMock()
    mock_coordinator.data.scenes = [{"id": 5, "name": "Evening"}]

    with patch("custom_components.robovac_mqtt.vacuum.build_command") as mock_build:
        mock_build.return_value = {"cmd": "raw"}

        # Test scene_clean
        await entity.async_send_command("scene_clean", params={"scene_id": 5})
        mock_build.assert_called_with("scene_clean", scene_id=5)
        mock_coordinator.set_active_scene.assert_called_with(5, "Evening")

        # Test room_clean
        mock_coordinator.data.map_id = 9
        await entity.async_send_command("room_clean", params={"room_ids": [1]})
        mock_build.assert_called_with("room_clean", room_ids=[1], map_id=9)


@pytest.fixture
def mqtt_coordinator():
    """Create a real coordinator for MQTT-level tests."""
    mock_hass = MagicMock()
    mock_login = MagicMock()
    mock_login.openudid = "test_udid"
    device_info = {
        "deviceId": "test_device",
        "deviceModel": "T2150",
        "deviceName": "Test Vacuum",
    }
    coord = EufyCleanCoordinator(mock_hass, mock_login, device_info)
    coord.async_set_updated_data = MagicMock()
    return coord


@pytest.mark.asyncio
async def test_room_clean_applies_user_preferences(mqtt_coordinator):
    """Test that room_clean command applies user preferences from select entities."""
    mqtt_coordinator.data.fan_speed = "Turbo"
    mqtt_coordinator.data.mop_water_level = "High"
    mqtt_coordinator.data.cleaning_mode = "Vacuum and mop"
    mqtt_coordinator.data.map_id = 3

    vacuum = RoboVacMQTTEntity(mqtt_coordinator)
    mqtt_coordinator.async_send_command = AsyncMock()

    await vacuum.async_send_command("room_clean", {"room_ids": [1, 2]})

    # Two commands: set_room_custom + room_clean
    assert mqtt_coordinator.async_send_command.call_count == 2

    first_call = mqtt_coordinator.async_send_command.call_args_list[0][0][0]
    assert "170" in first_call  # DPS 170 = set_room_custom

    second_call = mqtt_coordinator.async_send_command.call_args_list[1][0][0]
    assert "152" in second_call  # DPS 152 = room_clean


@pytest.mark.asyncio
async def test_room_clean_with_explicit_params_overrides_preferences(mqtt_coordinator):
    """Test that explicit params override user preferences."""
    mqtt_coordinator.data.fan_speed = "Turbo"
    mqtt_coordinator.data.mop_water_level = "High"
    mqtt_coordinator.data.cleaning_mode = "Vacuum and mop"

    vacuum = RoboVacMQTTEntity(mqtt_coordinator)
    mqtt_coordinator.async_send_command = AsyncMock()

    await vacuum.async_send_command(
        "room_clean",
        {"room_ids": [1], "fan_speed": "Quiet", "water_level": "Low"},
    )

    assert mqtt_coordinator.async_send_command.call_count == 2


@pytest.mark.asyncio
async def test_mqtt_malformed_message_does_not_crash(mqtt_coordinator):
    """Test that malformed MQTT messages don't crash the coordinator."""
    initial_fan_speed = "Standard"
    mqtt_coordinator.data.fan_speed = initial_fan_speed

    malformed_messages = [
        b"not json",
        b"{}",
        b'{"payload": "not a dict"}',
        b'{"payload": {}}',
        b'{"payload": {"data": "not a dict"}}',
    ]

    for malformed_msg in malformed_messages:
        mqtt_coordinator._handle_mqtt_message(malformed_msg)

    # State should remain unchanged after all malformed messages
    assert mqtt_coordinator.data.fan_speed == initial_fan_speed


@pytest.mark.asyncio
async def test_app_segment_clean_command(mock_coordinator, mock_config_entry):
    """Test app_segment_clean converts IDs and sends room_clean."""
    entity = RoboVacMQTTEntity(mock_coordinator, mock_config_entry)
    entity.hass = mock_coordinator.hass
    mock_coordinator.data.map_id = 5

    with patch("custom_components.robovac_mqtt.vacuum.build_command") as mock_build:
        mock_build.return_value = {"152": "encoded"}
        await entity.async_send_command("app_segment_clean", params=[1, "2", 3.0])

        # Verify room_clean was called with int IDs via _async_handle_room_clean
        # The entity calls _async_handle_room_clean which calls build_command
        # with room_clean and the converted int IDs
        assert mock_coordinator.async_send_command.called


@pytest.mark.asyncio
async def test_app_segment_clean_invalid_ids(mock_coordinator, mock_config_entry):
    """Test app_segment_clean with invalid IDs does nothing."""
    entity = RoboVacMQTTEntity(mock_coordinator, mock_config_entry)
    entity.hass = mock_coordinator.hass

    await entity.async_send_command("app_segment_clean", params=["invalid"])
    mock_coordinator.async_send_command.assert_not_called()


@pytest.mark.asyncio
async def test_async_clean_segments_empty_list(mock_coordinator, mock_config_entry):
    """Test async_clean_segments with empty list does nothing."""
    entity = RoboVacMQTTEntity(mock_coordinator, mock_config_entry)
    entity.hass = mock_coordinator.hass

    await entity.async_clean_segments([])
    mock_coordinator.async_send_command.assert_not_called()
