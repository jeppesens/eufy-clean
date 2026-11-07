"""Unit tests for Do Not Disturb time entities."""

from datetime import time as dt_time
from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.robovac_mqtt.api.commands import build_command
from custom_components.robovac_mqtt.const import DOMAIN, DPS_MAP
from custom_components.robovac_mqtt.models import VacuumState
from custom_components.robovac_mqtt.time import (
    DoNotDisturbEndTimeEntity,
    DoNotDisturbStartTimeEntity,
    OffPeakChargingStartTimeEntity,
    async_setup_entry,
)


@pytest.fixture
def coordinator_fixture() -> MagicMock:
    """Mock the coordinator."""
    coordinator = MagicMock()
    coordinator.device_id = "test_device"
    coordinator.device_name = "Test Vac"
    coordinator.device_model = "T2118"
    coordinator.api_type = "novel"
    coordinator.data = VacuumState()
    coordinator.build_device_command = MagicMock(
        side_effect=lambda cmd, **kw: build_command(cmd, api_type="novel", **kw)
    )
    coordinator.async_send_command = AsyncMock()
    coordinator.async_set_updated_data = MagicMock()
    coordinator.device_info = {}
    coordinator.last_update_success = True
    return coordinator


async def test_do_not_disturb_start_time_entity(
    hass: HomeAssistant, request: pytest.FixtureRequest
):
    """Test updating DND start time."""
    coordinator = request.getfixturevalue("coordinator_fixture")
    entry = MockConfigEntry(domain=DOMAIN, data={})
    entry.add_to_hass(hass)

    coordinator.data.received_fields = {"do_not_disturb"}
    coordinator.data.dnd_enabled = True
    coordinator.data.dnd_start_hour = 22
    coordinator.data.dnd_start_minute = 0
    coordinator.data.dnd_end_hour = 8
    coordinator.data.dnd_end_minute = 0

    entity = DoNotDisturbStartTimeEntity(coordinator)
    entity.hass = hass
    entity.platform = AsyncMock()
    entity.platform.platform = Platform.TIME

    assert entity.native_value == dt_time(22, 0)

    await entity.async_set_value(dt_time(23, 30))
    sent_command = coordinator.async_send_command.call_args_list[-1][0][0]
    assert DPS_MAP["UNDISTURBED"] in sent_command
    updated_state = coordinator.async_set_updated_data.call_args_list[-1][0][0]
    assert updated_state.dnd_start_hour == 23
    assert updated_state.dnd_start_minute == 30
    assert updated_state.dnd_end_hour == 8
    assert updated_state.dnd_end_minute == 0


async def test_do_not_disturb_end_time_entity(
    hass: HomeAssistant, request: pytest.FixtureRequest
):
    """Test updating DND end time."""
    coordinator = request.getfixturevalue("coordinator_fixture")
    entry = MockConfigEntry(domain=DOMAIN, data={})
    entry.add_to_hass(hass)

    coordinator.data.received_fields = {"do_not_disturb"}
    coordinator.data.dnd_enabled = True
    coordinator.data.dnd_start_hour = 22
    coordinator.data.dnd_start_minute = 0
    coordinator.data.dnd_end_hour = 8
    coordinator.data.dnd_end_minute = 0

    entity = DoNotDisturbEndTimeEntity(coordinator)
    entity.hass = hass
    entity.platform = AsyncMock()
    entity.platform.platform = Platform.TIME

    assert entity.native_value == dt_time(8, 0)

    await entity.async_set_value(dt_time(7, 15))
    sent_command = coordinator.async_send_command.call_args_list[-1][0][0]
    assert DPS_MAP["UNDISTURBED"] in sent_command
    updated_state = coordinator.async_set_updated_data.call_args_list[-1][0][0]
    assert updated_state.dnd_end_hour == 7
    assert updated_state.dnd_end_minute == 15
    assert updated_state.dnd_start_hour == 22
    assert updated_state.dnd_start_minute == 0


async def test_set_value_builds_through_the_coordinator(
    hass: HomeAssistant, request: pytest.FixtureRequest
):
    """Commands go through build_device_command, which picks the device's protocol."""
    coordinator = request.getfixturevalue("coordinator_fixture")
    coordinator.data.received_fields = {"do_not_disturb", "off_peak_charging"}

    await DoNotDisturbStartTimeEntity(coordinator).async_set_value(dt_time(21, 0))
    await OffPeakChargingStartTimeEntity(coordinator).async_set_value(dt_time(1, 0))

    built = [c.args[0] for c in coordinator.build_device_command.call_args_list]
    assert built == ["set_do_not_disturb", "set_off_peak_charging"]


@pytest.mark.parametrize(
    ("api_type", "expected"),
    [
        ("novel", {"do_not_disturb_start", "do_not_disturb_end",
                   "off_peak_charging_start", "off_peak_charging_end"}),
        ("scalar", {"do_not_disturb_start", "do_not_disturb_end"}),
        ("legacy", set()),
    ],
)
async def test_time_entities_only_where_the_parser_reports_them(
    hass: HomeAssistant, request: pytest.FixtureRequest, api_type, expected
):
    """No permanently unavailable schedule entities for protocols that lack them."""
    coordinator = request.getfixturevalue("coordinator_fixture")
    coordinator.api_type = api_type
    entry = MockConfigEntry(domain=DOMAIN, data={}, entry_id="time_entry")
    hass.data[DOMAIN] = {entry.entry_id: {"coordinators": [coordinator]}}

    add = MagicMock()
    await async_setup_entry(hass, entry, add)

    suffixes = {e.unique_id.removeprefix("test_device_") for e in add.call_args[0][0]}
    assert suffixes == expected
