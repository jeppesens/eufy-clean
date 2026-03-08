from __future__ import annotations

import logging
import random
import string

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant

from .api.cloud import EufyLogin
from .const import DOMAIN
from .coordinator import EufyCleanCoordinator

PLATFORMS: list[Platform] = [
    Platform.VACUUM,
    Platform.BUTTON,
    Platform.SENSOR,
    Platform.SELECT,
    Platform.SWITCH,
    Platform.NUMBER,
    Platform.BINARY_SENSOR,
]
_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Initialize the integration."""
    entry.async_on_unload(entry.add_update_listener(update_listener))

    username = entry.data[CONF_USERNAME]
    password = entry.data[CONF_PASSWORD]

    # Generate OpenUDID (consistent per session)
    openudid = "".join(random.choices(string.hexdigits, k=32))

    # Initialize Login Controller
    eufy_login = EufyLogin(username, password, openudid)
    try:
        await eufy_login.init()
    except Exception as e:
        _LOGGER.error("Failed to login to Eufy Clean: %s", e)
        return False

    coordinators = []

    # Get Devices and create coordinators
    # eufy_login.mqtt_devices populated by init/getDevices
    # mqtt_devices is a list of dicts with device info
    for device_info in eufy_login.mqtt_devices:
        device_id = device_info.get("deviceId")
        if not device_id:
            continue

        _LOGGER.debug(
            "Found device: %s (%s)",
            device_info.get("deviceName", "Unknown"),
            device_id,
        )

        coordinator = EufyCleanCoordinator(hass, eufy_login, device_info)
        try:
            await coordinator.initialize()
            
            # Migrate segments from config entry data to storage
            if last_seen := entry.data.get("last_seen_segments"):
                # last_seen in config entry was per-entry, but now it's per-device Store.
                # However, our current schema in ConfigEntry had it top-level?
                # Actually, vacuum.py was using self._config_entry.data.get(_LAST_SEEN_SEGMENTS_KEY)
                # which means it was shared across all devices in the same entry if not careful.
                # But typically there is one entry per user, containing multiple devices.
                # Since we are now using per-device store, we should check if this specific device
                # has its segments here. If the old implementation stored them for ALL devices
                # in one key, it was likely a bug or only worked for single-device setups.
                # Let's assume the old way was a bit broken for multi-device and we just try to 
                # migrate what we have if it matches the current device's segments.
                # Actually, looking at old code, it just did entry.data.set(key, serialized).
                # This would overwrite for each device if they shared an entry.
                
                # To be safe, we only migrate if the store is empty.
                if not coordinator.last_seen_segments:
                    await coordinator.async_save_segments(last_seen)
                    _LOGGER.info("Migrated last seen segments for %s to persistent storage", device_id)
            
            coordinators.append(coordinator)
        except Exception as e:
            _LOGGER.warning("Failed to initialize coordinator for %s: %s", device_id, e)

    if not coordinators:
        _LOGGER.warning("No Eufy Clean devices found or initialized.")
        # We generally return True anyway to avoid blocking HA startup,
        # unless critical failure?
        # But if no devices, nothing to do.

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {"coordinators": coordinators}

    # Clean up migrated data from config entry
    if "last_seen_segments" in entry.data:
        new_data = dict(entry.data)
        new_data.pop("last_seen_segments")
        hass.config_entries.async_update_entry(entry, data=new_data)
        _LOGGER.info("Removed legacy last_seen_segments from config entry %s", entry.entry_id)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        data = hass.data[DOMAIN].get(entry.entry_id)
        if data and "coordinators" in data:
            for coordinator in data["coordinators"]:
                # Disconnect client
                if coordinator.client:
                    await coordinator.client.disconnect()
                    # Need to ensure disconnect exists or implement it

        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok


async def update_listener(hass: HomeAssistant, entry: ConfigEntry):
    await hass.config_entries.async_reload(entry.entry_id)
