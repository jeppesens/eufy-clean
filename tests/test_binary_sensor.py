"""Unit tests for RoboVacBinarySensor entities."""

# pylint: disable=redefined-outer-name

from unittest.mock import MagicMock

import pytest
from homeassistant.components.binary_sensor import BinarySensorDeviceClass
from homeassistant.const import EntityCategory

from custom_components.robovac_mqtt.binary_sensor import RoboVacBinarySensor
from custom_components.robovac_mqtt.models import VacuumState


@pytest.fixture
def mock_coordinator():
    """Mock the coordinator."""
    coordinator = MagicMock()
    coordinator.device_id = "test_id"
    coordinator.device_name = "Test Vac"
    coordinator.device_model = "T2118"
    coordinator.data = VacuumState()
    return coordinator


def test_charging_sensor(mock_coordinator):
    """Test charging binary sensor."""
    mock_coordinator.data.charging = True

    entity = RoboVacBinarySensor(
        mock_coordinator,
        "charging",
        "Charging",
        lambda s: s.charging,
        device_class=BinarySensorDeviceClass.BATTERY_CHARGING,
    )
    entity.hass = MagicMock()

    assert entity.unique_id == "test_id_charging"
    assert entity.name == "Charging"
    assert entity.is_on is True
    assert entity.device_class == BinarySensorDeviceClass.BATTERY_CHARGING
    assert entity.entity_category == EntityCategory.DIAGNOSTIC

    # Update state
    mock_coordinator.data.charging = False
    assert entity.is_on is False
