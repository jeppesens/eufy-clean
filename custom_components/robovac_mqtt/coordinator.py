from __future__ import annotations

import json
import logging
from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api.client import EufyCleanClient
from .api.cloud import EufyLogin
from .api.parser import update_state
from .const import DOMAIN
from .models import VacuumState

_LOGGER = logging.getLogger(__name__)


class EufyCleanCoordinator(DataUpdateCoordinator[VacuumState]):
    """Coordinator to manage Eufy Clean device connection and state."""

    def __init__(
        self,
        hass: HomeAssistant,
        eufy_login: EufyLogin,
        device_info: dict[str, Any],
    ) -> None:
        """Initialize coordinator."""
        self.device_id = device_info["deviceId"]
        self.device_model = device_info["deviceModel"]
        self.device_name = device_info["deviceName"]
        self.eufy_login = eufy_login

        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{self.device_name}",
        )

        self.client: EufyCleanClient | None = None
        self.data = VacuumState()
        if dps := device_info.get("dps"):
            self.data = update_state(self.data, dps)

    async def initialize(self) -> None:
        """Initialize connection to the device."""
        try:
            if not self.eufy_login.mqtt_credentials:
                await self.eufy_login.checkLogin()

            creds = self.eufy_login.mqtt_credentials
            if not creds:
                raise UpdateFailed("Failed to retrieve MQTT credentials")

            self.client = EufyCleanClient(  # type: ignore[unreachable]
                device_id=self.device_id,
                user_id=creds["user_id"],
                app_name=creds["app_name"],
                thing_name=creds["thing_name"],
                access_key="",  # Unused
                ticket="",  # Unused
                openudid=self.eufy_login.openudid,
                certificate_pem=creds["certificate_pem"],
                private_key=creds["private_key"],
                device_model=self.device_model,
                endpoint=creds["endpoint_addr"],
            )

            self.client.set_on_message(self._handle_mqtt_message)
            await self.client.connect()

        except Exception as e:
            _LOGGER.error(
                f"Failed to initialize coordinator for {self.device_name}: {e}"
            )
            raise

    @callback
    def _handle_mqtt_message(self, payload: bytes) -> None:
        """Handle incoming MQTT message bytes."""
        try:
            # Parse MQTT wrapper and extract DPS data
            parsed = json.loads(payload.decode())
            if dps := parsed.get("payload", {}).get("data"):
                new_state = update_state(self.data, dps)
                self.async_set_updated_data(new_state)

        except Exception as e:
            _LOGGER.warning(f"Error handling MQTT message: {e}")

    async def async_send_command(self, command_dict: dict[str, Any]) -> None:
        """Send command to device."""
        if self.client:
            await self.client.send_command(command_dict)

    async def _async_update_data(self) -> VacuumState:
        """Fetch data from API endpoint.

        For this integration, we rely on push updates.
        This method is called by RequestRefresh or polling.
        We can potentially fetch HTTP state here if needed as fallback.
        For now, just return current state.
        """
        return self.data
