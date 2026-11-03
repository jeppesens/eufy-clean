from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import voluptuous as vol
from homeassistant.components.vacuum import (
    StateVacuumEntity,
    VacuumActivity,
    VacuumEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import (
    HomeAssistant,
    ServiceResponse,
    SupportsResponse,
    callback,
)
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_platform
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.issue_registry import (
    IssueSeverity,
    async_create_issue,
    async_delete_issue,
)
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api.commands import build_command
from .const import (
    API_TYPE_LEGACY,
    API_TYPE_NOVEL,
    API_TYPE_SCALAR,
    DOMAIN,
    EUFY_CLEAN_CLEANING_INTENSITIES,
    EUFY_CLEAN_CLEANING_MODES,
    EUFY_CLEAN_NOVEL_CLEAN_SPEED,
    EUFY_CLEAN_WATER_LEVELS,
    LEGACY_ROOM_FAN_LEVELS,
    LEGACY_ROOM_WATER_LEVELS,
    SCALAR_SUCTION_LEVELS,
)
from .coordinator import EufyCleanCoordinator
from .select import _format_option_label
from .utils import MAX_CLEAN_TIMES, MIN_CLEAN_TIMES

if TYPE_CHECKING:
    from homeassistant.components.vacuum import Segment
else:
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


def _serialize_segments(segments: list[Segment]) -> list[dict[str, Any]]:
    """Serialize segments for storage in config entry."""
    return [{"id": s.id, "name": s.name, "group": s.group} for s in segments]


def _deserialize_segments(data: list[dict[str, Any]]) -> list[Segment]:
    """Deserialize segments from config entry storage."""
    return [
        Segment(id=str(s["id"]), name=s["name"], group=s.get("group")) for s in data
    ]


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

    result: list[dict[str, Any]] = []
    for room in rooms:
        if "id" not in room:
            continue
        raw_id = room["id"]
        room_id = int(raw_id) if str(raw_id).isdigit() else raw_id
        name = room.get("name") or f"Room {raw_id}"
        result.append({"id": room_id, "name": name})
    return result


def _segment_name_map(segments: list[Segment]) -> dict[str, str]:
    """Return comparable segment id-to-name mapping."""
    return {segment.id: segment.name for segment in segments}


_LOGGER = logging.getLogger(__name__)

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
    "cleaning": VacuumActivity.CLEANING,
    "docked": VacuumActivity.DOCKED,
    "charging": VacuumActivity.DOCKED,
    "error": VacuumActivity.ERROR,
    "returning": VacuumActivity.RETURNING,
    "idle": VacuumActivity.IDLE,
    "paused": VacuumActivity.PAUSED,
}


PARALLEL_UPDATES = 1

_LEGACY_ROOM_LEVELS: dict[str, tuple[str, ...]] = {
    "fan_speed": LEGACY_ROOM_FAN_LEVELS,
    "water_level": LEGACY_ROOM_WATER_LEVELS,
}


