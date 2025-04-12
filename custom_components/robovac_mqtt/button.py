import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.helpers.entity import DeviceInfo
from .constants.hass import DOMAIN, DEVICES
from .EufyClean import EufyClean

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass, config_entry, async_add_entities):
    for device_id, device in hass.data[DOMAIN][DEVICES].items():
        _LOGGER.info("Adding button %s", device_id)
        entity = RoboVacButton(device)
        async_add_entities([entity])

class RoboVacButton(ButtonEntity):
    def __init__(self, device):
        self.vacuum = device
        self._attr_name = "Dry mop"
        self._attr_unique_id = device.device_id + "_dry_mop"
        self._attr_name = device.device_model_desc
        self._attr_model_code = device.device_model
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device.device_id)},
            name=self._attr_name,
            manufacturer="Eufy",
            model=self._attr_model_code,
        )

    async def async_press(self):
        await self.vacuum.go_dry()