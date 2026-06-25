from __future__ import annotations

import ipaddress
import logging
import random
import re
import string
from typing import Any

import homeassistant.helpers.config_validation as cv
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from voluptuous import In
from voluptuous import Optional as VOptional
from voluptuous import Required, Schema

from .api.cloud import EufyLogin
from .const import (
    CONF_LOCAL_DEVICES,
    CONF_LOCAL_HOST,
    CONF_LOCAL_VERSION,
    CONF_MAP_MAX_PX,
    CONF_NOTIFY_DESKTOP,
    CONF_NOTIFY_MOBILE_SERVICE,
    CONF_ROBOT_STYLE,
    CONF_ROOM_NAMES,
    DEFAULT_MAP_MAX_PX,
    DEFAULT_NOTIFY_DESKTOP,
    DEFAULT_NOTIFY_MOBILE_SERVICE,
    DEFAULT_ROBOT_STYLE,
    DOMAIN,
    VACS,
)

_LOGGER = logging.getLogger(__name__)

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

        title, errors = await self._login_and_get_title(username, user_input[CONF_PASSWORD])

        if not errors:
            data = user_input.copy()
            data[VACS] = {}
            return self.async_create_entry(title=title, data=data)

        return self.async_show_form(
            step_id="user", data_schema=USER_SCHEMA, errors=errors
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
        title = current_username
        username = user_input[CONF_USERNAME]

        # Verify username matches existing entry (optional, but robust)
        if username != current_username:
            errors[CONF_USERNAME] = "username_mismatch"
        else:
            title, errors = await self._login_and_get_title(username, user_input[CONF_PASSWORD])

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
            step_id="reconfigure", data_schema=schema, errors=errors
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

        _title, errors = await self._login_and_get_title(
            username, user_input[CONF_PASSWORD]
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
            description_placeholders={"username": username},
        )

    async def _login_and_get_title(
        self, username: str, password: str
    ) -> tuple[str, dict[str, str]]:
        """Login and return (title, errors).

        Title is the discovered device name(s) (MQTT + Tuya Cloud), falling
        back to the username when no devices are found.
        """
        errors: dict[str, str] = {}
        title = username
        try:
            openudid = "".join(random.choices(string.hexdigits, k=32))
            _LOGGER.info("Trying to login with username: %s", username)
            session = async_get_clientsession(self.hass)
            eufy_login = EufyLogin(username, password, openudid, websession=session)
            await eufy_login.init()
            devices = eufy_login.mqtt_devices + eufy_login.cloud_devices
            if devices:
                title = ", ".join(
                    d.get("deviceName") or "Eufy Robot" for d in devices
                )
            else:
                errors["base"] = "no_devices"
        except Exception as e:
            _LOGGER.exception("Unexpected exception: %s", e)
            errors["base"] = "invalid_auth"

        return title, errors


class OptionsFlowHandler(config_entries.OptionsFlow):
    """Eufy Robovac options: global settings + per-device local-Tuya overrides.

    Global settings cover map rendering, robot style and notifications. The
    per-device section lets a user opt a Tuya Cloud device into direct local
    push by entering its LAN address (the local key is auto-supplied by the
    Tuya Cloud login), plus manual room id->name overrides.
    """

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        # HA 2025+ deprecates assigning to self.config_entry; use a private ref.
        self._config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage integration options.

        Combines global settings (map rendering, robot style, notifications)
        with per-device local-Tuya promotion and manual room id->name
        overrides. Per-device fields use the dynamic keys ``{dev_id}__host`` /
        ``{dev_id}__version`` / ``{dev_id}__rooms``.
        """
        # Pull the live device list from running coordinators so the form
        # lists exactly the devices the user can target.
        runtime = self.hass.data.get(DOMAIN, {}).get(
            self._config_entry.entry_id, {}
        )
        coordinators = runtime.get("coordinators", []) if runtime else []
        eligible = [
            (c.device_id, c.device_name, c.device_model, c)
            for c in coordinators
            if getattr(c, "_local_key", None)  # devices Tuya gave us a key for
            or self._config_entry.options.get(CONF_LOCAL_DEVICES, {}).get(
                c.device_id
            )
        ]
        # Coordinators without a local key still benefit from the room
        # override field, so include them too.
        seen = {dev_id for dev_id, *_ in eligible}
        for c in coordinators:
            if c.device_id not in seen:
                eligible.append((c.device_id, c.device_name, c.device_model, c))

        existing: dict[str, dict] = self._config_entry.options.get(
            CONF_LOCAL_DEVICES, {}
        )

        if user_input is not None:
            # Split the submitted values: per-device keys -> CONF_LOCAL_DEVICES,
            # everything else -> global settings.
            #
            # Seed from the stored overrides so a device whose coordinator
            # failed to init (offline at load, hence absent from `eligible`)
            # keeps its saved host/version/room override instead of being
            # silently dropped.
            new_overrides: dict[str, dict] = {
                dev_id: dict(entry) for dev_id, entry in existing.items()
            }
            errors: dict[str, str] = {}
            for dev_id, _name, _model, coord in eligible:
                host = (user_input.pop(f"{dev_id}__host", "") or "").strip()
                version = user_input.pop(f"{dev_id}__version", 3.3)
                rooms_raw = user_input.pop(f"{dev_id}__rooms", "") or ""
                rooms_parsed = _parse_rooms_text(rooms_raw)
                # Validate a supplied host before saving. Empty host stays on
                # cloud and is not an error.
                if host and not _is_valid_host(host):
                    errors[f"{dev_id}__host"] = "invalid_host"
                    continue
                # The user cleared both fields for an eligible device: drop any
                # stored override for it.
                if not host and not rooms_parsed:
                    new_overrides.pop(dev_id, None)
                    continue
                entry: dict[str, Any] = {}
                if host and getattr(coord, "_local_key", None):
                    entry[CONF_LOCAL_HOST] = host
                    entry[CONF_LOCAL_VERSION] = float(version or 3.3)
                if rooms_parsed:
                    entry[CONF_ROOM_NAMES] = rooms_parsed
                new_overrides[dev_id] = entry

            if errors:
                return self._show_init_form(
                    eligible, existing, user_input, errors
                )

            # An unselected mobile-service dropdown submits None; store "" so
            # downstream consumers can rely on a plain string.
            if user_input.get(CONF_NOTIFY_MOBILE_SERVICE) is None:
                user_input[CONF_NOTIFY_MOBILE_SERVICE] = ""

            return self.async_create_entry(
                title="",
                data={
                    **self._config_entry.options,
                    **user_input,
                    CONF_LOCAL_DEVICES: new_overrides,
                },
            )

        return self._show_init_form(eligible, existing)

    def _show_init_form(
        self,
        eligible: list[tuple],
        existing: dict[str, dict],
        user_input: dict[str, Any] | None = None,
        errors: dict[str, str] | None = None,
    ) -> ConfigFlowResult:
        """Build and show the combined options form.

        When re-shown after a validation error, ``user_input`` carries the
        user's submitted global settings (the per-device keys have already
        been popped) so they aren't lost, and ``errors`` flags the offending
        per-device host fields.
        """
        submitted = user_input or {}
        opts = self._config_entry.options
        current_max_px = str(
            submitted.get(CONF_MAP_MAX_PX, opts.get(CONF_MAP_MAX_PX, DEFAULT_MAP_MAX_PX))
        )
        current_robot_style = submitted.get(
            CONF_ROBOT_STYLE, opts.get(CONF_ROBOT_STYLE, DEFAULT_ROBOT_STYLE)
        )
        current_notify_desktop = submitted.get(
            CONF_NOTIFY_DESKTOP, opts.get(CONF_NOTIFY_DESKTOP, DEFAULT_NOTIFY_DESKTOP)
        )
        current_notify_mobile_service = submitted.get(
            CONF_NOTIFY_MOBILE_SERVICE,
            opts.get(CONF_NOTIFY_MOBILE_SERVICE, DEFAULT_NOTIFY_MOBILE_SERVICE),
        )

        # Discover available mobile app notify services
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

        # Global settings first, then any per-device local-Tuya / room fields.
        schema_dict: dict = {
            Required(CONF_MAP_MAX_PX, default=current_max_px): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[
                        selector.SelectOptionDict(value="256", label="256 px (low)"),
                        selector.SelectOptionDict(value="512", label="512 px (default)"),
                        selector.SelectOptionDict(value="1024", label="1024 px (high)"),
                        selector.SelectOptionDict(value="2048", label="2048 px (ultra)"),
                    ],
                    mode=selector.SelectSelectorMode.LIST,
                )
            ),
            Required(CONF_ROBOT_STYLE, default=current_robot_style): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[
                        selector.SelectOptionDict(value="googly", label="Googly Eyes"),
                        selector.SelectOptionDict(value="dot", label="Dot"),
                    ],
                    mode=selector.SelectSelectorMode.LIST,
                )
            ),
            Required(
                CONF_NOTIFY_DESKTOP, default=current_notify_desktop
            ): selector.BooleanSelector(),
            # vol.Maybe lets an unselected dropdown (which submits None) pass
            # validation; the step normalises None back to "". A bare coercion
            # here would break schema serialization for the frontend.
            Required(
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

        for dev_id, name, model, coord in eligible:
            current = existing.get(dev_id, {})
            label = f"{name} ({model}) — {dev_id[:8]}"
            # Only offer host/version on devices we actually have a local key for.
            if getattr(coord, "_local_key", None):
                schema_dict[
                    VOptional(
                        f"{dev_id}__host",
                        default=current.get(CONF_LOCAL_HOST, ""),
                        description={"suggested_value": label},
                    )
                ] = cv.string
                schema_dict[
                    VOptional(
                        f"{dev_id}__version",
                        default=current.get(CONF_LOCAL_VERSION, 3.3),
                    )
                ] = In([3.1, 3.3, 3.4, 3.5])
            schema_dict[
                VOptional(
                    f"{dev_id}__rooms",
                    default=_format_rooms_text(current.get(CONF_ROOM_NAMES) or {}),
                )
            ] = cv.string

        return self.async_show_form(
            step_id="init", data_schema=Schema(schema_dict), errors=errors or {}
        )


def _parse_rooms_text(text: str) -> dict[int, str]:
    """Parse a user-entered "id: name" multi-line string into a dict.

    Lines starting with ``#`` are treated as comments. Whitespace and
    duplicate IDs are tolerated; the LAST occurrence of an ID wins. Lines
    that don't fit ``<int>: <text>`` are silently ignored — we'd rather
    accept loose input than reject the whole form.
    """
    rooms: dict[int, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
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


# A single hostname label: alphanumeric, may contain hyphens internally,
# 1-63 chars. The full hostname is one or more such labels joined by dots.
_HOSTNAME_LABEL = re.compile(r"^(?!-)[A-Za-z0-9-]{1,63}(?<!-)$")


def _is_valid_host(host: str) -> bool:
    """Return True if ``host`` is a bare IP address or plausible hostname.

    Rejects values carrying a scheme or port (e.g. ``http://x`` or
    ``1.2.3.4:6668``) since the local-Tuya client expects a bare host. An
    empty string is *not* validated here (empty = "stay on cloud").
    """
    if not host:
        return False
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        pass
    # Not an IP — accept a plausible hostname (no scheme, no port, no spaces).
    if len(host) > 253:
        return False
    return all(_HOSTNAME_LABEL.match(label) for label in host.split("."))


def _format_rooms_text(rooms: dict[int, str]) -> str:
    """Render the saved override dict back as the textarea default.

    Room ids are sorted numerically (not lexically) so that e.g. room 10
    comes after room 9 even when keys arrive as strings (JSON storage
    stringifies int keys).
    """
    if not rooms:
        return ""
    return "\n".join(
        f"{rid}: {name}"
        for rid, name in sorted(rooms.items(), key=lambda kv: int(kv[0]))
    )
