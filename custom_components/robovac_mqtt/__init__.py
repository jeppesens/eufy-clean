from __future__ import annotations

import logging
import random
import string
from pathlib import Path

import aiohttp
from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.loader import async_get_integration
from homeassistant.setup import async_when_setup

from .api.cloud import EufyLogin, EufyLoginError
from .const import (
    CONF_LOCAL_DEVICES,
    CONF_LOCAL_HOST,
    CONF_LOCAL_VERSION,
    CONF_ROOM_NAMES,
    DOMAIN,
)
from .coordinator import EufyCleanCoordinator

PLATFORMS: list[Platform] = [
    Platform.VACUUM,
    Platform.BUTTON,
    Platform.SENSOR,
    Platform.SELECT,
    Platform.SWITCH,
    Platform.NUMBER,
    Platform.BINARY_SENSOR,
    Platform.TIME,
    Platform.CAMERA,
]
_LOGGER = logging.getLogger(__name__)

_FRONTEND_DIR = Path(__file__).parent / "frontend"
# Unified room + zone card. Defines both `eufy-clean-card` and the backward-compat
# `zone-clean-card` alias, so older dashboards keep working after the rename.
_CARD_FILENAME = "eufy-clean-card.js"
_CARD_URL_PATH = f"/{DOMAIN}/{_CARD_FILENAME}"


async def _async_register_frontend_card(hass: HomeAssistant) -> None:
    """Serve and register the bundled Eufy Clean Lovelace card (once).

    Shipping the card inside the integration keeps it in lock-step with the
    ``room_clean`` / ``zone_clean`` send_command handlers — a single install
    delivers both, with no manual ``www/`` copy or Lovelace resource entry.
    """
    domain_data = hass.data.setdefault(DOMAIN, {})
    if domain_data.get("card_registered"):
        return

    integration = await async_get_integration(hass, DOMAIN)
    # ?v=<version> busts the browser cache whenever the integration updates.
    card_url = f"{_CARD_URL_PATH}?v={integration.version}"

    # Runs from async_when_setup(hass, "frontend", ...), so frontend is set up and
    # add_extra_js_url's hass.data is in place. We still don't declare a hard
    # `frontend` dependency (headless installs must load without it); the try/except
    # stays as a belt-and-suspenders guard so an optional card can never fail the
    # vacuum integration's setup.
    try:
        await hass.http.async_register_static_paths(
            [
                StaticPathConfig(
                    _CARD_URL_PATH,
                    str(_FRONTEND_DIR / _CARD_FILENAME),
                    cache_headers=False,
                )
            ]
        )
        add_extra_js_url(hass, card_url)
    except Exception:  # frontend not ready; skip the optional card, keep the entry
        _LOGGER.warning(
            "Could not register the bundled Eufy Clean card; skipping", exc_info=True
        )
        return

    domain_data["card_registered"] = True
    _LOGGER.debug("Registered bundled Eufy Clean card at %s", card_url)


async def _register_card_when_frontend_ready(
    hass: HomeAssistant, _component: str
) -> None:
    """``async_when_setup`` callback — register the card now that frontend is up."""
    await _async_register_frontend_card(hass)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Initialize the integration."""
    # NOTE: the options update listener is registered later, AFTER the legacy
    # last_seen_segments cleanup, so the cleanup's async_update_entry() does not
    # trigger a reload mid-setup. (Registering it here too would double-fire.)

    # Register the bundled card once `frontend` is set up. async_when_setup fires
    # immediately if it already is, else when it finishes — so the card registers
    # regardless of integration load order. Calling _async_register_frontend_card
    # directly here silently no-ops when this entry loads before frontend (the
    # add_extra_js_url hass.data isn't there yet), which is why the card was missing
    # on some installs (issue #140).
    async_when_setup(hass, "frontend", _register_card_when_frontend_ready)

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

    # Per-device local-Tuya overrides from options. The user enters the LAN
    # address of each dock through the integration's options flow; we promote
    # such devices from cloud-polled to direct local-push.
    local_overrides: dict[str, dict] = entry.options.get(CONF_LOCAL_DEVICES, {})
    if local_overrides:
        _LOGGER.debug(
            "Local Tuya overrides configured for: %s",
            list(local_overrides.keys()),
        )

    for device_info in all_devices:
        device_id = device_info.get("deviceId")
        if not device_id:
            continue
        if override := local_overrides.get(device_id):
            extras: dict = {}
            host = (override.get(CONF_LOCAL_HOST) or "").strip()
            if host and device_info.get("local_key"):
                extras["connection_type"] = "local"
                extras["local_host"] = host
                extras["local_version"] = override.get(CONF_LOCAL_VERSION, 3.3)
                _LOGGER.info(
                    "Device %s promoted to local Tuya (host=%s)", device_id, host
                )
            # Room ID → name overrides apply to any transport.
            # JSON storage stringifies int keys, so coerce back to int for
            # correct sort order and so downstream protobuf builders get the
            # right type.
            if room_overrides := override.get(CONF_ROOM_NAMES):
                coerced: dict[int, str] = {}
                for raw_id, name in room_overrides.items():
                    try:
                        coerced[int(raw_id)] = str(name)
                    except (TypeError, ValueError):
                        _LOGGER.warning(
                            "Device %s: ignoring non-integer room id %r",
                            device_id, raw_id,
                        )
                if coerced:
                    extras["room_name_overrides"] = coerced
                    _LOGGER.info(
                        "Device %s using %d manual room name override(s)",
                        device_id, len(coerced),
                    )
            if extras:
                device_info = {**device_info, **extras}

        _LOGGER.debug(
            "Found device: %s (%s)",
            device_info.get("deviceName", "Unknown"),
            device_id,
        )

        coordinator = EufyCleanCoordinator(hass, eufy_login, device_info, config_entry=entry)
        try:
            await coordinator.initialize()

            # Migrate segments from config entry data to per-device Store.
            # Only migrate if the store is empty and we have a single device
            # to avoid overwriting newer data or assigning to wrong device.
            if last_seen := entry.data.get("last_seen_segments"):
                if is_multi_device:
                    _LOGGER.info(
                        "Skipping migration of last seen segments for %s due to multi-device setup",
                        device_id,
                    )
                elif not coordinator.last_seen_segments:
                    await coordinator.async_save_segments(last_seen)
                    _LOGGER.info(
                        "Migrated last seen segments for %s to persistent storage",
                        device_id,
                    )

            coordinators.append(coordinator)
        except Exception as e:
            _LOGGER.warning("Failed to initialize coordinator for %s: %s", device_id, e)

    if not coordinators:
        raise ConfigEntryNotReady("No Eufy Clean devices could be initialized")

    # Check for orphaned devices and log warnings
    current_device_ids = {c.device_id for c in coordinators}
    device_registry = dr.async_get(hass)
    registry_devices = dr.async_entries_for_config_entry(
        device_registry, entry.entry_id
    )

    for device_entry in registry_devices:
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
        _LOGGER.info(
            "Removed legacy last_seen_segments from config entry %s", entry.entry_id
        )

    # Register update listener AFTER segment cleanup to avoid triggering
    # a reload from async_update_entry during setup
    entry.async_on_unload(entry.add_update_listener(update_listener))

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
