from __future__ import annotations

import logging
import random
import string

import aiohttp

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api.cloud import EufyLogin, EufyLoginError
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
    session = async_get_clientsession(hass)
    eufy_login = EufyLogin(username, password, openudid, websession=session)
    try:
        await eufy_login.init()
    except EufyLoginError as e:
        raise ConfigEntryAuthFailed(f"Invalid Eufy credentials: {e}") from e
    except (aiohttp.ClientError, TimeoutError, OSError) as e:
        raise ConfigEntryNotReady(f"Cannot reach Eufy servers: {e}") from e
    except Exception as e:
        raise ConfigEntryNotReady(f"Unexpected setup error: {e}") from e

    coordinators = []

    # Get Devices and create coordinators
    # eufy_login.mqtt_devices populated by init/getDevices
    # eufy_login.cloud_devices populated by init/getCloudDevices (Tuya Cloud)
    all_devices = eufy_login.mqtt_devices + eufy_login.cloud_devices
    is_multi_device = len(all_devices) > 1
    _LOGGER.debug(
        "Device discovery complete: %d MQTT + %d cloud = %d total",
        len(eufy_login.mqtt_devices),
        len(eufy_login.cloud_devices),
        len(all_devices),
    )

    for device_info in all_devices:
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

            # Migrate segments from config entry data to per-device Store.
            # Only migrate if the store is empty and we have a single device
            # to avoid overwriting newer data or assigning to wrong device.
            if last_seen := entry.data.get("last_seen_segments"):
                if is_multi_device:
                    _LOGGER.info("Skipping migration of last seen segments for %s due to multi-device setup", device_id)
                elif not coordinator.last_seen_segments:
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

    # Check for orphaned devices and log warnings
    current_device_ids = {c.device_id for c in coordinators}
    device_registry = dr.async_get(hass)
    devices = dr.async_entries_for_config_entry(device_registry, entry.entry_id)

    for device_entry in devices:
        # Extract our domain's device ID from identifiers set
        eufy_id = next(
            (id[1] for id in device_entry.identifiers if id[0] == DOMAIN), None
        )

        if eufy_id and eufy_id not in current_device_ids:
            _LOGGER.warning(
                "Device %s (%s) is registered but was not returned by the Eufy API. "
                "It will be shown as unavailable. You can manually remove it if it was deleted from your account.",
                device_entry.name_by_user or device_entry.name,
                eufy_id,
            )

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {"coordinators": coordinators}

    # Clean up migrated data from config entry (skip for multi-device to avoid
    # deleting data that was intentionally not migrated)
    if "last_seen_segments" in entry.data and not is_multi_device:
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
                coordinator.async_shutdown_timers()
                if coordinator.client:
                    await coordinator.client.disconnect()

        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok


async def async_remove_config_entry_device(
    hass: HomeAssistant, config_entry: ConfigEntry, device_entry: dr.DeviceEntry
) -> bool:
    """Remove a config entry device."""
    return True


async def update_listener(hass: HomeAssistant, entry: ConfigEntry):
    await hass.config_entries.async_reload(entry.entry_id)
