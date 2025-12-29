from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from homeassistant.components.switch import SwitchEntity
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
    """Setup switch entities."""
    data = hass.data[DOMAIN][config_entry.entry_id]
    coordinators: list[EufyCleanCoordinator] = data["coordinators"]

    entities = []

    for coordinator in coordinators:
        _LOGGER.debug("Adding switch entities for %s", coordinator.device_name)

        entities.append(
            DockSwitchEntity(
                coordinator,
                "auto_empty",
                "Auto Empty",
                lambda cfg: cfg.get("collectdust_v2", {})
                .get("sw", {})
                .get("value", False),
                _set_collect_dust,
                icon="mdi:delete-restore",
            )
        )

        entities.append(
            DockSwitchEntity(
                coordinator,
                "auto_wash",
                "Auto Wash",
                lambda cfg: cfg.get("wash", {}).get("cfg", "CLOSE") == "STANDARD",
                _set_wash_cfg,
                icon="mdi:water-sync",
            )
        )

    async_add_entities(entities)


def _set_collect_dust(cfg: dict[str, Any], val: bool) -> None:
    """Helper to set collect dust state in config dict."""
    if "collectdust_v2" not in cfg:
        cfg["collectdust_v2"] = {"sw": {"value": val}}
    else:
        if "sw" not in cfg["collectdust_v2"]:
            cfg["collectdust_v2"]["sw"] = {"value": val}
        else:
            cfg["collectdust_v2"]["sw"]["value"] = val


def _set_wash_cfg(cfg: dict[str, Any], val: bool) -> None:
    """Helper to set wash state in config dict."""
    if "wash" not in cfg:
        cfg["wash"] = {"cfg": 1 if val else 0}
    else:
        cfg["wash"]["cfg"] = 1 if val else 0


def _set_dry_cfg(cfg: dict[str, Any], val: bool) -> None:
    """Helper to set dry state in config dict."""
    if "dry" not in cfg:
        cfg["dry"] = {"cfg": 1 if val else 0}
    else:
        cfg["dry"]["cfg"] = 1 if val else 0


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

    async def _set_state(self, state: bool) -> None:
        """Send command to update config."""
        cfg = self.coordinator.data.dock_auto_cfg.copy()
        self._setter(cfg, state)

        command = build_command("set_auto_cfg", cfg=cfg)
        await self.coordinator.async_send_command(command)

        self.async_write_ha_state()
