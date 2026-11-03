from __future__ import annotations

import ipaddress
import logging
import math
import re
from typing import Any

import aiohttp
import homeassistant.helpers.config_validation as cv
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from voluptuous import In
from voluptuous import Optional as VOptional
from voluptuous import Required, Schema

from .api.cloud import (
    EufyLogin,
    EufyLoginChallengeError,
    EufyLoginError,
    EufyLoginRateLimitedError,
    EufyLoginTransientError,
)
from .auth_store import AuthCache, AuthStore, session_replaced_issue_id
from .const import (
    CONF_LOCAL_DEVICES,
    CONF_LOCAL_HOST,
    CONF_LOCAL_VERSION,
    CONF_MAP_ID,
    CONF_MAP_IDS,
    CONF_MAP_MAX_PX,
    CONF_NOTIFY_DESKTOP,
    CONF_NOTIFY_MOBILE_SERVICE,
    CONF_ROBOT_STYLE,
    CONF_ROOM_NAMES,
    CONF_TRAIL_COLOR,
    DEFAULT_MAP_MAX_PX,
    DEFAULT_NOTIFY_DESKTOP,
    DEFAULT_NOTIFY_MOBILE_SERVICE,
    DEFAULT_ROBOT_STYLE,
    DEFAULT_TRAIL_COLOR,
    DOMAIN,
    VACS,
)

_LOGGER = logging.getLogger(__name__)

# Map image sizes offered in the options form; DEFAULT_MAP_MAX_PX is labelled "(default)".
_MAP_SIZE_GRADES: dict[int, str] = {256: "low", 512: "medium", 1024: "high", 2048: "ultra"}

