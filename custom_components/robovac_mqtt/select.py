from __future__ import annotations

from dataclasses import replace
import logging
from collections.abc import Callable
from typing import Any

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api.commands import build_command
from .const import (
    DOMAIN,
    DRY_DURATION_MAP,
    EUFY_CLEAN_CLEANING_INTENSITIES,
    EUFY_CLEAN_NOVEL_CLEAN_SPEED,
    EUFY_CLEAN_CLEANING_MODES,
    EUFY_CLEAN_WATER_LEVELS,
)
from .coordinator import EufyCleanCoordinator

_LOGGER = logging.getLogger(__name__)

_MOP_INTENSITY_TO_WATER_LEVEL = {
    "Quiet": "Low",
    "Automatic": "Medium",
    "Max": "High",
}
_WATER_LEVEL_TO_MOP_INTENSITY = {
    value: key for key, value in _MOP_INTENSITY_TO_WATER_LEVEL.items()
}


def _format_option_label(item: dict[str, Any], default_name: str) -> str:
    """Format a select option label as '<name> (ID: <id>)'."""
    return f"{item.get('name') or default_name} (ID: {item['id']})"


def _optimistically_update_state(
    coordinator: EufyCleanCoordinator,
    **changes: Any,
) -> None:
    """Optimistically publish updated coordinator state after a successful command."""
    new_data = replace(coordinator.data, **changes)
    coordinator.data = new_data
    coordinator.async_set_updated_data(new_data)


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

        entities.append(SuctionLevelSelectEntity(coordinator))
        entities.append(CleaningModeSelectEntity(coordinator))
        entities.append(WaterLevelSelectEntity(coordinator))
        entities.append(MopIntensitySelectEntity(coordinator))
        entities.append(CleaningIntensitySelectEntity(coordinator))
        entities.append(SceneSelectEntity(coordinator))
        entities.append(RoomSelectEntity(coordinator))

        entities.append(
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
            )
        )

        entities.append(
            DockSelectEntity(
                coordinator,
                "dry_duration",
                "Dry Duration",
                list(DRY_DURATION_MAP.values()),
                _get_dry_duration,
                _set_dry_duration,
                icon="mdi:timer-sand",
            )
        )

        entities.append(
            DockSelectEntity(
                coordinator,
                "auto_empty_mode",
                "Auto Empty Mode",
                ["Smart", "15 min", "30 min", "45 min", "60 min"],
                _get_collect_dust_mode,
                _set_collect_dust_mode,
                icon="mdi:delete-restore",
            )
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
    # Find key by value
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
    """Configuration select for Dock/Station settings."""

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

    async def async_select_option(self, option: str) -> None:
        """Change the selected option."""
        cfg = self.coordinator.data.dock_auto_cfg.copy()
        self._setter(cfg, option)

        command = build_command("set_auto_cfg", cfg=cfg)
        await self.coordinator.async_send_command(command)

        self.async_write_ha_state()


class SceneSelectEntity(CoordinatorEntity[EufyCleanCoordinator], SelectEntity):
    """Select entity for choosing and triggering cleaning scenes."""

    def __init__(self, coordinator: EufyCleanCoordinator) -> None:
        """Initialize scene select."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.device_id}_scene_select"
        self._attr_has_entity_name = True
        self._attr_name = "Scene"
        self._attr_icon = "mdi:play-circle-outline"

        self._attr_device_info = coordinator.device_info

    @property
    def options(self) -> list[str]:
        """Return available scenes."""
        return [_format_option_label(s, "Scene") for s in self.coordinator.data.scenes]

    @property
    def current_option(self) -> str | None:
        """Return the currently active scene."""
        current_id = self.coordinator.data.current_scene_id
        if current_id > 0:
            scene = next(
                (s for s in self.coordinator.data.scenes if s["id"] == current_id), None
            )
            if scene:
                return _format_option_label(scene, "Scene")
            if self.coordinator.data.current_scene_name:
                return f"{self.coordinator.data.current_scene_name} (ID: {current_id})"

        return None

    async def async_select_option(self, option: str) -> None:
        """Trigger the selected scene."""
        scenes = self.coordinator.data.scenes
        scene = next(
            (s for s in scenes if _format_option_label(s, "Scene") == option),
            None,
        )
        if not scene:
            _LOGGER.error("Scene '%s' not found", option)
            return

        scene_id = scene["id"]

        command = build_command("scene_clean", scene_id=scene_id)
        await self.coordinator.async_send_command(command)

        self.async_write_ha_state()


class RoomSelectEntity(CoordinatorEntity[EufyCleanCoordinator], SelectEntity):
    """Select entity for choosing and triggering room cleaning."""

    def __init__(self, coordinator: EufyCleanCoordinator) -> None:
        """Initialize room select."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.device_id}_room_select"
        self._attr_has_entity_name = True
        self._attr_name = "Clean Room"
        self._attr_icon = "mdi:door-open"

        self._attr_device_info = coordinator.device_info

    @property
    def options(self) -> list[str]:
        """Return available rooms."""
        return [_format_option_label(r, "Room") for r in self.coordinator.data.rooms]

    @property
    def current_option(self) -> str | None:
        """Room selection is an action trigger."""
        return None

    async def async_select_option(self, option: str) -> None:
        """Trigger cleaning of the selected room."""
        rooms = self.coordinator.data.rooms
        room = next(
            (r for r in rooms if _format_option_label(r, "Room") == option),
            None,
        )
        if not room:
            _LOGGER.error("Room '%s' not found", option)
            return

        room_id = room["id"]
        map_id = self.coordinator.data.map_id or 1

        command = build_command("room_clean", room_ids=[room_id], map_id=map_id)
        await self.coordinator.async_send_command(command)

        self.async_write_ha_state()


_SUCTION_LEVELS = [speed.value for speed in EUFY_CLEAN_NOVEL_CLEAN_SPEED]


class _StateBackedSelectEntity(CoordinatorEntity[EufyCleanCoordinator], SelectEntity):
    """Base class for selects backed by coordinator state and a device command."""

    _command_name: str
    _command_arg_name: str
    _state_field: str
    _available_field: str | None = None
    _log_label: str

    def __init__(self, coordinator: EufyCleanCoordinator, unique_id_suffix: str) -> None:
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
            build_command(self._command_name, **{self._command_arg_name: state_value})
        )
        _optimistically_update_state(
            self.coordinator,
            **{self._state_field: state_value},
        )
        self.async_write_ha_state()