def _check_legacy_room_levels(settings: dict[str, Any]) -> None:
    """Raise ServiceValidationError for a level a legacy customRooms row cannot hold.

    Names match case-insensitively, as the command builder reads them.
    """
    for key, levels in _LEGACY_ROOM_LEVELS.items():
        value = settings.get(key)
        if value is None:
            continue
        if isinstance(value, str) and value.lower() in (lv.lower() for lv in levels):
            continue
        raise ServiceValidationError(
            f"Room {key} {value!r} is not supported; choose one of {', '.join(levels)}"
        )


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

    # Backs the card's tap-a-room selection; the registration de-dupes across entries.
    platform = entity_platform.async_get_current_platform()
    clean_times = vol.All(
        vol.Coerce(int), vol.Range(min=MIN_CLEAN_TIMES, max=MAX_CLEAN_TIMES)
    )
    platform.async_register_entity_service(
        "room_at_point",
        {
            vol.Required("x"): vol.All(vol.Coerce(float), vol.Range(min=0, max=1)),
            vol.Required("y"): vol.All(vol.Coerce(float), vol.Range(min=0, max=1)),
        },
        "async_room_at_point",
        supports_response=SupportsResponse.ONLY,
    )
    platform.async_register_entity_service(
        "map_load",
        {
            vol.Required("cloud_mapid"): vol.All(vol.Coerce(int), vol.Range(min=1)),
            vol.Optional("seq", default=1): vol.All(vol.Coerce(int), vol.Range(min=0)),
        },
        "async_map_load",
    )
    # Local only: prunes the learn-as-seen Switch Map list.
    platform.async_register_entity_service(
        "forget_map",
        {
            vol.Required("cloud_mapid"): vol.All(vol.Coerce(int), vol.Range(min=1)),
        },
        "async_forget_map",
    )
    # Legacy per-room settings persist in the map, so scheduled and auto cleans use
    # them too — unlike the novel room_clean per-call parameters.
    platform.async_register_entity_service(
        "set_room_config",
        {
            vol.Required("room"): vol.Coerce(str),
            vol.Optional("suction"): vol.In(LEGACY_ROOM_FAN_LEVELS),
            vol.Optional("wash"): vol.In(LEGACY_ROOM_WATER_LEVELS),
            vol.Optional("clean_times"): clean_times,
        },
        "async_set_room_config",
    )
    # Tuya cloud timer / scalar DPS 151.
    platform.async_register_entity_service(
        "set_schedule",
        {
            # No defaults: a field left out keeps the edited schedule's value.
            vol.Optional("time"): cv.string,
            vol.Optional("schedule_id"): vol.Any(cv.positive_int, cv.string),
            vol.Optional("days"): cv.ensure_list,
            vol.Optional("enabled"): cv.boolean,
            vol.Optional("suction"): cv.string,
            vol.Optional("wash"): cv.string,
            vol.Optional("rooms"): cv.ensure_list,
            vol.Optional("clean_times"): clean_times,
            vol.Optional("mode"): cv.string,
        },
        "async_set_schedule",
    )
    platform.async_register_entity_service(
        "delete_schedule",
        {
            vol.Optional("schedule_id"): vol.Any(cv.positive_int, cv.string),
        },
        "async_delete_schedule",
    )
    platform.async_register_entity_service(
        "enable_schedule",
        {
            vol.Required("enabled"): cv.boolean,
            vol.Optional("schedule_id"): vol.Any(cv.positive_int, cv.string),
        },
        "async_enable_schedule",
    )


