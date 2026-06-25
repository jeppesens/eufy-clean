"""Unit tests for the FindRobot switch entity."""

import unittest.mock
from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.robovac_mqtt.const import DOMAIN, DPS_MAP
from custom_components.robovac_mqtt.models import VacuumState
from custom_components.robovac_mqtt.switch import (
    ChildLockSwitchEntity,
    DockSwitchEntity,
    DoNotDisturbSwitchEntity,
    FindRobotSwitchEntity,
    set_collect_dust,
    set_wash_cfg,
)

# pylint: disable=redefined-outer-name


@pytest.fixture
def mock_coordinator() -> MagicMock:
    """Mock the coordinator."""
    coordinator = MagicMock()
    coordinator.device_id = "test_device"
    coordinator.device_name = "Test Vac"
    coordinator.device_model = "T2118"
    coordinator.api_type = "novel"
    coordinator.data = VacuumState()
    coordinator.async_send_command = AsyncMock()
    coordinator.async_set_updated_data = MagicMock()
    coordinator.build_device_command = MagicMock(
        return_value={DPS_MAP["GO_HOME"]: "cmd"}
    )
    coordinator.device_info = {}
    coordinator.last_update_success = True
    return coordinator


async def test_find_robot_entity(hass: HomeAssistant, mock_coordinator):
    """Test Find Robot switch entity."""
    entry = MockConfigEntry(domain=DOMAIN, data={})
    entry.add_to_hass(hass)

    mock_coordinator.data.find_robot = False

    # Initialize entity
    entity = FindRobotSwitchEntity(mock_coordinator)
    entity.hass = hass
    entity.platform = AsyncMock()
    entity.platform.platform = Platform.SWITCH

    # Test initial state
    assert entity.is_on is False
    assert entity.unique_id == "test_device_find_robot"
    assert entity.name == "Find Robot"
    assert entity.icon == "mdi:robot-vacuum-variant"

    # Test Update
    mock_coordinator.data.find_robot = True
    assert entity.is_on is True


async def test_find_robot_turn_on_off(hass: HomeAssistant, mock_coordinator):
    """Test turning find robot on and off."""
    entry = MockConfigEntry(domain=DOMAIN, data={})
    entry.add_to_hass(hass)

    entity = FindRobotSwitchEntity(mock_coordinator)
    entity.hass = hass

    await entity.async_turn_off()
    mock_coordinator.build_device_command.assert_called_with("find_robot", active=False)
    mock_coordinator.async_send_command.assert_called()


async def test_child_lock_switch_turn_on_off(hass: HomeAssistant, mock_coordinator):
    """Test toggling the child lock switch."""
    entry = MockConfigEntry(domain=DOMAIN, data={})
    entry.add_to_hass(hass)

    mock_coordinator.data.received_fields = {"child_lock"}
    mock_coordinator.data.child_lock = False

    entity = ChildLockSwitchEntity(mock_coordinator)
    entity.hass = hass

    assert entity.available is True
    assert entity.is_on is False

    await entity.async_turn_on()
    mock_coordinator.async_send_command.assert_called()
    mock_coordinator.build_device_command.assert_called_with(
        "set_child_lock", active=True
    )
    updated_state = mock_coordinator.async_set_updated_data.call_args_list[-1][0][0]
    assert updated_state.child_lock is True

    await entity.async_turn_off()
    mock_coordinator.build_device_command.assert_called_with(
        "set_child_lock", active=False
    )
    updated_state = mock_coordinator.async_set_updated_data.call_args_list[-1][0][0]
    assert updated_state.child_lock is False


def test_child_lock_switch_unavailable_without_field(mock_coordinator):
    """Test child lock switch is hidden until the device reports support."""
    entity = ChildLockSwitchEntity(mock_coordinator)

    assert entity.available is False


async def test_do_not_disturb_switch_turn_on_off(hass: HomeAssistant, mock_coordinator):
    """Test toggling the Do Not Disturb switch."""
    entry = MockConfigEntry(domain=DOMAIN, data={})
    entry.add_to_hass(hass)

    mock_coordinator.data.received_fields = {"do_not_disturb"}
    mock_coordinator.data.dnd_enabled = False
    mock_coordinator.data.dnd_start_hour = 22
    mock_coordinator.data.dnd_start_minute = 0
    mock_coordinator.data.dnd_end_hour = 8
    mock_coordinator.data.dnd_end_minute = 0

    entity = DoNotDisturbSwitchEntity(mock_coordinator)
    entity.hass = hass

    assert entity.available is True
    assert entity.is_on is False
    assert entity.extra_state_attributes == {
        "start_time": "22:00",
        "end_time": "08:00",
    }

    await entity.async_turn_on()
    last_call = mock_coordinator.build_device_command.call_args_list[-1]
    assert last_call[0][0] == "set_do_not_disturb"
    assert last_call[1]["active"] is True
    updated_state = mock_coordinator.async_set_updated_data.call_args_list[-1][0][0]
    assert updated_state.dnd_enabled is True


