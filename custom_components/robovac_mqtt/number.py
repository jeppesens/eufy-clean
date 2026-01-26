from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from homeassistant.components.number import NumberEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api.commands import build_command
from .const import DOMAIN
from .coordinator import EufyCleanCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Setup number entities."""
    data = hass.data[DOMAIN][config_entry.entry_id]
    coordinators: list[EufyCleanCoordinator] = data["coordinators"]

    entities = []

    for coordinator in coordinators:
        _LOGGER.debug("Adding number entities for %s", coordinator.device_name)

        # Wash Frequency Value
        entities.append(
            DockNumberEntity(
                coordinator,
                "wash_frequency_value",
                "Wash Frequency Value (Time)",
                15,
                25,
                1,  # step
                lambda cfg: cfg.get("wash", {})
                .get("wash_freq", {})
                .get("time_or_area", {})
                .get("value", 15),
                _set_wash_freq_value,
                icon="mdi:clock-time-four-outline",
            )
        )

    async_add_entities(entities)


def _set_wash_freq_value(cfg: dict[str, Any], val: float) -> None:
    """Helper to set wash freq value."""
    # Ensure structure exists
    if "wash" not in cfg:
        cfg["wash"] = {}
    if "wash_freq" not in cfg["wash"]:
        cfg["wash"]["wash_freq"] = {}
    if "time_or_area" not in cfg["wash"]["wash_freq"]:
        cfg["wash"]["wash_freq"]["time_or_area"] = {}

    cfg["wash"]["wash_freq"]["time_or_area"]["value"] = int(val)


class DockNumberEntity(CoordinatorEntity[EufyCleanCoordinator], NumberEntity):
    """Number entity for Dock settings."""

    def __init__(
        self,
        coordinator: EufyCleanCoordinator,
        id_suffix: str,
        name: str,
        min_val: float,
        max_val: float,
        step_val: float,
        getter: Callable[[dict[str, Any]], float],
        setter: Callable[[dict[str, Any], float], None],
        icon: str | None = None,
    ) -> None:
        """Initialize the dock number entity."""
        super().__init__(coordinator)
        self._id_suffix = id_suffix
        self._attr_unique_id = f"{coordinator.device_id}_{id_suffix}"
        self._attr_has_entity_name = True
        self._attr_name = name
        self._attr_native_min_value = min_val
        self._attr_native_max_value = max_val
        self._attr_native_step = step_val
        self._getter = getter
        self._setter = setter
        if icon:
            self._attr_icon = icon

        self._attr_device_info = coordinator.device_info
        self._attr_entity_category = EntityCategory.CONFIG

    @property
    def native_value(self) -> float | None:
        """Return the value."""
        cfg = self.coordinator.data.dock_auto_cfg
        if not cfg:
            return None
        try:
            return self._getter(cfg)
        except Exception as e:
            _LOGGER.debug("Error getting number value for %s: %s", self.name, e)
            return None

    async def async_set_native_value(self, value: float) -> None:
        """Set the value."""
        cfg = self.coordinator.data.dock_auto_cfg.copy()
        self._setter(cfg, value)

        command = build_command("set_auto_cfg", cfg=cfg)
        await self.coordinator.async_send_command(command)

        self.async_write_ha_state()
