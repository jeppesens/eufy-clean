from __future__ import annotations

import copy
import logging
from collections.abc import Callable
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import EufyCleanCoordinator

_LOGGER = logging.getLogger(__name__)


PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Setup switch entities."""
    data = hass.data[DOMAIN][config_entry.entry_id]
    coordinators: list[EufyCleanCoordinator] = data["coordinators"]

    entities = []

    for coordinator in coordinators:
        _LOGGER.debug("Adding switch entities for %s", coordinator.device_name)

        # Dock switches are novel-only (require protobuf DPS 173)
        if coordinator.api_type != "legacy":
            entities.append(
                DockSwitchEntity(
                    coordinator,
                    "auto_empty",
                    "Auto Empty",
                    lambda cfg: cfg.get("collectdust_v2", {})
                    .get("sw", {})
                    .get("value", False),
                    set_collect_dust,
                    icon="mdi:delete-restore",
                )
            )

            entities.append(
                DockSwitchEntity(
                    coordinator,
                    "auto_wash",
                    "Auto Wash",
                    lambda cfg: cfg.get("wash", {}).get("cfg", "CLOSE") == "STANDARD",
                    set_wash_cfg,
                    icon="mdi:water-sync",
                )
            )

        entities.append(FindRobotSwitchEntity(coordinator))

    async_add_entities(entities)


def set_collect_dust(cfg: dict[str, Any], val: bool) -> None:
    """Helper to set collect dust state in config dict."""
    if "collectdust_v2" not in cfg:
        cfg["collectdust_v2"] = {"sw": {"value": val}}
    else:
        if "sw" not in cfg["collectdust_v2"]:
            cfg["collectdust_v2"]["sw"] = {"value": val}
        else:
            cfg["collectdust_v2"]["sw"]["value"] = val


def set_wash_cfg(cfg: dict[str, Any], val: bool) -> None:
    """Helper to set wash state in config dict."""
    if "wash" not in cfg:
        cfg["wash"] = {"cfg": "STANDARD" if val else "CLOSE"}
    else:
        cfg["wash"]["cfg"] = "STANDARD" if val else "CLOSE"


class DockSwitchEntity(CoordinatorEntity[EufyCleanCoordinator], SwitchEntity):
    """Switch for Dock/Station settings."""

    def __init__(
        self,
        coordinator: EufyCleanCoordinator,
        id_suffix: str,
        name_suffix: str,
        getter: Callable[[dict[str, Any]], bool],
        setter: Callable[[dict[str, Any], bool], None],
        icon: str | None = None,
    ) -> None:
        """Initialize the dock switch entity."""
        super().__init__(coordinator)
        self._id_suffix = id_suffix
        self._getter = getter
        self._setter = setter
        self._attr_unique_id = f"{coordinator.device_id}_{id_suffix}"
        self._attr_has_entity_name = True
        self._attr_name = name_suffix
        self._attr_entity_category = EntityCategory.CONFIG
        if icon:
            self._attr_icon = icon

        self._attr_device_info = coordinator.device_info

    @property
    def is_on(self) -> bool | None:
        """Return true if switch is on."""
        cfg = self.coordinator.data.dock_auto_cfg
        if not cfg:
            return None
        try:
            return self._getter(cfg)
        except Exception as e:
            _LOGGER.debug("Error getting switch state for %s: %s", self._attr_name, e)
            return None

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the switch on."""
        await self._set_state(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the switch off."""
        await self._set_state(False)

    @property
    def available(self) -> bool:
        """Return whether the entity is available."""
        return super().available and bool(self.coordinator.data.dock_auto_cfg)

    async def _set_state(self, state: bool) -> None:
        """Send command to update config."""
        if not self.coordinator.data.dock_auto_cfg:
            raise HomeAssistantError("Dock configuration not yet received from device")
        cfg = copy.deepcopy(self.coordinator.data.dock_auto_cfg)
        self._setter(cfg, state)

        command = self.coordinator.build_device_command("set_auto_cfg", cfg=cfg)
        await self.coordinator.async_send_command(command)


class FindRobotSwitchEntity(CoordinatorEntity[EufyCleanCoordinator], SwitchEntity):
    """Switch for Find Robot feature."""

    def __init__(self, coordinator: EufyCleanCoordinator) -> None:
        """Initialize the find robot switch."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.device_id}_find_robot"
        self._attr_has_entity_name = True
        self._attr_name = "Find Robot"
        self._attr_icon = "mdi:robot-vacuum-variant"
        self._attr_device_info = coordinator.device_info

    @property
    def is_on(self) -> bool | None:
        """Return true if switch is on."""
        return self.coordinator.data.find_robot

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the switch on."""
        command = self.coordinator.build_device_command("find_robot", active=True)
        await self.coordinator.async_send_command(command)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the switch off."""
        command = self.coordinator.build_device_command("find_robot", active=False)
        await self.coordinator.async_send_command(command)
