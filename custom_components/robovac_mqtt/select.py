from __future__ import annotations

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
from .const import DOMAIN
from .coordinator import EufyCleanCoordinator

_LOGGER = logging.getLogger(__name__)


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
                ["2h", "3h", "4h"],
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
    levels = ["SHORT", "MEDIUM", "LONG"]
    displays = ["2h", "3h", "4h"]

    dry = cfg.get("dry", {})
    level = dry.get("duration", {}).get("level", "SHORT")

    try:
        idx = levels.index(level)
        return displays[idx]
    except ValueError:
        return "3h"


def _set_dry_duration(cfg: dict[str, Any], val: str) -> None:
    """Helper to set dry duration."""
    levels = ["SHORT", "MEDIUM", "LONG"]
    displays = ["2h", "3h", "4h"]
    try:
        idx = displays.index(val)
        level_str = levels[idx]

        if "dry" not in cfg:
            cfg["dry"] = {}
        if "duration" not in cfg["dry"]:
            cfg["dry"]["duration"] = {}
        cfg["dry"]["duration"]["level"] = level_str
    except ValueError:
        pass


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
        except ValueError:
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
        except Exception:
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
        return [scene["name"] for scene in self.coordinator.data.scenes]

    @property
    def current_option(self) -> str | None:
        """Scenes are action-triggers, they don't have a persistent 'current' state."""
        return None

    async def async_select_option(self, option: str) -> None:
        """Trigger the selected scene."""
        scene = next(
            (s for s in self.coordinator.data.scenes if s["name"] == option), None
        )
        if not scene:
            _LOGGER.error("Scene '%s' not found", option)
            return

        command = build_command("scene_clean", scene_id=scene["id"])
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
        rooms = self.coordinator.data.rooms
        return [f"{r.get('name') or 'Room'} (ID: {r['id']})" for r in rooms]

    @property
    def current_option(self) -> str | None:
        """Room selection is an action trigger."""
        return None

    async def async_select_option(self, option: str) -> None:
        """Trigger cleaning of the selected room."""
        rooms = self.coordinator.data.rooms
        room = next(
            (
                r
                for r in rooms
                if f"{r.get('name') or 'Room'} (ID: {r['id']})" == option
            ),
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
