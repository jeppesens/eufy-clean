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
        # Device id chosen in the "devices" step, configured in the "device" step.
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
        """Global settings: map rendering, robot style, notifications.

        Every field is optional (each has a current/default value), so any one
        can be changed without re-entering the others.
        """
        if user_input is not None:
            # An unselected mobile-service dropdown submits None; store "" so
            # downstream consumers can rely on a plain string.
            if user_input.get(CONF_NOTIFY_MOBILE_SERVICE) is None:
                user_input[CONF_NOTIFY_MOBILE_SERVICE] = ""
            return self.async_create_entry(
                title="", data={**self._config_entry.options, **user_input}
            )

        opts = self._config_entry.options
        current_max_px = str(opts.get(CONF_MAP_MAX_PX, DEFAULT_MAP_MAX_PX))
        current_robot_style = opts.get(CONF_ROBOT_STYLE, DEFAULT_ROBOT_STYLE)
        current_notify_desktop = opts.get(CONF_NOTIFY_DESKTOP, DEFAULT_NOTIFY_DESKTOP)
        current_notify_mobile_service = opts.get(
            CONF_NOTIFY_MOBILE_SERVICE, DEFAULT_NOTIFY_MOBILE_SERVICE
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

        schema = Schema(
            {
                VOptional(CONF_MAP_MAX_PX, default=current_max_px): selector.SelectSelector(
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
                    CONF_NOTIFY_DESKTOP, default=current_notify_desktop
                ): selector.BooleanSelector(),
                # vol.Maybe lets an unselected dropdown (which submits None) pass
                # validation; the step normalises None back to "".
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

        Uses static field keys (host/version/rooms) so they get proper
        translated labels, with the device name shown in the step description.
        """
        dev_id = self._selected_device
        devices = {d[0]: d for d in self._eligible_devices()}
        if not dev_id or dev_id not in devices:
            return self.async_abort(reason="no_devices")
        _id, name, model, coord = devices[dev_id]
        has_local_key = bool(getattr(coord, "_local_key", None))
        # Copy the full stored map so other devices' overrides are preserved.
        existing_all: dict[str, dict] = dict(
            self._config_entry.options.get(CONF_LOCAL_DEVICES, {})
        )
        current: dict[str, Any] = dict(existing_all.get(dev_id, {}))
        errors: dict[str, str] = {}

        if user_input is not None:
            host = (user_input.get(CONF_LOCAL_HOST, "") or "").strip()
            version = user_input.get(CONF_LOCAL_VERSION, 3.3)
            rooms_parsed = _parse_rooms_text(
                user_input.get(CONF_ROOM_NAMES, "") or ""
            )
            if host and not _is_valid_host(host):
                errors[CONF_LOCAL_HOST] = "invalid_host"
            if not errors:
                entry: dict[str, Any] = {}
                if host and has_local_key:
                    entry[CONF_LOCAL_HOST] = host
                    entry[CONF_LOCAL_VERSION] = float(version or 3.3)
                if rooms_parsed:
                    entry[CONF_ROOM_NAMES] = rooms_parsed
                if entry:
                    existing_all[dev_id] = entry
                else:
                    # Both fields cleared — drop any stored override.
                    existing_all.pop(dev_id, None)
                return self.async_create_entry(
                    title="",
                    data={
                        **self._config_entry.options,
                        CONF_LOCAL_DEVICES: existing_all,
                    },
                )
            # Re-show with the submitted values preserved.
            current = {
                CONF_LOCAL_HOST: host,
                CONF_LOCAL_VERSION: version,
                CONF_ROOM_NAMES: rooms_parsed,
            }

        schema_dict: dict = {}
        if has_local_key:
            schema_dict[
                VOptional(CONF_LOCAL_HOST, default=current.get(CONF_LOCAL_HOST, ""))
            ] = cv.string
            schema_dict[
                VOptional(
                    CONF_LOCAL_VERSION, default=current.get(CONF_LOCAL_VERSION, 3.3)
                )
            ] = In([3.1, 3.3, 3.4, 3.5])
        schema_dict[
            VOptional(
                CONF_ROOM_NAMES,
                default=_format_rooms_text(current.get(CONF_ROOM_NAMES) or {}),
            )
        ] = cv.string
        return self.async_show_form(
            step_id="device",
            data_schema=Schema(schema_dict),
            description_placeholders={"device": f"{name} ({model})"},
            errors=errors,
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
