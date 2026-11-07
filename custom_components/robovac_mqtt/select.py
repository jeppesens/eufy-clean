from __future__ import annotations

import copy
import logging
import re
from collections.abc import Callable
from dataclasses import replace
from typing import Any

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from ._orphan_cleanup import prune_orphan_entities
from .const import (
    API_TYPE_LEGACY,
    API_TYPE_NOVEL,
    API_TYPE_SCALAR,
    DOMAIN,
    DRY_DURATION_MAP,
    EUFY_CLEAN_CLEANING_INTENSITIES,
    EUFY_CLEAN_CLEANING_MODES,
    EUFY_CLEAN_NOVEL_CLEAN_SPEED,
    EUFY_CLEAN_WATER_LEVELS,
    LEGACY_ROOM_FAN_LEVELS,
    LEGACY_ROOM_WATER_LEVELS,
    SCALAR_CLEAN_PATTERN_NAMES,
    SCALAR_SUCTION_LEVELS,
    VOICE_CATALOG,
)
from .coordinator import EufyCleanCoordinator
from .entity import filter_supported_entities

_LOGGER = logging.getLogger(__name__)


def _format_option_label(item: dict[str, Any], default_name: str) -> str:
    """Format a select option label as '<name> (ID: <id>)'."""
    return f"{item.get('name') or default_name} (ID: {item['id']})"


_MOP_INTENSITY_TO_WATER_LEVEL = {
    "Quiet": "Low",
    "Automatic": "Medium",
    "Max": "High",
}
_WATER_LEVEL_TO_MOP_INTENSITY = {
    value: key for key, value in _MOP_INTENSITY_TO_WATER_LEVEL.items()
}


def _optimistically_update_state(
    coordinator: EufyCleanCoordinator, **changes: Any
) -> None:
    """Optimistically update the coordinator state and notify listeners.

    A silently failed command leaves the UI wrong until the next DPS update.
    """
    _LOGGER.debug(
        "Optimistically updating state for %s: %s",
        coordinator.device_name,
        changes,
    )
    new_data = replace(coordinator.data, **changes)
    coordinator.async_set_updated_data(new_data)


PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Setup select entities."""
    data = hass.data[DOMAIN][config_entry.entry_id]
    coordinators: list[EufyCleanCoordinator] = data["coordinators"]

    entities = []

    for coordinator in coordinators:
        _LOGGER.debug("Adding select entities for %s", coordinator.device_name)

        # Safe on every api type: set_fan_speed works on legacy, and the pattern
        # select is scalar-gated below.
        candidates = [
            SuctionLevelSelectEntity(coordinator),
            CleaningPatternSelectEntity(coordinator),
        ]

        if coordinator.api_type in (API_TYPE_SCALAR, API_TYPE_LEGACY):
            candidates.append(RoboVacScheduleSelectEntity(coordinator))

        # Novel-only: on legacy these build {} and are dropped, leaving dropdowns
        # that do nothing. Guarded here because the filter buckets legacy as novel.
        if coordinator.api_type != API_TYPE_LEGACY:
            candidates += [
                CleaningModeSelectEntity(coordinator),
                WaterLevelSelectEntity(coordinator),
                MopIntensitySelectEntity(coordinator),
                CleaningIntensitySelectEntity(coordinator),
                DockSelectEntity(
                    coordinator,
                    "wash_frequency_mode",
                    "Wash Frequency Mode",
                    ["ByRoom", "ByTime"],
                    lambda cfg: (
                        "ByRoom"
                        if cfg.get("wash", {})
                        .get("wash_freq", {})
                        .get("mode", "ByPartition")
                        == "ByPartition"
                        else "ByTime"
                    ),
                    _set_wash_freq_mode,
                    icon="mdi:calendar-sync",
                ),
                DockSelectEntity(
                    coordinator,
                    "dry_duration",
                    "Dry Duration",
                    list(DRY_DURATION_MAP.values()),
                    _get_dry_duration,
                    _set_dry_duration,
                    icon="mdi:timer-sand",
                ),
                DockSelectEntity(
                    coordinator,
                    "auto_empty_mode",
                    "Auto Empty Mode",
                    ["Smart", "15 min", "30 min", "45 min", "60 min"],
                    _get_collect_dust_mode,
                    _set_collect_dust_mode,
                    icon="mdi:delete-restore",
                ),
                VoiceSelectEntity(coordinator),
            ]

        # Scene data only arrives over MQTT/P2P; on Tuya it stays `unknown` forever.
        if coordinator.connection_type == "mqtt":
            candidates.append(SceneSelectEntity(coordinator))
            candidates.append(MapSelectEntity(coordinator))
        # Legacy devices get the entity whether or not the map blob fetch worked:
        # the prune below deletes any entity this setup did not add, so one failed
        # download would destroy the registry entry for good. An empty option list
        # self-heals instead — `options` is computed live.
        if (
            coordinator.connection_type == "mqtt"
            or coordinator.api_type == API_TYPE_LEGACY
            or coordinator.room_name_overrides
            or coordinator.data.rooms
        ):
            candidates.append(RoomSelectEntity(coordinator))

        entities.extend(filter_supported_entities(coordinator, candidates))

    # Drop entities an older build registered that this device no longer creates.
    prune_orphan_entities(
        hass,
        config_entry.entry_id,
        coordinators,
        added_unique_ids={e.unique_id for e in entities if e.unique_id},
        platform="select",
    )

    async_add_entities(entities)


def _set_wash_freq_mode(cfg: dict[str, Any], val: str) -> None:
    """Helper to set wash freq mode."""
    if "wash" not in cfg:
        cfg["wash"] = {}
    if "wash_freq" not in cfg["wash"]:
        cfg["wash"]["wash_freq"] = {}
    cfg["wash"]["wash_freq"]["mode"] = "ByPartition" if val == "ByRoom" else "ByTime"


def _get_dry_duration(cfg: dict[str, Any]) -> str:
    """Helper to get dry duration."""
    dry = cfg.get("dry", {})
    level = dry.get("duration", {}).get("level", "SHORT")
    return DRY_DURATION_MAP.get(level, "3h")


def _set_dry_duration(cfg: dict[str, Any], val: str) -> None:
    """Helper to set dry duration."""
    for level, display in DRY_DURATION_MAP.items():
        if display == val:
            if "dry" not in cfg:
                cfg["dry"] = {}
            if "duration" not in cfg["dry"]:
                cfg["dry"]["duration"] = {}
            cfg["dry"]["duration"]["level"] = level
            return


def _get_collect_dust_mode(cfg: dict[str, Any]) -> str:
    """Helper to get collect dust mode."""
    mode = cfg.get("collectdust_v2", {}).get("mode", {})
    val = mode.get("value", "BY_TASK")

    if val in (2, "2", "BY_TASK"):
        return "Smart"

    if val == "BY_TIME":
        time = mode.get("time", 15)
        return f"{time} min"

    return "Smart"


def _set_collect_dust_mode(cfg: dict[str, Any], val: str) -> None:
    """Helper to set collect dust mode."""
    if "collectdust_v2" not in cfg:
        cfg["collectdust_v2"] = {}
    if "mode" not in cfg["collectdust_v2"]:
        cfg["collectdust_v2"]["mode"] = {}

    if val == "Smart":
        cfg["collectdust_v2"]["mode"]["value"] = 2
    else:
        try:
            minutes = int(val.split(" ")[0])
            cfg["collectdust_v2"]["mode"]["value"] = 1
            cfg["collectdust_v2"]["mode"]["time"] = minutes
        except (ValueError, IndexError):
            pass


class DockSelectEntity(CoordinatorEntity[EufyCleanCoordinator], SelectEntity):
    """Configuration select for dock/station settings (devices with a station)."""

    supported_api_types = (API_TYPE_NOVEL,)

    def __init__(
        self,
        coordinator: EufyCleanCoordinator,
        id_suffix: str,
        name_suffix: str,
        options: list[str],
        getter: Callable[[dict[str, Any]], str],
        setter: Callable[[dict[str, Any], str], None],
        icon: str | None = None,
    ) -> None:
        """Initialize the dock select entity."""
        super().__init__(coordinator)
        self._id_suffix = id_suffix
        self._getter = getter
        self._setter = setter
        self._attr_options = options
        self._attr_unique_id = f"{coordinator.device_id}_{id_suffix}"
        self._attr_has_entity_name = True
        self._attr_name = name_suffix
        self._attr_entity_category = EntityCategory.CONFIG
        if icon:
            self._attr_icon = icon

        self._attr_device_info = coordinator.device_info

    @property
    def current_option(self) -> str | None:
        """Return the current selected option."""
        cfg = self.coordinator.data.dock_auto_cfg
        if not cfg:
            return None
        try:
            return self._getter(cfg)
        except Exception as e:
            _LOGGER.debug("Error getting select option for %s: %s", self.name, e)
            return None

    @property
    def available(self) -> bool:
        """Return whether the entity is available."""
        return super().available and bool(self.coordinator.data.dock_auto_cfg)

    async def async_select_option(self, option: str) -> None:
        """Change the selected option."""
        if not self.coordinator.data.dock_auto_cfg:
            raise HomeAssistantError("Dock configuration not yet received from device")
        cfg = copy.deepcopy(self.coordinator.data.dock_auto_cfg)
        self._setter(cfg, option)

        command = self.coordinator.build_device_command("set_auto_cfg", cfg=cfg)
        await self.coordinator.async_send_command(command)


class SceneSelectEntity(CoordinatorEntity[EufyCleanCoordinator], SelectEntity):
    """Select entity for choosing and triggering cleaning scenes."""

    supported_api_types = (API_TYPE_NOVEL,)

    def __init__(self, coordinator: EufyCleanCoordinator) -> None:
        """Initialize scene select."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.device_id}_scene_select"
        self._attr_has_entity_name = True
        self._attr_name = "Scene/Task"
        self._attr_icon = "mdi:play-circle-outline"

        self._attr_device_info = coordinator.device_info

    _PLACEHOLDER = "None"

    @property
    def options(self) -> list[str]:
        """Return available tasks with a placeholder as the first entry."""
        opts = [self._PLACEHOLDER] + [
            _format_option_label(s, "Task") for s in self.coordinator.data.scenes
        ]
        # Append an unlisted active scene, or HA logs an invalid-option warning.
        current = self.current_option
        if current and current != self._PLACEHOLDER and current not in opts:
            opts.append(current)
        return opts

    @property
    def current_option(self) -> str | None:
        """Return the currently active task, or the placeholder when idle."""
        current_id = self.coordinator.data.current_scene_id
        if current_id > 0:
            for scene in self.coordinator.data.scenes:
                if scene["id"] == current_id:
                    return _format_option_label(scene, "Task")

            if self.coordinator.data.current_scene_name:
                return f"{self.coordinator.data.current_scene_name} (ID: {current_id})"

        return self._PLACEHOLDER

    async def async_select_option(self, option: str) -> None:
        """Trigger the selected task."""
        if option == self._PLACEHOLDER:
            return

        scenes = self.coordinator.data.scenes
        scene = next(
            (s for s in scenes if _format_option_label(s, "Task") == option),
            None,
        )
        if not scene:
            raise ServiceValidationError(f"Task {option!r} not found")

        scene_id = scene["id"]
        _LOGGER.info("Triggering scene '%s' (ID: %s)", option, scene_id)

        command = self.coordinator.build_device_command("scene_clean", scene_id=scene_id)
        await self.coordinator.async_send_command(command)
        self.coordinator.set_active_scene(scene_id, scene.get("name"))

        self.async_write_ha_state()


