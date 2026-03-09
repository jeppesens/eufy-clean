from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Any

from homeassistant.components.vacuum import (
    StateVacuumEntity,
    VacuumActivity,
    VacuumEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.issue_registry import (
    IssueSeverity,
    async_create_issue,
    async_delete_issue,
)
from homeassistant.helpers.update_coordinator import CoordinatorEntity

try:
    from homeassistant.components.vacuum import Segment
except ImportError:
    # Fallback for HA < 2026.3
    @dataclass
    class Segment:
        """Fallback Segment dataclass (matches HA 2026.3 signature)."""
        id: str
        name: str
        group: str | None = None

from .api.commands import build_command
from .const import DOMAIN, EUFY_CLEAN_NOVEL_CLEAN_SPEED
from .coordinator import EufyCleanCoordinator


def _serialize_segments(segments: list[Segment]) -> list[dict[str, Any]]:
    """Serialize segments for storage in config entry."""
    return [{"id": s.id, "name": s.name, "group": s.group} for s in segments]


def _deserialize_segments(data: list[dict[str, Any]]) -> list[Segment]:
    """Deserialize segments from config entry storage."""
    return [Segment(id=s["id"], name=s["name"], group=s.get("group")) for s in data]


def _segments_to_attributes(segments: list[Segment]) -> list[dict[str, str]]:
    """Convert segments into HA state attributes used by Matter support."""
    attributes: list[dict[str, Any]] = []
    for segment in segments:
        segment_id: str | int = segment.id
        if isinstance(segment_id, str) and segment_id.isdigit():
            segment_id = int(segment_id)
        attributes.append({"id": segment_id, "name": segment.name})
    return attributes


def _rooms_to_attributes(rooms: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Convert coordinator room data into state attributes."""
    if not rooms:
        return []

    return [
        {"id": int(room["id"]) if str(room["id"]).isdigit() else room["id"], "name": room.get("name") or f"Room {room['id']}"}
        for room in rooms
        if "id" in room
    ]


def _segment_name_map(segments: list[Segment]) -> dict[str, str]:
    """Return comparable segment id-to-name mapping."""
    return {segment.id: segment.name for segment in segments}

_LOGGER = logging.getLogger(__name__)

_LAST_SEEN_SEGMENTS_KEY = "last_seen_segments"

# CLEAN_AREA was added in HA 2026.3; fall back gracefully on older installs
_CLEAN_AREA_FEATURE = getattr(VacuumEntityFeature, "CLEAN_AREA", None)

_BASE_SUPPORTED_FEATURES = (
    VacuumEntityFeature.START
    | VacuumEntityFeature.PAUSE
    | VacuumEntityFeature.STOP
    | VacuumEntityFeature.STATE
    | VacuumEntityFeature.FAN_SPEED
    | VacuumEntityFeature.RETURN_HOME
    | VacuumEntityFeature.SEND_COMMAND
    | VacuumEntityFeature.LOCATE
    | VacuumEntityFeature.CLEAN_SPOT
)

_ACTIVITY_MAP: dict[str, VacuumActivity] = {
    "cleaning":  VacuumActivity.CLEANING,
    "docked":    VacuumActivity.DOCKED,
    "charging":  VacuumActivity.DOCKED,
    "error":     VacuumActivity.ERROR,
    "returning": VacuumActivity.RETURNING,
    "idle":      VacuumActivity.IDLE,
    "paused":    VacuumActivity.PAUSED,
}


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up vacuum entities for Eufy Clean devices."""
    data = hass.data[DOMAIN][config_entry.entry_id]
    coordinators: list[EufyCleanCoordinator] = data["coordinators"]

    entities = []
    for coordinator in coordinators:
        _LOGGER.debug("Adding vacuum entity for %s", coordinator.device_name)
        entities.append(RoboVacMQTTEntity(coordinator, config_entry))

    async_add_entities(entities)


class RoboVacMQTTEntity(CoordinatorEntity[EufyCleanCoordinator], StateVacuumEntity):
    """Eufy Clean Vacuum Entity."""

    _attr_has_entity_name = True
    _attr_name = None

    def __init__(self, coordinator: EufyCleanCoordinator, config_entry: ConfigEntry | None = None) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        self._attr_unique_id = coordinator.device_id
        self._config_entry = config_entry

        self._attr_device_info = coordinator.device_info

        self._attr_fan_speed_list: list[str] = [
            speed.value for speed in EUFY_CLEAN_NOVEL_CLEAN_SPEED
        ]
        # Initialize last seen segments if this is the first time and segments are available
        if config_entry:
            self._initialize_last_seen_segments()

    async def async_added_to_hass(self) -> None:
        """Run when entity about to be added to hass."""
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                f"{DOMAIN}_{self.coordinator.device_id}_rooms_updated",
                self._check_for_segment_changes,
            )
        )

    def _initialize_last_seen_segments(self) -> None:
        """Initialize last seen segments if not already stored and segments are available."""
        if self.last_seen_segments is None:
            current_segments = self._get_room_segments()
            if current_segments:
                self._store_last_seen_segments(current_segments)
                _LOGGER.info(
                    "Initialized last seen segments for %s: %d segments",
                    self.coordinator.device_name,
                    len(current_segments),
                )

    def _get_room_segments(self) -> list[Segment]:
        """Return segments derived from the latest mapped rooms."""
        rooms = self.coordinator.data.rooms or []
        return [
            Segment(id=str(room["id"]), name=room.get("name") or f"Room {room['id']}")
            for room in rooms
            if "id" in room
        ]

    def _get_extra_room_attributes(self) -> list[dict[str, str]]:
        """Return room attributes derived from current segments."""
        return _rooms_to_attributes(self.coordinator.data.rooms)

    def _get_extra_segment_attributes(self) -> list[dict[str, Any]]:
        """Return segment attributes derived from current segments."""
        return _segments_to_attributes(self._get_room_segments())

    def _get_segments_issue_id(self) -> str:
        """Return the repair issue id for segment changes."""
        return f"segments_changed_{self.coordinator.device_id}"

    def _has_config_entry(self) -> bool:
        """Return whether config-entry-backed segment persistence is available."""
        return self._config_entry is not None

    def _get_room_clean_defaults(self) -> dict[str, Any]:
        """Return default room-clean parameters derived from coordinator state."""
        defaults: dict[str, Any] = {}

        if self.coordinator.data.fan_speed and self.coordinator.data.fan_speed != "Standard":
            defaults["fan_speed"] = self.coordinator.data.fan_speed

        if self.coordinator.data.cleaning_mode and self.coordinator.data.cleaning_mode != "Vacuum":
            defaults["clean_mode"] = self.coordinator.data.cleaning_mode

        if "mop_water_level" in self.coordinator.data.received_fields:
            defaults["water_level"] = self.coordinator.data.mop_water_level

        if "cleaning_intensity" in self.coordinator.data.received_fields:
            defaults["clean_intensity"] = self.coordinator.data.cleaning_intensity

        return defaults

    def _merge_room_clean_defaults(self, params: dict[str, Any]) -> dict[str, Any]:
        """Merge caller params with coordinator-derived room-clean defaults."""
        merged = dict(params)
        defaults = self._get_room_clean_defaults()

        explicit_custom_keys = (
            "fan_speed",
            "water_level",
            "clean_times",
            "clean_mode",
            "clean_intensity",
            "edge_mopping",
        )
        has_explicit_custom = any(merged.get(key) is not None for key in explicit_custom_keys)

        if has_explicit_custom:
            return merged

        for key, value in defaults.items():
            merged.setdefault(key, value)

        return merged

    async def _async_send_room_clean(
        self,
        room_ids: list[int],
        map_id: int,
        mode: str = "GENERAL",
    ) -> None:
        """Send a room-clean command."""
        command_kwargs: dict[str, Any] = {"room_ids": room_ids, "map_id": map_id}
        if mode != "GENERAL":
            command_kwargs["mode"] = mode
        
        command = build_command("room_clean", **command_kwargs)
        await self.coordinator.async_send_command(command)

    async def _async_send_room_custom(
        self,
        room_config: list[dict[str, Any]] | list[int],
        map_id: int,
        **kwargs: Any,
    ) -> None:
        """Send room customization parameters."""
        command = build_command(
            "set_room_custom",
            room_config=room_config,
            map_id=map_id,
            **kwargs,
        )
        await self.coordinator.async_send_command(command)

    async def _async_handle_room_clean(self, params: dict[str, Any]) -> None:
        """Handle room_clean command with optional custom parameters."""
        map_id = params.get("map_id") or self.coordinator.data.map_id or 1

        # New-style: 'rooms' is a list of dicts with per-room config
        rooms_config = params.get("rooms")
        
        if rooms_config and isinstance(rooms_config, list):
            # Extract IDs for the clean command
            room_ids = [int(r["id"]) for r in rooms_config if "id" in r]

            # 1. Configure Room Params (Pass the list of dicts)
            await self._async_send_room_custom(rooms_config, map_id)

            # 2. Start Clean with Custom Mode
            await self._async_send_room_clean(room_ids, map_id, mode="CUSTOMIZE")
            return

        # Legacy-style: 'room_ids' list of ints + optional global params
        if "room_ids" not in params:
            return

        room_ids = params["room_ids"]
        merged_params = self._merge_room_clean_defaults(params)
        
        fan_speed = merged_params.get("fan_speed")
        water_level = merged_params.get("water_level")
        clean_times = merged_params.get("clean_times")
        clean_mode = merged_params.get("clean_mode")
        clean_intensity = merged_params.get("clean_intensity")
        edge_mopping = merged_params.get("edge_mopping")
        
        has_explicit_custom = (
            any([fan_speed, water_level, clean_times, clean_mode, clean_intensity])
            or edge_mopping is not None
        )
        
        if has_explicit_custom:
            # 1. Configure Room Params
            await self._async_send_room_custom(
                room_ids,
                map_id,
                fan_speed=fan_speed,
                water_level=water_level,
                clean_times=clean_times,
                clean_mode=clean_mode,
                clean_intensity=clean_intensity,
                edge_mopping=edge_mopping,
            )

            # 2. Start Clean with Custom Mode
            await self._async_send_room_clean(room_ids, map_id, mode="CUSTOMIZE")
            return

        # 1. Start Clean with GENERAL Mode
        await self._async_send_room_clean(room_ids, map_id)

    async def async_clean_segments(self, segment_ids: list[str], **kwargs: Any) -> None:
        """Clean specific segments with current custom parameters."""
        room_ids = [int(segment_id) for segment_id in segment_ids if segment_id.isdigit()]
        
        if not room_ids:
            return

        # Use the same room_clean handling logic that supports custom parameters
        params = {"room_ids": room_ids}
        await self._async_handle_room_clean(params)

    @property
    def supported_features(self) -> VacuumEntityFeature:
        """Return the features supported by the vacuum."""
        supported_features = _BASE_SUPPORTED_FEATURES
        if _CLEAN_AREA_FEATURE is not None:
            supported_features |= _CLEAN_AREA_FEATURE
        return supported_features

    @property
    def activity(self) -> VacuumActivity | None:
        """Return the current vacuum activity."""
        activity = self.coordinator.data.activity
        if activity in _ACTIVITY_MAP:
            return _ACTIVITY_MAP[activity]
        if self.coordinator.data.error_code:
            return VacuumActivity.ERROR
        return None
    @property
    def fan_speed(self) -> str | None:
        """Return the fan speed of the vacuum."""
        return self.coordinator.data.fan_speed

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the state attributes."""
        data = self.coordinator.data
        rooms = self._get_extra_room_attributes()
        segments = self._get_extra_segment_attributes()
        return {
            "fan_speed": data.fan_speed,
            "cleaning_time": data.cleaning_time,
            "cleaning_area": data.cleaning_area,
            "task_status": data.task_status,
            "trigger_source": data.trigger_source,
            "error_code": data.error_code,
            "error_message": data.error_message,
            "status_code": data.status_code,
            "work_mode": data.work_mode,
            "rooms": rooms,
            "segments": segments,
        }

    async def async_return_to_base(self, **kwargs: Any) -> None:
        """Set the vacuum cleaner to return to the dock."""
        await self.coordinator.async_send_command(build_command("return_to_base"))

    async def async_start(self, **kwargs: Any) -> None:
        """Start or resume the cleaning task."""
        if self.activity == VacuumActivity.PAUSED:
            await self.coordinator.async_send_command(build_command("play"))
        else:
            await self.coordinator.async_send_command(build_command("start_auto"))

    async def async_pause(self, **kwargs: Any) -> None:
        """Pause the cleaning task."""
        await self.coordinator.async_send_command(build_command("pause"))

    async def async_stop(self, **kwargs: Any) -> None:
        """Stop the cleaning task."""
        await self.coordinator.async_send_command(build_command("stop"))

    async def async_clean_spot(self, **kwargs: Any) -> None:
        """Perform a spot clean-up."""
        await self.coordinator.async_send_command(build_command("clean_spot"))

    async def async_locate(self, **kwargs: Any) -> None:
        """Locate the vacuum cleaner."""
        await self.coordinator.async_send_command(
            build_command("find_robot", active=True)
        )

    async def async_set_fan_speed(self, fan_speed: str, **kwargs: Any) -> None:
        """Set fan speed."""
        if fan_speed not in self.fan_speed_list:
            raise ValueError(f"Fan speed {fan_speed} not supported")

        await self.coordinator.async_send_command(
            build_command("set_fan_speed", fan_speed=fan_speed)
        )

    async def async_get_segments(self) -> list[Segment]:
        """Return list of cleanable segments."""
        return self._get_room_segments()

    @property
    def last_seen_segments(self) -> list[Segment] | None:
        """Return segments as seen by the user, when last mapping the areas."""
        stored_segments = self.coordinator.last_seen_segments
        if stored_segments is None:
            return None
        return _deserialize_segments(stored_segments)

    @callback
    def async_create_segments_issue(self) -> None:
        """Create a repair issue when vacuum segments have changed."""
        if not self._has_config_entry():
            _LOGGER.warning("Cannot create segments issue: no config entry available")
            return
        async_create_issue(
            hass=self.coordinator.hass,
            domain=DOMAIN,
            issue_id=self._get_segments_issue_id(),
            is_fixable=False,
            severity=IssueSeverity.WARNING,
            translation_key="segments_changed",
            translation_placeholders={"device_name": self.coordinator.device_name},
        )

    async def async_send_command(
        self,
        command: str,
        params: dict[str, Any] | list[Any] | None = None,
        **kwargs: Any,
    ) -> None:
        """Send a raw command to the vacuum."""
        if command == "scene_clean":
            if isinstance(params, dict) and "scene_id" in params:
                await self.coordinator.async_send_command(
                    build_command("scene_clean", scene_id=params["scene_id"])
                )
            return

        if command == "room_clean" and isinstance(params, dict):
            await self._async_handle_room_clean(params)
            return

        # Handle Apple Home app_segment_clean command
        if command == "app_segment_clean" and isinstance(params, list):
            # Convert to room_clean format
            room_ids = [int(room_id) for room_id in params if isinstance(room_id, (int, str, float)) and str(room_id).isdigit()]
            if room_ids:
                await self._async_handle_room_clean({"room_ids": room_ids})
                return
            return

        # Check if this is a basic start command that might need room info
        if command == "start" or command == "start_cleaning":
            # TODO: Add logic here to check for selected rooms and convert to room_clean
            pass

        command_kwargs: dict[str, Any] = {}
        if isinstance(params, dict):
            command_kwargs.update(params)
        command_kwargs.update(kwargs)

        command_dict = build_command(command, **command_kwargs)
        if command_dict:
            await self.coordinator.async_send_command(command_dict)
            return

        _LOGGER.warning(
            "Command %s with params %s generated an empty payload (invalid parameters).",
            command,
            params,
        )

    @callback
    def _check_for_segment_changes(self) -> None:
        """Check for segment changes and create issue if needed."""
        if not self._has_config_entry():
            # Cannot create issues without config entry
            return
        current_segments = self._get_room_segments()
        last_seen = self.last_seen_segments

        if last_seen is None:
            # No previous mapping stored — silently record the baseline so future
            # changes can be detected.  Do NOT raise an issue here; the user has
            # not yet had a chance to configure area mapping.
            if current_segments:
                _LOGGER.info(
                    "First time detecting segments for %s: storing baseline (%d segments)",
                    self.coordinator.device_name,
                    len(current_segments),
                )
                self._store_last_seen_segments(current_segments)
            return

        # Compare segment IDs and names
        current_dict = _segment_name_map(current_segments)
        last_dict = _segment_name_map(last_seen)

        if current_dict != last_dict:
            _LOGGER.info(
                "Segment changes detected for %s: creating repair issue",
                self.coordinator.device_name,
            )
            self.async_create_segments_issue()

    @callback
    def _store_last_seen_segments(self, segments: list[Segment]) -> None:
        """Store the current segments as last seen and clear any existing issue."""
        serialized_segments = _serialize_segments(segments)
        self.coordinator.hass.async_create_task(
            self.coordinator.async_save_segments(serialized_segments)
        )
        # Clear any existing segment change issue
        async_delete_issue(
            hass=self.coordinator.hass,
            domain=DOMAIN,
            issue_id=self._get_segments_issue_id(),
        )
        _LOGGER.info(
            "Updated last seen segments for %s: %d segments stored",
            self.coordinator.device_name,
            len(segments),
        )
