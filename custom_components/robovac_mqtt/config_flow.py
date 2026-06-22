from __future__ import annotations

import logging
import random
import string
from typing import Any

import homeassistant.helpers.config_validation as cv
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.helpers import selector
from voluptuous import Required, Schema

from .api.cloud import EufyLogin
from .const import (
    CONF_MAP_MAX_PX,
    CONF_NOTIFY_DESKTOP,
    CONF_NOTIFY_MOBILE_SERVICE,
    CONF_ROBOT_STYLE,
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
    ) -> config_entries.OptionsFlow:
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

    @staticmethod
    async def _login_and_get_title(username: str, password: str) -> tuple[str, dict[str, str]]:
        """Login and return (title, errors). Title is device name(s) or username fallback."""
        errors: dict[str, str] = {}
        title = username
        try:
            openudid = "".join(random.choices(string.hexdigits, k=32))
            _LOGGER.info("Trying to login with username: %s", username)
            eufy_login = EufyLogin(username, password, openudid)
            await eufy_login.init()
            devices = eufy_login.mqtt_devices
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
    """Handle options for Eufy Robovac."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the options."""
        if user_input is not None:
            # An unselected mobile-service dropdown submits None; store "" so
            # downstream consumers can rely on a plain string.
            if user_input.get(CONF_NOTIFY_MOBILE_SERVICE) is None:
                user_input[CONF_NOTIFY_MOBILE_SERVICE] = ""
            return self.async_create_entry(title="", data=user_input)

        opts = self._config_entry.options
        current_max_px = str(opts.get(CONF_MAP_MAX_PX, DEFAULT_MAP_MAX_PX))
        current_robot_style = opts.get(CONF_ROBOT_STYLE, DEFAULT_ROBOT_STYLE)
        current_notify_desktop = opts.get(CONF_NOTIFY_DESKTOP, DEFAULT_NOTIFY_DESKTOP)
        current_notify_mobile_service = opts.get(CONF_NOTIFY_MOBILE_SERVICE, DEFAULT_NOTIFY_MOBILE_SERVICE)

        # Discover available mobile app notify services
        all_notify = self.hass.services.async_services().get("notify", {})
        mobile_services = sorted(
            svc for svc in all_notify if svc.startswith("mobile_app_")
        )
        mobile_options = [
            selector.SelectOptionDict(value=svc, label=svc.replace("mobile_app_", "").replace("_", " ").title())
            for svc in mobile_services
        ]

        schema = Schema(
            {
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
                Required(CONF_NOTIFY_DESKTOP, default=current_notify_desktop): selector.BooleanSelector(),
                # vol.Maybe lets an unselected dropdown (which submits None)
                # pass validation; the step normalises None back to "".
                # A bare coercion function here would break schema
                # serialization for the frontend (HTTP 500 on form load).
                Required(CONF_NOTIFY_MOBILE_SERVICE, default=current_notify_mobile_service): vol.Maybe(
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
        return self.async_show_form(step_id="init", data_schema=schema)