USER_SCHEMA = Schema(
    {
        Required(CONF_USERNAME): cv.string,
        Required(CONF_PASSWORD): cv.string,
    }
)


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):  # type: ignore[call-arg]
    """Handle a config flow for Eufy Robovac."""

    VERSION = 1
    data: dict[str, Any] | None

    @staticmethod
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> OptionsFlowHandler:
        """Return the options flow (global settings + per-device local-Tuya)."""
        return OptionsFlowHandler(config_entry)

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        if user_input is None:
            return self.async_show_form(step_id="user", data_schema=USER_SCHEMA)
        errors: dict[str, str] = {}
        username = user_input[CONF_USERNAME]
        await self.async_set_unique_id(username)
        self._abort_if_unique_id_configured()

        title, errors, placeholders = await self._login_and_get_title(
            username, user_input[CONF_PASSWORD]
        )

        if not errors:
            data = user_input.copy()
            data[VACS] = {}
            return self.async_create_entry(title=title, data=data)

        return self.async_show_form(
            step_id="user",
            data_schema=USER_SCHEMA,
            errors=errors,
            description_placeholders=placeholders,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle reconfiguration."""
        entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])
        assert entry
        current_username = entry.data[CONF_USERNAME]

        if user_input is None:
            schema = Schema(
                {
                    Required(CONF_USERNAME, default=current_username): cv.string,
                    Required(CONF_PASSWORD): cv.string,
                }
            )
            return self.async_show_form(
                step_id="reconfigure", data_schema=schema, description_placeholders={}
            )

        errors: dict[str, str] = {}
        placeholders: dict[str, str] = {}
        title = current_username
        username = user_input[CONF_USERNAME]

        if username != current_username:
            errors[CONF_USERNAME] = "username_mismatch"
        else:
            title, errors, placeholders = await self._login_existing_entry(
                entry, username, user_input[CONF_PASSWORD]
            )

        if not errors:
            return self.async_update_reload_and_abort(
                entry,
                data={**entry.data, CONF_PASSWORD: user_input[CONF_PASSWORD]},
                title=title,
            )

        schema = Schema(
            {
                Required(CONF_USERNAME, default=current_username): cv.string,
                Required(CONF_PASSWORD): cv.string,
            }
        )
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=schema,
            errors=errors,
            description_placeholders=placeholders,
        )

    async def async_step_reauth(
        self, entry_data: dict[str, Any]
    ) -> ConfigFlowResult:
        """Handle reauthentication when credentials expire."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle reauth confirmation step."""
        entry = self._get_reauth_entry()
        username = entry.data[CONF_USERNAME]

        if user_input is None:
            schema = Schema({Required(CONF_PASSWORD): cv.string})
            return self.async_show_form(
                step_id="reauth_confirm",
                data_schema=schema,
                description_placeholders={"username": username},
            )

        _title, errors, placeholders = await self._login_existing_entry(
            entry, username, user_input[CONF_PASSWORD]
        )

        if not errors:
            return self.async_update_reload_and_abort(
                entry,
                data={**entry.data, CONF_PASSWORD: user_input[CONF_PASSWORD]},
            )

        schema = Schema({Required(CONF_PASSWORD): cv.string})
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=schema,
            errors=errors,
            description_placeholders={"username": username, **placeholders},
        )

    async def _login_existing_entry(
        self, entry: config_entries.ConfigEntry, username: str, password: str
    ) -> tuple[str, dict[str, str], dict[str, str]]:
        """Log in with the entry's stored openudid and keep the fresh tokens.

        Rotating the openudid invalidates the account's tokens (auth_store.py);
        the saved tokens let the reload skip a second login.
        """
        store = AuthStore(self.hass, entry.entry_id)
        cached = await store.async_load()
        # Identity, probe memos and the login budget: the old tokens are what
        # failed, and a successful login here clears the session-replaced latch.
        # The throttle dict is shared, so ``cached`` sees the attempt too.
        cache = AuthCache(
            openudid=cached.openudid,
            login_label=cached.login_label,
            tuya_region=cached.tuya_region,
            throttle=cached.throttle,
        )
        title, errors, placeholders = await self._login_and_get_title(
            username, password, cache
        )
        if not errors:
            await store.async_save(cache)
            ir.async_delete_issue(
                self.hass, DOMAIN, session_replaced_issue_id(entry.entry_id)
            )
        else:
            # Keep the stored tokens, but count the attempt and any hold-off.
            await store.async_save(cached)
        return title, errors, placeholders

    async def _login_and_get_title(
        self,
        username: str,
        password: str,
        auth_cache: AuthCache | None = None,
    ) -> tuple[str, dict[str, str], dict[str, str]]:
        """Login and return (device names or username, errors, form placeholders).

        ``auth_cache`` supplies the openudid and receives the fresh tokens.
        """
        errors: dict[str, str] = {}
        placeholders: dict[str, str] = {}
        title = username
        cache = auth_cache or AuthCache()
        try:
            _LOGGER.debug("Trying to log in")
            session = async_get_clientsession(self.hass)
            eufy_login = EufyLogin(
                username,
                password,
                cache.openudid,
                websession=session,
                auth_cache=cache if auth_cache is not None else None,
            )
            await eufy_login.init()
            devices = eufy_login.mqtt_devices + eufy_login.cloud_devices
            if devices:
                title = ", ".join(
                    d.get("deviceName") or "Eufy Robot" for d in devices
                )
            else:
                errors["base"] = "no_devices"
        except EufyLoginChallengeError as e:
            _LOGGER.debug("Eufy login needs a challenge answer: %s", e)
            errors["base"] = "login_challenge"
        except EufyLoginError as e:
            _LOGGER.debug("Eufy login rejected: %s", e)
            errors["base"] = "invalid_auth"
        except EufyLoginRateLimitedError as e:
            _LOGGER.debug("Eufy login held off: %s", e)
            errors["base"] = "rate_limited"
            placeholders["minutes"] = str(max(1, math.ceil((e.retry_after or 0) / 60)))
        except (EufyLoginTransientError, aiohttp.ClientError, TimeoutError) as e:
            _LOGGER.debug("Eufy login unavailable: %s", e)
            errors["base"] = "cannot_connect"
        except Exception:  # noqa: BLE001 - surfaced as a form error
            _LOGGER.exception("Unexpected error during Eufy login")
            errors["base"] = "unknown"

        return title, errors, placeholders


