from __future__ import annotations

import logging

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, EntityCategory
from homeassistant.helpers.entity import DeviceInfo

from .const import DEVICES, DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, config_entry, async_add_entities):
    for device_id, device in hass.data[DOMAIN][DEVICES].items():
        _LOGGER.info("Adding sensors for %s", device_id)

        # Battery sensor
        battery = RoboVacSensor(
            device,
            "battery",
            "_battery",
            getter_name="get_battery_level",
            device_class=SensorDeviceClass.BATTERY,
            unit=PERCENTAGE,
            state_class=SensorStateClass.MEASUREMENT,
        )

        # Water level sensor
        water = RoboVacSensor(
            device,
            "water_level",
            "_water",
            getter_name="get_water_level",
            device_class=None,  # no standard device class for water level %
            unit=PERCENTAGE,
            state_class=SensorStateClass.MEASUREMENT,
        )

        # dock status sensor
        dock_status = RoboVacSensor(
            device,
            "dock_status",
            "_dock_status",
            getter_name="get_dock_status",
            device_class=None,  # no standard device class for dock status
            unit=None,
            state_class=None,
        )

        # Active map ID sensor
        active_map = RoboVacSensor(
            device,
            "active_map",
            "_active_map",
            getter_name="get_active_map_id",
            device_class=None,
            unit=None,
            state_class=None,
        )
        active_map._attr_icon = "mdi:map-marker-path"

        async_add_entities([battery, water, dock_status, active_map])


class RoboVacSensor(SensorEntity):
    def __init__(
        self,
        device,
        name,
        unique_suffix,
        getter_name: str,
        device_class=None,
        unit=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
    ):
        super().__init__()
        self.vacuum = device
        self._attr_name = name
        self._attr_unique_id = f"{device.device_id}{unique_suffix}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device.device_id)},
            name=device.device_model_desc,
            manufacturer="Eufy",
            model=device.device_model,
        )
        # initialize native value to None; will be populated asynchronously
        self._attr_native_value = None
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._attr_native_unit_of_measurement = unit
        self._attr_device_class = device_class
        self._attr_state_class = state_class

        # ensure HA doesn't try to poll this entity; we push updates via listeners
        self._attr_should_poll = False

        self._getter_name = getter_name

    async def _handle_update(self) -> None:
        """Called by SharedConnect when new data arrives."""
        _LOGGER.debug("Listener called for %s", self._attr_unique_id)
        try:
            await self.async_update()
            _LOGGER.debug(
                "Updated value for %s -> %s",
                self._attr_unique_id,
                self._attr_native_value,
            )
            self.async_write_ha_state()
        except Exception:
            _LOGGER.exception("Error handling update for %s", self._attr_unique_id)

    async def async_added_to_hass(self):
        # fetch initial value when entity is added
        await self.async_update()
        self.async_write_ha_state()

        # register for push updates from the device controller
        try:
            self.vacuum.add_listener(self._handle_update)
        except Exception:
            _LOGGER.exception(
                "Failed to add update listener for %s", self._attr_unique_id
            )

    async def async_will_remove_from_hass(self):
        # try to remove listener when entity is removed
        try:
            if hasattr(self.vacuum, "_update_listeners"):
                try:
                    self.vacuum._update_listeners.remove(self._handle_update)
                except ValueError:
                    pass
        except Exception:
            _LOGGER.exception(
                "Failed to remove update listener for %s", self._attr_unique_id
            )

    async def async_update(self):
        getter = getattr(self.vacuum, self._getter_name, None)
        if getter is None or not callable(getter):
            _LOGGER.warning(
                "Getter %s not found for device %s",
                self._getter_name,
                getattr(self.vacuum, "device_id", "unknown"),
            )
            return

        try:
            value = await getter()
            _LOGGER.debug(
                "Getter %s returned %r for %s",
                self._getter_name,
                value,
                self._attr_unique_id,
            )
        except Exception:
            _LOGGER.exception(
                "Failed to update %s for %s",
                self._getter_name,
                getattr(self.vacuum, "device_id", "unknown"),
            )
            return

        # Only update entity state when getter returns a real value.
        # If getter returns None (unknown / not present), preserve last known value.
        if value is not None:
            self._attr_native_value = value
        else:
            _LOGGER.debug(
                "Getter %s returned None for %s — keeping last known value %r",
                self._getter_name,
                self._attr_unique_id,
                self._attr_native_value,
            )
