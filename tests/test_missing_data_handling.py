# pylint: disable=redefined-outer-name
import pytest
"""Tests for missing data handling in vacuum and sensor entities.

This module contains comprehensive tests for how entities handle missing,
invalid, or edge case data from the coordinator.
"""

from unittest.mock import MagicMock

import pytest

from custom_components.robovac_mqtt.models import VacuumState
from custom_components.robovac_mqtt.sensor import BatterySensorEntity
from custom_components.robovac_mqtt.vacuum import RoboVacMQTTEntity
from custom_components.robovac_mqtt.select import (
    CleaningModeSelectEntity,
    SuctionLevelSelectEntity,
)


@pytest.fixture
def mock_coordinator():
    """Mock the coordinator."""
    coordinator = MagicMock()
    coordinator.device_id = "test_device"
    coordinator.device_name = "Test Vacuum"
    coordinator.device_model = "T2118"
    coordinator.data = VacuumState()
    coordinator.hass = MagicMock()

    # Required for entity device_info
    coordinator.device_info = {}

    return coordinator


def test_vacuum_entity_empty_rooms(mock_coordinator):
    """Test vacuum entity with empty rooms list."""
    mock_coordinator.data = VacuumState(rooms=[])
    entity = RoboVacMQTTEntity(mock_coordinator)
    attrs = entity.extra_state_attributes

    assert "rooms" in attrs
    assert attrs["rooms"] == []


def test_vacuum_entity_none_rooms(mock_coordinator):
    """Test vacuum entity with None rooms."""
    mock_coordinator.data = VacuumState(rooms=None)
    entity = RoboVacMQTTEntity(mock_coordinator)
    attrs = entity.extra_state_attributes

    assert "rooms" in attrs
    assert attrs["rooms"] == []


def test_vacuum_entity_valid_rooms(mock_coordinator):
    """Test vacuum entity with valid rooms."""
    rooms = [{"id": 1, "name": "Kitchen"}, {"id": 2, "name": "Living Room"}]
    mock_coordinator.data = VacuumState(rooms=rooms)
    entity = RoboVacMQTTEntity(mock_coordinator)
    attrs = entity.extra_state_attributes

    assert "rooms" in attrs
    assert attrs["rooms"] == [
        {"id": 1, "name": "Kitchen"},
        {"id": 2, "name": "Living Room"}
    ]


def test_battery_sensor_none_battery(mock_coordinator):
    """Test battery sensor with None battery."""
    mock_coordinator.data = VacuumState(battery_level=None)
    entity = BatterySensorEntity(mock_coordinator)
    assert entity.native_value is None


def test_battery_sensor_negative_battery(mock_coordinator):
    """Test battery sensor with negative battery."""
    mock_coordinator.data = VacuumState(battery_level=-1)
    entity = BatterySensorEntity(mock_coordinator)
    assert entity.native_value is None


def test_battery_sensor_valid_battery(mock_coordinator):
    """Test battery sensor with valid battery."""
    mock_coordinator.data = VacuumState(battery_level=75)
    entity = BatterySensorEntity(mock_coordinator)
    assert entity.native_value == 75


def test_battery_sensor_zero_battery(mock_coordinator):
    """Test battery sensor with zero battery (edge case)."""
    mock_coordinator.data = VacuumState(battery_level=0)
    entity = BatterySensorEntity(mock_coordinator)
    assert entity.native_value == 0


# ============================================================================
# Room Data Handling Tests
# ============================================================================


def test_missing_room_data_handling(mock_coordinator):
    """Test that missing room data is handled gracefully with empty list."""
    # Setup vacuum entity with no room data
    mock_coordinator.data.rooms = None

    entity = RoboVacMQTTEntity(mock_coordinator)
    entity.hass = MagicMock()

    # Get extra state attributes
    attrs = entity.extra_state_attributes

    # Should have rooms key with empty lis
    assert "rooms" in attrs
    assert attrs["rooms"] == []


def test_empty_room_data_handling(mock_coordinator):
    """Test that empty room list is handled correctly."""
    # Setup vacuum entity with empty room lis
    mock_coordinator.data.rooms = []

    entity = RoboVacMQTTEntity(mock_coordinator)
    entity.hass = MagicMock()

    # Get extra state attributes
    attrs = entity.extra_state_attributes

    # Should have rooms key with empty lis
    assert "rooms" in attrs
    assert attrs["rooms"] == []


def test_valid_room_data_handling(mock_coordinator):
    """Test that valid room data is exposed correctly."""
    # Setup vacuum entity with valid room data
    mock_coordinator.data.rooms = [
        {"id": 1, "name": "Kitchen"},
        {"id": 2, "name": "Living Room"},
    ]

    entity = RoboVacMQTTEntity(mock_coordinator)
    entity.hass = MagicMock()

    # Get extra state attributes
    attrs = entity.extra_state_attributes

    # Should have rooms key with the room data
    assert "rooms" in attrs
    assert len(attrs["rooms"]) == 2
    assert attrs["rooms"][0]["id"] == 1
    assert attrs["rooms"][0]["name"] == "Kitchen"


# ============================================================================
# Select Entity Data Handling Tests
# ============================================================================


def test_suction_level_entity_missing_fan_speed(mock_coordinator):
    """Test suction level entity with missing fan speed data."""
    mock_coordinator.data.fan_speed = None

    entity = SuctionLevelSelectEntity(mock_coordinator)
    entity.hass = MagicMock()

    # Should handle missing data gracefully
    assert entity.current_option is None


def test_cleaning_mode_entity_missing_cleaning_mode(mock_coordinator):
    """Test cleaning mode entity with missing cleaning mode data."""
    mock_coordinator.data.cleaning_mode = None

    entity = CleaningModeSelectEntity(mock_coordinator)
    entity.hass = MagicMock()

    # Should handle missing data gracefully
    assert entity.current_option is None


# ============================================================================
# Edge Case Data Tests
# ============================================================================


def test_vacuum_entity_all_missing_data(mock_coordinator):
    """Test vacuum entity when all coordinator data is missing."""
    # Create empty state
    mock_coordinator.data = VacuumState()

    entity = RoboVacMQTTEntity(mock_coordinator)
    entity.hass = MagicMock()

    attrs = entity.extra_state_attributes

    # Should handle all missing data gracefully
    assert attrs["rooms"] == []
    assert "fan_speed" in attrs
    assert "cleaning_time" in attrs
    assert "cleaning_area" in attrs
    assert "task_status" in attrs
    assert "trigger_source" in attrs
    assert "error_code" in attrs
    assert "error_message" in attrs
    assert "status_code" in attrs
