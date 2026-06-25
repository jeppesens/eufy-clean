"""Unit tests for the Select entities."""

# pylint: disable=redefined-outer-name

from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.const import EntityCategory

from custom_components.robovac_mqtt.coordinator import EufyCleanCoordinator
from custom_components.robovac_mqtt.models import VacuumState
from custom_components.robovac_mqtt.select import (
    CleaningIntensitySelectEntity,
    CleaningModeSelectEntity,
    DockSelectEntity,
    MopIntensitySelectEntity,
    RoomSelectEntity,
    SceneSelectEntity,
    SuctionLevelSelectEntity,
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
    coordinator.api_type = "novel"
    coordinator.async_send_command = AsyncMock()
    coordinator.build_device_command = MagicMock(return_value={"cmd": "val"})
    coordinator.set_active_scene = MagicMock()
    coordinator.set_active_cleaning_targets = MagicMock()
    coordinator.last_update_success = True
    # Manual room overrides default empty — falls through to coordinator.data.rooms
    coordinator.room_name_overrides = {}
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


@pytest.mark.asyncio
async def test_dock_select_entity_async(mock_coordinator):
    """Test DockSelectEntity async methods."""
    # Setup
    mock_coordinator.data.dock_auto_cfg = {
        "wash": {"wash_freq": {"mode": "ByPartition"}}
    }

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

    await entity.async_select_option("B")

    # Verify setter called (model updated)
    assert model["val"] == "B"

    # Verify command sent
    mock_coordinator.build_device_command.assert_called_with("set_auto_cfg", cfg={"val": "B"})
    mock_coordinator.async_send_command.assert_called_with({"cmd": "val"})


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

    assert entity.name == "Scene/Task"
    assert entity.options == ["None", "Scene 1 (ID: 1)", "Scene 2 (ID: 2)"]
    assert entity.current_option == "None"

    await entity.async_select_option("Scene 2 (ID: 2)")

    mock_coordinator.build_device_command.assert_called_with("scene_clean", scene_id=2)
    mock_coordinator.async_send_command.assert_called_with({"cmd": "val"})
    mock_coordinator.set_active_scene.assert_called_with(2, "Scene 2")


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
    assert entity.options == ["None", "Kitchen (ID: 10)", "Living Room (ID: 12)"]
    assert entity.current_option == "None"

    await entity.async_select_option("Kitchen (ID: 10)")

    mock_coordinator.build_device_command.assert_called_with(
        "room_clean", room_ids=[10], map_id=5
    )
    mock_coordinator.async_send_command.assert_called_with({"cmd": "val"})
    mock_coordinator.set_active_cleaning_targets.assert_called_with(room_ids=[10])


@pytest.mark.asyncio
async def test_cleaning_mode_select_entity(mock_coordinator):
    """Test CleaningModeSelectEntity sends a command."""
    mock_coordinator.data.cleaning_mode = "Vacuum"

    entity = CleaningModeSelectEntity(mock_coordinator)
    entity.hass = MagicMock()
    entity.async_write_ha_state = MagicMock()

    await entity.async_select_option("Mop")

    mock_coordinator.build_device_command.assert_called_with(
        "set_cleaning_mode", clean_mode="Mop"
    )
    mock_coordinator.async_send_command.assert_called_with({"cmd": "val"})


@pytest.mark.asyncio
async def test_water_level_select_entity(mock_coordinator):
    """Test WaterLevelSelectEntity sends a command."""
    mock_coordinator.data.mop_water_level = "Medium"
    mock_coordinator.data.received_fields = {"mop_water_level"}

    entity = WaterLevelSelectEntity(mock_coordinator)
    entity.hass = MagicMock()
    entity.async_write_ha_state = MagicMock()

    await entity.async_select_option("High")

    mock_coordinator.build_device_command.assert_called_with(
        "set_water_level", water_level="High"
    )
    mock_coordinator.async_send_command.assert_called_with({"cmd": "val"})


@pytest.mark.asyncio
async def test_cleaning_intensity_select_entity(mock_coordinator):
    """Test CleaningIntensitySelectEntity sends a command."""
    mock_coordinator.data.cleaning_intensity = "Normal"
    mock_coordinator.data.received_fields = {"cleaning_intensity"}

    entity = CleaningIntensitySelectEntity(mock_coordinator)
    entity.hass = MagicMock()
    entity.async_write_ha_state = MagicMock()

    await entity.async_select_option("Quick")

    mock_coordinator.build_device_command.assert_called_with(
        "set_cleaning_intensity", cleaning_intensity="Quick"
    )
    mock_coordinator.async_send_command.assert_called_with({"cmd": "val"})


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
    assert entity._state_to_option("Unknown") is None  # unmapped values return None


@pytest.mark.asyncio
async def test_mop_intensity_select_entity_async(mock_coordinator):
    """Test MopIntensitySelectEntity sends correct command."""
    mock_coordinator.data.mop_water_level = "Medium"
    mock_coordinator.data.received_fields = {"mop_water_level"}

    entity = MopIntensitySelectEntity(mock_coordinator)
    entity.hass = MagicMock()
    entity.async_write_ha_state = MagicMock()

    await entity.async_select_option("Max")

    # Should map "Max" to "High" for the device command
    mock_coordinator.build_device_command.assert_called_with(
        "set_water_level", water_level="High"
    )
    mock_coordinator.async_send_command.assert_called_with({"cmd": "val"})


@pytest.mark.asyncio
async def test_dock_select_deepcopy_no_mutation(mock_coordinator):
    """Test that async_select_option does not mutate coordinator.data.dock_auto_cfg."""
    original_cfg = {"wash": {"wash_freq": {"mode": "ByPartition"}}}
    mock_coordinator.data.dock_auto_cfg = original_cfg

    def getter(cfg):
        return (
            "ByRoom"
            if cfg.get("wash", {}).get("wash_freq", {}).get("mode") == "ByPartition"
            else "ByTime"
        )

    def setter(cfg, val):
        if "wash" not in cfg:
            cfg["wash"] = {}
        if "wash_freq" not in cfg["wash"]:
            cfg["wash"]["wash_freq"] = {}
        cfg["wash"]["wash_freq"]["mode"] = (
            "ByPartition" if val == "ByRoom" else "ByTime"
        )

    entity = DockSelectEntity(
        mock_coordinator,
        "wash_frequency_mode",
        "Wash Frequency Mode",
        ["ByRoom", "ByTime"],
        getter,
        setter,
    )
    entity.hass = MagicMock()
    entity.async_write_ha_state = MagicMock()

    await entity.async_select_option("ByTime")

    # Original config should be unchanged (deepcopy prevents mutation)
    assert original_cfg["wash"]["wash_freq"]["mode"] == "ByPartition"


def test_dock_select_unavailable_no_cfg(mock_coordinator):
    """Test dock select is unavailable when dock_auto_cfg is empty."""
    mock_coordinator.data.dock_auto_cfg = {}
    mock_coordinator.last_update_success = True

    entity = DockSelectEntity(
        mock_coordinator,
        "test_select",
        "Test Select",
        ["A", "B"],
        lambda cfg: "A",
        lambda cfg, val: None,
    )

    assert entity.available is False


def test_scene_select_current_option_with_id(mock_coordinator):
    """Test current_option includes ID even for duplicate scene names."""
    mock_coordinator.data.scenes = [
        {"id": 1, "name": "Clean"},
        {"id": 2, "name": "Clean"},
    ]
    mock_coordinator.data.current_scene_id = 2
    mock_coordinator.data.current_scene_name = "Clean"

    entity = SceneSelectEntity(mock_coordinator)
    assert entity.current_option == "Clean (ID: 2)"


# -- Select Entity Availability Tests --


def test_suction_level_unavailable_without_fan_speed(mock_coordinator):
    """SuctionLevelSelectEntity should be unavailable until fan_speed is tracked."""
    mock_coordinator.data.received_fields = set()
    mock_coordinator.last_updated = None

    entity = SuctionLevelSelectEntity(mock_coordinator)
    assert entity.available is False


def test_suction_level_available_with_fan_speed(mock_coordinator):
    """SuctionLevelSelectEntity should be available once fan_speed is tracked."""
    mock_coordinator.data.received_fields = {"fan_speed"}
    mock_coordinator.last_updated = None

    entity = SuctionLevelSelectEntity(mock_coordinator)
    assert entity.available is True


@pytest.mark.asyncio
async def test_legacy_coordinator_excludes_novel_only_selects():
    """Legacy (Tuya Cloud) devices must not get novel-only selects whose
    commands silently no-op — only the universal SuctionLevel select."""
    from unittest.mock import patch

    from custom_components.robovac_mqtt.select import async_setup_entry

    coordinator = MagicMock(spec=EufyCleanCoordinator)
    coordinator.device_id = "legacy_dev"
    coordinator.device_name = "Legacy Vac"
    coordinator.device_model = "T2210"
    coordinator.api_type = "legacy"
    coordinator.connection_type = "cloud"
    coordinator.room_name_overrides = {}
    coordinator.data = VacuumState()
    coordinator.last_update_success = True

    hass = MagicMock()
    config_entry = MagicMock()
    config_entry.entry_id = "legacy_entry"
    hass.data = {"robovac_mqtt": {"legacy_entry": {"coordinators": [coordinator]}}}

    added_entities: list = []
    with patch("custom_components.robovac_mqtt.select.prune_orphan_entities"):
        await async_setup_entry(hass, config_entry, added_entities.extend)

    classes = {type(e).__name__ for e in added_entities}
    for novel_only in (
        "CleaningModeSelectEntity",
        "WaterLevelSelectEntity",
        "MopIntensitySelectEntity",
        "CleaningIntensitySelectEntity",
        "DockSelectEntity",
        "VoiceSelectEntity",
    ):
        assert novel_only not in classes, f"{novel_only} should be hidden on legacy"
    # The universal suction-level select stays (set_fan_speed works on legacy).
    assert "SuctionLevelSelectEntity" in classes
