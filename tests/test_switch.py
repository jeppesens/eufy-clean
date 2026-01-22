"""Unit tests for the FindRobot switch entity."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.robovac_mqtt.const import DOMAIN, DPS_MAP
from custom_components.robovac_mqtt.models import VacuumState
from custom_components.robovac_mqtt.switch import (
    DockSwitchEntity,
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
    coordinator.data = VacuumState()
    coordinator.async_send_command = AsyncMock()
    coordinator.device_info = {}
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
    mock_coordinator.async_send_command.assert_called_with(
        {DPS_MAP["FIND_ROBOT"]: False}
    )


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
    # Expected config update in command
    # Check that command included the updated config
    mock_coordinator.async_send_command.assert_called()
    call_args = mock_coordinator.async_send_command.call_args[0][0]
    assert DPS_MAP["GO_HOME"] in call_args

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
