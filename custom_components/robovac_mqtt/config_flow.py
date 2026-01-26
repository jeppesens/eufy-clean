from __future__ import annotations

import logging
import random
import string
from typing import Any

import homeassistant.helpers.config_validation as cv
from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.data_entry_flow import FlowResult
from voluptuous import Required, Schema

from .api.http import EufyHTTPClient
from .const import DOMAIN, VACS

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

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
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
            return self.async_create_entry(title=username, data=user_input)

        return self.async_show_form(
            step_id="user", data_schema=USER_SCHEMA, errors=errors
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
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

    @staticmethod
    async def _validate_login(username: str, password: str) -> dict[str, str]:
        """Validate login credentials."""
        errors: dict[str, str] = {}
        try:
            # Generate a new openudid for validation
            openudid = "".join(random.choices(string.hexdigits, k=32))
            _LOGGER.info("Trying to login with username: %s", username)

            eufy_api = EufyHTTPClient(username, password, openudid)
            login_resp = await eufy_api.login(validate_only=True)
            if not login_resp.get("session"):
                errors["base"] = "invalid_auth"
        except Exception as e:
            _LOGGER.exception("Unexpected exception: %s", e)
            errors["base"] = "unknown"

        return errors
