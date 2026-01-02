"""Unit tests for parsing cleaning statistics."""

# pylint: disable=redefined-outer-name

from unittest.mock import MagicMock

import pytest
from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass

from custom_components.robovac_mqtt.api.parser import update_state
from custom_components.robovac_mqtt.const import DPS_MAP
from custom_components.robovac_mqtt.models import VacuumState
from custom_components.robovac_mqtt.proto.cloud.clean_statistics_pb2 import (
    CleanStatistics,
)
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


def test_parsing_cleaning_stats():
    """Test parsing of CLEANING_STATISTICS DPS."""
    state = VacuumState()

    # Create dummy stats proto
    stats = CleanStatistics()
    stats.single.clean_duration = 2700  # 45 minutes in seconds
    stats.single.clean_area = 50  # 50 m2
    stats.total.clean_duration = 60000
    stats.total.clean_area = 1200
    stats.total.clean_count = 25

    encoded_value = encode_message(stats)

    dps = {DPS_MAP["CLEANING_STATISTICS"]: encoded_value}
    new_state = update_state(state, dps)

    assert new_state.cleaning_time == 2700
    assert new_state.cleaning_area == 50


def test_cleaning_stats_sensors(mock_coordinator):
    """Test cleaning stats sensor entities."""
    mock_coordinator.data.cleaning_time = 2700  # 45 min
    mock_coordinator.data.cleaning_area = 50

    # Test Time Sensor
    time_sensor = RoboVacSensor(
        mock_coordinator,
        "cleaning_time",
        "Cleaning Time",
        lambda s: s.cleaning_time,
        device_class=SensorDeviceClass.DURATION,
        unit="s",
        state_class=SensorStateClass.MEASUREMENT,
    )
    assert time_sensor.native_value == 2700
    assert time_sensor.native_unit_of_measurement == "s"

    # Test Area Sensor
    area_sensor = RoboVacSensor(
        mock_coordinator,
        "cleaning_area",
        "Cleaning Area",
        lambda s: s.cleaning_area,
        unit="m²",
        state_class=SensorStateClass.MEASUREMENT,
    )
    assert area_sensor.native_value == 50
    assert area_sensor.native_unit_of_measurement == "m²"