class RoomSelectEntity(CoordinatorEntity[EufyCleanCoordinator], SelectEntity):
    """Select entity for choosing and triggering room cleaning.

    Rooms from ``coordinator.selectable_rooms()``: manual ``room_name_overrides``
    from the options flow, else ``coordinator.data.rooms`` (P2P on novel devices,
    the Tuya cloud-storage map blob on legacy ones).
    """

    supported_api_types = (API_TYPE_NOVEL,)

    def __init__(self, coordinator: EufyCleanCoordinator) -> None:
        """Initialize room select."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.device_id}_room_select"
        self._attr_has_entity_name = True
        self._attr_name = "Clean Room"
        self._attr_icon = "mdi:door-open"

        self._attr_device_info = coordinator.device_info

    _PLACEHOLDER = "None"

    def _room_labels(self) -> list[tuple[Any, str]]:
        """Return ``(room_id, "<name> (ID: <id>)")`` for each room the select lists."""
        return [
            (room["id"], _format_option_label(room, "Room"))
            for room in self.coordinator.selectable_rooms()
        ]

    @property
    def options(self) -> list[str]:
        """Return available rooms with a placeholder as the first entry."""
        return [self._PLACEHOLDER] + [label for _, label in self._room_labels()]

    @property
    def current_option(self) -> str | None:
        """Return active room if cleaning, otherwise the placeholder."""
        active_ids = set(self.coordinator.data.active_room_ids)
        if active_ids:
            for room_id, label in self._room_labels():
                if room_id in active_ids:
                    return label
        return self._PLACEHOLDER

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose each listed room's current per-room cleaning settings (read-only).

        Keyed by option label; values come from the map room with the same id.
        Legacy only, from the map blob's ``customRooms`` (``-1``/``0`` show as
        "Default"); novel room lists carry no per-room settings.
        """
        map_rooms = {room.get("id"): room for room in self.coordinator.data.rooms}
        settings: dict[str, dict[str, Any]] = {}
        for room_id, label in self._room_labels():
            room = map_rooms.get(room_id, {})
            fan = room.get("fan_speed")
            water = room.get("water_level")
            times = room.get("clean_times")
            if fan is None and water is None and times is None:
                continue
            settings[label] = {
                "suction": (
                    LEGACY_ROOM_FAN_LEVELS[fan]
                    if isinstance(fan, int) and 0 <= fan < len(LEGACY_ROOM_FAN_LEVELS)
                    else "Default"
                ),
                "wash": (
                    LEGACY_ROOM_WATER_LEVELS[water]
                    if isinstance(water, int)
                    and 0 <= water < len(LEGACY_ROOM_WATER_LEVELS)
                    else "Default"
                ),
                "clean_times": times if isinstance(times, int) and times >= 1 else 1,
            }
        return {"room_settings": settings} if settings else {}

    @staticmethod
    def _label_name(label: str) -> str:
        """The room name inside a label, dropping any ``(ID: n)`` suffix."""
        return re.sub(r"\s*\(ID: \d+\)$", "", label)

    async def async_select_option(self, option: str) -> None:
        """Trigger cleaning of the selected room."""
        if option == self._PLACEHOLDER:
            return

        # Room ids are resolved against whichever map is active, and legacy devices
        # can switch maps without bumping DPS 125, so a
        # cached id can clean the wrong room — re-fetch the newest stored map first.
        if (
            self.coordinator.api_type == API_TYPE_LEGACY
            and not self.coordinator.room_name_overrides
        ):
            try:
                await self.coordinator.async_refresh_legacy_map()
            except Exception:  # noqa: BLE001 - keep the cached rooms on failure
                _LOGGER.debug(
                    "Room clean: legacy map refresh failed; using cached rooms"
                )

        labels = self._room_labels()
        room_id = next((rid for rid, label in labels if label == option), None)
        if room_id is None:
            # A refresh can move a room to another id; match on the name.
            name = self._label_name(option)
            room_id = next(
                (rid for rid, label in labels if self._label_name(label) == name),
                None,
            )
        if room_id is None:
            raise ServiceValidationError(f"Room {option!r} is not in the active map")

        # Manual override wins, then the discovered map_id, then 1.
        map_id = self.coordinator.resolve_map_id()
        _LOGGER.info(
            "Triggering cleaning for room '%s' (ID: %s, Map ID: %s)",
            option,
            room_id,
            map_id,
        )

        command = self.coordinator.build_device_command("room_clean", room_ids=[room_id], map_id=map_id)
        await self.coordinator.async_send_command(command)
        self.coordinator.set_active_cleaning_targets(room_ids=[room_id])

        self.async_write_ha_state()


