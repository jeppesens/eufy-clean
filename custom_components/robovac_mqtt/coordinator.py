from __future__ import annotations

import base64
import json
import logging
import time
from dataclasses import replace
from typing import Any

from homeassistant.components.persistent_notification import (
    async_create as pn_async_create,
)
from homeassistant.components.persistent_notification import (
    async_dismiss as pn_async_dismiss,
)
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
from .api.map_stream import (
    MapData,
    parse_biz_protocol41,
    render_map_png,
    try_decode_as_dynamic_data,
    try_extract_map_data,
)
from .api.parser import update_state
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
)
from .models import VacuumState

_LOGGER = logging.getLogger(__name__)


def _px_dist(a: tuple[int, int], b: tuple[int, int]) -> float:
    """Euclidean distance between two pixel coords."""
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5


class EufyCleanCoordinator(DataUpdateCoordinator[VacuumState]):
    """Coordinator to manage Eufy Clean device connection and state."""

    def __init__(
        self,
        hass: HomeAssistant,
        eufy_login: EufyLogin,
        device_info: dict[str, Any],
        entry_id: str = "",
    ) -> None:
        """Initialize coordinator."""
        self.entry_id = entry_id
        self.device_id = device_info["deviceId"]
        self.device_model = device_info["deviceModel"]
        # DPS protocol ("novel" protobuf / "scalar" Tuya-int / "legacy"),
        # classified cloud-side by EufyLogin.checkApiType from the initial snapshot.
        self.api_type = device_info.get("apiType", "novel")
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
        self.data = VacuumState(device_model=self.device_model, api_type=self.api_type)
        self._dock_idle_cancel: CALLBACK_TYPE | None = (
            None  # Timer for dock IDLE debounce
        )
        self._segment_update_cancel: CALLBACK_TYPE | None = (
            None  # Timer for segment updates debounce
        )
        self._pending_dock_status: str | None = None
        self.last_seen_segments: list[Any] | None = None
        self._store = Store(hass, 1, f"{DOMAIN}.{self.device_id}")
        self._map_data_chan_id: int | None = None
        self._map_data: MapData | None = None
        self._robot_pixel: tuple[int, int] | None = None
        self._robot_trail: list[tuple[int, int]] = []
        self._dock_pixel: tuple[int, int] | None = None
        self._dock_arrival_time: float | None = None
        self._last_robot_render: float = 0.0
        self.map_image: bytes | None = None

        if dps := device_info.get("dps"):
            self.data, _ = update_state(self.data, dps)
            # Use the product name from the device itself (DPS 169) if the
            # cloud API only returned a generic placeholder like "Robovac".
            if self.data.product_name and self.device_name.lower() in (
                "robovac", "eufy robovac", ""
            ):
                self.device_name = self.data.product_name

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
            self.client.set_on_biz_message(self._handle_biz_message)
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
            parsed = json.loads(payload.decode("utf-8", errors="replace"))
            payload_data = parsed.get("payload", {})
            # Payload can be a nested JSON string or a dict
            if isinstance(payload_data, str):
                payload_data = json.loads(payload_data)

            if dps := payload_data.get("data"):
                # Calculate new state based on connection
                prev_activity = self.data.activity
                new_state, changes = update_state(self.data, dps)

                if "error_code" in changes:
                    if new_state.error_code != 0:
                        self._notify_error(new_state.error_code, new_state.error_message)
                    elif self.data.error_code != 0:
                        self._clear_error_notification()

                _rerender_after_update = False
                if "activity" in changes:
                    # Clear trail when a new cleaning session starts, but preserve it
                    # when the robot briefly docks to empty its bin and then resumes
                    # (dock visits under 10 minutes are treated as a pause, not a new session).
                    if new_state.activity == "cleaning" and prev_activity != "cleaning":
                        brief_dock_visit = (
                            self._dock_arrival_time is not None
                            and time.monotonic() - self._dock_arrival_time < 600
                        )
                        if not brief_dock_visit:
                            self._robot_trail.clear()
                            self._robot_pixel = None
                            _LOGGER.debug("New cleaning session — trail cleared for %s", self.device_name)
                        self._dock_arrival_time = None
                    # Capture dock position when robot docks or enters idle/sleep in dock
                    elif new_state.activity in ("docked", "idle") and self._robot_pixel is not None:
                        if self._dock_arrival_time is None:
                            self._dock_arrival_time = time.monotonic()
                        if self._dock_pixel != self._robot_pixel:
                            self._dock_pixel = self._robot_pixel
                            _LOGGER.debug("Dock position captured at %s for %s", self._dock_pixel, self.device_name)
                    # Schedule re-render after state update so _get_robot_status() sees
                    # the new activity (calling it here would read stale self.data).
                    if self._map_data is not None:
                        _rerender_after_update = True

                # Battery reaching 100% clears the charging badge — re-render so the
                # map updates without waiting for an activity change.
                if (
                    "battery_level" in changes
                    and new_state.activity in ("docked", "idle")
                    and self._map_data is not None
                ):
                    _rerender_after_update = True

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

                # Re-render now that self.data reflects the new activity/dock state.
                if _rerender_after_update:
                    self._rerender_map()

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
    def _handle_biz_message(self, payload: bytes) -> None:
        """Handle incoming biz/ MQTT message (map stream data)."""
        _LOGGER.debug(
            "biz/ message received (%d bytes) for %s: %s",
            len(payload),
            self.device_name,
            payload[:300],
        )
        result = parse_biz_protocol41(payload)
        if result is None:
            _LOGGER.debug("biz/ message not a map stream, skipping")
            return

        channel_id, hex_data = result
        _LOGGER.debug("biz/ protocol-41 channel_id=%d, hex_len=%d", channel_id, len(hex_data))

        # Small channels (<200 hex chars = ~100 bytes): try as robot pose (DynamicData).
        if len(hex_data) < 200:
            pose = try_decode_as_dynamic_data(hex_data)
            if pose is not None:
                robot_px = self._pose_to_pixel(pose[0], pose[1])
                if robot_px is not None:
                    # Only accumulate trail during active cleaning — poses that arrive
                    # while returning or docked would create through-wall lines on resume.
                    if self.data.activity == "cleaning":
                        if not self._robot_trail:
                            self._robot_trail.append(robot_px)
                        else:
                            d = _px_dist(self._robot_trail[-1], robot_px)
                            max_step = (
                                max(self._map_data.width, self._map_data.height) // 10
                                if self._map_data else 400
                            )
                            if 3 <= d <= max_step:
                                self._robot_trail.append(robot_px)
                    if robot_px != self._robot_pixel:
                        self._robot_pixel = robot_px
                        now = time.monotonic()
                        if now - self._last_robot_render >= 2.0 and self._map_data is not None:
                            self._last_robot_render = now
                            self._rerender_map()
            return

        # Large channels: try as map data.
        # Always attempt for: the cached map channel, unknown channel, or any >15 KB channel
        # (map arrives on a different channel during cleaning vs. map editing).
        is_map_candidate = (
            self._map_data_chan_id is None
            or channel_id == self._map_data_chan_id
            or len(hex_data) > 15000
        )
        if not is_map_candidate:
            return

        map_data = try_extract_map_data(hex_data)
        if map_data is None:
            return

        if self._map_data_chan_id != channel_id:
            self._map_data_chan_id = channel_id
            _LOGGER.debug(
                "Discovered map channel %d for %s", channel_id, self.device_name
            )

        # Preserve cached RoomOutline + zone/name data from the last MapBackup
        # when a plain Map update arrives (plain Map has none of these).
        if self._map_data is not None and map_data.room_pixels is None:
            map_data.room_pixels = self._map_data.room_pixels
            map_data.room_outline_width = self._map_data.room_outline_width
            map_data.room_outline_height = self._map_data.room_outline_height
            map_data.room_outline_origin_x = self._map_data.room_outline_origin_x
            map_data.room_outline_origin_y = self._map_data.room_outline_origin_y
            map_data.room_names = self._map_data.room_names
            map_data.virtual_walls = self._map_data.virtual_walls
            map_data.forbidden_zones = self._map_data.forbidden_zones
            map_data.ban_mop_zones = self._map_data.ban_mop_zones

        self._map_data = map_data
        self._rerender_map()

    def _pose_to_pixel(self, x_cm: int, y_cm: int) -> tuple[int, int] | None:
        """Convert robot pose (cm) to map pixel coordinates."""
        if self._map_data is None:
            return None
        res = self._map_data.resolution or 5
        px = round((x_cm - self._map_data.origin_x) / res)
        py = round((y_cm - self._map_data.origin_y) / res)
        if 0 <= px < self._map_data.width and 0 <= py < self._map_data.height:
            return px, py
        return None

    def _get_robot_status(self) -> str | None:
        """Return a status badge string for the current dock/activity state."""
        dock = self.data.dock_status
        activity = self.data.activity
        if dock == "Washing":
            return "washing"
        if dock == "Drying":
            return "drying"
        if dock == "Emptying dust":
            return "emptying"
        if dock in ("Adding clean water", "Recycling waste water", "Making disinfectant", "Cutting hair"):
            return "station"
        if activity in ("docked", "idle"):
            # "idle" covers sleep/standby while the robot rests in the dock.
            batt = self.data.battery_level
            if batt is not None and batt >= 100:
                return None  # full battery — no charging badge
            return "charging"
        return None

    def _rerender_map(self) -> None:
        """Re-render the PNG from current map data and robot position."""
        if self._map_data is None:
            return
        # When docked/idle, show robot at the known dock pixel rather than last pose.
        robot_px = (
            self._dock_pixel
            if self.data.activity in ("docked", "idle") and self._dock_pixel is not None
            else self._robot_pixel
        )
        entry = self.hass.config_entries.async_get_entry(self.entry_id)
        opts = entry.options if entry else {}
        max_px = int(opts.get(CONF_MAP_MAX_PX, DEFAULT_MAP_MAX_PX))
        robot_style = opts.get(CONF_ROBOT_STYLE, DEFAULT_ROBOT_STYLE)
        png = render_map_png(
            self._map_data,
            robot_pixel=robot_px,
            robot_trail=self._robot_trail or None,
            dock_pixel=self._dock_pixel,
            robot_status=self._get_robot_status(),
            max_px=max_px,
            robot_style=robot_style,
        )
        self.map_image = png
        _LOGGER.debug("Map image updated (%d bytes PNG) for %s", len(png), self.device_name)
        self.hass.async_create_task(self._async_save_map_image())
        async_dispatcher_send(self.hass, f"{DOMAIN}_{self.device_id}_map_updated")

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
        if self._map_data is not None:
            self._rerender_map()

    @callback
    def _async_commit_segment_changes(self, _now: Any) -> None:
        """Commit segment changes."""
        self._segment_update_cancel = None
        async_dispatcher_send(self.hass, f"{DOMAIN}_{self.device_id}_rooms_updated")

    def _notify_error(self, code: int, message: str) -> None:
        """Fire error notifications through configured channels."""
        entry = self.hass.config_entries.async_get_entry(self.entry_id)
        opts = entry.options if entry else {}
        title = f"{self.device_name} Error"
        msg = f"Error {code}: {message.title()}"
        if opts.get(CONF_NOTIFY_DESKTOP, DEFAULT_NOTIFY_DESKTOP):
            pn_async_create(
                self.hass,
                message=msg,
                title=title,
                notification_id=f"{DOMAIN}_{self.device_id}_error",
            )
        mobile_svc = opts.get(CONF_NOTIFY_MOBILE_SERVICE, DEFAULT_NOTIFY_MOBILE_SERVICE).strip()
        if mobile_svc:
            self.hass.async_create_task(
                self.hass.services.async_call(
                    "notify", mobile_svc,
                    {"title": title, "message": msg},
                    blocking=False,
                )
            )

    def _clear_error_notification(self) -> None:
        """Dismiss the persistent error notification when error clears."""
        pn_async_dismiss(self.hass, notification_id=f"{DOMAIN}_{self.device_id}_error")

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
            if map_b64 := data.get("map_image_png"):
                self.map_image = base64.b64decode(map_b64)
                _LOGGER.debug(
                    "Loaded cached map image (%d bytes) for %s",
                    len(self.map_image),
                    self.device_name,
                )
            if trail := data.get("robot_trail"):
                self._robot_trail = [tuple(p) for p in trail]
                _LOGGER.debug(
                    "Loaded robot trail (%d points) for %s",
                    len(self._robot_trail),
                    self.device_name,
                )
            if dp := data.get("dock_pixel"):
                self._dock_pixel = tuple(dp)
            if md_raw := data.get("map_data"):
                try:
                    self._map_data = MapData(
                        raw_pixels=base64.b64decode(md_raw["raw_pixels"]),
                        width=md_raw["width"],
                        height=md_raw["height"],
                        origin_x=md_raw["origin_x"],
                        origin_y=md_raw["origin_y"],
                        resolution=md_raw["resolution"],
                        room_pixels=base64.b64decode(md_raw["room_pixels"]) if md_raw.get("room_pixels") else None,
                        room_outline_width=md_raw.get("room_outline_width", 0),
                        room_outline_height=md_raw.get("room_outline_height", 0),
                        room_outline_origin_x=md_raw.get("room_outline_origin_x", 0),
                        room_outline_origin_y=md_raw.get("room_outline_origin_y", 0),
                        room_names={int(k): v for k, v in md_raw.get("room_names", {}).items()},
                        virtual_walls=[(tuple(w[0]), tuple(w[1])) for w in md_raw.get("virtual_walls", [])],
                        forbidden_zones=[[tuple(p) for p in zone] for zone in md_raw.get("forbidden_zones", [])],
                        ban_mop_zones=[[tuple(p) for p in zone] for zone in md_raw.get("ban_mop_zones", [])],
                    )
                    _LOGGER.debug("Loaded map data from storage for %s", self.device_name)
                except Exception as exc:
                    _LOGGER.warning("Failed to restore map data for %s: %s", self.device_name, exc)

    async def _async_save_map_image(self) -> None:
        """Persist the current map image, trail, and raw map data to storage."""
        if self.map_image is None:
            return
        data = await self._store.async_load() or {}
        data["map_image_png"] = base64.b64encode(self.map_image).decode()
        data["robot_trail"] = list(self._robot_trail)
        if self._dock_pixel is not None:
            data["dock_pixel"] = list(self._dock_pixel)
        if self._map_data is not None:
            md = self._map_data
            data["map_data"] = {
                "raw_pixels": base64.b64encode(md.raw_pixels).decode(),
                "width": md.width,
                "height": md.height,
                "origin_x": md.origin_x,
                "origin_y": md.origin_y,
                "resolution": md.resolution,
                "room_pixels": base64.b64encode(md.room_pixels).decode() if md.room_pixels else None,
                "room_outline_width": md.room_outline_width,
                "room_outline_height": md.room_outline_height,
                "room_outline_origin_x": md.room_outline_origin_x,
                "room_outline_origin_y": md.room_outline_origin_y,
                "room_names": {str(k): v for k, v in md.room_names.items()},
                "virtual_walls": [[list(p) for p in wall] for wall in md.virtual_walls],
                "forbidden_zones": [[list(p) for p in zone] for zone in md.forbidden_zones],
                "ban_mop_zones": [[list(p) for p in zone] for zone in md.ban_mop_zones],
            }
        await self._store.async_save(data)

    async def async_save_segments(self, segments_payload: list[dict[str, Any]]) -> None:
        """Save segments to storage."""
        self.last_seen_segments = segments_payload
        data = await self._store.async_load() or {}
        data["last_seen_segments"] = segments_payload
        await self._store.async_save(data)
        _LOGGER.debug(
            "Saved %s segments to storage for %s",
            len(segments_payload),
            self.device_name,
        )
