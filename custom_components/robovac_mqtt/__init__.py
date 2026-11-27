from __future__ import annotations

import hashlib
import logging
import secrets
from collections.abc import Callable
from pathlib import Path
from typing import Any

import aiohttp
from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.setup import async_when_setup

from .api.cloud import EufyLogin, EufyLoginError
from .api.mega_http import (
    CONF_COUNTRY_CODE,
    CONF_MEGA_SESSION,
    CONF_OPENUDID,
    DEFAULT_COUNTRY_CODE,
    MegaCaptchaRequiredError,
    MegaSessionExpiredError,
    MegaTwoFactorRequiredError,
)
from .const import (
    CONF_LOCAL_DEVICES,
    CONF_LOCAL_HOST,
    CONF_LOCAL_VERSION,
    CONF_MAP_ID,
    CONF_MAP_IDS,
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
_CARD_FILENAME = "eufy-clean-card.js"
_CARD_URL_PATH = f"/{DOMAIN}/{_CARD_FILENAME}"


async def _async_register_frontend_card(hass: HomeAssistant) -> None:
    """Serve and register the bundled Eufy Clean Lovelace card (once)."""
    domain_data = hass.data.setdefault(DOMAIN, {})
    if domain_data.get("card_registered"):
        return

    card = await hass.async_add_executor_job((_FRONTEND_DIR / _CARD_FILENAME).read_bytes)
    card_url = f"{_CARD_URL_PATH}?v={hashlib.sha256(card).hexdigest()[:12]}"

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
    except Exception:  # noqa: BLE001
        _LOGGER.warning(
            "Could not register the bundled Eufy Clean card; skipping", exc_info=True
        )
        return

    domain_data["card_registered"] = True
    _LOGGER.debug("Registered bundled Eufy Clean card at %s", card_url)


async def _register_card_when_frontend_ready(
    hass: HomeAssistant, _component: str
) -> None:
    await _async_register_frontend_card(hass)


def _int_keyed(
    raw: dict, convert: Callable[[Any], Any], device_id: str, what: str
) -> dict[int, Any]:
    coerced: dict[int, Any] = {}
    for raw_key, raw_value in raw.items():
        try:
            coerced[int(raw_key)] = convert(raw_value)
        except (TypeError, ValueError):
            _LOGGER.warning(
                "Device %s: ignoring non-integer %s %r", device_id, what, raw_key
            )
    return coerced


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Initialize the integration."""
    async_when_setup(hass, "frontend", _register_card_when_frontend_ready)

    username = entry.data[CONF_USERNAME]
    password = entry.data[CONF_PASSWORD]
    country_code = entry.data.get(
        CONF_COUNTRY_CODE, hass.config.country or DEFAULT_COUNTRY_CODE
    )
    mega_session = entry.data.get(CONF_MEGA_SESSION)

    # Persist a stable openudid per entry so the v6 auth token stays bound across restarts.
    openudid = entry.data.get(CONF_OPENUDID) or (
        mega_session.get("openudid") if isinstance(mega_session, dict) else None
    )
    if not openudid:
        openudid = secrets.token_hex(8)
        hass.config_entries.async_update_entry(
            entry,
            data={**entry.data, CONF_OPENUDID: openudid},
        )

    def _on_session_updated(new_session: dict[str, Any]) -> None:
        hass.config_entries.async_update_entry(
            entry,
            data={
                **entry.data,
                CONF_OPENUDID: openudid,
                CONF_COUNTRY_CODE: country_code,
                CONF_MEGA_SESSION: new_session,
            },
        )

    session = async_get_clientsession(hass)
    eufy_login = EufyLogin(
        username,
        password,
        openudid,
        websession=session,
        country_code=country_code,
        mega_session=mega_session,
        on_session_updated=_on_session_updated,
    )
    try:
        await eufy_login.init()
    except (
        EufyLoginError,
        MegaSessionExpiredError,
        MegaCaptchaRequiredError,
        MegaTwoFactorRequiredError,
    ) as e:
        raise ConfigEntryAuthFailed(f"Eufy authentication required: {e}") from e
    except (aiohttp.ClientError, TimeoutError, OSError) as e:
        raise ConfigEntryNotReady(f"Cannot reach Eufy servers: {e}") from e
    except Exception as e:
        raise ConfigEntryNotReady(f"Unexpected setup error: {e}") from e

    coordinators = []

    all_devices = eufy_login.mqtt_devices + eufy_login.cloud_devices
    is_multi_device = len(all_devices) > 1
    _LOGGER.debug(
        "Device discovery complete: %d MQTT + %d cloud = %d total",
        len(eufy_login.mqtt_devices),
        len(eufy_login.cloud_devices),
        len(all_devices),
    )

    local_overrides: dict[str, dict] = entry.options.get(CONF_LOCAL_DEVICES, {})

    for device_info in all_devices:
        device_id = device_info.get("deviceId")
        if not device_id:
            continue
        if override := local_overrides.get(device_id):
            extras: dict[str, Any] = {}
            host = (override.get(CONF_LOCAL_HOST) or "").strip()
            if host and device_info.get("local_key"):
                extras["connection_type"] = "local"
                extras["local_host"] = host
                extras["local_version"] = override.get(CONF_LOCAL_VERSION, 3.3)
            if room_overrides := override.get(CONF_ROOM_NAMES):
                coerced = _int_keyed(room_overrides, str, device_id, "room id")
                if coerced:
                    extras["room_name_overrides"] = coerced
            if (map_override := override.get(CONF_MAP_ID)) is not None:
                try:
                    extras["map_id_override"] = int(map_override)
                except (TypeError, ValueError):
                    _LOGGER.warning(
                        "Device %s: ignoring non-integer map id %r",
                        device_id,
                        map_override,
                    )
            if map_overrides := override.get(CONF_MAP_IDS):
                per_map = _int_keyed(map_overrides, int, device_id, "map id")
                if per_map:
                    extras["map_id_overrides"] = per_map
            if extras:
                device_info = {**device_info, **extras}

        coordinator = EufyCleanCoordinator(
            hass, eufy_login, device_info, config_entry=entry
        )
        try:
            await coordinator.initialize()

            if last_seen := entry.data.get("last_seen_segments"):
                if not is_multi_device and not coordinator.last_seen_segments:
                    await coordinator.async_save_segments(last_seen)

            coordinators.append(coordinator)
        except Exception as e:  # noqa: BLE001
            _LOGGER.warning(
                "Failed to initialize coordinator for %s: %s", device_id, e
            )

    if not coordinators:
        raise ConfigEntryNotReady("No Eufy Clean devices could be initialized")

    current_device_ids = {c.device_id for c in coordinators}
    device_registry = dr.async_get(hass)
    registry_devices = dr.async_entries_for_config_entry(
        device_registry, entry.entry_id
    )

    for device_entry in registry_devices:
        eufy_id = next(
            (ident[1] for ident in device_entry.identifiers if ident[0] == DOMAIN),
            None,
        )
        if eufy_id and eufy_id not in current_device_ids:
            _LOGGER.warning(
                "Device %s (%s) is registered but was not returned by the Eufy API.",
                device_entry.name_by_user or device_entry.name,
                eufy_id,
            )

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {"coordinators": coordinators}

    if "last_seen_segments" in entry.data and not is_multi_device:
        new_data = dict(entry.data)
        new_data.pop("last_seen_segments")
        hass.config_entries.async_update_entry(entry, data=new_data)

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
                await coordinator.async_stop_p2p()
                if coordinator.client:
                    await coordinator.client.disconnect()

        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok


async def async_remove_config_entry_device(
    hass: HomeAssistant, config_entry: ConfigEntry, device_entry: dr.DeviceEntry
) -> bool:
    """Remove a config entry device."""
    return True
