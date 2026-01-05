from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api.commands import build_command
from .const import DOMAIN
from .coordinator import EufyCleanCoordinator
from .proto.cloud.consumable_pb2 import ConsumableRequest

_LOGGER = logging.getLogger(__name__)


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

        entities.extend(
            [
                RoboVacButton(coordinator, "Dry Mop", "_dry_mop", "go_dry"),
                RoboVacButton(coordinator, "Wash Mop", "_wash_mop", "go_selfcleaning"),
                RoboVacButton(
                    coordinator, "Empty Dust Bin", "_empty_dust_bin", "collect_dust"
                ),
                RoboVacButton(coordinator, "Stop Dry Mop", "_stop_dry_mop", "stop_dry"),
            ]
        )

        # Accessory Reset Buttons
        accessories = [
            (
                "Reset Filter",
                "_reset_filter",
                ConsumableRequest.FILTER_MESH,
                "mdi:air-filter",
            ),
            (
                "Reset Rolling Brush",
                "_reset_main_brush",
                ConsumableRequest.ROLLING_BRUSH,
                "mdi:broom",
            ),
            (
                "Reset Side Brush",
                "_reset_side_brush",
                ConsumableRequest.SIDE_BRUSH,
                "mdi:broom",
            ),
            (
                "Reset Sensors",
                "_reset_sensors",
                ConsumableRequest.SENSOR,
                "mdi:eye-outline",
            ),
            (
                "Reset Cleaning Tray",
                "_reset_scrape",
                ConsumableRequest.SCRAPE,
                "mdi:wiper",
            ),
            ("Reset Mopping Cloth", "_reset_mop", ConsumableRequest.MOP, "mdi:water"),
        ]

        for name, suffix, reset_type, icon in accessories:
            entities.append(
                RoboVacButton(
                    coordinator,
                    name,
                    suffix,
                    "reset_accessory",
                    icon,
                    category=EntityCategory.CONFIG,
                    reset_type=reset_type,
                )
            )

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
        **kwargs: Any,
    ) -> None:
        """Initialize button."""
        super().__init__(coordinator)
        self._command = command
        self._command_kwargs = kwargs
        self._attr_unique_id = f"{coordinator.device_id}{id_suffix}"

        # Use Home Assistant standard naming
        self._attr_has_entity_name = True
        self._attr_name = name_suffix

        self._attr_device_info = coordinator.device_info
        self._attr_entity_category = category
        if icon:
            self._attr_icon = icon

    async def async_press(self) -> None:
        """Press the button."""
        cmd = build_command(self._command, **self._command_kwargs)
        await self.coordinator.async_send_command(cmd)
