"""Unit tests for RoboVacBinarySensor entities."""

# pylint: disable=redefined-outer-name

from unittest.mock import MagicMock

import pytest
from homeassistant.components.binary_sensor import BinarySensorDeviceClass
from homeassistant.const import EntityCategory

from custom_components.robovac_mqtt.binary_sensor import (
    RoboVacBinarySensor,
    async_setup_entry,
)
from custom_components.robovac_mqtt.models import VacuumState


@pytest.fixture
def mock_coordinator():
    """Mock the coordinator."""
    coordinator = MagicMock()
    coordinator.device_id = "test_id"
    coordinator.device_name = "Test Vac"
    coordinator.device_model = "T2118"
    coordinator.data = VacuumState()
    coordinator.last_update_success = True
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


def test_charging_sensor_default_false(mock_coordinator):
    """Test charging sensor returns False before any data received."""
    # VacuumState defaults charging=False
    assert mock_coordinator.data.charging is False

    entity = RoboVacBinarySensor(
        mock_coordinator,
        "charging",
        "Charging",
        lambda s: s.charging,
        device_class=BinarySensorDeviceClass.BATTERY_CHARGING,
    )
    entity.hass = MagicMock()

    assert entity.is_on is False


def test_binary_sensor_availability_honors_coordinator_state(mock_coordinator):
    """Test custom availability does not bypass coordinator availability."""
    mock_coordinator.data.received_fields = {"child_lock"}

    entity = RoboVacBinarySensor(
        mock_coordinator,
        "child_lock",
        "Child Lock",
        lambda s: s.child_lock,
        availability_fn=lambda s: "child_lock" in s.received_fields,
    )
    entity.hass = MagicMock()

    assert entity.available is True

    mock_coordinator.last_update_success = False
    assert entity.available is False


@pytest.mark.asyncio
async def test_remote_mode_sensor_follows_the_work_state(mock_coordinator):
    """Remote Mode is on exactly while the robot reports state 6 (REMOTE_CTRL)."""
    mock_coordinator.api_type = "novel"
    hass = MagicMock()
    hass.data = {"robovac_mqtt": {"e": {"coordinators": [mock_coordinator]}}}
    added: list = []
    await async_setup_entry(hass, MagicMock(entry_id="e"), added.extend)
    sensor = next(e for e in added if e.unique_id == "test_id_remote_mode")
    sensor.hass = MagicMock()
    for state, expected in ((6, True), (5, False), (3, False)):
        mock_coordinator.data.status_code = state
        assert sensor.is_on is expected
    assert sensor.entity_category is None


@pytest.mark.asyncio
async def test_remote_mode_sensor_not_created_for_other_protocols(mock_coordinator):
    mock_coordinator.api_type = "scalar"
    hass = MagicMock()
    hass.data = {"robovac_mqtt": {"e": {"coordinators": [mock_coordinator]}}}
    added: list = []
    await async_setup_entry(hass, MagicMock(entry_id="e"), added.extend)
    assert all(e.unique_id != "test_id_remote_mode" for e in added)
