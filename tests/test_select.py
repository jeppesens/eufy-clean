"""Unit tests for the Select entities."""

# pylint: disable=redefined-outer-name

from unittest.mock import AsyncMock, MagicMock, patch

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
    coordinator.async_send_command = AsyncMock()
    coordinator.set_active_scene = MagicMock()
    coordinator.set_active_cleaning_targets = MagicMock()
    coordinator.last_update_success = True
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


_STATUS_OPTIONS_FIXTURE = ["Idle", "Cleaning", "Returning", "Paused", "Error"]


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
    assert entity.options == _STATUS_OPTIONS_FIXTURE + [
        "Scene 1 (ID: 1)",
        "Scene 2 (ID: 2)",
    ]
    # VacuumState defaults activity to "idle" → renders as "Idle".
    assert entity.current_option == "Idle"

    with patch("custom_components.robovac_mqtt.select.build_command") as mock_build:
        mock_build.return_value = {"cmd": "scene_cmd"}

        await entity.async_select_option("Scene 2 (ID: 2)")

        mock_build.assert_called_with("scene_clean", scene_id=2)
        mock_coordinator.async_send_command.assert_called_with({"cmd": "scene_cmd"})
        mock_coordinator.set_active_scene.assert_called_with(2, "Scene 2")


@pytest.mark.parametrize(
    "activity,expected",
    [
        ("idle", "Idle"),
        ("docked", "Idle"),
        ("charging", "Idle"),
        ("cleaning", "Cleaning"),
        ("returning", "Returning"),
        ("paused", "Paused"),
        ("error", "Error"),
        ("totally_unknown_state", None),
    ],
)
def test_scene_select_current_option_mirrors_activity(
    mock_coordinator, activity, expected
):
    """When no scene is active, current_option mirrors the vacuum activity."""
    mock_coordinator.data.scenes = [{"id": 1, "name": "Scene 1", "type": 1}]
    mock_coordinator.data.current_scene_id = 0
    mock_coordinator.data.activity = activity

    entity = SceneSelectEntity(mock_coordinator)
    assert entity.current_option == expected


def test_room_select_current_option_mirrors_activity(mock_coordinator):
    """RoomSelectEntity surfaces the vacuum activity as its current option."""
    mock_coordinator.data.rooms = [{"id": 10, "name": "Kitchen"}]
    mock_coordinator.data.activity = "cleaning"

    entity = RoomSelectEntity(mock_coordinator)
    assert entity.current_option == "Cleaning"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "sentinel", ["Idle", "Cleaning", "Returning", "Paused", "Error"]
)
async def test_scene_select_status_sentinels_are_noop(mock_coordinator, sentinel):
    """Selecting any status sentinel must not dispatch a command."""
    mock_coordinator.data.scenes = [{"id": 1, "name": "Scene 1", "type": 1}]

    entity = SceneSelectEntity(mock_coordinator)
    entity.hass = MagicMock()
    entity.async_write_ha_state = MagicMock()

    with patch("custom_components.robovac_mqtt.select.build_command") as mock_build:
        await entity.async_select_option(sentinel)

    mock_build.assert_not_called()
    mock_coordinator.async_send_command.assert_not_called()
    mock_coordinator.set_active_scene.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "sentinel", ["Idle", "Cleaning", "Returning", "Paused", "Error"]
)
async def test_room_select_status_sentinels_are_noop(mock_coordinator, sentinel):
    """Selecting any status sentinel on the Room select must be a no-op."""
    mock_coordinator.data.rooms = [{"id": 10, "name": "Kitchen"}]

    entity = RoomSelectEntity(mock_coordinator)
    entity.hass = MagicMock()
    entity.async_write_ha_state = MagicMock()

    with patch("custom_components.robovac_mqtt.select.build_command") as mock_build:
        await entity.async_select_option(sentinel)

    mock_build.assert_not_called()
    mock_coordinator.async_send_command.assert_not_called()
    mock_coordinator.set_active_cleaning_targets.assert_not_called()


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
    assert entity.options == _STATUS_OPTIONS_FIXTURE + [
        "Kitchen (ID: 10)",
        "Living Room (ID: 12)",
    ]
    # VacuumState defaults activity to "idle" → renders as "Idle".
    assert entity.current_option == "Idle"

    with patch("custom_components.robovac_mqtt.select.build_command") as mock_build:
        mock_build.return_value = {"cmd": "room_cmd"}

        await entity.async_select_option("Kitchen (ID: 10)")

        mock_build.assert_called_with("room_clean", room_ids=[10], map_id=5)
        mock_coordinator.async_send_command.assert_called_with({"cmd": "room_cmd"})
        mock_coordinator.set_active_cleaning_targets.assert_called_with(room_ids=[10])


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
    assert entity._state_to_option("Unknown") is None  # unmapped values return None


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

    with patch("custom_components.robovac_mqtt.select.build_command") as mock_build:
        mock_build.return_value = {"cmd": "val"}
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


# ── Select Entity Availability Tests ─────────────────────────────────


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
