from __future__ import annotations

import hashlib
import logging
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

import aiohttp
from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONF_PASSWORD,
    CONF_USERNAME,
    EVENT_HOMEASSISTANT_STOP,
    Platform,
)
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.typing import ConfigType
from homeassistant.loader import async_get_integration
from homeassistant.setup import async_when_setup

from .api.cloud import (
    EufyLogin,
    EufyLoginChallengeError,
    EufyLoginError,
    EufyLoginRateLimitedError,
    EufyLoginTransientError,
    EufySessionReplacedError,
)
from .auth_store import AuthStore
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
from .vacuum import segments_issue_id
from .websocket_api import async_setup as async_setup_websocket_api

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
    Platform.UPDATE,
]
_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

_FRONTEND_DIR = Path(__file__).parent / "frontend"
# Also defines the pre-rename `zone-clean-card` alias for older dashboards.
_CARD_FILENAME = "eufy-clean-card.js"
_CARD_URL_PATH = f"/{DOMAIN}/{_CARD_FILENAME}"
# Imported by the card, which resolves it relative to its own module URL, so it
# must be served from the same URL directory.
_RENDERER_FILENAME = "eufy-map-renderer.js"
_RENDERER_URL_PATH = f"/{DOMAIN}/{_RENDERER_FILENAME}"


def _card_cache_key(paths: list[Path], fallback: str) -> str:
    """Short content hash over EVERY frontend file, for the ``?v=`` cache-bust.

    Hashes the whole bundle: the card propagates its own query string to the renderer
    it imports, so a card-only hash would leave a renderer-only edit uncached-busted.
    Blocking file I/O — call via ``async_add_executor_job``.
    """
    digest = hashlib.sha256()
    for path in sorted(paths):
        try:
            digest.update(path.read_bytes())
        except OSError:
            return str(fallback)
        digest.update(b"\0")
    return f"{fallback}-{digest.hexdigest()[:12]}"