class RoboVacMQTTEntity(CoordinatorEntity[EufyCleanCoordinator], StateVacuumEntity):
    """Eufy Clean Vacuum Entity."""

    _attr_has_entity_name = True
    _attr_name = None

    def __init__(
        self, coordinator: EufyCleanCoordinator, config_entry: ConfigEntry | None = None
    ) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        self._attr_unique_id = coordinator.device_id
        self._config_entry = config_entry

        self._attr_device_info = coordinator.device_info

        # On scalar devices BoostIQ is a separate switch (DPS 118), not a 5th speed.
        if coordinator.api_type == API_TYPE_SCALAR:
            self._attr_fan_speed_list: list[str] = list(SCALAR_SUCTION_LEVELS)
        elif coordinator.api_type == API_TYPE_LEGACY:
            self._attr_fan_speed_list = coordinator.legacy_fan_speeds
        else:
            self._attr_fan_speed_list = [
                speed.value for speed in EUFY_CLEAN_NOVEL_CLEAN_SPEED
            ]
        # Fixed for the life of the entity, so build it once rather than per read.
        self._room_clean_options = self._build_room_clean_options()

        if config_entry:
            self._initialize_last_seen_segments()

    def _build_room_clean_options(self) -> dict[str, Any]:
        """Per-room option vocabularies THIS device's room-clean builder accepts.

        The card renders one field per key and nothing for an absent key: the
        firmware silently ignores a value it does not declare, so an undeclared
        control would do nothing with no error anywhere. A list is an enum field's
        vocabulary; ``True`` means supported but not an enum.
        """
        if self.coordinator.api_type == API_TYPE_LEGACY:
            # A legacy ``customRooms`` document carries suction, water and repeat
            # count only; the other fields do not exist in it.
            return {
                "fan_speed": list(LEGACY_ROOM_FAN_LEVELS),
                "water_level": list(LEGACY_ROOM_WATER_LEVELS),
                "clean_times": True,
            }
        return {
            "clean_mode": list(EUFY_CLEAN_CLEANING_MODES),
            "fan_speed": list(self.fan_speed_list or []),
            "water_level": list(EUFY_CLEAN_WATER_LEVELS),
            "clean_intensity": list(EUFY_CLEAN_CLEANING_INTENSITIES),
            "clean_times": True,
            "edge_mopping": True,
        }

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
        if self.stored_last_seen_segments is None:
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
        """Return default room-clean parameters derived from coordinator state.

        "Standard" fan speed and "Vacuum" mode are omitted: they are the factory
        defaults, and sending them would force CUSTOMIZE mode for no gain.
        """
        defaults: dict[str, Any] = {}

        if (
            self.coordinator.data.fan_speed
            and self.coordinator.data.fan_speed != "Standard"
        ):
            defaults["fan_speed"] = self.coordinator.data.fan_speed

        if (
            self.coordinator.data.cleaning_mode
            and self.coordinator.data.cleaning_mode != "Vacuum"
        ):
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
        has_explicit_custom = any(
            merged.get(key) is not None for key in explicit_custom_keys
        )

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

        command = self.coordinator.build_device_command("room_clean", **command_kwargs)
        self.coordinator.set_active_cleaning_targets(room_ids=room_ids)
        await self.coordinator.async_send_command(command)

    async def _async_send_room_custom(
        self,
        room_config: list[dict[str, Any]] | list[int],
        map_id: int,
        **kwargs: Any,
    ) -> None:
        """Send room customization parameters."""
        command = self.coordinator.build_device_command(
            "set_room_custom",
            room_config=room_config,
            map_id=map_id,
            **kwargs,
        )
        await self.coordinator.async_send_command(command)

    async def _async_send_legacy_room_custom(
        self, rooms_config: list[dict[str, Any]]
    ) -> None:
        """Apply per-room settings on a legacy device without collapsing the rest.

        A room the caller left entirely unset is not made a target, so selecting it
        for a clean never writes an override it did not have.

        Raises:
            ServiceValidationError: a fan/water level customRooms cannot store.
            HomeAssistantError: the coordinator refused the write.
        """
        targets: dict[int, dict[str, Any]] = {}
        for room in rooms_config:
            settings = {
                key: room.get(key)
                for key in ("fan_speed", "water_level", "clean_times")
                if room.get(key) is not None
            }
            if not settings:
                continue
            _check_legacy_room_levels(settings)
            try:
                targets[int(room["id"])] = settings
            except (KeyError, TypeError, ValueError):
                _LOGGER.warning("Skipping room with invalid id: %s", room.get("id"))
        if targets and not await self.coordinator.async_set_room_configs(targets):
            raise HomeAssistantError(
                f"Per-room settings for room(s) {sorted(targets)} were refused; "
                "the room clean was not sent."
            )

    async def _async_handle_room_clean(self, params: dict[str, Any]) -> None:
        """Handle room_clean command with optional custom parameters."""
        map_id = params.get("map_id") or self.coordinator.resolve_map_id()

        # New-style: 'rooms' is a list of dicts with per-room config
        rooms_config = params.get("rooms")

        if rooms_config and isinstance(rooms_config, list):
            room_ids: list[int] = []
            valid_rooms: list[dict[str, Any]] = []
            for r in rooms_config:
                if not isinstance(r, dict) or "id" not in r:
                    continue
                try:
                    room_ids.append(int(r["id"]))
                    valid_rooms.append(r)
                except (ValueError, TypeError):
                    _LOGGER.warning("Skipping room with invalid id: %s", r.get("id"))

            if not room_ids:
                return

            if self.coordinator.api_type == API_TYPE_LEGACY:
                # customRooms is REPLACE-ALL: any room missing from it is collapsed,
                # so the coordinator resends the ones that already have an override.
                await self._async_send_legacy_room_custom(valid_rooms)
            else:
                await self._async_send_room_custom(valid_rooms, map_id)

            await self._async_send_room_clean(room_ids, map_id, mode="CUSTOMIZE")
            return

        # Legacy-style: 'room_ids' list of ints + optional global params
        if "room_ids" not in params:
            return

        room_ids = params["room_ids"]
        # Legacy settings persist per room, so only what the caller passed is written.
        merged_params = (
            dict(params)
            if self.coordinator.api_type == API_TYPE_LEGACY
            else self._merge_room_clean_defaults(params)
        )

        fan_speed = merged_params.get("fan_speed")
        water_level = merged_params.get("water_level")
        clean_times = merged_params.get("clean_times")
        clean_mode = merged_params.get("clean_mode")
        clean_intensity = merged_params.get("clean_intensity")
        edge_mopping = merged_params.get("edge_mopping")

        has_explicit_custom = (
            any(
                v is not None
                for v in [
                    fan_speed,
                    water_level,
                    clean_times,
                    clean_mode,
                    clean_intensity,
                ]
            )
            or edge_mopping is not None
        )

        if has_explicit_custom:
            if self.coordinator.api_type == API_TYPE_LEGACY:
                # Same REPLACE-ALL hazard as above; these settings are global, so
                # every selected room gets the same row.
                await self._async_send_legacy_room_custom(
                    [
                        {
                            "id": room_id,
                            "fan_speed": fan_speed,
                            "water_level": water_level,
                            "clean_times": clean_times,
                        }
                        for room_id in room_ids
                    ]
                )
            else:
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

            await self._async_send_room_clean(room_ids, map_id, mode="CUSTOMIZE")
            return

        await self._async_send_room_clean(room_ids, map_id)

    async def _async_handle_set_nogo_zones(self, params: dict[str, Any]) -> None:
        """Handle a ``set_nogo_zones`` command from the card.

        ``forbidden``/``ban_mop``/``walls``: normalized ``(x0, y0, x1, y1)`` rects on
        the rendered map image, or explicit points (4 corners, or 2 endpoints) for a
        rotated shape. A wall is a LINE between its two endpoints, not an area.
        ``remove_*`` and ``move_*`` address existing shapes by INDEX into the order
        ``robovac_mqtt/map/geometry`` serves (optionally guarded by ``revision``), so
        surviving shapes never round-trip through image coordinates, which clamp to
        the image and would move anything outside it. ``move_*`` entries are
        ``{"index": i, "dx": cm, "dy": cm, "rotate": radians}`` in the world frame.
        ``replace`` (default false) sends only what is supplied: the underlying DPS
        document is replace-all, so merging is the safe default.
        """
        forbidden = params.get("forbidden") or params.get("zones") or []
        ban_mop = params.get("ban_mop") or []
        walls = params.get("walls") or []
        remove_forbidden = params.get("remove_forbidden") or []
        remove_ban_mop = params.get("remove_ban_mop") or []
        remove_walls = params.get("remove_walls") or []
        move_forbidden = params.get("move_forbidden") or []
        move_ban_mop = params.get("move_ban_mop") or []
        move_walls = params.get("move_walls") or []
        replace = bool(params.get("replace", False))
        revision = params.get("revision")
        if not all(isinstance(v, list) for v in (forbidden, ban_mop, walls)):
            raise HomeAssistantError(
                "set_nogo_zones: 'forbidden', 'ban_mop' and 'walls' must be lists"
            )
        if not all(
            isinstance(v, list)
            for v in (remove_forbidden, remove_ban_mop, remove_walls)
        ):
            raise HomeAssistantError(
                "set_nogo_zones: 'remove_forbidden', 'remove_ban_mop' and "
                "'remove_walls' must be lists of indices"
            )
        if not all(
            isinstance(v, list) for v in (move_forbidden, move_ban_mop, move_walls)
        ):
            raise HomeAssistantError(
                "set_nogo_zones: 'move_forbidden', 'move_ban_mop' and 'move_walls' "
                "must be lists of {index, dx, dy, rotate} entries"
            )
        removing = bool(
            remove_forbidden or remove_ban_mop or remove_walls
            or move_forbidden or move_ban_mop or move_walls
        )
        if not forbidden and not ban_mop and not walls and not replace and not removing:
            raise HomeAssistantError(
                "set_nogo_zones called with no shapes. Pass replace: true to "
                "clear the existing restricted geometry deliberately."
            )
        await self.coordinator.async_set_nogo_zones(
            add_forbidden=forbidden,
            add_ban_mop=ban_mop,
            add_walls=walls,
            remove_forbidden=remove_forbidden,
            remove_ban_mop=remove_ban_mop,
            remove_walls=remove_walls,
            move_forbidden=move_forbidden,
            move_ban_mop=move_ban_mop,
            move_walls=move_walls,
            expect_revision=None if revision is None else int(revision),
            replace=replace,
        )

    async def _async_handle_zone_clean(self, params: dict[str, Any]) -> None:
        """Handle a zone_clean command.

        ``params['zones']``: normalized rects ``(x0, y0, x1, y1)`` as fractions (0-1)
        of the rendered map image, converted to world-cm quads against the current map.
        """
        rects = params.get("zones") or params.get("rects")
        if not rects or not isinstance(rects, list):
            raise HomeAssistantError(
                "zone_clean called without a 'zones' list of rectangles"
            )

        quads_cm = self.coordinator.normalized_rects_to_quads_cm(rects)
        if not quads_cm:
            raise HomeAssistantError(
                "zone_clean: no map available yet (run a clean once so the map "
                "populates), or every rectangle was invalid — nothing was sent"
            )

        map_id = params.get("map_id") or self.coordinator.resolve_map_id()
        clean_times = int(params.get("clean_times", 1))

        command = self.coordinator.build_device_command(
            "zone_clean",
            zones_cm=quads_cm,
            map_id=map_id,
            clean_times=clean_times,
        )
        # A builder that declines returns {}; returning quietly would answer 200
        # while the robot never moves.
        if not command:
            raise HomeAssistantError(
                f"This device ({self.coordinator.api_type}) could not build a "
                "zone_clean command. If it is a legacy device, it must expose the "
                "mapOperations datapoint (DPS 124) for zone cleaning."
            )

        self.coordinator.set_active_cleaning_targets(zone_count=len(quads_cm))
        await self.coordinator.async_send_command(command)

    async def async_clean_segments(self, segment_ids: list[str], **kwargs: Any) -> None:
        """Clean specific segments with current custom parameters."""
        room_ids = [
            int(segment_id) for segment_id in segment_ids if segment_id.isdigit()
        ]

        if not room_ids:
            return

        params = {"room_ids": room_ids}
        await self._async_handle_room_clean(params)

    async def async_room_at_point(self, x: float, y: float) -> ServiceResponse:
        """Resolve which room sits under a normalized (0-1) point on the rendered map.

        ``x``/``y`` are fractions of the map image, top-left origin. A ``room_id`` of
        None means no room is there.
        """
        room_id, room_name = self.coordinator.room_id_at_normalized(x, y)
        return {"room_id": room_id, "room_name": room_name or ""}

    async def async_map_load(self, cloud_mapid: int, seq: int = 1) -> None:
        """Switch the active map to a saved multi-map by its cloud map id.

        The map and room list load immediately, but the robot re-localizes only when
        it next moves, so map-tap and zone targeting are unreliable until then.
        """
        if self.coordinator.api_type != API_TYPE_NOVEL:
            raise HomeAssistantError(
                "Switching maps is only supported on novel (protobuf) devices, "
                f"not api_type={self.coordinator.api_type}"
            )
        command = self.coordinator.build_device_command(
            "map_load", cloud_mapid=int(cloud_mapid), seq=int(seq)
        )
        if not command:
            raise HomeAssistantError(
                "Failed to build map_load command "
                "(unsupported device or invalid map id)"
            )
        await self.coordinator.async_send_command(command)

    async def async_forget_map(self, cloud_mapid: int) -> None:
        """Remove a saved map from the Switch Map list (``last_seen_maps``).

        The list is learn-as-seen — the device exposes no authoritative map list —
        so a map deleted on the device lingers until pruned here. Local only; the
        active map cannot be forgotten because it would immediately re-seed.
        """
        cloud_mapid = int(cloud_mapid)
        if cloud_mapid == self.coordinator.data.map_id:
            raise HomeAssistantError(
                f"Cannot forget map {cloud_mapid} — it is the active map."
            )
        await self.coordinator.async_forget_map(cloud_mapid)

    def _resolve_room_id(self, room: str) -> Any | None:
        """Resolve a room name, Clean Room option label or numeric id to a room id.

        Searches the Clean Room select's rooms (overrides first), then the map
        rooms; names and labels match case-insensitively.
        """
        rooms = [*self.coordinator.selectable_rooms(), *self.coordinator.data.rooms]
        needle = str(room).strip().lower()
        for r in rooms:
            if r.get("id") is None:
                continue
            if needle in (
                str(r.get("name") or "").strip().lower(),
                _format_option_label(r, "Room").lower(),
            ):
                return r["id"]
        try:
            rid = int(needle)
        except (TypeError, ValueError):
            return None
        return rid if any(r.get("id") == rid for r in rooms) else None

    async def async_set_room_config(
        self,
        room: str,
        suction: str | None = None,
        wash: str | None = None,
        clean_times: int | None = None,
    ) -> None:
        """Set a room's persistent suction / wash level / repeat count.

        Legacy only: writes the map's ``customRooms`` so scheduled and auto cleans
        use them. Novel devices take per-room parameters on ``room_clean`` instead.
        """
        if not self.coordinator.legacy_room_config_supported:
            raise HomeAssistantError(
                "Per-room config isn't available on this device. On X-series "
                "vacuums, pass per-room parameters with a room_clean send_command."
            )
        if suction is None and wash is None and clean_times is None:
            raise HomeAssistantError(
                "Specify at least one of suction, wash, or clean_times."
            )
        room_id = self._resolve_room_id(room)
        if room_id is None:
            raise HomeAssistantError(f"Unknown room: {room!r}")
        # customRooms rows exist only for map rooms; an override id may have none.
        if not any(r.get("id") == room_id for r in self.coordinator.data.rooms):
            raise HomeAssistantError(f"Room {room!r} is not on the current map.")

        if not await self.coordinator.async_set_room_config(
            room_id, fan_speed=suction, water_level=wash, clean_times=clean_times
        ):
            raise HomeAssistantError("Failed to set room configuration.")

    async def async_set_schedule(
        self,
        time: str | None = None,
        schedule_id: int | str | None = None,
        days: list[str] | str | None = None,
        enabled: bool | None = None,
        suction: str | None = None,
        wash: str | None = None,
        rooms: list[int | str] | str | None = None,
        clean_times: int | None = None,
        mode: str | None = None,
    ) -> None:
        """Add a cleaning schedule, or change the given fields of an existing one."""
        room_ids: list[int] | None = None
        if rooms is not None:
            room_list: list[int | str] = (
                [rooms] if isinstance(rooms, (int, str)) else list(rooms)
            )
            room_ids = []
            for r in room_list:
                rid = self._resolve_room_id(str(r))
                if rid is None:
                    raise HomeAssistantError(f"Unknown room in schedule: {r!r}")
                room_ids.append(rid)

        await self.coordinator.async_set_schedule(
            schedule_id=schedule_id,
            time=time,
            days=days,
            enabled=enabled,
            suction=suction,
            water=wash,
            rooms=room_ids,
            clean_times=clean_times,
            mode=mode,
        )

    async def async_delete_schedule(self, schedule_id: int | str | None = None) -> None:
        """Delete a cleaning schedule."""
        await self.coordinator.async_delete_schedule(schedule_id)

    async def async_enable_schedule(self, enabled: bool, schedule_id: int | str | None = None) -> None:
        """Enable or disable a cleaning schedule."""
        await self.coordinator.async_set_schedule_status(schedule_id, enabled)

    @property
    def supported_features(self) -> VacuumEntityFeature:
        """Return the features supported by the vacuum."""
        supported_features = _BASE_SUPPORTED_FEATURES
        if self.coordinator.api_type == API_TYPE_SCALAR:
            # Vacuum-only Tuya device: no areas and no spot clean.
            return supported_features & ~VacuumEntityFeature.CLEAN_SPOT
        if _CLEAN_AREA_FEATURE is not None and self.coordinator.api_type != API_TYPE_LEGACY:
            supported_features |= _CLEAN_AREA_FEATURE
        return supported_features

    @property
    def activity(self) -> VacuumActivity | None:
        """Return the current vacuum activity."""
        activity = self.coordinator.data.activity
        if activity in _ACTIVITY_MAP:
            return _ACTIVITY_MAP[activity]
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
            "cleaning_time": data.cleaning_time,
            "cleaning_area": data.cleaning_area,
            "task_status": data.task_status,
            "trigger_source": data.trigger_source,
            "error_code": data.error_code,
            "error_message": data.error_message,
            "error_codes": data.error_codes,
            "warn_codes": data.warn_codes,
            "status_code": data.status_code,
            "work_mode": data.work_mode,
            "active_room_ids": data.active_room_ids,
            "active_zone_count": data.active_zone_count,
            "rooms": rooms,
            "segments": segments,
            "room_clean_options": self._room_clean_options,
        }

    async def async_return_to_base(self, **kwargs: Any) -> None:
        """Set the vacuum cleaner to return to the dock."""
        await self.coordinator.async_send_command(
            self.coordinator.build_device_command("return_to_base")
        )

    async def async_start(self, **kwargs: Any) -> None:
        """Start or resume the cleaning task."""
        if self.activity == VacuumActivity.PAUSED:
            await self.coordinator.async_send_command(
                self.coordinator.build_device_command("play")
            )
        else:
            await self.coordinator.async_send_command(
                self.coordinator.build_device_command("start_auto")
            )

    async def async_pause(self, **kwargs: Any) -> None:
        """Pause the cleaning task."""
        await self.coordinator.async_send_command(
            self.coordinator.build_device_command("pause")
        )

    async def async_stop(self, **kwargs: Any) -> None:
        """Stop the cleaning task."""
        await self.coordinator.async_send_command(
            self.coordinator.build_device_command("stop")
        )

    async def async_clean_spot(self, **kwargs: Any) -> None:
        """Perform a spot clean-up."""
        await self.coordinator.async_send_command(
            self.coordinator.build_device_command("clean_spot")
        )

    async def async_locate(self, **kwargs: Any) -> None:
        """Locate the vacuum cleaner."""
        await self.coordinator.async_send_command(
            self.coordinator.build_device_command("find_robot", active=True)
        )

    async def async_set_fan_speed(self, fan_speed: str, **kwargs: Any) -> None:
        """Set fan speed."""
        if fan_speed not in self.fan_speed_list:
            raise ServiceValidationError(
                f"Fan speed {fan_speed!r} is not supported; choose one of "
                f"{', '.join(self.fan_speed_list)}"
            )

        await self.coordinator.async_send_command(
            self.coordinator.build_device_command("set_fan_speed", fan_speed=fan_speed)
        )

    async def async_get_segments(self) -> list[Segment]:
        """Return list of cleanable segments."""
        return self._get_room_segments()

    @property
    def stored_last_seen_segments(self) -> list[Segment] | None:
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
                scene_id = params["scene_id"]
                scene_name = next(
                    (
                        scene.get("name")
                        for scene in self.coordinator.data.scenes
                        if scene["id"] == scene_id
                    ),
                    None,
                )
                await self.coordinator.async_send_command(
                    self.coordinator.build_device_command(
                        "scene_clean", scene_id=scene_id
                    )
                )
                self.coordinator.set_active_scene(scene_id, scene_name)
            return

        if command == "room_clean" and isinstance(params, dict):
            await self._async_handle_room_clean(params)
            return

        if command == "zone_clean" and isinstance(params, dict):
            await self._async_handle_zone_clean(params)
            return

        if command == "set_nogo_zones" and isinstance(params, dict):
            await self._async_handle_set_nogo_zones(params)
            return

        if command == "app_segment_clean" and isinstance(params, list):
            # Ids arrive from JSON as int, str or float.
            room_ids = []
            for room_id in params:
                try:
                    room_ids.append(int(room_id))
                except (ValueError, TypeError):
                    pass
            if room_ids:
                await self._async_handle_room_clean({"room_ids": room_ids})
                return
            return

        command_kwargs: dict[str, Any] = {}
        if isinstance(params, dict):
            command_kwargs.update(params)
        command_kwargs.update(kwargs)
        # An explicit api_type in params overrides the detected one, but never for
        # legacy: those devices cannot speak protobuf.
        if "api_type" in command_kwargs and self.coordinator.api_type != API_TYPE_LEGACY:
            command_dict = build_command(command, **command_kwargs)
        else:
            command_kwargs.pop("api_type", None)
            command_dict = self.coordinator.build_device_command(
                command, **command_kwargs
            )
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
            return
        current_segments = self._get_room_segments()
        last_seen = self.stored_last_seen_segments

        if last_seen is None:
            # Record the baseline silently: an issue here would fire before the
            # user could configure area mapping at all.
            if current_segments:
                _LOGGER.info(
                    "First time detecting segments for %s: storing baseline (%d segments)",
                    self.coordinator.device_name,
                    len(current_segments),
                )
                self._store_last_seen_segments(current_segments)
            return

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
        # Not awaited (the coordinator debounces by 2 s); tied to the entry so
        # unload waits for it. Callers guard on a config entry.
        assert self._config_entry is not None
        self._config_entry.async_create_task(
            self.coordinator.hass,
            self.coordinator.async_save_segments(serialized_segments),
            "robovac_mqtt save segments",
        )
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
