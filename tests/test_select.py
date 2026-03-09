"""Unit tests for the Select entities."""

# pylint: disable=redefined-outer-name

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.const import EntityCategory

from custom_components.robovac_mqtt.coordinator import EufyCleanCoordinator
from custom_components.robovac_mqtt.models import VacuumState
from custom_components.robovac_mqtt.select import (
    CleaningModeSelectEntity,
    CleaningIntensitySelectEntity,
    DockSelectEntity,
    MopIntensitySelectEntity,
    RoomSelectEntity,
    SceneSelectEntity,
    WaterLevelSelectEntity,
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
    assert entity.options == ["Scene 1", "Scene 2"]
    assert entity.current_option is None

    with patch("custom_components.robovac_mqtt.select.build_command") as mock_build:
        mock_build.return_value = {"cmd": "scene_cmd"}

        await entity.async_select_option("Scene 2")

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
    # Matches format "Name"
    assert "Kitchen" in entity.options
    assert "Living Room" in entity.options
    assert entity.current_option is None

    with patch("custom_components.robovac_mqtt.select.build_command") as mock_build:
        mock_build.return_value = {"cmd": "room_cmd"}

        await entity.async_select_option("Kitchen")

        mock_build.assert_called_with(
            "room_clean", room_ids=[10], map_id=5, mode="CUSTOMIZE"
        )
        mock_coordinator.async_send_command.assert_called_with({"cmd": "room_cmd"})


@pytest.mark.asyncio
async def test_cleaning_mode_select_entity(mock_coordinator):
    """Test CleaningModeSelectEntity sends a command."""
    mock_coordinator.data.cleaning_mode = "Vacuum"

    entity = CleaningModeSelectEntity(mock_coordinator)
    entity.hass = MagicMock()
    entity.async_write_ha_state = MagicMock()

    with patch("custom_components.robovac_mqtt.select.build_command") as mock_build:
        mock_build.return_value = {"cmd": "clean_mode_cmd"}

        await entity.async_select_option("Mop")

        mock_build.assert_called_with("set_cleaning_mode", clean_mode="Mop")
        mock_coordinator.async_send_command.assert_called_with(
            {"cmd": "clean_mode_cmd"}
        )


@pytest.mark.asyncio
async def test_water_level_select_entity(mock_coordinator):
    """Test WaterLevelSelectEntity sends a command."""
    mock_coordinator.data.mop_water_level = "Medium"
    mock_coordinator.data.received_fields = {"mop_water_level"}

    entity = WaterLevelSelectEntity(mock_coordinator)
    entity.hass = MagicMock()
    entity.async_write_ha_state = MagicMock()

    with patch("custom_components.robovac_mqtt.select.build_command") as mock_build:
        mock_build.return_value = {"cmd": "water_level_cmd"}

        await entity.async_select_option("High")

        mock_build.assert_called_with("set_water_level", water_level="High")
        mock_coordinator.async_send_command.assert_called_with(
            {"cmd": "water_level_cmd"}
        )


@pytest.mark.asyncio
async def test_cleaning_intensity_select_entity(mock_coordinator):
    """Test CleaningIntensitySelectEntity sends a command."""
    mock_coordinator.data.cleaning_intensity = "Normal"
    mock_coordinator.data.received_fields = {"cleaning_intensity"}

    entity = CleaningIntensitySelectEntity(mock_coordinator)
    entity.hass = MagicMock()
    entity.async_write_ha_state = MagicMock()

    with patch("custom_components.robovac_mqtt.select.build_command") as mock_build:
        mock_build.return_value = {"cmd": "clean_intensity_cmd"}

        await entity.async_select_option("Quick")

        mock_build.assert_called_with(
            "set_cleaning_intensity", cleaning_intensity="Quick"
        )
        mock_coordinator.async_send_command.assert_called_with(
            {"cmd": "clean_intensity_cmd"}
        )


def test_mop_intensity_select_entity_entity_category(mock_coordinator):
    """Test MopIntensitySelectEntity has CONFIG entity category."""
    entity = MopIntensitySelectEntity(mock_coordinator)
    
    assert entity.entity_category == EntityCategory.CONFIG
    assert entity.name == "Mop Intensity"
    assert entity.options == ["Quiet", "Automatic", "Max"]


def test_mop_intensity_select_entity_mapping(mock_coordinator):
    """Test MopIntensitySelectEntity option to state mapping."""
    entity = MopIntensitySelectEntity(mock_coordinator)
    
    # Test option to state mapping
    assert entity._option_to_state("Quiet") == "Low"
    assert entity._option_to_state("Automatic") == "Medium"
    assert entity._option_to_state("Max") == "High"
    
    # Test state to option mapping
    assert entity._state_to_option("Low") == "Quiet"
    assert entity._state_to_option("Medium") == "Automatic"
    assert entity._state_to_option("High") == "Max"
    assert entity._state_to_option("Unknown") == "Unknown"  # fallback


@pytest.mark.asyncio
async def test_mop_intensity_select_entity_async(mock_coordinator):
    """Test MopIntensitySelectEntity sends correct command."""
    mock_coordinator.data.mop_water_level = "Medium"
    mock_coordinator.data.received_fields = {"mop_water_level"}

    entity = MopIntensitySelectEntity(mock_coordinator)
    entity.hass = MagicMock()
    entity.async_write_ha_state = MagicMock()

    with patch("custom_components.robovac_mqtt.select.build_command") as mock_build:
        mock_build.return_value = {"cmd": "water_level_cmd"}

        await entity.async_select_option("Max")

        # Should map "Max" to "High" for the device command
        mock_build.assert_called_with("set_water_level", water_level="High")
        mock_coordinator.async_send_command.assert_called_with(
            {"cmd": "water_level_cmd"}
        )