class MapSelectEntity(CoordinatorEntity[EufyCleanCoordinator], SelectEntity):
    """Writable map switcher ("Switch Map"); the "Active Map" sensor is read-only.

    Learn-as-seen: bulk enumeration is P2P-only, so options accumulate as the robot
    visits maps, labelled ``Map (ID: <id>)`` until a ``MapDescription`` supplies a
    name. Selecting one sends ``map_load``; the pose re-localizes onto the new map
    only when the vacuum next moves.
    """

    supported_api_types = (API_TYPE_NOVEL,)

    def __init__(self, coordinator: EufyCleanCoordinator) -> None:
        """Initialize the map switcher select."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.device_id}_map_select"
        self._attr_has_entity_name = True
        self._attr_name = "Switch Map"
        self._attr_icon = "mdi:map-outline"
        self._attr_device_info = coordinator.device_info

    def _known_maps(self) -> dict[int, str]:
        """Discovered ``{map_id: name}``, including the active map id if unnamed."""
        maps = dict(self.coordinator.last_seen_maps or {})
        active = self.coordinator.data.map_id
        if active and active not in maps:
            maps[active] = ""  # id-only; label falls back to "Map (ID: <id>)"
        return maps

    @property
    def options(self) -> list[str]:
        """Return discovered maps as labels, sorted by id for stable ordering."""
        return [
            _format_option_label({"id": mid, "name": name}, "Map")
            for mid, name in sorted(self._known_maps().items())
        ]

    @property
    def current_option(self) -> str | None:
        """Return the active map's label."""
        active = self.coordinator.data.map_id
        if not active:
            return None
        return _format_option_label(
            {"id": active, "name": self._known_maps().get(active, "")}, "Map"
        )

    @property
    def available(self) -> bool:
        """Available once at least one map has been discovered."""
        return super().available and bool(self._known_maps())

    async def async_select_option(self, option: str) -> None:
        """Switch the active map to the selected one via ``map_load``."""
        target = next(
            (
                mid
                for mid, name in self._known_maps().items()
                if _format_option_label({"id": mid, "name": name}, "Map") == option
            ),
            None,
        )
        if target is None:
            raise HomeAssistantError(f"Unknown map option: {option}")

        command = self.coordinator.build_device_command("map_load", cloud_mapid=target)
        if not command:
            raise HomeAssistantError("map_load is not supported on this device")
        await self.coordinator.async_send_command(command)
        self.async_write_ha_state()


