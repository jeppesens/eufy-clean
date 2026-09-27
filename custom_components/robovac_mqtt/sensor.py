from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    PERCENTAGE,
    SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
    EntityCategory,
    UnitOfArea,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from ._orphan_cleanup import prune_orphan_entities
from .const import API_TYPE_LEGACY, API_TYPE_NOVEL, API_TYPE_SCALAR, DOMAIN
from .coordinator import EufyCleanCoordinator, VacuumState
from .entity import filter_supported_entities
from .profiles import AccessorySpec, DeviceProfile, get_device_profile

_LOGGER = logging.getLogger(__name__)


PARALLEL_UPDATES = 0


def _active_rooms_value(state: VacuumState) -> str:
    """Return a display label for the current active cleaning target."""
    if state.active_room_names:
        return state.active_room_names
    if state.current_scene_name:
        return state.current_scene_name
    if state.active_zone_count:
        suffix = "" if state.active_zone_count == 1 else "s"
        return f"{state.active_zone_count} zone{suffix}"
    return "None"


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Setup sensor entities."""
    data = hass.data[DOMAIN][config_entry.entry_id]
    coordinators: list[EufyCleanCoordinator] = data["coordinators"]

    entities = []

    for coordinator in coordinators:
        _LOGGER.debug("Adding sensors for %s", coordinator.device_name)

        sensors: list[SensorEntity] = [
            BatterySensorEntity(coordinator),
            RoboVacSensor(
                coordinator,
                "error_message",
                "Error Message",
                lambda s: s.error_message,
                device_class=None,
                unit=None,
                state_class=None,
                icon="mdi:alert-circle-outline",
                category=EntityCategory.DIAGNOSTIC,
            ),
            RoboVacSensor(
                coordinator,
                "task_status",
                "Task Status",
                lambda s: s.task_status,
                device_class=None,
                unit=None,
                state_class=None,
                icon="mdi:robot-vacuum",
                category=EntityCategory.DIAGNOSTIC,
            ),
            RoboVacSensor(
                coordinator,
                "work_mode",
                "Work Mode",
                lambda s: s.work_mode,
                device_class=None,
                unit=None,
                state_class=None,
                icon="mdi:cog-outline",
                category=EntityCategory.DIAGNOSTIC,
                supported_api_types=(API_TYPE_NOVEL,),
            ),
        ]

        # Every protocol reports cleaning stats, and each sensor stays hidden by its
        # availability_fn until a value arrives, so offer them for all api types.
        stats_sensors: list[SensorEntity] = [
            RoboVacSensor(
                coordinator,
                "cleaning_time",
                "Cleaning Time",
                lambda s: s.cleaning_time,
                device_class=SensorDeviceClass.DURATION,
                unit="s",
                state_class=SensorStateClass.MEASUREMENT,
                icon="mdi:clock-outline",
                availability_fn=lambda s: "cleaning_stats" in s.received_fields,
                # Stored in seconds; default the display to whole minutes.
                suggested_unit_of_measurement="min",
                suggested_display_precision=0,
            ),
            # Reported in m² on every protocol.
            RoboVacSensor(
                coordinator,
                "cleaning_area",
                "Cleaning Area",
                lambda s: s.cleaning_area,
                device_class=SensorDeviceClass.AREA,
                unit=UnitOfArea.SQUARE_METERS,
                state_class=SensorStateClass.MEASUREMENT,
                icon="mdi:floor-plan",
                availability_fn=lambda s: "cleaning_stats" in s.received_fields,
                suggested_display_precision=0,
            ),
            RoboVacSensor(
                coordinator,
                "total_cleaning_area",
                "Total Cleaning Area",
                lambda s: s.total_cleaning_area,
                device_class=SensorDeviceClass.AREA,
                unit=UnitOfArea.SQUARE_METERS,
                state_class=SensorStateClass.TOTAL,
                icon="mdi:floor-plan",
                availability_fn=lambda s: "cleaning_totals" in s.received_fields,
                suggested_display_precision=0,
            ),
            RoboVacSensor(
                coordinator,
                "total_cleaning_time",
                "Total Cleaning Time",
                lambda s: s.total_cleaning_time,
                device_class=SensorDeviceClass.DURATION,
                unit="s",
                state_class=SensorStateClass.TOTAL,
                icon="mdi:clock-outline",
                availability_fn=lambda s: "cleaning_totals" in s.received_fields,
                suggested_unit_of_measurement="h",
                suggested_display_precision=1,
            ),
        ]

        # These rely on DPS keys (154, 165, 167, 168, 173, ...) that legacy Tuya
        # Cloud devices don't have; scalar-vs-novel gating is left to each sensor's
        # supported_api_types.
        novel_sensors: list[SensorEntity] = [
            RoboVacSensor(
                coordinator,
                "total_cleaning_count",
                "Total Cleaning Count",
                lambda s: s.total_cleaning_count,
                device_class=None,
                unit=None,
                state_class=SensorStateClass.TOTAL,
                icon="mdi:counter",
                availability_fn=lambda s: "cleaning_totals" in s.received_fields,
            ),
            # Station / map sensors — scalar vacuum-only devices have neither.
            RoboVacSensor(
                coordinator,
                "water_level",
                "Water Level",
                lambda s: s.station_clean_water,
                device_class=None,
                unit=PERCENTAGE,
                state_class=SensorStateClass.MEASUREMENT,
                availability_fn=lambda s: "station_clean_water" in s.received_fields,
                supported_api_types=(API_TYPE_NOVEL,),
            ),
            # Dirty water level sensor (Station Dirty Water tank)
            RoboVacSensor(
                coordinator,
                "dirty_water_level",
                "Dirty Water Level",
                lambda s: s.station_dirty_water,
                device_class=None,
                unit=None,
                state_class=None,
                availability_fn=lambda s: "station_dirty_water" in s.received_fields,
                supported_api_types=(API_TYPE_NOVEL,),
            ),
            # Dock status sensor
            RoboVacSensor(
                coordinator,
                "dock_status",
                "Dock Status",
                lambda s: s.dock_status,
                device_class=None,
                unit=None,
                state_class=None,
                category=EntityCategory.DIAGNOSTIC,
                availability_fn=lambda s: "dock_status" in s.received_fields,
                supported_api_types=(API_TYPE_NOVEL,),
            ),
            RoboVacSensor(
                coordinator,
                "active_cleaning_target",
                "Active Cleaning Target",
                _active_rooms_value,
                device_class=None,
                unit=None,
                state_class=None,
                icon="mdi:floor-plan",
                category=EntityCategory.DIAGNOSTIC,
                extra_state_attributes_fn=lambda s: {
                    "room_ids": s.active_room_ids,
                    "scene_id": s.current_scene_id,
                    "scene_name": s.current_scene_name,
                    "zone_count": s.active_zone_count,
                },
                supported_api_types=(API_TYPE_NOVEL,),
            ),
            # WiFi + robot-position diagnostics come from novel-only DPS 169/176/179.
            RoboVacSensor(
                coordinator,
                "wifi_signal",
                "WiFi Signal Strength",
                lambda s: s.wifi_signal,
                device_class=SensorDeviceClass.SIGNAL_STRENGTH,
                unit=SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
                state_class=SensorStateClass.MEASUREMENT,
                icon="mdi:wifi",
                category=EntityCategory.DIAGNOSTIC,
                availability_fn=lambda s: "wifi_signal" in s.received_fields,
                enabled_default=False,
                supported_api_types=(API_TYPE_NOVEL,),
            ),
            RoboVacSensor(
                coordinator,
                "wifi_ssid",
                "WiFi SSID",
                lambda s: s.wifi_ssid or None,
                icon="mdi:wifi",
                category=EntityCategory.DIAGNOSTIC,
                availability_fn=lambda s: "wifi_ssid" in s.received_fields,
                enabled_default=False,
                supported_api_types=(API_TYPE_NOVEL,),
            ),
            RoboVacSensor(
                coordinator,
                "wifi_ip",
                "IP Address",
                lambda s: s.wifi_ip or None,
                icon="mdi:ip-network",
                category=EntityCategory.DIAGNOSTIC,
                availability_fn=lambda s: "wifi_ip" in s.received_fields,
                enabled_default=False,
                supported_api_types=(API_TYPE_NOVEL,),
            ),
            RoboVacSensor(
                coordinator,
                "dock_firmware_version",
                "Dock Firmware Version",
                lambda s: s.dock_firmware_version or None,
                icon="mdi:chip",
                category=EntityCategory.DIAGNOSTIC,
                availability_fn=lambda s: "dock_firmware_version" in s.received_fields,
                supported_api_types=(API_TYPE_NOVEL,),
            ),
            RoboVacSensor(
                coordinator,
                "robot_position_x",
                "Robot Position X (raw)",
                lambda s: s.robot_position_x,
                state_class=SensorStateClass.MEASUREMENT,
                icon="mdi:crosshairs-gps",
                category=EntityCategory.DIAGNOSTIC,
                availability_fn=lambda s: "robot_position" in s.received_fields,
                enabled_default=False,
                supported_api_types=(API_TYPE_NOVEL,),
            ),
            RoboVacSensor(
                coordinator,
                "robot_position_y",
                "Robot Position Y (raw)",
                lambda s: s.robot_position_y,
                state_class=SensorStateClass.MEASUREMENT,
                icon="mdi:crosshairs-gps",
                category=EntityCategory.DIAGNOSTIC,
                availability_fn=lambda s: "robot_position" in s.received_fields,
                enabled_default=False,
                supported_api_types=(API_TYPE_NOVEL,),
            ),
        ]

        profile = (
            coordinator.profile
            if isinstance(getattr(coordinator, "profile", None), DeviceProfile)
            else get_device_profile(
                getattr(coordinator, "device_model", ""),
                getattr(coordinator, "api_type", API_TYPE_NOVEL),
            )
        )
        for spec in profile.accessories.values():
            def get_accessory_remaining(
                state: VacuumState, s: AccessorySpec = spec
            ) -> int | None:
                usage = getattr(state.accessories, s.attr_name) or 0
                used_h = usage / 60 if s.time_unit == "m" else usage
                return max(0, round(s.max_life_hours - used_h))

            def get_attributes(
                state: VacuumState, s: AccessorySpec = spec
            ) -> dict[str, Any]:
                usage = getattr(state.accessories, s.attr_name) or 0
                used_h = usage / 60 if s.time_unit == "m" else usage
                pct = (
                    max(0, round(100 * (1 - used_h / s.max_life_hours)))
                    if s.max_life_hours > 0
                    else 0
                )
                attrs: dict[str, Any] = {
                    "usage_hours": round(used_h, 1) if s.time_unit == "m" else usage,
                    "total_life_hours": s.max_life_hours,
                    "percent_remaining": pct,
                }
                if s.is_maintenance:
                    attrs["is_maintenance"] = True
                return attrs

            def accessory_available(
                state: VacuumState, s: AccessorySpec = spec
            ) -> bool:
                return "accessories" in state.received_fields

            stats_sensors.append(
                RoboVacSensor(
                    coordinator,
                    spec.sensor_id,
                    spec.sensor_name,
                    get_accessory_remaining,
                    device_class=SensorDeviceClass.DURATION,
                    unit="h",
                    state_class=SensorStateClass.MEASUREMENT,
                    icon=spec.icon,
                    category=EntityCategory.DIAGNOSTIC,
                    extra_state_attributes_fn=get_attributes,
                    availability_fn=accessory_available,
                    supported_api_types=spec.supported_api_types,
                )
            )

        # Only the MQTT transport carries MultiMapsManageResponse; on Tuya the id
        # never arrives, so skip the entity rather than leave it `unavailable`.
        if coordinator.connection_type == "mqtt":
            novel_sensors.append(CurrentRoomSensorEntity(coordinator))
            novel_sensors.append(
                RoboVacSensor(
                    coordinator,
                    "active_map",
                    "Active Map",
                    lambda s: s.map_id,
                    device_class=None,
                    unit=None,
                    state_class=None,
                    icon="mdi:map-marker-path",
                    category=EntityCategory.DIAGNOSTIC,
                    availability_fn=lambda s: "map_id" in s.received_fields,
                    supported_api_types=(API_TYPE_NOVEL,),
                )
            )

        sensors += stats_sensors
        if coordinator.api_type != API_TYPE_LEGACY:
            sensors += novel_sensors

        entities.extend(filter_supported_entities(coordinator, sensors))

        # State = entry count, entries in attributes. Gated explicitly because
        # "legacy" reads as "novel" in the supported_api_types filter.
        if coordinator.api_type in (API_TYPE_SCALAR, API_TYPE_LEGACY):
            entities.append(
                RoboVacSensor(
                    coordinator,
                    "schedules",
                    "Schedules",
                    lambda s: len(s.schedules),
                    device_class=None,
                    unit=None,
                    state_class=None,
                    icon="mdi:calendar-clock",
                    category=EntityCategory.DIAGNOSTIC,
                    availability_fn=lambda s: "schedules" in s.received_fields,
                    extra_state_attributes_fn=lambda s: {"entries": s.schedules},
                )
            )

    # Drop entities an older build registered that this device no longer creates.
    prune_orphan_entities(
        hass,
        config_entry.entry_id,
        coordinators,
        added_unique_ids={e.unique_id for e in entities if e.unique_id},
        platform="sensor",
    )

    async_add_entities(entities)


class RoboVacSensor(CoordinatorEntity[EufyCleanCoordinator], SensorEntity):
    """Eufy Clean Sensor Entity."""

    def __init__(
        self,
        coordinator: EufyCleanCoordinator,
        id_suffix: str,
        name_suffix: str,
        value_fn: Callable[[VacuumState], Any],
        device_class: SensorDeviceClass | None = None,
        unit: str | None = None,
        state_class: SensorStateClass | None = None,
        icon: str | None = None,
        category: EntityCategory | None = EntityCategory.DIAGNOSTIC,
        extra_state_attributes_fn: (
            Callable[[VacuumState], dict[str, Any]] | None
        ) = None,
        availability_fn: Callable[[VacuumState], bool] | None = None,
        enabled_default: bool = True,
        suggested_display_precision: int | None = None,
        suggested_unit_of_measurement: str | None = None,
        supported_api_types: tuple[str, ...] | None = None,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        # DPS protocols this sensor exists on (see entity.py); None = all.
        self.supported_api_types = supported_api_types
        self._value_fn = value_fn
        self._extra_attrs_fn = extra_state_attributes_fn
        self._availability_fn = availability_fn
        self._attr_unique_id = f"{coordinator.device_id}_{id_suffix}"

        # HA prefixes the device name to the entity id, which avoids collisions
        # between devices.
        self._attr_has_entity_name = True
        self._attr_name = name_suffix
        self._attr_entity_registry_enabled_default = enabled_default

        self._attr_device_info = coordinator.device_info

        self._attr_native_unit_of_measurement = unit
        self._attr_device_class = device_class
        self._attr_state_class = state_class
        self._attr_entity_category = category
        if icon:
            self._attr_icon = icon
        if suggested_display_precision is not None:
            self._attr_suggested_display_precision = suggested_display_precision
        if suggested_unit_of_measurement is not None:
            self._attr_suggested_unit_of_measurement = suggested_unit_of_measurement

    @property
    def available(self) -> bool:
        """Return True if the coordinator and the optional availability_fn agree."""
        if not super().available:
            return False
        if self._availability_fn is not None:
            return self._availability_fn(self.coordinator.data)
        return True

    @property
    def native_value(self) -> Any:
        """Return the state of the sensor."""
        return self._value_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return entity specific state attributes."""
        if self._extra_attrs_fn:
            return self._extra_attrs_fn(self.coordinator.data)
        return None


