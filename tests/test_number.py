"""Unit tests for the DockNumberEntity number entity."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.robovac_mqtt.const import DOMAIN, DPS_MAP
from custom_components.robovac_mqtt.coordinator import EufyCleanCoordinator
from custom_components.robovac_mqtt.models import VacuumState
from custom_components.robovac_mqtt.number import (
    DockNumberEntity,
    _set_wash_freq_value,
    async_setup_entry,
)

# pylint: disable=redefined-outer-name

# Getter/setter used by the wash frequency number entity
_WASH_FREQ_GETTER = (
    lambda cfg: cfg.get("wash", {})
    .get("wash_freq", {})
    .get("time_or_area", {})
    .get("value", 15)
)


@pytest.fixture
def mock_coordinator() -> MagicMock:
    """Mock the coordinator."""
    coordinator = MagicMock(spec=EufyCleanCoordinator)
    coordinator.device_id = "TEST123"
    coordinator.device_name = "Test Vacuum"
    coordinator.api_type = "novel"
    coordinator.data = VacuumState()
    coordinator.async_send_command = AsyncMock()
    coordinator.build_device_command = MagicMock(return_value={DPS_MAP["GO_HOME"]: "cmd"})
    coordinator.device_info = {}
    coordinator.last_update_success = True
    return coordinator


def _make_entity(mock_coordinator) -> DockNumberEntity:
    """Create a DockNumberEntity for wash frequency value."""
    entity = DockNumberEntity(
        mock_coordinator,
        "wash_frequency_value",
        "Wash Frequency Value (Time)",
        15,
        25,
        1,
        _WASH_FREQ_GETTER,
        _set_wash_freq_value,
        icon="mdi:clock-time-four-outline",
    )
    return entity


async def test_dock_number_native_value(hass: HomeAssistant, mock_coordinator):
    """native_value reads from dock_auto_cfg via getter."""
    entry = MockConfigEntry(domain=DOMAIN, data={})
    entry.add_to_hass(hass)

    mock_coordinator.data.dock_auto_cfg = {
        "wash": {"wash_freq": {"time_or_area": {"value": 20}}}
    }

    entity = _make_entity(mock_coordinator)
    entity.hass = hass

    assert entity.native_value == 20


async def test_dock_number_native_value_empty_cfg(
    hass: HomeAssistant, mock_coordinator
):
    """native_value returns None when dock_auto_cfg is empty."""
    entry = MockConfigEntry(domain=DOMAIN, data={})
    entry.add_to_hass(hass)

    mock_coordinator.data.dock_auto_cfg = {}

    entity = _make_entity(mock_coordinator)
    entity.hass = hass

    assert entity.native_value is None


async def test_dock_number_unavailable_no_cfg(
    hass: HomeAssistant, mock_coordinator
):
    """Entity is unavailable when dock_auto_cfg is empty."""
    entry = MockConfigEntry(domain=DOMAIN, data={})
    entry.add_to_hass(hass)

    mock_coordinator.data.dock_auto_cfg = {}

    entity = _make_entity(mock_coordinator)
    entity.hass = hass
    entity.platform = AsyncMock()
    entity.platform.platform = Platform.NUMBER

    assert entity.available is False


async def test_dock_number_available_with_cfg(
    hass: HomeAssistant, mock_coordinator
):
    """Entity is available when dock_auto_cfg has data."""
    entry = MockConfigEntry(domain=DOMAIN, data={})
    entry.add_to_hass(hass)

    mock_coordinator.data.dock_auto_cfg = {
        "wash": {"wash_freq": {"time_or_area": {"value": 20}}}
    }

    entity = _make_entity(mock_coordinator)
    entity.hass = hass
    entity.platform = AsyncMock()
    entity.platform.platform = Platform.NUMBER

    assert entity.available is True


@pytest.mark.asyncio
async def test_dock_number_set_value_deepcopy(
    hass: HomeAssistant, mock_coordinator
):
    """async_set_native_value does not mutate coordinator.data.dock_auto_cfg."""
    entry = MockConfigEntry(domain=DOMAIN, data={})
    entry.add_to_hass(hass)

    mock_coordinator.data.dock_auto_cfg = {
        "wash": {"wash_freq": {"time_or_area": {"value": 20}}}
    }

    entity = _make_entity(mock_coordinator)
    entity.hass = hass

    await entity.async_set_native_value(22)

    # Original cfg must be unchanged
    original_value = (
        mock_coordinator.data.dock_auto_cfg["wash"]["wash_freq"]["time_or_area"][
            "value"
        ]
    )
    assert original_value == 20


@pytest.mark.asyncio
async def test_dock_number_set_value_sends_command(
    hass: HomeAssistant, mock_coordinator
):
    """async_set_native_value sends the right command via coordinator."""
    entry = MockConfigEntry(domain=DOMAIN, data={})
    entry.add_to_hass(hass)

    mock_coordinator.data.dock_auto_cfg = {
        "wash": {"wash_freq": {"time_or_area": {"value": 20}}}
    }

    entity = _make_entity(mock_coordinator)
    entity.hass = hass

    await entity.async_set_native_value(18)

    mock_coordinator.build_device_command.assert_called_once()
    mock_coordinator.async_send_command.assert_called_once()
    call_args = mock_coordinator.async_send_command.call_args[0][0]
    assert DPS_MAP["GO_HOME"] in call_args
