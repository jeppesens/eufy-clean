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
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from ._orphan_cleanup import prune_orphan_entities
from .const import (
    ACCESSORY_MAX_LIFE,
    DOMAIN,
    SCALAR_ACCESSORY_MAX_LIFE,
)
from .coordinator import EufyCleanCoordinator, VacuumState
from .entity import API_TYPE_NOVEL, API_TYPE_SCALAR, filter_supported_entities

_LOGGER = logging.getLogger(__name__)


PARALLEL_UPDATES = 0


def _active_rooms_available(state: VacuumState) -> bool:
    """Return whether the active cleaning target sensor has meaningful data."""
    return bool(
        state.active_room_names or state.current_scene_name or state.active_zone_count
    )


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
            # Battery sensor
            BatterySensorEntity(coordinator),
            # Error Message Sensor
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
            # Task Status Sensor
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
            # Work Mode Sensor (novel WorkStatus mode; scalar G50 has no
            # equivalent)
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

        # Novel/scalar sensors: these rely on DPS keys (154, 165, 167, 168,
        # 173, ...) that legacy (plain Tuya Cloud) devices don't support, so
        # they are skipped entirely for legacy devices. Per-protocol gating
        # (scalar vs novel) is handled by filter_supported_entities via each
        # sensor's supported_api_types. The "active_map" sensor additionally
        # requires the MQTT/P2P transport (Tuya Cloud / local-Tuya don't carry
        # MultiMapsManageResponse) and is appended separately below.
        novel_sensors: list[SensorEntity] = [
            # Cleaning Time Sensor
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
            # Cleaning Area Sensor (verified: scalar DPS 110 = m²,
            # 4=43ft²/3=32ft²; X-series via cleaning stats).
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
            # Total Cleaning Area
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
            # Total Cleaning Time
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
            # Total Cleaning Count
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
            # Station / map sensors — scalar (Tuya) vacuum-only devices like
            # the G50 have no station and no maps.
            # Water level sensor (Station Clean Water)
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
            # Active cleaning target sensor
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
            # WiFi + robot-position diagnostics come from novel-only DPS
            # (169/176/179); scalar (Tuya) devices never report them.
            # WiFi Signal Strength (from DPS 176 UnisettingResponse)
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
            # WiFi SSID (from DPS 169 DeviceInfo)
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
            # WiFi IP Address (from DPS 169 DeviceInfo)
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
            # Dock firmware version (from DPS 169 DeviceInfo.station.software)
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
            # Robot Position - raw (from DPS 179 telemetry, diagnostic)
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
            # Schedules (read-only; scalar/Tuya devices, DPS 151). State =
            # entry count; the decoded entries are exposed as attributes.
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
                supported_api_types=(API_TYPE_SCALAR,),
            ),
        ]

        # Accessory Sensors. Filter/brushes/sensor are universal; cleaning tray
        # and mopping cloth only exist on mop-capable (novel) devices.
        accessories = [
            ("filter_usage", "Filter Remaining", "mdi:air-filter", None),
            ("main_brush_usage", "Rolling Brush Remaining", "mdi:broom", None),
            ("side_brush_usage", "Side Brush Remaining", "mdi:broom", None),
            ("sensor_usage", "Sensor Remaining", "mdi:eye-outline", None),
            (
                "scrape_usage",
                "Cleaning Tray Remaining",
                "mdi:wiper",
                (API_TYPE_NOVEL,),
            ),
            ("mop_usage", "Mopping Cloth Remaining", "mdi:water", (API_TYPE_NOVEL,)),
        ]

        for attr, name, icon, supported_api_types in accessories:
            # We must capture the specific attr value in the lambda default args
            # otherwise all lambdas will point to the last attr in the loop.
            # X-series report usage in hours; scalar-protocol (scalar protocol) report
            # usage in MINUTES with their own per-accessory max life (hours).
            def get_accessory_remaining(
                state: VacuumState, a: str = attr
            ) -> int | None:
                usage = getattr(state.accessories, a) or 0
                if state.api_type == "scalar":
                    max_h = SCALAR_ACCESSORY_MAX_LIFE.get(a)
                    if not max_h:
                        return None  # accessory not present on this device
                    return max(0, round(max_h - usage / 60))
                max_life = ACCESSORY_MAX_LIFE.get(a, 0)
                # Ensure we don't go negative if usage exceeds defaults
                return max(0, max_life - usage)

            # Extra attributes explicitly using specific attr
            def get_attributes(state: VacuumState, a: str = attr) -> dict[str, Any]:
                usage = getattr(state.accessories, a) or 0
                if state.api_type == "scalar":
                    max_h = SCALAR_ACCESSORY_MAX_LIFE.get(a, 0)
                    used_h = usage / 60
                    pct = max(0, round(100 * (1 - used_h / max_h))) if max_h else None
                    return {
                        "usage_hours": round(used_h, 1),
                        "total_life_hours": max_h,
                        "percent_remaining": pct,
                    }
                return {
                    "usage_hours": usage,
                    "total_life_hours": ACCESSORY_MAX_LIFE.get(a, 0),
                }

            def accessory_available(state: VacuumState, a: str = attr) -> bool:
                if "accessories" not in state.received_fields:
                    return False
                if state.api_type == "scalar":
                    # Hide accessories the scalar-protocol device doesn't have (mop, tray)
                    return a in SCALAR_ACCESSORY_MAX_LIFE
                return True

            novel_sensors.append(
                RoboVacSensor(
                    coordinator,
                    attr.replace("_usage", "_remaining"),
                    name,
                    get_accessory_remaining,
                    device_class=SensorDeviceClass.DURATION,
                    unit="h",  # Hours
                    state_class=SensorStateClass.MEASUREMENT,
                    icon=icon,
                    category=EntityCategory.DIAGNOSTIC,
                    extra_state_attributes_fn=get_attributes,
                    availability_fn=accessory_available,
                    supported_api_types=supported_api_types,
                )
            )

        # Active map ID sensor — only populated by the MQTT/P2P transport.
        # Tuya Cloud / local-Tuya don't carry MultiMapsManageResponse so the
        # ID never arrives; skip the entity to avoid permanent `unavailable`.
        if coordinator.connection_type == "mqtt":
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

        # Legacy (plain Tuya Cloud) devices only support the universal sensors;
        # the novel/scalar DPS keys those sensors rely on are unavailable, so
        # only merge them for non-legacy devices.
        if coordinator.api_type != "legacy":
            sensors += novel_sensors

        # Apply protocol gating (scalar vs novel) before adding entities.
        entities.extend(filter_supported_entities(coordinator, sensors))

    # Prune registry orphans (e.g., active_map entity registered by an old
    # build but no longer created on the Tuya transport, or novel sensors no
    # longer created for legacy devices).
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

        # Use Home Assistant standard naming
        # This will prefix the device name to the entity name if the
        # device name is not in the entity name
        # Result: sensor.robovac_water_level (Safer, avoids collisions)
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
        """Return True if entity is available.

        Checks coordinator availability and optional custom availability function.
        """
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


class BatterySensorEntity(CoordinatorEntity[EufyCleanCoordinator], SensorEntity):
    """Dedicated battery sensor entity for Matter Bridge compatibility.

    Matter Bridges require devices that operate on battery power to explicitly
    expose a dedicated battery sensor entity (device_class=battery) rather than
    just exposing the battery level as a state attribute on the Vacuum entity.
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
