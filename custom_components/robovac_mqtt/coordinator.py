from __future__ import annotations

import json
import logging
from dataclasses import replace
from datetime import timedelta
from typing import Any

from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.storage import Store
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api.client import EufyCleanClient
from .api.cloud import EufyLogin
from .api.commands import build_command
from .api.legacy_commands import build_legacy_command
from .api.legacy_parser import update_state_legacy
from .api.parser import update_state
from .const import DOMAIN
from .models import VacuumState

_LOGGER = logging.getLogger(__name__)

_CLOUD_POLL_INTERVAL = timedelta(seconds=30)
_MAX_BACKOFF_INTERVAL = timedelta(minutes=5)
_FAILURE_THRESHOLD = 5  # Raise UpdateFailed after this many consecutive failures


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
        self.serial_number = device_info.get("deviceId")  # Usually deviceId is SN
        self.firmware_version = device_info.get("softVersion")
        self.eufy_login = eufy_login

        # API type determines parser/command builder
        self.api_type: str = device_info.get("apiType", "novel")
        # Connection type determines transport (push vs poll)
        self.connection_type: str = "mqtt" if device_info.get("mqtt", True) else "cloud"

        update_interval = _CLOUD_POLL_INTERVAL if self.connection_type == "cloud" else None

        _LOGGER.debug(
            "Coordinator created: device=%s, model=%s, api_type=%s, connection=%s, poll=%s",
            self.device_id, self.device_model, self.api_type, self.connection_type, update_interval,
        )

        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{self.device_name}",
            update_interval=update_interval,
        )

        self.client: EufyCleanClient | None = None
        self.data = VacuumState()
        self._consecutive_cloud_failures: int = 0
        self._base_poll_interval: timedelta | None = update_interval
        self._dock_idle_cancel: CALLBACK_TYPE | None = (
            None  # Timer for dock IDLE debounce
        )
        self._segment_update_cancel: CALLBACK_TYPE | None = (
            None  # Timer for segment updates debounce
        )
        self._pending_dock_status: str | None = None
        self.last_seen_segments: list[Any] | None = None
        self._store = Store(hass, 1, f"{DOMAIN}.{self.device_id}")

        if dps := device_info.get("dps"):
            self.data, _ = self._parse_dps(dps)

    def _parse_dps(self, dps: dict[str, Any]) -> tuple[VacuumState, dict[str, Any]]:
        """Dispatch DPS parsing based on api_type."""
        if self.api_type == "legacy":
            return update_state_legacy(self.data, dps)
        return update_state(self.data, dps)

    def build_device_command(self, command: str, **kwargs: Any) -> dict[str, Any]:
        """Build a DPS command dict appropriate for this device's API type."""
        if self.api_type == "legacy":
            return build_legacy_command(command, **kwargs)
        return build_command(command, **kwargs)

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info."""
        return DeviceInfo(
            identifiers={(DOMAIN, self.device_id)},
            name=self.device_name,
            manufacturer="Eufy",
            model=self.device_model,
            serial_number=self.serial_number,
            sw_version=self.firmware_version,
        )

    async def initialize(self) -> None:
        """Initialize connection to the device."""
        _LOGGER.debug("Initializing %s via %s", self.device_name, self.connection_type)
        if self.connection_type == "cloud":
            await self._initialize_cloud()
        else:
            await self._initialize_mqtt()

    async def _initialize_mqtt(self) -> None:
        """Initialize MQTT connection."""
        try:
            if not self.eufy_login.mqtt_credentials:
                await self.eufy_login.checkLogin()

            creds = self.eufy_login.mqtt_credentials
            if not creds:
                raise UpdateFailed("Failed to retrieve MQTT credentials")

            self.client = EufyCleanClient(
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
            await self.async_load_storage()

        except Exception as e:
            _LOGGER.error(
                "Failed to initialize MQTT coordinator for %s: %s", self.device_name, e
            )
            raise

    async def _initialize_cloud(self) -> None:
        """Initialize cloud polling connection."""
        _LOGGER.info(
            "Initializing cloud polling for %s (interval: %s)",
            self.device_name,
            _CLOUD_POLL_INTERVAL,
        )
        await self.async_load_storage()

    @callback
    def _handle_mqtt_message(self, payload: bytes) -> None:
        """Handle incoming MQTT message bytes."""
        try:
            # Parse MQTT wrapper and extract DPS data
            parsed = json.loads(payload.decode())
            payload_data = parsed.get("payload", {})
            # Payload can be a nested JSON string or a dict
            if isinstance(payload_data, str):
                payload_data = json.loads(payload_data)

            if dps := payload_data.get("data"):
                # Calculate new state based on connection
                new_state, changes = self._parse_dps(dps)

                # Only consider debounce if dock_status was explicitly set in this message
                # This prevents messages without dock info (like DPS 154) from
                # incorrectly resetting the debounce timer
                if "dock_status" in changes:
                    new_dock = changes["dock_status"]

                    # Determine the status we are currently "heading towards"
                    target_dock = (
                        self._pending_dock_status
                        if self._pending_dock_status
                        else self.data.dock_status
                    )

                    # If the reported dock status differs from our target,
                    # restart the debounce timer
                    if new_dock != target_dock:
                        _LOGGER.debug(
                            "Dock status change: %s -> %s (committed: %s). Restarting debounce.",
                            target_dock,
                            new_dock,
                            self.data.dock_status,
                        )
                        if self._dock_idle_cancel:
                            _LOGGER.debug("Cancelling existing debounce timer.")
                            self._dock_idle_cancel()

                        self._pending_dock_status = new_dock
                        self._dock_idle_cancel = async_call_later(
                            self.hass, 2.0, self._async_commit_dock_status
                        )

                # Always update the rest of the state immediately
                # But force dock_status to remain at the currently visible value
                # until the timer fires
                effective_current_status = self.data.dock_status
                state_to_publish = replace(
                    new_state, dock_status=effective_current_status
                )

                self.async_set_updated_data(state_to_publish)

                # Check for segment changes if rooms were updated (debounced)
                if "rooms" in changes:
                    if self._segment_update_cancel:
                        self._segment_update_cancel()
                    self._segment_update_cancel = async_call_later(
                        self.hass, 2.0, self._async_commit_segment_changes
                    )

        except Exception as e:
            _LOGGER.warning("Error handling MQTT message: %s", e)

    @callback
    def _async_commit_dock_status(self, _now: Any) -> None:
        """Commit the pending dock status."""
        _LOGGER.debug(
            "Debounce timer fired. Committing status: %s", self._pending_dock_status
        )
        self._dock_idle_cancel = None
        final_dock = self._pending_dock_status
        self._pending_dock_status = None

        if final_dock is None:
            _LOGGER.warning("Pending dock status was None when timer fired!")
            return

        # Apply the final dock status to the current data
        committed_state = replace(self.data, dock_status=final_dock)
        self.async_set_updated_data(committed_state)

    @callback
    def _async_commit_segment_changes(self, _now: Any) -> None:
        """Commit segment changes."""
        self._segment_update_cancel = None
        async_dispatcher_send(
            self.hass, f"{DOMAIN}_{self.device_id}_rooms_updated"
        )

    def async_shutdown_timers(self) -> None:
        """Cancel active debounce timers (call before teardown)."""
        if self._dock_idle_cancel:
            self._dock_idle_cancel()
            self._dock_idle_cancel = None
        if self._segment_update_cancel:
            self._segment_update_cancel()
            self._segment_update_cancel = None

    async def async_send_command(self, command_dict: dict[str, Any]) -> None:
        """Send command to device."""
        if not command_dict:
            _LOGGER.debug("Ignoring empty command for %s", self.device_name)
            return
        _LOGGER.debug(
            "Sending command to %s via %s: %s",
            self.device_name, self.connection_type, command_dict,
        )
        try:
            if self.connection_type == "cloud":
                await self.eufy_login.sendCloudCommand(self.device_id, command_dict)
            elif self.client:
                await self.client.send_command(command_dict)
            else:
                raise HomeAssistantError(
                    f"Cannot send command to {self.device_name}: no connection available"
                )
        except HomeAssistantError:
            raise
        except Exception as e:
            raise HomeAssistantError(
                f"Failed to send command to {self.device_name}: {e}"
            ) from e

    async def _async_update_data(self) -> VacuumState:
        """Fetch data from API endpoint.

        For MQTT devices, we rely on push updates.
        For cloud devices, poll via Tuya Cloud API with exponential backoff.
        """
        if self.connection_type == "cloud":
            _LOGGER.debug("Cloud poll starting for %s", self.device_name)
            try:
                dps = await self.eufy_login.getCloudDevice(self.device_id)
                if dps:
                    new_state, _ = self._parse_dps(dps)
                    self._on_cloud_success()
                    return new_state
            except Exception as e:
                _LOGGER.warning(
                    "Error polling cloud device %s: %s", self.device_name, e
                )

            # Poll returned None or raised — count as failure
            self._on_cloud_failure()
            if self._consecutive_cloud_failures >= _FAILURE_THRESHOLD:
                raise UpdateFailed(
                    f"Cloud device {self.device_name} unreachable after "
                    f"{self._consecutive_cloud_failures} consecutive failures"
                )

        return self.data

    def _on_cloud_success(self) -> None:
        """Reset failure counter and restore base poll interval."""
        if self._consecutive_cloud_failures > 0:
            _LOGGER.debug(
                "Cloud device %s recovered after %d failure(s)",
                self.device_name,
                self._consecutive_cloud_failures,
            )
        self._consecutive_cloud_failures = 0
        if self._base_poll_interval:
            self.update_interval = self._base_poll_interval

    def _on_cloud_failure(self) -> None:
        """Increment failure counter and apply exponential backoff."""
        self._consecutive_cloud_failures += 1
        if self._base_poll_interval:
            backoff = self._base_poll_interval * (
                2 ** min(self._consecutive_cloud_failures, 4)
            )
            self.update_interval = min(backoff, _MAX_BACKOFF_INTERVAL)
            _LOGGER.debug(
                "Cloud device %s: failure %d, next poll in %s",
                self.device_name,
                self._consecutive_cloud_failures,
                self.update_interval,
            )

    async def async_load_storage(self) -> None:
        """Load data from storage."""
        if data := await self._store.async_load():
            self.last_seen_segments = data.get("last_seen_segments")
            _LOGGER.debug(
                "Loaded %s segments from storage for %s",
                len(self.last_seen_segments) if self.last_seen_segments else 0,
                self.device_name,
            )

    async def async_save_segments(self, segments_payload: list[dict[str, Any]]) -> None:
        """Save segments to storage."""
        self.last_seen_segments = segments_payload
        await self._store.async_save({"last_seen_segments": segments_payload})
        _LOGGER.debug(
            "Saved %s segments to storage for %s",
            len(segments_payload),
            self.device_name,
        )
