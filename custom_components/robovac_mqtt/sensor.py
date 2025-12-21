import logging

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.const import (PERCENTAGE, EntityCategory)
from .constants.hass import DOMAIN, DEVICES
from .EufyClean import EufyClean

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass, config_entry, async_add_entities):
    for device_id, device in hass.data[DOMAIN][DEVICES].items():
        _LOGGER.info("Adding sensors for %s", device_id)

        # Dry mop button
        battery = RoboVacSensor(device, "battery", "_battery")
        async_add_entities([battery])

class RoboVacSensor(SensorEntity):
    def __init__(self, device, name, unique_suffix):
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
        self._attr_native_unit_of_measurement = PERCENTAGE
        self._attr_device_class = SensorDeviceClass.BATTERY
        self._attr_state_class = SensorStateClass.MEASUREMENT

    async def async_added_to_hass(self):
        # fetch initial value when entity is added
        await self.async_update()
        self.async_write_ha_state()

    async def async_update(self):
        try:
            battery = await self.vacuum.get_battery_level()
        except Exception:  # keep minimal; log for debugging
            _LOGGER.exception("Failed to update battery level for %s", self.vacuum.device_id)
            return
        self._attr_native_value = battery
