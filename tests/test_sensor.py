"""Unit tests for RoboVacSensor entities."""

# pylint: disable=redefined-outer-name


from unittest.mock import MagicMock

import pytest
from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.const import PERCENTAGE, EntityCategory

from custom_components.robovac_mqtt.models import VacuumState
from custom_components.robovac_mqtt.sensor import RoboVacSensor


@pytest.fixture
def mock_coordinator():
    """Mock the coordinator."""
    coordinator = MagicMock()
    coordinator.device_id = "test_id"
    coordinator.device_name = "Test Vac"
    coordinator.device_model = "T2118"
    coordinator.data = VacuumState()
    return coordinator


def test_sensor_generic(mock_coordinator):
    """Test generic sensor initialization and value extraction."""
    # Define a simple lambda to extract a value
    mock_coordinator.data.battery_level = 95

    entity = RoboVacSensor(
        mock_coordinator,
        "test_sensor",
        "Test Sensor",
        lambda s: s.battery_level,
        device_class=SensorDeviceClass.BATTERY,
        unit=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
    )
    entity.hass = MagicMock()

    assert entity.unique_id == "test_id_test_sensor"
    assert entity.name == "Test Sensor"
    assert entity.native_value == 95
    assert entity.device_class == SensorDeviceClass.BATTERY
    assert entity.native_unit_of_measurement == PERCENTAGE
    assert entity.state_class == SensorStateClass.MEASUREMENT


def test_dock_status_sensor(mock_coordinator):
    """Test dock status sensor logic."""
    mock_coordinator.data.dock_status = "Emptying dust"

    entity = RoboVacSensor(
        mock_coordinator,
        "dock_status",
        "Dock Status",
        lambda s: s.dock_status,
        category=EntityCategory.DIAGNOSTIC,
    )

    assert entity.native_value == "Emptying dust"
    assert entity.entity_category == EntityCategory.DIAGNOSTIC


def test_water_level_sensor(mock_coordinator):
    """Test clean water level sensor."""
    mock_coordinator.data.station_clean_water = 50

    entity = RoboVacSensor(
        mock_coordinator,
        "water_level",
        "Water Level",
        lambda s: s.station_clean_water,
        unit=PERCENTAGE,
    )

    assert entity.native_value == 50
    assert entity.native_unit_of_measurement == PERCENTAGE

    # Update state
    mock_coordinator.data.station_clean_water = 20
    assert entity.native_value == 20