async def test_dock_switches(hass: HomeAssistant, mock_coordinator):
    """Test DockSwitchEntity for auto empty and auto wash."""
    entry = MockConfigEntry(domain=DOMAIN, data={})
    entry.add_to_hass(hass)

    # Setup initial data
    mock_coordinator.data.dock_auto_cfg = {
        "collectdust_v2": {"sw": {"value": False}},
        "wash": {"cfg": 0},
    }

    # --- Auto Empty Switch ---
    auto_empty = DockSwitchEntity(
        mock_coordinator,
        "auto_empty",
        "Auto Empty",
        lambda cfg: cfg.get("collectdust_v2", {}).get("sw", {}).get("value", False),
        set_collect_dust,
        icon="mdi:delete-restore",
    )
    auto_empty.hass = hass
    auto_empty.platform = AsyncMock()
    auto_empty.platform.platform = Platform.SWITCH
    auto_empty.entity_id = "switch.test_auto_empty"

    # Test Initial State (False)
    assert auto_empty.is_on is False

    # Test Turn On
    await auto_empty.async_turn_on()
    mock_coordinator.build_device_command.assert_called_with("set_auto_cfg", cfg=unittest.mock.ANY)
    # Verify the mutated cfg was passed through to send_command
    built_cmd = mock_coordinator.build_device_command.return_value
    mock_coordinator.async_send_command.assert_called_with(built_cmd)

    # Test Turn Off
    await auto_empty.async_turn_off()

    # --- Auto Wash Switch ---
    auto_wash = DockSwitchEntity(
        mock_coordinator,
        "auto_wash",
        "Auto Wash",
        lambda cfg: cfg.get("wash", {}).get("cfg", "CLOSE") == "STANDARD",
        set_wash_cfg,
        icon="mdi:water-sync",
    )
    auto_wash.hass = hass
    auto_wash.platform = AsyncMock()
    auto_wash.platform.platform = Platform.SWITCH
    auto_wash.entity_id = "switch.test_auto_wash"

    # Test Initial State (0 -> False)
    is_on = auto_wash.is_on
    assert is_on is False

    mock_coordinator.data.dock_auto_cfg["wash"][
        "cfg"
    ] = "STANDARD"  # "STANDARD" usually maps to 1 in proto logic, but here raw data

    assert auto_wash.is_on

    # Test Turn Off
    await auto_wash.async_turn_off()
    mock_coordinator.async_send_command.assert_called()


def test_set_wash_cfg_writes_string_values():
    """Test set_wash_cfg writes STANDARD/CLOSE strings, not integers."""
    cfg = {}
    set_wash_cfg(cfg, True)
    assert cfg["wash"]["cfg"] == "STANDARD"
    set_wash_cfg(cfg, False)
    assert cfg["wash"]["cfg"] == "CLOSE"


async def test_dock_switch_deepcopy_no_mutation(hass: HomeAssistant, mock_coordinator):
    """Test that _set_state does not mutate coordinator.data.dock_auto_cfg."""
    entry = MockConfigEntry(domain=DOMAIN, data={})
    entry.add_to_hass(hass)

    original_cfg = {
        "collectdust_v2": {"sw": {"value": False}},
        "wash": {"cfg": "CLOSE"},
    }
    mock_coordinator.data.dock_auto_cfg = original_cfg

    entity = DockSwitchEntity(
        mock_coordinator,
        "auto_empty",
        "Auto Empty",
        lambda cfg: cfg.get("collectdust_v2", {}).get("sw", {}).get("value", False),
        set_collect_dust,
        icon="mdi:delete-restore",
    )
    entity.hass = hass

    await entity.async_turn_on()

    # Original config should be unchanged (deepcopy prevents mutation)
    collectdust_cfg = original_cfg["collectdust_v2"]
    assert isinstance(collectdust_cfg, dict)
    sw_cfg = collectdust_cfg["sw"]
    assert isinstance(sw_cfg, dict)
    assert sw_cfg["value"] is False


def test_dock_switch_unavailable_no_cfg(mock_coordinator):
    """Test dock switch is unavailable when no dock_auto_cfg."""
    mock_coordinator.data.dock_auto_cfg = {}
    mock_coordinator.last_update_success = True

    entity = DockSwitchEntity(
        mock_coordinator,
        "auto_empty",
        "Auto Empty",
        lambda cfg: cfg.get("collectdust_v2", {}).get("sw", {}).get("value", False),
        set_collect_dust,
        icon="mdi:delete-restore",
    )

    assert entity.available is False
