"""Unit tests for the Eufy Clean update platform."""

import dataclasses
from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.components.update import UpdateDeviceClass, UpdateEntityFeature
from homeassistant.exceptions import HomeAssistantError
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.robovac_mqtt.const import DOMAIN
from custom_components.robovac_mqtt.coordinator import VacuumState
from custom_components.robovac_mqtt.update import (
    INSTALL_POLL_INTERVAL,
    EufyCleanUpdateEntity,
    async_setup_entry,
)


@pytest.fixture(name="mock_coordinator")
def fixture_mock_coordinator():
    coordinator = MagicMock()
    coordinator.device_id = "test_dev_123"
    coordinator.device_name = "RoboVac X8"
    coordinator.firmware_version = "3.6.7"
    coordinator.device_info = {
        "identifiers": {(DOMAIN, "test_dev_123")},
        "name": "RoboVac X8",
        "sw_version": "3.6.7",
    }
    coordinator.data = VacuumState(
        installed_version="3.6.7",
        latest_version="3.6.8",
        release_summary="Bug fixes and performance improvements",
        update_in_progress=False,
        auto_update_enabled=True,
        firmware_modules=[
            {
                "type": 0,
                "typeDesc": "Main Module",
                "currentVersion": "3.6.7",
                "version": "3.6.8",
            }
        ],
    )
    coordinator.async_install_firmware = AsyncMock(return_value=True)
    coordinator.async_check_firmware_updates = AsyncMock(return_value=True)
    coordinator.eufy_login.tuya_device_ids = {"test_dev_123"}
    return coordinator


def test_update_entity_properties(mock_coordinator):
    """Test update entity property mappings."""
    entity = EufyCleanUpdateEntity(mock_coordinator)

    assert entity.unique_id == "test_dev_123_firmware"
    assert entity.device_class == UpdateDeviceClass.FIRMWARE
    assert entity.supported_features & UpdateEntityFeature.INSTALL
    assert entity.supported_features & UpdateEntityFeature.RELEASE_NOTES
    assert entity.installed_version == "3.6.7"
    assert entity.latest_version == "3.6.8"
    assert entity.release_summary == "Bug fixes and performance improvements"
    assert entity.in_progress is False
    assert entity.extra_state_attributes["auto_update_enabled"] is True
    assert len(entity.extra_state_attributes["modules"]) == 1


def test_update_entity_progress(mock_coordinator):
    """in_progress follows the firmware status; the info call has no percentage."""
    entity = EufyCleanUpdateEntity(mock_coordinator)

    mock_coordinator.data = dataclasses.replace(
        mock_coordinator.data, update_in_progress=True
    )
    assert entity.in_progress is True


@pytest.mark.asyncio
async def test_update_entity_actions(hass, mock_coordinator):
    """Test install and release notes actions."""
    entity = EufyCleanUpdateEntity(mock_coordinator)
    entity.hass = hass

    await entity.async_install(version="3.6.8", backup=False)
    mock_coordinator.async_install_firmware.assert_awaited_once_with(version="3.6.8")
    await entity.async_will_remove_from_hass()

    notes = await entity.async_release_notes()
    assert notes == "Bug fixes and performance improvements"


@pytest.mark.asyncio
async def test_install_raises_when_the_upgrade_could_not_be_started(mock_coordinator):
    """async_install_firmware reports failure by RETURNING False.

    Discarding it made update.install a silent no-op that still reported success
    — which is what happens on an MQTT-only account (no Thing client) or when the
    gateway accepts none of the OTA trigger actions.
    """
    mock_coordinator.async_install_firmware = AsyncMock(return_value=False)
    entity = EufyCleanUpdateEntity(mock_coordinator)

    with pytest.raises(HomeAssistantError):
        await entity.async_install(version=None, backup=False)


@pytest.mark.asyncio
async def test_update_async_setup_entry(hass, mock_coordinator):
    """Test platform setup."""
    config_entry = MagicMock()
    config_entry.entry_id = "test_entry_id"
    hass.data[DOMAIN] = {config_entry.entry_id: {"coordinators": [mock_coordinator]}}

    async_add_entities = MagicMock()
    await async_setup_entry(hass, config_entry, async_add_entities)

    async_add_entities.assert_called_once()
    added = async_add_entities.call_args[0][0]
    assert len(added) == 1
    assert isinstance(added[0], EufyCleanUpdateEntity)


async def test_install_polls_status_until_it_leaves_installing(hass, mock_coordinator):
    """A started install polls the cloud status and stops once it completes."""
    entity = EufyCleanUpdateEntity(mock_coordinator)
    entity.hass = hass
    mock_coordinator.data = dataclasses.replace(
        mock_coordinator.data, update_in_progress=True
    )

    polls = {"n": 0}

    async def check() -> bool:
        polls["n"] += 1
        if polls["n"] == 2:
            mock_coordinator.data = dataclasses.replace(
                mock_coordinator.data, update_in_progress=False
            )
        return False

    mock_coordinator.async_check_firmware_updates = AsyncMock(side_effect=check)
    await entity.async_install(version=None, backup=False)

    start = dt_util.utcnow()
    for tick in range(1, 5):
        async_fire_time_changed(hass, start + INSTALL_POLL_INTERVAL * tick)
        await hass.async_block_till_done()

    assert polls["n"] == 2
    assert entity._install_poll_cancel is None


async def test_install_poll_is_cancelled_on_removal(hass, mock_coordinator):
    """Removing the entity mid-install stops the status poll."""
    entity = EufyCleanUpdateEntity(mock_coordinator)
    entity.hass = hass
    await entity.async_install(version=None, backup=False)
    assert entity._install_poll_cancel is not None

    await entity.async_will_remove_from_hass()

    assert entity._install_poll_cancel is None
    async_fire_time_changed(hass, dt_util.utcnow() + INSTALL_POLL_INTERVAL * 2)
    await hass.async_block_till_done()
    mock_coordinator.async_check_firmware_updates.assert_not_called()


@pytest.mark.asyncio
async def test_no_update_entity_without_the_tuya_thing_client(hass, mock_coordinator):
    """Firmware status and OTA need the Tuya Thing API; without it no entity is made."""
    mock_coordinator.eufy_login.tuya_thing_client = None
    config_entry = MagicMock()
    config_entry.entry_id = "test_entry_id"
    hass.data[DOMAIN] = {config_entry.entry_id: {"coordinators": [mock_coordinator]}}

    async_add_entities = MagicMock()
    await async_setup_entry(hass, config_entry, async_add_entities)

    assert async_add_entities.call_args[0][0] == []
