"""Unit tests for RoboVacButton entities."""

# pylint: disable=redefined-outer-name

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.robovac_mqtt.button import RoboVacButton, async_setup_entry
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
    coordinator.api_type = "novel"
    coordinator.data = VacuumState()
    coordinator.async_send_command = AsyncMock()
    coordinator.build_device_command = MagicMock(return_value={"cmd": "val"})
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

    await entity.async_press()

    mock_coordinator.build_device_command.assert_called_with("collect_dust")
    mock_coordinator.async_send_command.assert_called_with({"cmd": "val"})


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

    await entity.async_press()

    mock_coordinator.build_device_command.assert_called_with(
        "reset_accessory", reset_type=ConsumableRequest.FILTER_MESH
    )
    mock_coordinator.async_send_command.assert_called_with({"cmd": "val"})


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("model", "present", "absent"),
    [
        # Default table: the six accessories, no dust bag.
        (
            "T2261",
            ["filter", "main_brush", "side_brush", "sensors", "scrape", "mop"],
            ["dustbag"],
        ),
        # L60 SES: MODEL_ACCESSORY_MAX_LIFE lists no sensor/tray/mop, but a dust bag.
        (
            "T2277",
            ["filter", "main_brush", "side_brush", "dustbag"],
            ["sensors", "scrape", "mop"],
        ),
    ],
)
async def test_novel_reset_buttons_follow_lifespan_table(model, present, absent):
    """Novel devices only get reset buttons for accessories their table lists."""
    coordinator = MagicMock()
    coordinator.device_id = "novel_dev"
    coordinator.device_name = "Novel Vac"
    coordinator.device_model = model
    coordinator.api_type = "novel"
    coordinator.connection_type = "mqtt"
    coordinator.data = VacuumState()

    hass = MagicMock()
    config_entry = MagicMock()
    config_entry.entry_id = "test_entry"
    hass.data = {"robovac_mqtt": {"test_entry": {"coordinators": [coordinator]}}}

    added_entities = []
    await async_setup_entry(hass, config_entry, added_entities.extend)
    entity_ids = {e.unique_id for e in added_entities}

    for part in present:
        assert f"novel_dev_reset_{part}" in entity_ids
    for part in absent:
        assert f"novel_dev_reset_{part}" not in entity_ids
