from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import API_TYPE_LEGACY, API_TYPE_NOVEL, API_TYPE_SCALAR, DOMAIN
from .coordinator import EufyCleanCoordinator
from .entity import filter_supported_entities, has_firmware_api
from .profiles import DeviceProfile, get_device_profile

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Setup button entities."""
    data = hass.data[DOMAIN][config_entry.entry_id]
    coordinators: list[EufyCleanCoordinator] = data["coordinators"]

    entities = []

    for coordinator in coordinators:
        _LOGGER.debug("Adding buttons for %s", coordinator.device_name)
        profile = (
            coordinator.profile
            if isinstance(getattr(coordinator, "profile", None), DeviceProfile)
            else get_device_profile(
                getattr(coordinator, "device_model", ""),
                getattr(coordinator, "api_type", API_TYPE_NOVEL),
            )
        )

        buttons = [
            RoboVacButton(coordinator, "Start Cleaning", "_start_cleaning", "start_auto"),
            RoboVacButton(coordinator, "Pause", "_pause", "pause"),
            RoboVacButton(coordinator, "Return to Base", "_return_to_base", "return_to_base"),
        ]

        if coordinator.api_type != API_TYPE_LEGACY:
            buttons.extend([
                # station actions; scalar devices are vacuum-only, no station
                RoboVacButton(
                    coordinator,
                    "Dry Mop",
                    "_dry_mop",
                    "go_dry",
                    supported_api_types=(API_TYPE_NOVEL,),
                ),
                RoboVacButton(
                    coordinator,
                    "Wash Mop",
                    "_wash_mop",
                    "go_selfcleaning",
                    supported_api_types=(API_TYPE_NOVEL,),
                ),
                RoboVacButton(
                    coordinator,
                    "Empty Dust Bin",
                    "_empty_dust_bin",
                    "collect_dust",
                    supported_api_types=(API_TYPE_NOVEL,),
                ),
                RoboVacButton(
                    coordinator,
                    "Stop Dry Mop",
                    "_stop_dry_mop",
                    "stop_dry",
                    supported_api_types=(API_TYPE_NOVEL,),
                ),
                # scalar DPS 153
                RoboVacButton(
                    coordinator,
                    "Detangle Roller Brush",
                    "_detangle_brush",
                    "detangle_brush",
                    "mdi:broom",
                    category=EntityCategory.CONFIG,
                    supported_api_types=(API_TYPE_SCALAR,),
                ),
            ])

        for spec in profile.accessories.values():
            buttons.append(
                RoboVacButton(
                    coordinator,
                    spec.button_name,
                    spec.button_id,
                    "reset_accessory",
                    spec.icon,
                    category=EntityCategory.CONFIG,
                    supported_api_types=spec.supported_api_types,
                    reset_type=spec.proto_type,
                    scalar_key=spec.scalar_key,
                    legacy_key=spec.legacy_key,
                )
            )

        if coordinator.api_type == API_TYPE_LEGACY:
            entities.extend(buttons)
        else:
            entities.extend(filter_supported_entities(coordinator, buttons))
        if has_firmware_api(coordinator):
            entities.append(CheckFirmwareUpdatesButton(coordinator))

    async_add_entities(entities)


class RoboVacButton(CoordinatorEntity[EufyCleanCoordinator], ButtonEntity):
    """Eufy Clean Button Entity."""

    def __init__(
        self,
        coordinator: EufyCleanCoordinator,
        name_suffix: str,
        id_suffix: str,
        command: str,
        icon: str | None = None,
        category: EntityCategory | None = None,
        available_fn: Callable[[EufyCleanCoordinator], bool] | None = None,
        supported_api_types: tuple[str, ...] | None = None,
        **kwargs: Any,
    ) -> None:
        """Initialize button."""
        super().__init__(coordinator)
        # protocols this button exists on (see entity.py); None = all
        self.supported_api_types = supported_api_types
        self._command = command
        self._command_kwargs = kwargs
        self._available_fn = available_fn
        self._attr_unique_id = f"{coordinator.device_id}{id_suffix}"

        self._attr_has_entity_name = True
        self._attr_name = name_suffix

        self._attr_device_info = coordinator.device_info
        self._attr_entity_category = category
        if icon:
            self._attr_icon = icon

    @property
    def available(self) -> bool:
        """Return whether the button is available."""
        if self._available_fn is not None:
            return super().available and self._available_fn(self.coordinator)
        return super().available

    async def async_press(self) -> None:
        """Press the button."""
        cmd = self.coordinator.build_device_command(
            self._command,
            **self._command_kwargs,
        )
        await self.coordinator.async_send_command(cmd)


class CheckFirmwareUpdatesButton(CoordinatorEntity[EufyCleanCoordinator], ButtonEntity):
    """Button to manually check for firmware updates from the cloud."""

    _attr_has_entity_name = True
    _attr_name = "Check for Firmware Updates"
    _attr_icon = "mdi:refresh"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: EufyCleanCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.device_id}_check_firmware_updates"
        self._attr_device_info = coordinator.device_info

    async def async_press(self) -> None:
        """Handle the button press."""
        await self.coordinator.async_check_firmware_updates()