_SUCTION_LEVELS = [speed.value for speed in EUFY_CLEAN_NOVEL_CLEAN_SPEED]


# pylint: disable=no-self-use
class _StateBackedSelectEntity(CoordinatorEntity[EufyCleanCoordinator], SelectEntity):
    """Base class for selects backed by coordinator state and a device command."""

    _command_name: str
    _command_arg_name: str
    _state_field: str
    _available_field: str | None = None
    _log_label: str

    def __init__(
        self, coordinator: EufyCleanCoordinator, unique_id_suffix: str
    ) -> None:
        """Initialize the state-backed select entity."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.device_id}_{unique_id_suffix}"
        self._attr_device_info = coordinator.device_info

    @property
    def current_option(self) -> str | None:
        """Return the current selected option."""
        return self._state_to_option(getattr(self.coordinator.data, self._state_field))

    @property
    def available(self) -> bool:
        """Return whether the entity is available."""
        return super().available and (
            self._available_field is None
            or self._available_field in self.coordinator.data.received_fields
        )

    def _state_to_option(self, value: str | None) -> str | None:
        """Map the coordinator state value to a select option."""
        return value

    def _option_to_state(self, option: str) -> str:
        """Map a select option to the coordinator state value."""
        return option

    async def async_select_option(self, option: str) -> None:
        """Change the selected option."""
        if option not in self.options:
            _LOGGER.warning("%s '%s' not supported", self._log_label, option)
            return

        state_value = self._option_to_state(option)
        await self.coordinator.async_send_command(
            self.coordinator.build_device_command(
                self._command_name, **{self._command_arg_name: state_value}
            )
        )
        _optimistically_update_state(
            self.coordinator,
            **{self._state_field: state_value},
        )
        self.async_write_ha_state()


class SuctionLevelSelectEntity(_StateBackedSelectEntity):
    """Select entity for adjusting suction level.

    Hidden until a fan speed value is reported from DPS 154 (novel) or DPS 102 (legacy).
    """

    _attr_has_entity_name = True
    _attr_name = "Suction Level"
    _attr_icon = "mdi:fan"
    _attr_entity_category = EntityCategory.CONFIG
    _command_name = "set_fan_speed"
    _command_arg_name = "fan_speed"
    _state_field = "fan_speed"
    _available_field = "fan_speed"
    _log_label = "Suction level"

    def __init__(self, coordinator: EufyCleanCoordinator) -> None:
        """Initialize suction level select."""
        super().__init__(coordinator, "suction_level")
        # On scalar, BoostIQ is a separate switch (DPS 118), not a 5th level.
        if coordinator.api_type == API_TYPE_SCALAR:
            self._attr_options = SCALAR_SUCTION_LEVELS
        elif coordinator.api_type == API_TYPE_LEGACY:
            self._attr_options = coordinator.legacy_fan_speeds
        else:
            self._attr_options = _SUCTION_LEVELS


class CleaningModeSelectEntity(_StateBackedSelectEntity):
    """Select entity for adjusting cleaning mode.

    Hidden until a cleaning mode value is reported from DPS 154.
    """

    supported_api_types = (API_TYPE_NOVEL,)

    _attr_has_entity_name = True
    _attr_name = "Cleaning Mode"
    _attr_icon = "mdi:spray-bottle"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_options = EUFY_CLEAN_CLEANING_MODES
    _command_name = "set_cleaning_mode"
    _command_arg_name = "clean_mode"
    _state_field = "cleaning_mode"
    _available_field = None
    _log_label = "Cleaning mode"

    def __init__(self, coordinator: EufyCleanCoordinator) -> None:
        """Initialize cleaning mode select."""
        super().__init__(coordinator, "cleaning_mode")


class CleaningPatternSelectEntity(_StateBackedSelectEntity):
    """Select entity for the cleaning path pattern (Arranged/Random).

    Scalar only (DPS 154 int); the Vacuum/Mop axis is CleaningModeSelectEntity.
    """

    supported_api_types = (API_TYPE_SCALAR,)

    _attr_has_entity_name = True
    _attr_name = "Cleaning Pattern"
    _attr_icon = "mdi:vector-polyline"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_options = list(SCALAR_CLEAN_PATTERN_NAMES.values())
    _command_name = "set_cleaning_pattern"
    _command_arg_name = "pattern"
    _state_field = "cleaning_pattern"
    _available_field = "cleaning_pattern"
    _log_label = "Cleaning pattern"

    def __init__(self, coordinator: EufyCleanCoordinator) -> None:
        """Initialize cleaning pattern select."""
        super().__init__(coordinator, "cleaning_pattern")


class WaterLevelSelectEntity(_StateBackedSelectEntity):
    """Select entity for adjusting global mop water level.

    Duplicates MopIntensitySelectEntity on purpose: this one uses the raw device
    names, that one the Matter aliases the Matter bridge discovers.
    """

    supported_api_types = (API_TYPE_NOVEL,)

    _attr_has_entity_name = True
    _attr_name = "Water Level"
    _attr_icon = "mdi:water"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_options = EUFY_CLEAN_WATER_LEVELS
    _command_name = "set_water_level"
    _command_arg_name = "water_level"
    _state_field = "mop_water_level"
    _available_field = None
    _log_label = "Water level"

    def __init__(self, coordinator: EufyCleanCoordinator) -> None:
        """Initialize water level select."""
        super().__init__(coordinator, "water_level")


class MopIntensitySelectEntity(_StateBackedSelectEntity):
    """Select entity for mop water level, modeled as Matter MopIntensity.

    Low/Medium/High are renamed to the Matter enum names Quiet/Automatic/Max, odd
    as those read for a water level.
    """

    supported_api_types = (API_TYPE_NOVEL,)

    _attr_has_entity_name = True
    _attr_name = "Mop Intensity"
    _attr_icon = "mdi:water"
    _attr_options = ["Quiet", "Automatic", "Max"]
    _attr_entity_category = EntityCategory.CONFIG
    _command_name = "set_water_level"
    _command_arg_name = "water_level"
    _state_field = "mop_water_level"
    _available_field = None
    _log_label = "Mop intensity"

    def __init__(self, coordinator: EufyCleanCoordinator) -> None:
        """Initialize mop intensity select."""
        super().__init__(coordinator, "mop_intensity")

    def _state_to_option(self, value: str | None) -> str | None:
        """Map the device water level to the Matter-facing intensity option."""
        if value is None:
            return None
        return _WATER_LEVEL_TO_MOP_INTENSITY.get(value)

    def _option_to_state(self, option: str) -> str:
        """Map the Matter-facing intensity option to the device water level."""
        return _MOP_INTENSITY_TO_WATER_LEVEL.get(option, option)


class CleaningIntensitySelectEntity(_StateBackedSelectEntity):
    """Select entity for adjusting global cleaning intensity."""

    supported_api_types = (API_TYPE_NOVEL,)

    _attr_has_entity_name = True
    _attr_name = "Cleaning Intensity"
    _attr_icon = "mdi:tune-vertical"
    _attr_options = EUFY_CLEAN_CLEANING_INTENSITIES
    _command_name = "set_cleaning_intensity"
    _command_arg_name = "cleaning_intensity"
    _state_field = "cleaning_intensity"
    _available_field = None
    _log_label = "Cleaning intensity"

    def __init__(self, coordinator: EufyCleanCoordinator) -> None:
        """Initialize cleaning intensity select."""
        super().__init__(coordinator, "cleaning_intensity")


_VOICE_OPTIONS = [label for label, _ in VOICE_CATALOG.values()]
_VOICE_LABEL_TO_SET_ID = {label: set_id for set_id, (label, _) in VOICE_CATALOG.items()}


class VoiceSelectEntity(CoordinatorEntity[EufyCleanCoordinator], SelectEntity):
    """Select entity for voice/language pack selection (novel-protocol, DPS 162)."""

    supported_api_types = (API_TYPE_NOVEL,)

    _attr_has_entity_name = True
    _attr_name = "Voice"
    _attr_icon = "mdi:account-voice"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_options = _VOICE_OPTIONS

    def __init__(self, coordinator: EufyCleanCoordinator) -> None:
        """Initialize voice select."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.device_id}_voice"
        self._attr_device_info = coordinator.device_info

    @property
    def available(self) -> bool:
        return super().available and "voice" in self.coordinator.data.received_fields

    @property
    def current_option(self) -> str | None:
        """Return the label for the current voice pack."""
        entry = VOICE_CATALOG.get(self.coordinator.data.voice_set_id)
        return entry[0] if entry else None

    async def async_select_option(self, option: str) -> None:
        """Change the active voice pack."""
        set_id = _VOICE_LABEL_TO_SET_ID.get(option)
        if set_id is None:
            _LOGGER.warning("Unknown voice option '%s'", option)
            return

        command = self.coordinator.build_device_command("set_voice", set_id=set_id)
        if not command:
            return

        await self.coordinator.async_send_command(command)
        _optimistically_update_state(self.coordinator, voice_set_id=set_id)
        self.async_write_ha_state()


