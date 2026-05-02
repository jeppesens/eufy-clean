from __future__ import annotations

import json
import logging
from dataclasses import replace
from typing import Any

from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.device_registry import (
    CONNECTION_NETWORK_MAC,
    DeviceInfo,
    format_mac,
)
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api.client import EufyCleanClient
from .api.cloud import EufyLogin
from .api.parser import update_state
from .const import DOMAIN, EVENT_DPS_179
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
        self.serial_number = device_info.get("deviceId")  # Usually deviceId is SN
        self.firmware_version = device_info.get("softVersion")
        self.eufy_login = eufy_login

        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{self.device_name}",
        )

        self.client: EufyCleanClient | None = None
        self.data = VacuumState()
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
            self.data, _ = update_state(self.data, dps)

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info."""
        info = DeviceInfo(
            identifiers={(DOMAIN, self.device_id)},
            name=self.device_name,
            manufacturer="Eufy",
            model=self.device_model,
            serial_number=self.serial_number,
            sw_version=self.firmware_version,
        )
        # Add MAC address from DPS 169 DeviceInfo if available
        if mac := self.data.device_mac:
            info["connections"] = {(CONNECTION_NETWORK_MAC, format_mac(mac))}
        return info

    async def initialize(self) -> None:
        """Initialize connection to the device."""
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
                "Failed to initialize coordinator for %s: %s", self.device_name, e
            )
            raise

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
                # Fire raw DPS 179 onto the HA event bus before any parsing so
                # external integrations can consume position telemetry directly.
                raw_179 = dps.get("179")
                if isinstance(raw_179, str):
                    try:
                        self.hass.bus.async_fire(
                            EVENT_DPS_179,
                            {
                                "device_id": self.device_id,
                                "device_name": self.device_name,
                                "device_model": self.device_model,
                                "payload": raw_179,
                            },
                        )
                    except Exception:
                        _LOGGER.exception(
                            "Failed to fire DPS 179 event for %s",
                            self.device_name,
                        )

                # Calculate new state based on connection
                new_state, changes = update_state(self.data, dps)

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
        async_dispatcher_send(self.hass, f"{DOMAIN}_{self.device_id}_rooms_updated")

    def async_shutdown_timers(self) -> None:
        """Cancel active debounce timers (call before teardown)."""
        if self._dock_idle_cancel:
            self._dock_idle_cancel()
            self._dock_idle_cancel = None
        if self._segment_update_cancel:
            self._segment_update_cancel()
            self._segment_update_cancel = None

    @callback
    def set_active_cleaning_targets(
        self,
        room_ids: list[int] | None = None,
        zone_count: int = 0,
    ) -> None:
        """Set active cleaning targets on state (called when HA sends commands)."""
        rooms = self.data.rooms
        if room_ids:
            room_lookup = {r["id"]: r.get("name", f"Room {r['id']}") for r in rooms}
            names = [room_lookup.get(rid, f"Room {rid}") for rid in room_ids]
            new_state = replace(
                self.data,
                active_room_ids=room_ids,
                active_room_names=", ".join(names),
                active_zone_count=0,
                current_scene_id=0,
                current_scene_name=None,
                received_fields=self.data.received_fields | {"active_room_ids"},
            )
        else:
            new_state = replace(
                self.data,
                active_room_ids=[],
                active_room_names="",
                active_zone_count=zone_count,
                current_scene_id=0,
                current_scene_name=None,
                received_fields=self.data.received_fields | {"active_room_ids"},
            )
        self.async_set_updated_data(new_state)

    @callback
    def set_active_scene(self, scene_id: int, scene_name: str | None) -> None:
        """Set the active cleaning scene on state."""
        new_state = replace(
            self.data,
            current_scene_id=scene_id,
            current_scene_name=scene_name,
            active_room_ids=[],
            active_room_names="",
            active_zone_count=0,
        )
        self.async_set_updated_data(new_state)

    async def async_send_command(self, command_dict: dict[str, Any]) -> None:
        """Send command to device."""
        if self.client:
            await self.client.send_command(command_dict)
        else:
            _LOGGER.warning("Cannot send command: no MQTT client available")

    async def _async_update_data(self) -> VacuumState:
        """Fetch data from API endpoint.

        For this integration, we rely on push updates.
        This method is called by RequestRefresh or polling.
        We can potentially fetch HTTP state here if needed as fallback.
        For now, just return current state.
        """
        return self.data

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
