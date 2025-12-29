import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.helpers.entity import DeviceInfo
from .constants.hass import DOMAIN, DEVICES

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass, config_entry, async_add_entities):
    for device_id, device in hass.data[DOMAIN][DEVICES].items():
        _LOGGER.info("Adding buttons for %s", device_id)

        # Dry mop button
        dry_mop_button = RoboVacButton(device, "Dry mop", "_dry_mop", device.go_dry)
        # Clean mop button
        clean_mop_button = RoboVacButton(device, "Wash mop", "_wash_mop", device.go_selfcleaning)
        # Empty dust bin button
        collect_dust_button = RoboVacButton(device, "Empty dust bin", "_empty_dust_bin", device.collect_dust)
        # Stop mop dry button
        stop_dry_mop_button = RoboVacButton(device, "Stop dry mop", "_stop_dry_mop", device.stop_dry_mop)
        async_add_entities([dry_mop_button, clean_mop_button, collect_dust_button, stop_dry_mop_button])


class RoboVacButton(ButtonEntity):
    def __init__(self, device, name, unique_suffix, action):
        self.vacuum = device
        self._attr_name = name
        self._attr_unique_id = device.device_id + unique_suffix
        self._action = action
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device.device_id)},
            name=device.device_model_desc,
            manufacturer="Eufy",
            model=device.device_model,
        )

    async def async_press(self):
        await self._action()