def _format_schedule_option(s: dict[str, Any]) -> str:
    """Format a schedule entry into a human-readable dropdown option."""
    t = s.get("time") or "00:00"
    days = s.get("days") or "Once"
    sid = s.get("id")
    enabled_str = "Enabled" if s.get("enabled", True) else "Disabled"
    return f"{t} ({days}) - {enabled_str} [ID: {sid}]"


class RoboVacScheduleSelectEntity(CoordinatorEntity[EufyCleanCoordinator], SelectEntity):
    """Select entity for picking and managing cleaning schedules."""

    _attr_has_entity_name = True
    _attr_name = "Selected Schedule"
    _attr_icon = "mdi:calendar-clock"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: EufyCleanCoordinator) -> None:
        """Initialize schedule select entity."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.device_id}_selected_schedule"
        self._attr_device_info = coordinator.device_info

    @property
    def available(self) -> bool:
        """Available once schedules have been loaded from Tuya Cloud or DPS 151."""
        return super().available and "schedules" in self.coordinator.data.received_fields

    @property
    def options(self) -> list[str]:
        """Dynamically return list of existing schedules plus 'Create New'."""
        schedules = self.coordinator.data.schedules or []
        opts = ["Create New"]
        for s in schedules:
            opts.append(_format_schedule_option(s))
        return opts

    @property
    def current_option(self) -> str:
        """Return the currently selected option."""
        schedules = self.coordinator.data.schedules or []
        sel_id = self.coordinator.selected_schedule_id
        if sel_id is not None:
            for s in schedules:
                if str(s.get("id")) == str(sel_id):
                    return _format_schedule_option(s)
        return "Create New"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose detailed parameters of the currently selected schedule."""
        schedules = self.coordinator.data.schedules or []
        sel_id = self.coordinator.selected_schedule_id
        if sel_id is not None:
            for s in schedules:
                if str(s.get("id")) == str(sel_id):
                    return {
                        "schedule_id": s.get("id"),
                        "time": s.get("time"),
                        "days": s.get("days"),
                        "enabled": s.get("enabled", True),
                        "suction": s.get("suction"),
                        "wash": s.get("wash") or s.get("water"),
                        "rooms": s.get("rooms"),
                        "clean_times": s.get("clean_times", 1),
                        "mode": s.get("mode") or s.get("action") or "general",
                        "action": "edit",
                    }
        return {
            "schedule_id": None,
            "action": "create",
        }

    async def async_select_option(self, option: str) -> None:
        """Select a schedule option."""
        if option == "Create New":
            self.coordinator.selected_schedule_id = None
        else:
            match = re.search(r"\[ID:\s*([^\]]+)\]", option)
            if match:
                raw_id = match.group(1).strip()
                self.coordinator.selected_schedule_id = int(raw_id) if raw_id.isdigit() else raw_id
            else:
                self.coordinator.selected_schedule_id = None
        self.async_write_ha_state()
