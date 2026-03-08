"""Tests for missing data handling in vacuum and sensor entities."""

from unittest.mock import MagicMock

import pytest

from custom_components.robovac_mqtt.models import VacuumState
from custom_components.robovac_mqtt.sensor import BatterySensorEntity
from custom_components.robovac_mqtt.vacuum import RoboVacMQTTEntity


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
        {"id": "1", "name": "Kitchen"},
        {"id": "2", "name": "Living Room"}
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
