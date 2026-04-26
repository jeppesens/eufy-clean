from __future__ import annotations

import logging
import random
import string
from typing import Any

import homeassistant.helpers.config_validation as cv
from homeassistant import config_entries
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from voluptuous import Required, Schema

from .api.http import EufyHTTPClient
from .const import (
    CONF_LOCAL_DEVICES,
    CONF_LOCAL_HOST,
    CONF_LOCAL_VERSION,
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
    ) -> "OptionsFlowHandler":
        """Return the options flow handler — local-Tuya per-device LAN addresses."""
        return OptionsFlowHandler(config_entry)

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        if user_input is None:
            return self.async_show_form(step_id="user", data_schema=USER_SCHEMA)
        errors = {}
        username = user_input[CONF_USERNAME]
        await self.async_set_unique_id(username)
        self._abort_if_unique_id_configured()

        errors = await self._validate_login(username, user_input[CONF_PASSWORD])

        if not errors:
            data = user_input.copy()
            data[VACS] = {}
            return self.async_create_entry(title=username, data=data)

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

        errors = {}
        username = user_input[CONF_USERNAME]

        # Verify username matches existing entry (optional, but robust)
        if username != current_username:
            errors[CONF_USERNAME] = "username_mismatch"
        else:
            errors = await self._validate_login(username, user_input[CONF_PASSWORD])

        if not errors:
            return self.async_update_reload_and_abort(
                entry,
                data={**entry.data, CONF_PASSWORD: user_input[CONF_PASSWORD]},
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

        errors = await self._validate_login(username, user_input[CONF_PASSWORD])

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

    async def _validate_login(self, username: str, password: str) -> dict[str, str]:
        """Validate login credentials."""
        from homeassistant.helpers.aiohttp_client import async_get_clientsession

        errors: dict[str, str] = {}
        try:
            # Generate a new openudid for validation
            openudid = "".join(random.choices(string.hexdigits, k=32))
            _LOGGER.info("Trying to login with username: %s", username)

            session = async_get_clientsession(self.hass)
            eufy_api = EufyHTTPClient(username, password, openudid, websession=session)
            login_resp = await eufy_api.login(validate_only=True)
            if not login_resp.get("session"):
                errors["base"] = "invalid_auth"
        except Exception as e:
            _LOGGER.exception("Unexpected exception: %s", e)
            errors["base"] = "unknown"

        return errors


class OptionsFlowHandler(config_entries.OptionsFlow):
    """Per-device local-Tuya LAN address configuration.

    The Tuya Cloud transport polls every 30 s. If the user knows the LAN
    address of a dock they can opt-in to direct local push (instant updates,
    works offline). The local key is auto-supplied by the Tuya Cloud login.
    """

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        # HA 2025+ deprecates `self.config_entry =` assignment; the property
        # is provided by the base class.
        self._entry_ref = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show one form per cloud-discovered device with its current LAN host."""
        from homeassistant.const import CONF_HOST
        from voluptuous import Optional as VOptional, Coerce, In

        # Pull live device list out of the running coordinator data so the
        # form lists exactly the devices the user can target. If the
        # integration hasn't loaded yet, fall back to whatever's in options.
        runtime = self.hass.data.get(DOMAIN, {}).get(self._entry_ref.entry_id, {})
        coordinators = runtime.get("coordinators", []) if runtime else []
        eligible = [
            (c.device_id, c.device_name, c.device_model)
            for c in coordinators
            if getattr(c, "_local_key", None)  # only devices Tuya gave us a key for
            or self._entry_ref.options.get(CONF_LOCAL_DEVICES, {}).get(c.device_id)
        ]

        existing: dict[str, dict] = self._entry_ref.options.get(CONF_LOCAL_DEVICES, {})

        if user_input is not None:
            new_overrides: dict[str, dict] = {}
            for dev_id, _name, _model in eligible:
                host_field = f"{dev_id}__host"
                ver_field = f"{dev_id}__version"
                host = (user_input.get(host_field) or "").strip()
                if host:
                    new_overrides[dev_id] = {
                        CONF_LOCAL_HOST: host,
                        CONF_LOCAL_VERSION: float(
                            user_input.get(ver_field, 3.3) or 3.3
                        ),
                    }
            return self.async_create_entry(
                title="",
                data={**self._entry_ref.options, CONF_LOCAL_DEVICES: new_overrides},
            )

        if not eligible:
            # Nothing to configure — show an empty form so the user understands.
            return self.async_show_form(
                step_id="init",
                data_schema=Schema({}),
                description_placeholders={"info": "no_local_capable_devices"},
            )

        schema_dict: dict = {}
        for dev_id, name, model in eligible:
            current = existing.get(dev_id, {})
            label = f"{name} ({model}) — {dev_id[:8]}"
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

        return self.async_show_form(step_id="init", data_schema=Schema(schema_dict))