class OptionsFlowHandler(config_entries.OptionsFlow):
    """Eufy Robovac options: global settings + per-device local-Tuya overrides."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        # HA 2025+ deprecates assigning to self.config_entry; use a private ref.
        self._config_entry = config_entry
        # chosen in the "devices" step, configured in the "device" step
        self._selected_device: str | None = None

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Top-level options menu."""
        return self.async_show_menu(
            step_id="init",
            menu_options=["settings", "devices"],
        )

    async def async_step_settings(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Global settings: map rendering, robot style, notifications."""
        if user_input is not None:
            # an unselected dropdown submits None; store "" so consumers always
            # get a plain string
            if user_input.get(CONF_NOTIFY_MOBILE_SERVICE) is None:
                user_input[CONF_NOTIFY_MOBILE_SERVICE] = ""
            return self.async_create_entry(
                title="", data={**self._config_entry.options, **user_input}
            )

        opts = self._config_entry.options
        current_max_px = str(opts.get(CONF_MAP_MAX_PX, DEFAULT_MAP_MAX_PX))
        current_robot_style = opts.get(CONF_ROBOT_STYLE, DEFAULT_ROBOT_STYLE)
        # ColorRGBSelector round-trips a JSON list, so seed it as a list
        current_trail_color = list(opts.get(CONF_TRAIL_COLOR, DEFAULT_TRAIL_COLOR))
        current_notify_desktop = opts.get(CONF_NOTIFY_DESKTOP, DEFAULT_NOTIFY_DESKTOP)
        current_notify_mobile_service = opts.get(
            CONF_NOTIFY_MOBILE_SERVICE, DEFAULT_NOTIFY_MOBILE_SERVICE
        )

        all_notify = self.hass.services.async_services().get("notify", {})
        mobile_services = sorted(
            svc for svc in all_notify if svc.startswith("mobile_app_")
        )
        mobile_options = [
            selector.SelectOptionDict(
                value=svc,
                label=svc.replace("mobile_app_", "").replace("_", " ").title(),
            )
            for svc in mobile_services
        ]

        schema = Schema(
            {
                VOptional(CONF_MAP_MAX_PX, default=current_max_px): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[
                            selector.SelectOptionDict(
                                value=str(px),
                                label=f"{px} px (default)"
                                if px == DEFAULT_MAP_MAX_PX
                                else f"{px} px ({grade})",
                            )
                            for px, grade in _MAP_SIZE_GRADES.items()
                        ],
                        mode=selector.SelectSelectorMode.LIST,
                    )
                ),
                VOptional(CONF_ROBOT_STYLE, default=current_robot_style): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[
                            selector.SelectOptionDict(value="googly", label="Googly Eyes"),
                            selector.SelectOptionDict(value="dot", label="Dot"),
                        ],
                        mode=selector.SelectSelectorMode.LIST,
                    )
                ),
                VOptional(
                    CONF_TRAIL_COLOR, default=current_trail_color
                ): selector.ColorRGBSelector(),
                VOptional(
                    CONF_NOTIFY_DESKTOP, default=current_notify_desktop
                ): selector.BooleanSelector(),
                # vol.Maybe lets an unselected dropdown (None) pass validation
                VOptional(
                    CONF_NOTIFY_MOBILE_SERVICE, default=current_notify_mobile_service
                ): vol.Maybe(
                    selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=mobile_options,
                            custom_value=True,
                            mode=selector.SelectSelectorMode.DROPDOWN,
                        )
                    )
                ),
            }
        )
        return self.async_show_form(step_id="settings", data_schema=schema)

    def _eligible_devices(self) -> list[tuple[str, str, str, Any]]:
        """Return (device_id, name, model, coordinator) for each loaded device."""
        runtime = self.hass.data.get(DOMAIN, {}).get(
            self._config_entry.entry_id, {}
        )
        coordinators = runtime.get("coordinators", []) if runtime else []
        return [
            (c.device_id, c.device_name, c.device_model, c) for c in coordinators
        ]

    async def async_step_devices(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Pick a device to configure (local-Tuya address + room overrides)."""
        devices = self._eligible_devices()
        if not devices:
            return self.async_abort(reason="no_devices")

        if user_input is not None:
            self._selected_device = user_input["device"]
            return await self.async_step_device()

        options = [
            selector.SelectOptionDict(value=dev_id, label=f"{name} ({model})")
            for dev_id, name, model, _coord in devices
        ]
        schema = Schema(
            {
                Required("device", default=options[0]["value"]): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=options, mode=selector.SelectSelectorMode.LIST
                    )
                )
            }
        )
        return self.async_show_form(step_id="devices", data_schema=schema)

    async def async_step_device(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Configure one device's local-Tuya host / protocol / room overrides.

        Field keys are static so they pick up translated labels; the device name
        goes in the step description instead.
        """
        dev_id = self._selected_device
        devices = {d[0]: d for d in self._eligible_devices()}
        if not dev_id or dev_id not in devices:
            return self.async_abort(reason="no_devices")
        _id, name, model, coord = devices[dev_id]
        has_local_key = bool(getattr(coord, "_local_key", None))
        # copy the whole map so other devices' overrides survive the write
        existing_all: dict[str, dict] = dict(
            self._config_entry.options.get(CONF_LOCAL_DEVICES, {})
        )
        current: dict[str, Any] = dict(existing_all.get(dev_id, {}))
        map_ids_text = _format_map_ids_text(
            current.get(CONF_MAP_ID), current.get(CONF_MAP_IDS) or {}
        )
        errors: dict[str, str] = {}

        if user_input is not None:
            host = (user_input.get(CONF_LOCAL_HOST, "") or "").strip()
            version = user_input.get(CONF_LOCAL_VERSION, 3.3)
            rooms_parsed = _parse_rooms_text(
                user_input.get(CONF_ROOM_NAMES, "") or ""
            )
            map_ids_text = user_input.get(CONF_MAP_ID, "") or ""
            if host and not _is_valid_host(host):
                errors[CONF_LOCAL_HOST] = "invalid_host"
            try:
                map_id_all, map_ids = _parse_map_ids_text(map_ids_text)
            except ValueError:
                map_id_all, map_ids = None, {}
                errors[CONF_MAP_ID] = "invalid_map_id"
            if not errors:
                entry: dict[str, Any] = {}
                if host and has_local_key:
                    entry[CONF_LOCAL_HOST] = host
                    entry[CONF_LOCAL_VERSION] = float(version or 3.3)
                if rooms_parsed:
                    entry[CONF_ROOM_NAMES] = rooms_parsed
                if map_id_all is not None:
                    entry[CONF_MAP_ID] = map_id_all
                if map_ids:
                    entry[CONF_MAP_IDS] = map_ids
                if entry:
                    existing_all[dev_id] = entry
                else:
                    # All fields cleared — drop any stored override.
                    existing_all.pop(dev_id, None)
                return self.async_create_entry(
                    title="",
                    data={
                        **self._config_entry.options,
                        CONF_LOCAL_DEVICES: existing_all,
                    },
                )
            # Re-show with the submitted values preserved (the map id text is
            # kept as typed so a malformed line can be corrected in place).
            current = {
                CONF_LOCAL_HOST: host,
                CONF_LOCAL_VERSION: version,
                CONF_ROOM_NAMES: rooms_parsed,
            }

        # Pre-fill with suggested_value, not default=: the frontend omits an
        # emptied optional field from the submission, and a default= would put
        # the stored value back, making a saved override impossible to clear.
        schema_dict: dict = {}
        if has_local_key:
            schema_dict[
                VOptional(
                    CONF_LOCAL_HOST,
                    description={"suggested_value": current.get(CONF_LOCAL_HOST, "")},
                )
            ] = cv.string
            schema_dict[
                VOptional(
                    CONF_LOCAL_VERSION, default=current.get(CONF_LOCAL_VERSION, 3.3)
                )
            ] = In([3.1, 3.3, 3.4, 3.5])
        schema_dict[
            VOptional(
                CONF_ROOM_NAMES,
                description={
                    "suggested_value": _format_rooms_text(
                        current.get(CONF_ROOM_NAMES) or {}
                    )
                },
            )
        ] = selector.TextSelector(
            selector.TextSelectorConfig(multiline=True)
        )
        schema_dict[
            VOptional(CONF_MAP_ID, description={"suggested_value": map_ids_text})
        ] = selector.TextSelector(
            selector.TextSelectorConfig(multiline=True)
        )
        return self.async_show_form(
            step_id="device",
            data_schema=Schema(schema_dict),
            description_placeholders={"device": f"{name} ({model})"},
            errors=errors,
        )


def _option_lines(text: str) -> list[str]:
    """Return the meaningful lines of a multi-line options field.

    Whitespace is stripped; blank lines and ``#`` comments are dropped.
    """
    lines = (raw_line.strip() for raw_line in text.splitlines())
    return [line for line in lines if line and not line.startswith("#")]


def _parse_rooms_text(text: str) -> dict[int, str]:
    """Parse a user-entered "id: name" multi-line string into a dict.

    ``#`` lines are comments; unparsable lines are ignored rather than
    rejecting the whole form, and the last occurrence of an id wins.
    """
    rooms: dict[int, str] = {}
    for line in _option_lines(text):
        if ":" not in line:
            continue
        id_part, _, name_part = line.partition(":")
        try:
            room_id = int(id_part.strip())
        except ValueError:
            continue
        name = name_part.strip()
        if name:
            rooms[room_id] = name
    return rooms


# one hostname label: 1-63 chars, hyphens allowed but not at either end
_HOSTNAME_LABEL = re.compile(r"^(?!-)[A-Za-z0-9-]{1,63}(?<!-)$")


def _is_valid_host(host: str) -> bool:
    """Return True if ``host`` is a bare IP address or plausible hostname.

    The local-Tuya client wants a bare host, so a scheme or port (``1.2.3.4:6668``)
    is rejected; empty means "stay on cloud" and is rejected here too.
    """
    if not host:
        return False
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        pass
    if len(host) > 253:
        return False
    return all(_HOSTNAME_LABEL.match(label) for label in host.split("."))


def _format_rooms_text(rooms: dict[int, str]) -> str:
    """Render the saved override dict back as the textarea default.

    Sort numerically: JSON storage stringifies the int keys, so a lexical sort
    would put room 10 before room 9.
    """
    if not rooms:
        return ""
    return "\n".join(
        f"{rid}: {name}"
        for rid, name in sorted(rooms.items(), key=lambda kv: int(kv[0]))
    )


def _parse_map_ids_text(text: str) -> tuple[int | None, dict[int, int]]:
    """Parse the map id override field into (all-maps id, per-map ids).

    A bare ``<local id>`` line applies to every map; a ``<reported id>:
    <local id>`` line applies only while the device reports that map id. For
    duplicates the LAST line wins. Unlike room names, a malformed line raises
    ``ValueError``: silently ignoring it would send room cleans to a map id the
    firmware rejects.
    """
    all_maps: int | None = None
    per_map: dict[int, int] = {}
    for line in _option_lines(text):
        reported_part, separator, local_part = line.partition(":")
        if separator:
            per_map[_positive_int(reported_part)] = _positive_int(local_part)
        else:
            all_maps = _positive_int(line)
    return all_maps, per_map


def _positive_int(text: str) -> int:
    """Return ``text`` as an int greater than zero, else raise ``ValueError``."""
    value = int(text.strip())
    if value <= 0:
        raise ValueError(f"not a positive integer: {text!r}")
    return value


def _format_map_ids_text(all_maps: int | None, per_map: dict[int, int]) -> str:
    """Render the saved map id overrides back as the textarea default.

    The all-maps id comes first. Reported ids are sorted numerically because
    JSON storage stringifies the int keys.
    """
    lines = [str(all_maps)] if all_maps else []
    lines.extend(
        f"{reported_id}: {local_id}"
        for reported_id, local_id in sorted(
            per_map.items(), key=lambda kv: int(kv[0])
        )
    )
    return "\n".join(lines)
