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

from .const import ACCESSORY_MAX_LIFE, DOMAIN
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

        # Error Message Sensor
        entities.append(
            RoboVacSensor(
                coordinator,
                "error_message",
                "Error Message",
                lambda s: s.error_message,
                device_class=None,
                unit=None,
                state_class=None,
                icon="mdi:alert-circle-outline",
                category=EntityCategory.DIAGNOSTIC,
            )
        )

        # Task Status Sensor
        entities.append(
            RoboVacSensor(
                coordinator,
                "task_status",
                "Task Status",
                lambda s: s.task_status,
                device_class=None,
                unit=None,
                state_class=None,
                icon="mdi:robot-vacuum",
                category=EntityCategory.DIAGNOSTIC,
            )
        )

        # Cleaning Time Sensor
        entities.append(
            RoboVacSensor(
                coordinator,
                "cleaning_time",
                "Cleaning Time",
                lambda s: s.cleaning_time,
                device_class=SensorDeviceClass.DURATION,
                unit="s",
                state_class=SensorStateClass.MEASUREMENT,
                icon="mdi:clock-outline",
                availability_fn=lambda s: "cleaning_stats" in s.received_fields,
            )
        )

        # Cleaning Area Sensor
        entities.append(
            RoboVacSensor(
                coordinator,
                "cleaning_area",
                "Cleaning Area",
                lambda s: s.cleaning_area,
                device_class=None,
                unit="m²",
                state_class=SensorStateClass.MEASUREMENT,
                icon="mdi:floor-plan",
                availability_fn=lambda s: "cleaning_stats" in s.received_fields,
            )
        )

        # Water level sensor (Station Clean Water)
        # Uses availability_fn to hide sensor on devices that don't report water level
        entities.append(
            RoboVacSensor(
                coordinator,
                "water_level",
                "Water Level",
                lambda s: s.station_clean_water,
                device_class=None,
                unit=PERCENTAGE,
                state_class=SensorStateClass.MEASUREMENT,
                availability_fn=lambda s: "station_clean_water" in s.received_fields,
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
                availability_fn=lambda s: "dock_status" in s.received_fields,
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
                availability_fn=lambda s: "map_id" in s.received_fields,
            )
        )

        # Accessory Sensors
        accessories = [
            ("filter_usage", "Filter Remaining", "mdi:air-filter"),
            ("main_brush_usage", "Rolling Brush Remaining", "mdi:broom"),
            ("side_brush_usage", "Side Brush Remaining", "mdi:broom"),
            ("sensor_usage", "Sensor Remaining", "mdi:eye-outline"),
            ("scrape_usage", "Cleaning Tray Remaining", "mdi:wiper"),
            ("mop_usage", "Mopping Cloth Remaining", "mdi:water"),
        ]

        for attr, name, icon in accessories:
            # We must capture the specific attr value in the lambda default args
            # otherwise all lambdas will point to the last attr in the loop
            def get_accessory_remaining(state: VacuumState, a: str = attr) -> int:
                usage = getattr(state.accessories, a) or 0
                max_life = ACCESSORY_MAX_LIFE.get(a, 0)
                # Ensure we don't go negative if usage exceeds defaults
                return max(0, max_life - usage)

            max_life_val = ACCESSORY_MAX_LIFE.get(attr, 0)

            # Extra attributes explicitly using specific attr
            def get_attributes(
                state: VacuumState, a: str = attr, m: int = max_life_val
            ) -> dict[str, Any]:
                usage = getattr(state.accessories, a) or 0
                return {
                    "usage_hours": usage,
                    "total_life_hours": m,
                }

            entities.append(
                RoboVacSensor(
                    coordinator,
                    attr.replace("_usage", "_remaining"),
                    name,
                    get_accessory_remaining,
                    device_class=SensorDeviceClass.DURATION,
                    unit="h",  # Hours
                    state_class=SensorStateClass.MEASUREMENT,
                    icon=icon,
                    category=EntityCategory.DIAGNOSTIC,
                    extra_state_attributes_fn=get_attributes,
                    availability_fn=lambda s: "accessories" in s.received_fields,
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
        extra_state_attributes_fn: (
            Callable[[VacuumState], dict[str, Any]] | None
        ) = None,
        availability_fn: Callable[[VacuumState], bool] | None = None,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._value_fn = value_fn
        self._extra_attrs_fn = extra_state_attributes_fn
        self._availability_fn = availability_fn
        self._attr_unique_id = f"{coordinator.device_id}_{id_suffix}"

        # Use Home Assistant standard naming
        # This will prefix the device name to the entity name if the
        # device name is not in the entity name
        # Result: sensor.robovac_water_level (Safer, avoids collisions)
        self._attr_has_entity_name = True
        self._attr_name = name_suffix

        self._attr_device_info = coordinator.device_info

        self._attr_native_unit_of_measurement = unit
        self._attr_device_class = device_class
        self._attr_state_class = state_class
        self._attr_entity_category = category
        if icon:
            self._attr_icon = icon

    @property
    def available(self) -> bool:
        """Return True if entity is available.

        Checks coordinator availability and optional custom availability function.
        """
        if not super().available:
            return False
        if self._availability_fn is not None:
            return self._availability_fn(self.coordinator.data)
        return True

    @property
    def native_value(self) -> Any:
        """Return the state of the sensor."""
        return self._value_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return entity specific state attributes."""
        if self._extra_attrs_fn:
            return self._extra_attrs_fn(self.coordinator.data)
        return None