class SuctionLevelSelectEntity(_StateBackedSelectEntity):
    """Select entity for adjusting suction level."""

    _attr_has_entity_name = True
    _attr_name = "Suction Level"
    _attr_icon = "mdi:fan"
    _attr_options = _SUCTION_LEVELS
    _command_name = "set_fan_speed"
    _command_arg_name = "fan_speed"
    _state_field = "fan_speed"
    _log_label = "Suction level"

    def __init__(self, coordinator: EufyCleanCoordinator) -> None:
        """Initialize suction level select."""
        super().__init__(coordinator, "suction_level")


class CleaningModeSelectEntity(_StateBackedSelectEntity):
    """Select entity for adjusting cleaning mode."""

    _attr_has_entity_name = True
    _attr_name = "Cleaning Mode"
    _attr_icon = "mdi:spray-bottle"
    _attr_options = EUFY_CLEAN_CLEANING_MODES
    _command_name = "set_cleaning_mode"
    _command_arg_name = "clean_mode"
    _state_field = "cleaning_mode"
    _log_label = "Cleaning mode"

    def __init__(self, coordinator: EufyCleanCoordinator) -> None:
        """Initialize cleaning mode select."""
        super().__init__(coordinator, "cleaning_mode")


class WaterLevelSelectEntity(_StateBackedSelectEntity):
    """Select entity for adjusting global mop water level."""

    _attr_has_entity_name = True
    _attr_name = "Water Level"
    _attr_icon = "mdi:water"
    _attr_options = EUFY_CLEAN_WATER_LEVELS
    _command_name = "set_water_level"
    _command_arg_name = "water_level"
    _state_field = "mop_water_level"
    _available_field = "mop_water_level"
    _log_label = "Water level"

    def __init__(self, coordinator: EufyCleanCoordinator) -> None:
        """Initialize water level select."""
        super().__init__(coordinator, "water_level")


class MopIntensitySelectEntity(_StateBackedSelectEntity):
    """Select entity alias for Matter Hub mop intensity discovery."""

    _attr_has_entity_name = True
    _attr_name = "Mop Intensity"
    _attr_icon = "mdi:water"
    _attr_options = ["Quiet", "Automatic", "Max"]
    _command_name = "set_water_level"
    _command_arg_name = "water_level"
    _state_field = "mop_water_level"
    _available_field = "mop_water_level"
    _log_label = "Mop intensity"

    def __init__(self, coordinator: EufyCleanCoordinator) -> None:
        """Initialize mop intensity select."""
        super().__init__(coordinator, "mop_intensity")

    def _state_to_option(self, value: str | None) -> str | None:
        """Map the device water level to the Matter-facing intensity option."""
        return _WATER_LEVEL_TO_MOP_INTENSITY.get(value, value)

    def _option_to_state(self, option: str) -> str:
        """Map the Matter-facing intensity option to the device water level."""
        return _MOP_INTENSITY_TO_WATER_LEVEL.get(option, option)


class CleaningIntensitySelectEntity(_StateBackedSelectEntity):
    """Select entity for adjusting global cleaning intensity."""

    _attr_has_entity_name = True
    _attr_name = "Cleaning Intensity"
    _attr_icon = "mdi:tune-vertical"
    _attr_options = EUFY_CLEAN_CLEANING_INTENSITIES
    _command_name = "set_cleaning_intensity"
    _command_arg_name = "cleaning_intensity"
    _state_field = "cleaning_intensity"
    _available_field = "cleaning_intensity"
    _log_label = "Cleaning intensity"

    def __init__(self, coordinator: EufyCleanCoordinator) -> None:
        """Initialize cleaning intensity select."""
        super().__init__(coordinator, "cleaning_intensity")
