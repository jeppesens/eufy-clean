from __future__ import annotations

import copy
import logging
from collections.abc import Callable
from dataclasses import replace
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
from .entity import API_TYPE_NOVEL, API_TYPE_SCALAR, filter_supported_entities

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

        entities.extend(
            filter_supported_entities(
                coordinator,
                [
                    DockSwitchEntity(
                        coordinator,
                        "auto_empty",
                        "Auto Empty",
                        lambda cfg: cfg.get("collectdust_v2", {})
                        .get("sw", {})
                        .get("value", False),
                        set_collect_dust,
                        icon="mdi:delete-restore",
                    ),
                    DockSwitchEntity(
                        coordinator,
                        "auto_wash",
                        "Auto Wash",
                        lambda cfg: cfg.get("wash", {}).get("cfg", "CLOSE")
                        == "STANDARD",
                        set_wash_cfg,
                        icon="mdi:water-sync",
                    ),
                    DoNotDisturbSwitchEntity(coordinator),
                    OffPeakChargingSwitchEntity(coordinator),
                    ChildLockSwitchEntity(coordinator),
                    FindRobotSwitchEntity(coordinator),
                    BoostIQSwitchEntity(coordinator),
                    AutoReturnSwitchEntity(coordinator),
                    ActivityLogSwitchEntity(coordinator),
                ],
            )
        )

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


def _current_off_peak_schedule(coordinator: EufyCleanCoordinator) -> dict[str, Any]:
    """Return the current off-peak charging schedule from coordinator state."""
    data = coordinator.data
    return {
        "active": data.off_peak_enabled,
        "begin_hour": data.off_peak_start_hour,
        "begin_minute": data.off_peak_start_minute,
        "end_hour": data.off_peak_end_hour,
        "end_minute": data.off_peak_end_minute,
    }


def _current_dnd_schedule(coordinator: EufyCleanCoordinator) -> dict[str, Any]:
    """Return the current Do Not Disturb schedule from coordinator state."""
    data = coordinator.data
    return {
        "active": data.dnd_enabled,
        "begin_hour": data.dnd_start_hour,
        "begin_minute": data.dnd_start_minute,
        "end_hour": data.dnd_end_hour,
        "end_minute": data.dnd_end_minute,
    }


class DockSwitchEntity(CoordinatorEntity[EufyCleanCoordinator], SwitchEntity):
    """Switch for Dock/Station settings.

    Station features; scalar (Tuya) vacuum-only devices like the G50 have no
    station.
    """

    supported_api_types = (API_TYPE_NOVEL,)

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


