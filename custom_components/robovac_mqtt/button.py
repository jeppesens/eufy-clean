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

        # Scalar (Tuya) devices like the G50 are vacuum-only: no station (wash/dry/
        # dust), no mop. Skip those buttons entirely instead of leaving them dead.
        is_scalar = coordinator.api_type == "scalar"

        if not is_scalar:
            entities.extend(
                [
                    RoboVacButton(coordinator, "Dry Mop", "_dry_mop", "go_dry"),
                    RoboVacButton(
                        coordinator, "Wash Mop", "_wash_mop", "go_selfcleaning"
                    ),
                    RoboVacButton(
                        coordinator, "Empty Dust Bin", "_empty_dust_bin", "collect_dust"
                    ),
                    RoboVacButton(
                        coordinator, "Stop Dry Mop", "_stop_dry_mop", "stop_dry"
                    ),
                ]
            )

        # Accessory Reset Buttons (filter/brushes/sensor are universal).
        accessories = [
            # (name, id_suffix, novel reset_type, icon, scalar DPS-150 key)
            (
                "Reset Filter",
                "_reset_filter",
                ConsumableRequest.FILTER_MESH,
                "mdi:air-filter",
                "dust_filter",
            ),
            (
                "Reset Rolling Brush",
                "_reset_main_brush",
                ConsumableRequest.ROLLING_BRUSH,
                "mdi:broom",
                "roller_brush",
            ),
            (
                "Reset Side Brush",
                "_reset_side_brush",
                ConsumableRequest.SIDE_BRUSH,
                "mdi:broom",
                "side_brush",
            ),
            (
                "Reset Sensors",
                "_reset_sensors",
                ConsumableRequest.SENSOR,
                "mdi:eye-outline",
                "sensors",
            ),
        ]
        if not is_scalar:
            # Cleaning tray + mopping cloth only exist on mop-capable devices.
            accessories += [
                (
                    "Reset Cleaning Tray",
                    "_reset_scrape",
                    ConsumableRequest.SCRAPE,
                    "mdi:wiper",
                    None,
                ),
                (
                    "Reset Mopping Cloth",
                    "_reset_mop",
                    ConsumableRequest.MOP,
                    "mdi:water",
                    None,
                ),
            ]

        for name, suffix, reset_type, icon, scalar_key in accessories:
            entities.append(
                RoboVacButton(
                    coordinator,
                    name,
                    suffix,
                    "reset_accessory",
                    icon,
                    category=EntityCategory.CONFIG,
                    reset_type=reset_type,
                    scalar_key=scalar_key,
                )
            )

        # Detangle roller brush — scalar/Tuya devices only (DPS 153).
        if is_scalar:
            entities.append(
                RoboVacButton(
                    coordinator,
                    "Detangle Roller Brush",
                    "_detangle_brush",
                    "detangle_brush",
                    "mdi:broom",
                    category=EntityCategory.CONFIG,
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
        available_fn: Callable[[EufyCleanCoordinator], bool] | None = None,
        **kwargs: Any,
    ) -> None:
        """Initialize button."""
        super().__init__(coordinator)
        self._command = command
        self._command_kwargs = kwargs
        self._available_fn = available_fn
        self._attr_unique_id = f"{coordinator.device_id}{id_suffix}"

        # Use Home Assistant standard naming
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
        cmd = build_command(
            self._command,
            api_type=self.coordinator.api_type,
            **self._command_kwargs,
        )
        await self.coordinator.async_send_command(cmd)
