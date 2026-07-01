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

from .const import DOMAIN
from .coordinator import EufyCleanCoordinator
from .entity import API_TYPE_NOVEL, API_TYPE_SCALAR, filter_supported_entities
from .proto.cloud.consumable_pb2 import ConsumableRequest

_LOGGER = logging.getLogger(__name__)

# Accessory reset buttons: (name, id_suffix, novel reset_type, icon,
# scalar DPS-150 key, supported api types). Filter/brushes/sensor are
# universal; cleaning tray + mopping cloth only exist on mop-capable
# (novel) devices.
_ACCESSORY_RESET_BUTTONS: list[
    tuple[str, str, int, str, str | None, tuple[str, ...] | None]
] = [
    (
        "Reset Filter",
        "_reset_filter",
        ConsumableRequest.FILTER_MESH,
        "mdi:air-filter",
        "dust_filter",
        None,
    ),
    (
        "Reset Rolling Brush",
        "_reset_main_brush",
        ConsumableRequest.ROLLING_BRUSH,
        "mdi:broom",
        "roller_brush",
        None,
    ),
    (
        "Reset Side Brush",
        "_reset_side_brush",
        ConsumableRequest.SIDE_BRUSH,
        "mdi:broom",
        "side_brush",
        None,
    ),
    (
        "Reset Sensors",
        "_reset_sensors",
        ConsumableRequest.SENSOR,
        "mdi:eye-outline",
        "sensors",
        None,
    ),
    (
        "Reset Cleaning Tray",
        "_reset_scrape",
        ConsumableRequest.SCRAPE,
        "mdi:wiper",
        None,
        (API_TYPE_NOVEL,),
    ),
    (
        "Reset Mopping Cloth",
        "_reset_mop",
        ConsumableRequest.MOP,
        "mdi:water",
        None,
        (API_TYPE_NOVEL,),
    ),
]


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

        # Dock and accessory buttons require protobuf DPS (173/168) and are not
        # available on legacy (Tuya Cloud plain-value) devices.
        if coordinator.api_type == "legacy":
            continue

        buttons = [
            # Vacuum control buttons — mirrors the Eufy app's main screen controls.
            RoboVacButton(coordinator, "Start Cleaning", "_start_cleaning", "start_auto"),
            RoboVacButton(coordinator, "Pause", "_pause", "pause"),
            RoboVacButton(coordinator, "Return to Base", "_return_to_base", "return_to_base"),
            # Station buttons (wash/dry/dust) — scalar (Tuya) devices like the
            # G50 are vacuum-only and have no station.
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
            # Detangle roller brush — scalar/Tuya devices only (DPS 153).
            RoboVacButton(
                coordinator,
                "Detangle Roller Brush",
                "_detangle_brush",
                "detangle_brush",
                "mdi:broom",
                category=EntityCategory.CONFIG,
                supported_api_types=(API_TYPE_SCALAR,),
            ),
        ]

        for (
            name,
            suffix,
            reset_type,
            icon,
            scalar_key,
            supported,
        ) in _ACCESSORY_RESET_BUTTONS:
            buttons.append(
                RoboVacButton(
                    coordinator,
                    name,
                    suffix,
                    "reset_accessory",
                    icon,
                    category=EntityCategory.CONFIG,
                    supported_api_types=supported,
                    reset_type=reset_type,
                    scalar_key=scalar_key,
                )
            )

        entities.extend(filter_supported_entities(coordinator, buttons))

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
        # DPS protocols this button exists on (see entity.py); None = all.
        self.supported_api_types = supported_api_types
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
        cmd = self.coordinator.build_device_command(
            self._command,
            **self._command_kwargs,
        )
        await self.coordinator.async_send_command(cmd)
