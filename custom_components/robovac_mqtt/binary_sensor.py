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

from .const import DOMAIN, WORK_STATE_REMOTE_CTRL
from .coordinator import EufyCleanCoordinator, VacuumState

_LOGGER = logging.getLogger(__name__)


PARALLEL_UPDATES = 0


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

        if coordinator.api_type == "novel":
            # Read-only: the camera is armed on the robot itself by holding
            # Start/Pause + Recharge for 10 s, never over the network.
            entities.append(
                RoboVacBinarySensor(
                    coordinator,
                    "camera_enabled",
                    "Camera Enabled",
                    lambda s: bool(s.camera_enabled),
                    availability_fn=lambda s: "camera_enabled" in s.received_fields,
                )
            )

            # On while the robot is under manual control; the dashboard's drive
            # pad is only useful (and only shown) then.
            entities.append(
                RoboVacBinarySensor(
                    coordinator,
                    "remote_mode",
                    "Remote Mode",
                    lambda s: s.status_code == WORK_STATE_REMOTE_CTRL,
                    category=None,
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
        availability_fn: Callable[[VacuumState], bool] | None = None,
    ) -> None:
        """Initialize the binary sensor."""
        super().__init__(coordinator)
        self._value_fn = value_fn
        self._availability_fn = availability_fn
        self._attr_unique_id = f"{coordinator.device_id}_{id_suffix}"
        self._attr_has_entity_name = True
        self._attr_name = name_suffix
        self._attr_device_info = coordinator.device_info
        self._attr_device_class = device_class
        self._attr_entity_category = category

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        if not super().available:
            return False
        if self._availability_fn is not None:
            return self._availability_fn(self.coordinator.data)
        return True

    @property
    def is_on(self) -> bool | None:
        """Return true if the binary sensor is on."""
        return self._value_fn(self.coordinator.data)
