from __future__ import annotations

import logging
from collections.abc import Callable

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import EufyCleanCoordinator, VacuumState

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Setup binary sensor entities."""
    data = hass.data[DOMAIN][config_entry.entry_id]
    coordinators: list[EufyCleanCoordinator] = data["coordinators"]

    entities = []

    for coordinator in coordinators:
        _LOGGER.debug("Adding binary sensors for %s", coordinator.device_name)

        entities.append(
            RoboVacBinarySensor(
                coordinator,
                "charging",
                "Charging",
                lambda s: s.charging,
                device_class=BinarySensorDeviceClass.BATTERY_CHARGING,
            )
        )

    async_add_entities(entities)


class RoboVacBinarySensor(CoordinatorEntity[EufyCleanCoordinator], BinarySensorEntity):
    """Eufy Clean Binary Sensor Entity."""

    def __init__(
        self,
        coordinator: EufyCleanCoordinator,
        id_suffix: str,
        name_suffix: str,
        value_fn: Callable[[VacuumState], bool],
        device_class: BinarySensorDeviceClass | None = None,
        category: EntityCategory | None = EntityCategory.DIAGNOSTIC,
    ) -> None:
        """Initialize the binary sensor."""
        super().__init__(coordinator)
        self._value_fn = value_fn
        self._attr_unique_id = f"{coordinator.device_id}_{id_suffix}"
        self._attr_has_entity_name = True
        self._attr_name = name_suffix
        self._attr_device_info = coordinator.device_info
        self._attr_device_class = device_class
        self._attr_entity_category = category

    @property
    def is_on(self) -> bool | None:
        """Return true if the binary sensor is on."""
        return self._value_fn(self.coordinator.data)
