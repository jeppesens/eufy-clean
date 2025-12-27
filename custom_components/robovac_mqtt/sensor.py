from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, EntityCategory
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
    """Setup sensor entities."""
    data = hass.data[DOMAIN][config_entry.entry_id]
    coordinators: list[EufyCleanCoordinator] = data["coordinators"]

    entities = []

    for coordinator in coordinators:
        _LOGGER.debug("Adding sensors for %s", coordinator.device_name)

        # Battery sensor
        entities.append(
            RoboVacSensor(
                coordinator,
                "battery",
                "Battery",
                lambda s: s.battery_level,
                device_class=SensorDeviceClass.BATTERY,
                unit=PERCENTAGE,
                state_class=SensorStateClass.MEASUREMENT,
            )
        )

        # Water level sensor (Station Clean Water)
        entities.append(
            RoboVacSensor(
                coordinator,
                "water_level",
                "Water Level",
                lambda s: s.station_clean_water,
                device_class=None,
                unit=PERCENTAGE,
                state_class=SensorStateClass.MEASUREMENT,
            )
        )

        # Dock status sensor
        entities.append(
            RoboVacSensor(
                coordinator,
                "dock_status",
                "Dock Status",
                lambda s: s.dock_status,
                device_class=None,
                unit=None,
                state_class=None,
                category=EntityCategory.DIAGNOSTIC,
            )
        )

        # Active map ID sensor
        entities.append(
            RoboVacSensor(
                coordinator,
                "active_map",
                "Active Map",
                lambda s: s.map_id,
                device_class=None,
                unit=None,
                state_class=None,
                icon="mdi:map-marker-path",
                category=EntityCategory.DIAGNOSTIC,
            )
        )

    async_add_entities(entities)


class RoboVacSensor(CoordinatorEntity[EufyCleanCoordinator], SensorEntity):
    """Eufy Clean Sensor Entity."""

    def __init__(
        self,
        coordinator: EufyCleanCoordinator,
        id_suffix: str,
        name_suffix: str,
        value_fn: Callable[[VacuumState], Any],
        device_class: SensorDeviceClass | None = None,
        unit: str | None = None,
        state_class: SensorStateClass | None = None,
        icon: str | None = None,
        category: EntityCategory | None = EntityCategory.DIAGNOSTIC,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._value_fn = value_fn
        self._attr_unique_id = f"{coordinator.device_id}_{id_suffix}"

        # Use Home Assistant standard naming
        # This will prefix the device name to the entity name if the device name is not in the entity name
        # Result: sensor.robovac_water_level (Safer, avoids collisions)
        self._attr_has_entity_name = True
        self._attr_name = name_suffix

        self._attr_device_info = {
            "identifiers": {(DOMAIN, coordinator.device_id)},
            "name": coordinator.device_name,
            "manufacturer": "Eufy",
            "model": coordinator.device_model,
        }

        self._attr_native_unit_of_measurement = unit
        self._attr_device_class = device_class
        self._attr_state_class = state_class
        self._attr_entity_category = category
        if icon:
            self._attr_icon = icon

    @property
    def native_value(self) -> Any:
        """Return the state of the sensor."""
        return self._value_fn(self.coordinator.data)
