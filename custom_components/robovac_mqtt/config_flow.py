from __future__ import annotations

import logging
import random
import string
from typing import Any, Optional

import homeassistant.helpers.config_validation as cv
from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.data_entry_flow import FlowResult
from voluptuous import Required, Schema

from .const import DOMAIN, VACS
from .EufyApi import EufyApi

_LOGGER = logging.getLogger(__name__)

USER_SCHEMA = Schema(
    {
        Required(CONF_USERNAME): cv.string,
        Required(CONF_PASSWORD): cv.string,
    }
)


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Eufy Robovac."""

    data: dict[str, Any] | None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        if user_input is None:
            return self.async_show_form(step_id="user", data_schema=USER_SCHEMA)
        errors = {}
        try:
            openudid = "".join(random.choices(string.hexdigits, k=32))
            username = user_input[CONF_USERNAME]
            _LOGGER.info(f"Trying to login with username: {username}")
            unique_id = username
            eufy_api = EufyApi(username, user_input[CONF_PASSWORD], openudid)
            login_resp = await eufy_api.login(validate_only=True)
            if not login_resp.get("session"):
                errors["base"] = "invalid_auth"
            else:
                data = user_input.copy()
                data[VACS] = {}
                return self.async_create_entry(title=unique_id, data=user_input)
        except Exception as e:
            _LOGGER.exception(f"Unexpected exception: {e}")
            errors["base"] = "unknown"
        else:
            await self.async_set_unique_id(unique_id)
            self._abort_if_unique_id_configured()
            return True
        return self.async_show_form(
            step_id="user", data_schema=USER_SCHEMA, errors=errors
        )
