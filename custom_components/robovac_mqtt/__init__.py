from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.typing import ConfigType

from .const import DEVICES, DOMAIN, VACS
from .EufyClean import EufyClean

PLATFORMS: list[Platform] = [
    Platform.VACUUM,
    Platform.BUTTON,
    Platform.SENSOR,
    Platform.SELECT,
    Platform.NUMBER,
    Platform.SWITCH,
]
_LOGGER = logging.getLogger(__name__)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    hass.data.setdefault(DOMAIN, {VACS: {}, DEVICES: {}})
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    entry.async_on_unload(entry.add_update_listener(update_listener))

    # Init EufyClean
    username = entry.data[CONF_USERNAME]
    password = entry.data[CONF_PASSWORD]
    eufy_clean = EufyClean(username, password)
    await eufy_clean.init()

    # Load devices
    for vacuum in await eufy_clean.get_devices():
        device = await eufy_clean.init_device(vacuum["deviceId"])
        await device.connect()
        _LOGGER.info("Adding %s", device.device_id)
        hass.data[DOMAIN][DEVICES][device.device_id] = device

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def update_listener(hass: HomeAssistant, entry: ConfigEntry):
    await hass.config_entries.async_reload(entry.entry_id)