async def _async_register_frontend_card(hass: HomeAssistant) -> None:
    """Serve and register the bundled Eufy Clean Lovelace card (once)."""
    domain_data = hass.data.setdefault(DOMAIN, {})
    if domain_data.get("card_registered"):
        return

    integration = await async_get_integration(hass, DOMAIN)
    # ?v= hashes the frontend bytes, not the manifest version, which can drift from
    # the shipped file and pin stale content. Falls back to the version on error.
    card_version = await hass.async_add_executor_job(
        _card_cache_key,
        [_FRONTEND_DIR / _CARD_FILENAME, _FRONTEND_DIR / _RENDERER_FILENAME],
        integration.version,
    )
    card_url = f"{_CARD_URL_PATH}?v={card_version}"

    # No hard `frontend` dependency (headless installs), so the optional card must
    # never fail setup.
    try:
        await hass.http.async_register_static_paths(
            [
                StaticPathConfig(
                    _CARD_URL_PATH,
                    str(_FRONTEND_DIR / _CARD_FILENAME),
                    cache_headers=False,
                ),
                # Not in add_extra_js_url: the card imports it on demand.
                StaticPathConfig(
                    _RENDERER_URL_PATH,
                    str(_FRONTEND_DIR / _RENDERER_FILENAME),
                    cache_headers=False,
                ),
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
    """Register the card now that frontend is up (``async_when_setup`` callback)."""
    await _async_register_frontend_card(hass)


def _int_keyed(
    raw: dict, convert: Callable[[Any], Any], device_name: str, what: str
) -> dict[int, Any]:
    """Coerce a stored override dict back to int keys.

    JSON storage stringifies int keys; coerce them back for correct sort order
    and so downstream protobuf builders get the right type. Entries that don't
    convert are logged and dropped.
    """
    coerced: dict[int, Any] = {}
    for raw_key, raw_value in raw.items():
        try:
            coerced[int(raw_key)] = convert(raw_value)
        except (TypeError, ValueError):
            _LOGGER.warning(
                "%s: ignoring non-integer %s %r", device_name, what, raw_key
            )
    return coerced


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the global, entry-independent parts once per HA run."""
    # Deferred: registering before `frontend` is up silently no-ops.
    async_when_setup(hass, "frontend", _register_card_when_frontend_ready)
    # Websocket command names are global; registering one twice raises.
    async_setup_websocket_api(hass)
    return True


def _session_replaced_issue_id(entry_id: str) -> str:
    """Repair issue id for an entry whose session another client keeps ending."""
    return f"session_replaced_{entry_id}"


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Delete this entry's cached credentials (bearer tokens, X.509 private key)
    and its repair issues."""
    await AuthStore(hass, entry.entry_id).async_remove()
    ir.async_delete_issue(hass, DOMAIN, _session_replaced_issue_id(entry.entry_id))
    # Runs before HA detaches the entry's devices.
    for device_entry in dr.async_entries_for_config_entry(
        dr.async_get(hass), entry.entry_id
    ):
        for domain, eufy_id in device_entry.identifiers:
            if domain == DOMAIN:
                ir.async_delete_issue(hass, DOMAIN, segments_issue_id(eufy_id))


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Initialize the integration."""
    username = entry.data[CONF_USERNAME]
    password = entry.data[CONF_PASSWORD]

    # The openudid must stay stable across setups or every restart announces a
    # brand-new device to Eufy. See auth_store.py.
    auth_store = AuthStore(hass, entry.entry_id)
    auth_cache = await auth_store.async_load()

    session = async_get_clientsession(hass)
    issue_id = _session_replaced_issue_id(entry.entry_id)
    # Constructed inside the try: it restores the persisted cache, and a corrupt
    # store must degrade to the retried ConfigEntryNotReady, not SETUP_ERROR.
    try:
        eufy_login = EufyLogin(
            username,
            password,
            auth_cache.openudid,
            websession=session,
            auth_cache=auth_cache,
        )
        await eufy_login.init()
    except EufySessionReplacedError as e:
        ir.async_create_issue(
            hass,
            DOMAIN,
            issue_id,
            is_fixable=False,
            severity=ir.IssueSeverity.ERROR,
            translation_key="session_replaced",
            translation_placeholders={"account": username},
        )
        # Reauth is the user's explicit decision to take the session back.
        raise ConfigEntryAuthFailed(str(e)) from e
    except EufyLoginChallengeError as e:
        raise ConfigEntryAuthFailed(
            f"Eufy asks for a verification code or captcha; sign in once in the "
            f"Eufy app, then reauthenticate: {e}"
        ) from e
    except EufyLoginError as e:
        # Bad credentials invalidate every cached token; do not keep serving them.
        auth_cache.clear_tokens()
        raise ConfigEntryAuthFailed(f"Invalid Eufy credentials: {e}") from e
    except EufyLoginRateLimitedError as e:
        raise ConfigEntryNotReady(f"Eufy cloud rate limit: {e}") from e
    except EufyLoginTransientError as e:
        # 5xx or network: the cached tokens may still be good.
        raise ConfigEntryNotReady(f"Eufy servers unavailable: {e}") from e
    except (aiohttp.ClientError, TimeoutError, OSError) as e:
        raise ConfigEntryNotReady(f"Cannot reach Eufy servers: {e}") from e
    except Exception as e:
        raise ConfigEntryNotReady(f"Unexpected setup error: {e}") from e
    finally:
        # Every outcome: the openudid and the login budget and hold-offs for the
        # retry, fresh tokens, and the tokens a rejected cached run cleared.
        await auth_store.async_save(auth_cache)
    ir.async_delete_issue(hass, DOMAIN, issue_id)

    coordinators = []

    all_devices = eufy_login.mqtt_devices + eufy_login.cloud_devices
    is_multi_device = len(all_devices) > 1
    _LOGGER.debug(
        "Device discovery complete: %d MQTT + %d cloud = %d total",
        len(eufy_login.mqtt_devices),
        len(eufy_login.cloud_devices),
        len(all_devices),
    )

    # A LAN address in the options flow promotes a device to direct local-push.
    local_overrides: dict[str, dict] = entry.options.get(CONF_LOCAL_DEVICES, {})
    if local_overrides:
        _LOGGER.debug(
            "Local Tuya overrides configured for %d device(s)", len(local_overrides)
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
                    "%s: using the local Tuya transport",
                    device_info.get("deviceName", "Unknown"),
                )
            device_name = device_info.get("deviceName", "Unknown")
            # Room ID → name overrides apply to any transport.
            if room_overrides := override.get(CONF_ROOM_NAMES):
                coerced = _int_keyed(room_overrides, str, device_name, "room id")
                if coerced:
                    extras["room_name_overrides"] = coerced
                    _LOGGER.info(
                        "%s: using %d manual room name override(s)",
                        device_name, len(coerced),
                    )
            # Manual map-id override for room/zone clean commands (devices
            # that report their cloud map id, which the firmware rejects).
            if (map_override := override.get(CONF_MAP_ID)) is not None:
                try:
                    extras["map_id_override"] = int(map_override)
                    _LOGGER.info(
                        "%s: using manual map id override %d",
                        device_name, extras["map_id_override"],
                    )
                except (TypeError, ValueError):
                    _LOGGER.warning(
                        "%s: ignoring non-integer map id %r",
                        device_name, map_override,
                    )
            # Per-map variant, keyed by the map id the device reports.
            if map_overrides := override.get(CONF_MAP_IDS):
                per_map = _int_keyed(map_overrides, int, device_name, "map id")
                if per_map:
                    extras["map_id_overrides"] = per_map
                    _LOGGER.info(
                        "%s: using %d per-map map id override(s)",
                        device_name, len(per_map),
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

            # Only with an empty store and one device: otherwise this could
            # overwrite newer data or attach it to the wrong device.
            if last_seen := entry.data.get("last_seen_segments"):
                if is_multi_device:
                    _LOGGER.info(
                        "Skipping migration of last seen segments for %s due to multi-device setup",
                        coordinator.device_name,
                    )
                elif not coordinator.last_seen_segments:
                    await coordinator.async_save_segments(last_seen)
                    _LOGGER.info(
                        "Migrated last seen segments for %s to persistent storage",
                        coordinator.device_name,
                    )

            coordinators.append(coordinator)
        except Exception as e:
            _LOGGER.warning(
                "Failed to initialize %s: %s",
                device_info.get("deviceName", "Unknown"),
                e,
            )
            _LOGGER.debug("Failed device id: %s", device_id)
            # initialize() may have written the MQTT cert/key files or started a
            # transport before failing; each setup retry would leak another set.
            await coordinator.async_teardown()

    # A coordinator's checkLogin() may have spent a login or fetched credentials.
    await auth_store.async_save(auth_cache)

    if not coordinators:
        raise ConfigEntryNotReady("No Eufy Clean devices could be initialized")

    _schedule_reload_for_mqtt_credentials(hass, entry, eufy_login)

    current_device_ids = {c.device_id for c in coordinators}
    device_registry = dr.async_get(hass)
    registry_devices = dr.async_entries_for_config_entry(
        device_registry, entry.entry_id
    )

    for device_entry in registry_devices:
        eufy_id = next(
            (id[1] for id in device_entry.identifiers if id[0] == DOMAIN), None
        )

        if eufy_id and eufy_id not in current_device_ids:
            _LOGGER.warning(
                "Device %s is registered but was not returned by the Eufy API. "
                "It will be shown as unavailable. You can manually remove it if it was deleted from your account.",
                device_entry.name_by_user or device_entry.name,
            )
            _LOGGER.debug("Missing device id: %s", eufy_id)

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {"coordinators": coordinators}

    # Skip for multi-device: that data was intentionally not migrated.
    if "last_seen_segments" in entry.data and not is_multi_device:
        new_data = dict(entry.data)
        new_data.pop("last_seen_segments")
        hass.config_entries.async_update_entry(entry, data=new_data)
        _LOGGER.info(
            "Removed legacy last_seen_segments from config entry %s", entry.entry_id
        )

    # After the segment cleanup, whose async_update_entry() would else reload us.
    entry.async_on_unload(entry.add_update_listener(update_listener))

    async def _async_stop(_event: Event) -> None:
        """Close every transport when Home Assistant stops.

        HA does not unload config entries on shutdown, so async_unload_entry never
        runs on this path and the local Tuya listener would keep blocking executor
        threads during teardown.
        """
        for coordinator in coordinators:
            await coordinator.async_teardown()

    entry.async_on_unload(
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, _async_stop)
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


def _schedule_reload_for_mqtt_credentials(
    hass: HomeAssistant, entry: ConfigEntry, eufy_login: EufyLogin
) -> None:
    """Reload the entry once a login is allowed when MQTT robots were left
    without MQTT credentials because logins were refused.

    A fallback-session account never gets MQTT credentials: no reload.
    """
    if (
        eufy_login.mqtt_credentials
        or not eufy_login.mqtt_devices
        or not eufy_login.has_user_center
    ):
        return
    wait = eufy_login.throttle.login_wait()
    if wait is None:
        return
    _LOGGER.info(
        "%d MQTT device(s) wait for MQTT credentials; reloading when a login is "
        "allowed, in %.0f min",
        len(eufy_login.mqtt_devices),
        wait / 60,
    )

    @callback
    def _reload(_now: datetime) -> None:
        hass.config_entries.async_schedule_reload(entry.entry_id)

    entry.async_on_unload(async_call_later(hass, wait, _reload))


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        data = hass.data[DOMAIN].get(entry.entry_id)
        if data and "coordinators" in data:
            for coordinator in data["coordinators"]:
                await coordinator.async_teardown()

        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok


async def async_remove_config_entry_device(
    hass: HomeAssistant, config_entry: ConfigEntry, device_entry: dr.DeviceEntry
) -> bool:
    """Allow removing a device only when the Eufy API no longer returns it."""
    data = hass.data.get(DOMAIN, {}).get(config_entry.entry_id) or {}
    live_ids = {c.device_id for c in data.get("coordinators", [])}
    return not any(
        domain == DOMAIN and eufy_id in live_ids
        for domain, eufy_id in device_entry.identifiers
    )


async def update_listener(hass: HomeAssistant, entry: ConfigEntry):
    await hass.config_entries.async_reload(entry.entry_id)
