"""Unit tests for RoboVacButton entities."""

# pylint: disable=redefined-outer-name

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.robovac_mqtt.button import RoboVacButton
from custom_components.robovac_mqtt.models import VacuumState
from custom_components.robovac_mqtt.proto.cloud.consumable_pb2 import (
    ConsumableRequest,
)


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


@pytest.mark.asyncio
async def test_button_press(mock_coordinator):
    """Test button press sends correct command."""
    entity = RoboVacButton(
        mock_coordinator,
        "Empty Dust Bin",
        "_empty_dust_bin",
        "collect_dust",
        "mdi:delete",
    )
    entity.hass = MagicMock()

    assert entity.name == "Empty Dust Bin"
    assert entity.unique_id == "test_id_empty_dust_bin"
    assert entity.icon == "mdi:delete"

    with patch("custom_components.robovac_mqtt.button.build_command") as mock_build:
        mock_build.return_value = {"cmd": "collect"}

        await entity.async_press()

        mock_build.assert_called_with("collect_dust")
        mock_coordinator.async_send_command.assert_called_with({"cmd": "collect"})


@pytest.mark.asyncio
async def test_button_reset_accessory(mock_coordinator):
    """Test button with kwargs (reset accessory)."""
    entity = RoboVacButton(
        mock_coordinator,
        "Reset Filter",
        "_reset_filter",
        "reset_accessory",
        "mdi:air-filter",
        reset_type=ConsumableRequest.FILTER_MESH,
    )

    with patch("custom_components.robovac_mqtt.button.build_command") as mock_build:
        mock_build.return_value = {"cmd": "reset"}

        await entity.async_press()

        mock_build.assert_called_with(
            "reset_accessory", reset_type=ConsumableRequest.FILTER_MESH
        )
        mock_coordinator.async_send_command.assert_called_with({"cmd": "reset"})
