"""Update entity platform for Eufy Clean robot vacuums."""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta
from typing import Any

from homeassistant.components.update import (
    UpdateDeviceClass,
    UpdateEntity,
    UpdateEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import EufyCleanCoordinator
from .entity import has_firmware_api

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 0

# The cloud reports no completion event; poll the upgrade status while installing.
INSTALL_POLL_INTERVAL = timedelta(seconds=30)
# Stop polling after this long even if the cloud still says "installing".
INSTALL_POLL_TIMEOUT_S = 3600


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Eufy Clean update platform."""
    coordinators: list[EufyCleanCoordinator] = hass.data[DOMAIN][config_entry.entry_id]["coordinators"]
    entities: list[UpdateEntity] = []

    for coordinator in coordinators:
        if has_firmware_api(coordinator):
            entities.append(EufyCleanUpdateEntity(coordinator))

    async_add_entities(entities)


class EufyCleanUpdateEntity(CoordinatorEntity[EufyCleanCoordinator], UpdateEntity):
    """Represent the firmware update entity for a Eufy robot vacuum."""

    _attr_has_entity_name = True
    _attr_name = None
    _attr_device_class = UpdateDeviceClass.FIRMWARE
    _attr_supported_features = (
        UpdateEntityFeature.INSTALL
        | UpdateEntityFeature.PROGRESS
        | UpdateEntityFeature.RELEASE_NOTES
    )

    def __init__(self, coordinator: EufyCleanCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.device_id}_firmware"
        self._attr_device_info = coordinator.device_info
        self._install_poll_cancel: CALLBACK_TYPE | None = None
        self._install_poll_deadline = 0.0

    @property
    def installed_version(self) -> str | None:
        """Version currently installed."""
        return self.coordinator.data.installed_version or self.coordinator.firmware_version or None

    @property
    def latest_version(self) -> str | None:
        """Latest version available for install."""
        return (
            self.coordinator.data.latest_version
            or self.installed_version
        )

    @property
    def release_summary(self) -> str | None:
        """Summary of release notes."""
        return self.coordinator.data.release_summary or None

    @property
    def in_progress(self) -> bool:
        """Whether an update is currently installing."""
        return bool(self.coordinator.data.update_in_progress)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return device-specific firmware attributes."""
        attrs: dict[str, Any] = {}
        if self.coordinator.data.firmware_modules:
            attrs["modules"] = self.coordinator.data.firmware_modules
        attrs["auto_update_enabled"] = self.coordinator.data.auto_update_enabled
        return attrs

    async def async_install(
        self, version: str | None, backup: bool, **kwargs: Any
    ) -> None:
        """Install an update.

        ``async_install_firmware`` signals failure by returning False, not by
        raising; ignoring it would make this a silent no-op.
        """
        if not await self.coordinator.async_install_firmware(version=version):
            raise HomeAssistantError(
                f"Could not start the firmware upgrade for "
                f"{self.coordinator.device_name}"
            )
        self._start_install_poll()

    @callback
    def _start_install_poll(self) -> None:
        """Poll the upgrade status until it leaves "installing" or times out."""
        self._stop_install_poll()
        self._install_poll_deadline = time.monotonic() + INSTALL_POLL_TIMEOUT_S
        self._install_poll_cancel = async_track_time_interval(
            self.hass, self._async_poll_install, INSTALL_POLL_INTERVAL
        )

    @callback
    def _stop_install_poll(self) -> None:
        if self._install_poll_cancel is not None:
            self._install_poll_cancel()
            self._install_poll_cancel = None

    async def _async_poll_install(self, _now: datetime) -> None:
        await self.coordinator.async_check_firmware_updates()
        if (
            not self.coordinator.data.update_in_progress
            or time.monotonic() >= self._install_poll_deadline
        ):
            self._stop_install_poll()

    async def async_will_remove_from_hass(self) -> None:
        """Cancel a running install poll."""
        self._stop_install_poll()
        await super().async_will_remove_from_hass()

    async def async_release_notes(self) -> str | None:
        """Return the release notes."""
        return self.coordinator.data.release_summary or None
