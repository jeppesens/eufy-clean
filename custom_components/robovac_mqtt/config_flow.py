import logging
from typing import Any, Optional

import homeassistant.helpers.config_validation as cv
from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.data_entry_flow import FlowResult
from voluptuous import Required, Schema

from .constants.hass import DOMAIN
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

    data: Optional[dict[str, Any]]

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        if user_input is None:
            return self.async_show_form(step_id="user", data_schema=USER_SCHEMA)
        errors = {}
        try:
            unique_id = user_input[CONF_USERNAME]
            eufy_api = EufyApi(self["username"], self["password"])
            login_resp = eufy_api.login()
            if not login_resp.get('user'):
                errors["base"] = "invalid_auth"
        except Exception as e:
            _LOGGER.exception("Unexpected exception: {}".format(e))
            errors["base"] = "unknown"
        else:
            await self.async_set_unique_id(unique_id)
            self._abort_if_unique_id_configured()
            return True
        return self.async_show_form(
            step_id="user", data_schema=USER_SCHEMA, errors=errors
        )