class ChildLockSwitchEntity(CoordinatorEntity[EufyCleanCoordinator], SwitchEntity):
    """Switch for the device child lock setting."""

    def __init__(self, coordinator: EufyCleanCoordinator) -> None:
        """Initialize the child lock switch."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.device_id}_child_lock"
        self._attr_has_entity_name = True
        self._attr_name = "Child Lock"
        self._attr_icon = "mdi:lock-outline"
        self._attr_entity_category = EntityCategory.CONFIG
        self._attr_device_info = coordinator.device_info

    @property
    def is_on(self) -> bool | None:
        """Return true if child lock is enabled."""
        return self.coordinator.data.child_lock

    @property
    def available(self) -> bool:
        """Return whether the entity is available."""
        return (
            super().available and "child_lock" in self.coordinator.data.received_fields
        )

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Enable child lock."""
        await self._set_state(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Disable child lock."""
        await self._set_state(False)

    async def _set_state(self, state: bool) -> None:
        """Send child lock command and optimistically update state."""
        command = self.coordinator.build_device_command(
            "set_child_lock",
            active=state,
        )
        await self.coordinator.async_send_command(command)
        self.coordinator.async_set_updated_data(
            replace(self.coordinator.data, child_lock=state)
        )


class DoNotDisturbSwitchEntity(CoordinatorEntity[EufyCleanCoordinator], SwitchEntity):
    """Switch for the Do Not Disturb schedule."""

    def __init__(self, coordinator: EufyCleanCoordinator) -> None:
        """Initialize the DND switch."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.device_id}_do_not_disturb"
        self._attr_has_entity_name = True
        self._attr_name = "Do Not Disturb"
        self._attr_icon = "mdi:minus-circle-off-outline"
        self._attr_entity_category = EntityCategory.CONFIG
        self._attr_device_info = coordinator.device_info

    @property
    def is_on(self) -> bool | None:
        """Return true if DND is enabled."""
        return self.coordinator.data.dnd_enabled

    @property
    def available(self) -> bool:
        """Return whether the entity is available."""
        return (
            super().available
            and "do_not_disturb" in self.coordinator.data.received_fields
        )

    @property
    def extra_state_attributes(self) -> dict[str, str]:
        """Return the current DND schedule."""
        data = self.coordinator.data
        return {
            "start_time": f"{data.dnd_start_hour:02d}:{data.dnd_start_minute:02d}",
            "end_time": f"{data.dnd_end_hour:02d}:{data.dnd_end_minute:02d}",
        }

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Enable Do Not Disturb."""
        await self._set_state(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Disable Do Not Disturb."""
        await self._set_state(False)

    async def _set_state(self, state: bool) -> None:
        """Send DND command and optimistically update state."""
        schedule = _current_dnd_schedule(self.coordinator)
        schedule["active"] = state
        command = self.coordinator.build_device_command(
            "set_do_not_disturb",
            **schedule,
        )
        await self.coordinator.async_send_command(command)
        self.coordinator.async_set_updated_data(
            replace(self.coordinator.data, dnd_enabled=state)
        )


class OffPeakChargingSwitchEntity(CoordinatorEntity[EufyCleanCoordinator], SwitchEntity):
    """Switch for the Off-Peak Charging schedule."""

    supported_api_types = (API_TYPE_NOVEL,)

    def __init__(self, coordinator: EufyCleanCoordinator) -> None:
        """Initialize the off-peak charging switch."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.device_id}_off_peak_charging"
        self._attr_has_entity_name = True
        self._attr_name = "Off-Peak Charging"
        self._attr_icon = "mdi:calendar-clock"
        self._attr_entity_category = EntityCategory.CONFIG
        self._attr_device_info = coordinator.device_info

    @property
    def is_on(self) -> bool | None:
        """Return true if off-peak charging is enabled."""
        return self.coordinator.data.off_peak_enabled

    @property
    def available(self) -> bool:
        """Return whether the entity is available."""
        return (
            super().available
            and "off_peak_charging" in self.coordinator.data.received_fields
        )

    @property
    def extra_state_attributes(self) -> dict[str, str]:
        """Return the current off-peak charging schedule."""
        data = self.coordinator.data
        return {
            "start_time": f"{data.off_peak_start_hour:02d}:{data.off_peak_start_minute:02d}",
            "end_time": f"{data.off_peak_end_hour:02d}:{data.off_peak_end_minute:02d}",
        }

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Enable off-peak charging."""
        await self._set_state(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Disable off-peak charging."""
        await self._set_state(False)

    async def _set_state(self, state: bool) -> None:
        """Send off-peak charging command and optimistically update state."""
        schedule = _current_off_peak_schedule(self.coordinator)
        schedule["active"] = state
        command = self.coordinator.build_device_command(
            "set_off_peak_charging", **schedule
        )
        await self.coordinator.async_send_command(command)
        self.coordinator.async_set_updated_data(
            replace(self.coordinator.data, off_peak_enabled=state)
        )


class BoostIQSwitchEntity(CoordinatorEntity[EufyCleanCoordinator], SwitchEntity):
    """Switch for BoostIQ (auto carpet suction boost).

    scalar-protocol only (DPS 118). X-series lumps BoostIQ into the fan-speed
    list, so this entity is not created there.
    """

    supported_api_types = (API_TYPE_SCALAR,)

    def __init__(self, coordinator: EufyCleanCoordinator) -> None:
        """Initialize the BoostIQ switch."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.device_id}_boost_iq"
        self._attr_has_entity_name = True
        self._attr_name = "BoostIQ"
        self._attr_icon = "mdi:car-turbocharger"
        self._attr_entity_category = EntityCategory.CONFIG
        self._attr_device_info = coordinator.device_info

    @property
    def is_on(self) -> bool | None:
        """Return true if BoostIQ is enabled."""
        return self.coordinator.data.boost_iq

    @property
    def available(self) -> bool:
        """Return whether the entity is available."""
        return super().available and "boost_iq" in self.coordinator.data.received_fields

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Enable BoostIQ."""
        await self._set_state(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Disable BoostIQ."""
        await self._set_state(False)

    async def _set_state(self, state: bool) -> None:
        """Send BoostIQ command and optimistically update state."""
        command = self.coordinator.build_device_command("set_boost_iq", active=state)
        await self.coordinator.async_send_command(command)
        self.coordinator.async_set_updated_data(
            replace(self.coordinator.data, boost_iq=state)
        )


class _ScalarToggleSwitchEntity(CoordinatorEntity[EufyCleanCoordinator], SwitchEntity):
    """Base for simple scalar-protocol on/off switches backed by a state bool.

    Subclasses set _state_field, _available_field, _command_name + the display
    attrs. Hidden until the field is reported (scalar devices only).
    """

    supported_api_types = (API_TYPE_SCALAR,)

    _state_field: str
    _available_field: str
    _command_name: str

    def __init__(self, coordinator: EufyCleanCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_has_entity_name = True
        self._attr_device_info = coordinator.device_info

    @property
    def is_on(self) -> bool | None:
        return getattr(self.coordinator.data, self._state_field)

    @property
    def available(self) -> bool:
        return (
            super().available
            and self._available_field in self.coordinator.data.received_fields
        )

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._set_state(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._set_state(False)

    async def _set_state(self, state: bool) -> None:
        await self.coordinator.async_send_command(
            self.coordinator.build_device_command(self._command_name, active=state)
        )
        self.coordinator.async_set_updated_data(
            replace(self.coordinator.data, **{self._state_field: state})
        )


class AutoReturnSwitchEntity(_ScalarToggleSwitchEntity):
    """ "Auto-Return Cleaning" toggle (scalar DPS 135)."""

    _state_field = "auto_return"
    _available_field = "auto_return"
    _command_name = "set_auto_return"

    def __init__(self, coordinator: EufyCleanCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.device_id}_auto_return"
        self._attr_name = "Auto-Return Cleaning"
        self._attr_icon = "mdi:tune"
        self._attr_entity_category = EntityCategory.CONFIG


class ActivityLogSwitchEntity(_ScalarToggleSwitchEntity):
    """Activity-log upload toggle (scalar DPS 142)."""

    _state_field = "activity_log_upload"
    _available_field = "activity_log_upload"
    _command_name = "set_activity_log"

    def __init__(self, coordinator: EufyCleanCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.device_id}_activity_log_upload"
        self._attr_name = "Activity Log Upload"
        self._attr_icon = "mdi:upload"
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