class CurrentRoomSensorEntity(RoboVacSensor):
    """Physical room determined from the robot's live map position."""

    def __init__(self, coordinator: EufyCleanCoordinator) -> None:
        super().__init__(
            coordinator,
            "current_room",
            "Current Room",
            lambda _: self._room_value(),
            icon="mdi:map-marker",
            category=None,
            extra_state_attributes_fn=lambda _: self._room_attributes(),
            supported_api_types=(API_TYPE_NOVEL,),
        )

    def _room_value(self) -> str | None:
        room_id, room_name = self.coordinator.current_room()
        return (room_name or f"Room {room_id}") if room_id else None

    def _room_attributes(self) -> dict[str, Any]:
        room_id, room_name = self.coordinator.current_room()
        return {"room_id": room_id or None, "room_name": room_name}

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                f"{DOMAIN}_{self.coordinator.device_id}_current_room_updated",
                self._handle_room_update,
            )
        )

    @callback
    def _handle_room_update(self) -> None:
        self.async_write_ha_state()


class BatterySensorEntity(CoordinatorEntity[EufyCleanCoordinator], SensorEntity):
    """Dedicated battery sensor entity for Matter Bridge compatibility.

    A Matter Bridge needs a real device_class=battery entity; the battery level as
    an attribute on the vacuum entity is not enough.
    """

    _attr_has_entity_name = True
    _attr_name = "Battery"
    _attr_icon = "mdi:battery"
    _attr_device_class = SensorDeviceClass.BATTERY
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: EufyCleanCoordinator) -> None:
        """Initialize the battery sensor."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.device_id}_battery"
        self._attr_device_info = coordinator.device_info

    @property
    def native_value(self) -> int | None:
        """Return the battery level, or None if not yet received."""
        if "battery_level" not in self.coordinator.data.received_fields:
            return None
        battery = self.coordinator.data.battery_level
        if battery is None or battery < 0:
            return None
        return battery
