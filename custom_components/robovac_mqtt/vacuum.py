from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.vacuum import (
    StateVacuumEntity,
    VacuumActivity,
    VacuumEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api.commands import build_command
from .const import DOMAIN, EUFY_CLEAN_NOVEL_CLEAN_SPEED
from .coordinator import EufyCleanCoordinator

_LOGGER = logging.getLogger(__name__)


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
        entities.append(RoboVacMQTTEntity(coordinator))

    async_add_entities(entities)


class RoboVacMQTTEntity(CoordinatorEntity[EufyCleanCoordinator], StateVacuumEntity):
    """Eufy Clean Vacuum Entity."""

    _attr_has_entity_name = True
    _attr_name = None

    def __init__(self, coordinator: EufyCleanCoordinator) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        self._attr_unique_id = coordinator.device_id

        self._attr_device_info = coordinator.device_info

        self._attr_fan_speed_list: list[str] = [
            speed.value for speed in EUFY_CLEAN_NOVEL_CLEAN_SPEED
        ]
        self._attr_supported_features = (
            VacuumEntityFeature.START
            | VacuumEntityFeature.PAUSE
            | VacuumEntityFeature.STOP
            | VacuumEntityFeature.STATE
            | VacuumEntityFeature.FAN_SPEED
            | VacuumEntityFeature.RETURN_HOME
            | VacuumEntityFeature.SEND_COMMAND
            | VacuumEntityFeature.LOCATE
        )

    @property
    def activity(self) -> VacuumActivity | None:
        """Return the current vacuum activity."""
        state = self.coordinator.data.activity

        if state == "cleaning":
            return VacuumActivity.CLEANING
        elif state == "docked":
            return VacuumActivity.DOCKED
        elif state == "charging":
            return VacuumActivity.DOCKED
        elif state == "error":
            return VacuumActivity.ERROR
        elif state == "returning":
            return VacuumActivity.RETURNING
        elif state == "idle":
            return VacuumActivity.IDLE
        elif state == "paused":
            return VacuumActivity.PAUSED

        return None

    @property
    def fan_speed(self) -> str | None:
        """Return the fan speed of the vacuum."""
        return self.coordinator.data.fan_speed

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the state attributes."""
        data = self.coordinator.data
        return {
            "fan_speed": data.fan_speed,
            "cleaning_time": data.cleaning_time,
            "cleaning_area": data.cleaning_area,
            "task_status": data.task_status,
            "trigger_source": data.trigger_source,
            "error_code": data.error_code,
            "error_message": data.error_message,
            "status_code": data.status_code,
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

    async def async_set_fan_speed(self, fan_speed: str, **kwargs: Any) -> None:
        """Set fan speed."""
        if fan_speed not in self.fan_speed_list:
            raise ValueError(f"Fan speed {fan_speed} not supported")

        await self.coordinator.async_send_command(
            build_command("set_fan_speed", fan_speed=fan_speed)
        )

    async def async_locate(self, **kwargs: Any) -> None:
        """Locate the vacuum cleaner."""
        await self.coordinator.async_send_command(
            build_command("find_robot", active=True)
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

        elif command == "room_clean":
            if isinstance(params, dict):
                map_id = params.get("map_id") or self.coordinator.data.map_id or 1

                # Check for new 'rooms' parameter (list of dicts)
                rooms_config = params.get("rooms")
                if rooms_config and isinstance(rooms_config, list):
                    # Extract IDs for the clean command
                    room_ids = [int(r["id"]) for r in rooms_config if "id" in r]

                    # 1. Configure Room Params (Pass the list of dicts)
                    await self.coordinator.async_send_command(
                        build_command(
                            "set_room_custom", room_config=rooms_config, map_id=map_id
                        )
                    )
                    # 2. Start Clean with Custom Mode
                    await self.coordinator.async_send_command(
                        build_command(
                            "room_clean",
                            room_ids=room_ids,
                            map_id=map_id,
                            mode="CUSTOMIZE",
                        )
                    )
                    return

                # Legacy: 'room_ids' (list of ints) + optional global params
                elif "room_ids" in params:
                    room_ids = params["room_ids"]
                    fan_speed = params.get("fan_speed")
                    water_level = params.get("water_level")
                    clean_times = params.get("clean_times")
                    clean_mode = params.get("clean_mode")
                    clean_intensity = params.get("clean_intensity")
                    edge_mopping = params.get("edge_mopping")

                    custom_params = [
                        fan_speed,
                        water_level,
                        clean_times,
                        clean_mode,
                        clean_intensity,
                    ]
                    # Check if any standard params are set OR if edge_mopping is explicitly provided (bool)
                    if any(custom_params) or edge_mopping is not None:
                        # 1. Configure Room Params
                        await self.coordinator.async_send_command(
                            build_command(
                                "set_room_custom",
                                room_config=room_ids,  # Pass list of ints
                                map_id=map_id,
                                fan_speed=fan_speed,
                                water_level=water_level,
                                clean_times=clean_times,
                                clean_mode=clean_mode,
                                clean_intensity=clean_intensity,
                                edge_mopping=edge_mopping,
                            )
                        )
                        # 2. Start Clean with Custom Mode
                        await self.coordinator.async_send_command(
                            build_command(
                                "room_clean",
                                room_ids=room_ids,
                                map_id=map_id,
                                mode="CUSTOMIZE",
                            )
                        )
                    else:
                        # Standard room clean (no custom settings)
                        await self.coordinator.async_send_command(
                            build_command(
                                "room_clean", room_ids=room_ids, map_id=map_id
                            )
                        )
                    return

        _LOGGER.warning(
            "Command %s with params %s not fully implemented or invalid.",
            command,
            params,
        )
