"""Unit tests for the Select entities."""

# pylint: disable=redefined-outer-name

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.const import EntityCategory

from custom_components.robovac_mqtt.coordinator import EufyCleanCoordinator
from custom_components.robovac_mqtt.models import VacuumState
from custom_components.robovac_mqtt.select import (
    DockSelectEntity,
    RoomSelectEntity,
    SceneSelectEntity,
)


@pytest.fixture
def mock_coordinator():
    """Mock the coordinator."""
    coordinator = MagicMock(spec=EufyCleanCoordinator)
    coordinator.data = VacuumState()
    coordinator.device_id = "test_device"
    coordinator.device_name = "Test Device"
    coordinator.device_model = "T2118"
    coordinator.async_send_command = AsyncMock()
    return coordinator


def test_dock_select_entity(mock_coordinator):
    """Test DockSelectEntity."""
    # Setup initial state
    mock_coordinator.data.dock_auto_cfg = {
        "wash": {"wash_freq": {"mode": "ByPartition"}}
    }

    # Helper functions from select.py
    def _get_wash_freq(cfg):
        mode = cfg.get("wash", {}).get("wash_freq", {}).get("mode", "ByPartition")
        return "ByRoom" if mode == "ByPartition" else "ByTime"

    def _set_wash_freq(cfg, val):
        if "wash" not in cfg:
            cfg["wash"] = {}
        if "wash_freq" not in cfg["wash"]:
            cfg["wash"]["wash_freq"] = {}

        mode = "ByPartition" if val == "ByRoom" else "ByTime"
        cfg["wash"]["wash_freq"]["mode"] = mode

    entity = DockSelectEntity(
        mock_coordinator,
        "wash_frequency_mode",
        "Wash Frequency Mode",
        ["ByRoom", "ByTime"],
        _get_wash_freq,
        _set_wash_freq,
        "mdi:calendar-sync",
    )

    # Test properties
    assert entity.name == "Wash Frequency Mode"
    assert entity.unique_id == "test_device_wash_frequency_mode"
    assert entity.icon == "mdi:calendar-sync"
    assert entity.entity_category == EntityCategory.CONFIG
    assert entity.options == ["ByRoom", "ByTime"]
    assert entity.current_option == "ByRoom"

    # Test select option
    with patch("custom_components.robovac_mqtt.select.build_command") as mock_build:
        mock_build.return_value = {"cmd": "val"}

        # We need to simulate the coroutine execution since we are in a sync
        # test context but the method is async.
        # However, pytest-homeassistant-custom-component handles async tests
        # if we mark them.
        pass


@pytest.mark.asyncio
async def test_dock_select_entity_async(mock_coordinator):
    """Test DockSelectEntity async methods."""
    # Setup
    mock_coordinator.data.dock_auto_cfg = {
        "wash": {"wash_freq": {"mode": "ByPartition"}}
    }

    # We need to import the actual getter/setters or redefining them is fine
    # if they match logic
    # But for unit testing the *Entity*, we can pass mocks or the real ones.
    # Let's use the real ones by importing them if we could, but they are private
    # in select.py
    # So we used lambdas/functions in the init called in select.py.
    # To test the entity class generally, we can pass simple lambda.

    model = {"val": "A"}

    def getter(cfg):
        return model["val"]

    def setter(cfg, val):
        model["val"] = val
        cfg["val"] = val

    entity = DockSelectEntity(
        mock_coordinator, "test_select", "Test Select", ["A", "B"], getter, setter
    )

    # Mock data
    mock_coordinator.data.dock_auto_cfg = {"val": "A"}

    # Mock hass for entity
    entity.hass = MagicMock()
    entity.async_write_ha_state = MagicMock()

    assert entity.current_option == "A"

    with patch("custom_components.robovac_mqtt.select.build_command") as mock_build:
        mock_build.return_value = {"cmd": "test_cmd"}

        await entity.async_select_option("B")

        # Verify setter called (model updated)
        assert model["val"] == "B"

        # Verify command sent
        mock_build.assert_called_with("set_auto_cfg", cfg={"val": "B"})
        mock_coordinator.async_send_command.assert_called_with({"cmd": "test_cmd"})


@pytest.mark.asyncio
async def test_scene_select_entity(mock_coordinator):
    """Test SceneSelectEntity."""
    mock_coordinator.data.scenes = [
        {"id": 1, "name": "Scene 1", "type": 1},
        {"id": 2, "name": "Scene 2", "type": 2},
    ]

    entity = SceneSelectEntity(mock_coordinator)
    entity.hass = MagicMock()
    entity.async_write_ha_state = MagicMock()

    assert entity.name == "Scene"
    assert entity.options == ["Scene 1 (ID: 1)", "Scene 2 (ID: 2)"]
    assert entity.current_option is None

    with patch("custom_components.robovac_mqtt.select.build_command") as mock_build:
        mock_build.return_value = {"cmd": "scene_cmd"}

        await entity.async_select_option("Scene 2 (ID: 2)")

        mock_build.assert_called_with("scene_clean", scene_id=2)
        mock_coordinator.async_send_command.assert_called_with({"cmd": "scene_cmd"})


@pytest.mark.asyncio
async def test_room_select_entity(mock_coordinator):
    """Test RoomSelectEntity."""
    mock_coordinator.data.rooms = [
        {"id": 10, "name": "Kitchen"},
        {"id": 12, "name": "Living Room"},
    ]
    mock_coordinator.data.map_id = 5

    entity = RoomSelectEntity(mock_coordinator)
    entity.hass = MagicMock()
    entity.async_write_ha_state = MagicMock()

    assert entity.name == "Clean Room"
    # Matches format "Name (ID: id)"
    assert "Kitchen (ID: 10)" in entity.options
    assert "Living Room (ID: 12)" in entity.options
    assert entity.current_option is None

    with patch("custom_components.robovac_mqtt.select.build_command") as mock_build:
        mock_build.return_value = {"cmd": "room_cmd"}

        await entity.async_select_option("Kitchen (ID: 10)")

        mock_build.assert_called_with("room_clean", room_ids=[10], map_id=5)
        mock_coordinator.async_send_command.assert_called_with({"cmd": "room_cmd"})
