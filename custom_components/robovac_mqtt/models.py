from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class CleaningPreferences:
    """Represent cleaning preferences (suction, water, etc)."""

    fan_speed: str = "Standard"
    water_level: int = 1
    auto_empty_mode: bool = False
    auto_mop_wash_mode: bool = False


@dataclass
class AccessoryState:
    """Represent accessory usage/lifespan state."""

    filter_usage: int = 0
    main_brush_usage: int = 0
    side_brush_usage: int = 0
    sensor_usage: int = 0
    scrape_usage: int = 0
    mop_usage: int = 0
    dustbag_usage: int = 0
    dirty_watertank_usage: int = 0
    dirty_waterfilter_usage: int = 0


@dataclass
class VacuumState:
    """Represent the complete state of a Eufy vacuum."""

    device_model: str = ""

    # DPS protocol variant, classified by EufyLogin.checkApiType: "novel" = Anker
    # protobuf, "scalar" = plain int/JSON Tuya DPS over MQTT, "legacy" = Tuya cloud.
    api_type: str = "novel"

    activity: str = "idle"  # cleaning, docked, error, etc.
    battery_level: int = 0
    fan_speed: str = "Standard"

    error_code: int = 0
    error_message: str = ""
    error_codes: list[int] = field(default_factory=list)
    warn_codes: list[int] = field(default_factory=list)
    charging: bool = False

    cleaning_time: int = 0  # seconds
    cleaning_area: int = 0  # m2
    total_cleaning_area: int = 0  # m2, user total (resets on user change)
    total_cleaning_time: int = 0  # seconds, user total
    total_cleaning_count: int = 0  # user total

    task_status: str = "idle"
    find_robot: bool = False

    map_id: int = 0
    map_url: str | None = None
    rooms: list[dict[str, Any]] = field(default_factory=list)
    scenes: list[dict[str, Any]] = field(default_factory=list)

    status_code: int = 0
    dock_status: str | None = None  # debounced in the coordinator
    station_clean_water: int = 0  # percent?
    station_dirty_water: str = "Unknown"  # Station dirty-water tank level (WaterLevel name)
    station_waste_water: int = 0
    dock_auto_cfg: dict[str, Any] = field(default_factory=dict)
    trigger_source: str = "unknown"
    work_mode: str = "unknown"
    current_scene_id: int = 0
    current_scene_name: str | None = None

    # Active cleaning targets, echoed on DPS 152
    active_room_ids: list[int] = field(default_factory=list)
    active_room_names: str = ""  # comma-separated
    active_zone_count: int = 0

    accessories: AccessoryState = field(default_factory=AccessoryState)

    preferences: CleaningPreferences = field(default_factory=CleaningPreferences)
    cleaning_mode: str = "Vacuum"  # Matter vocabulary
    mop_water_level: str = "Medium"  # DPS 154

    cleaning_intensity: str = "Normal"  # DPS 154 clean extent
    carpet_strategy: str = "Auto Raise"  # DPS 154
    corner_cleaning: str = "Normal"  # DPS 154
    smart_mode: bool = False  # DPS 154

    voice_set_id: int = 1201  # DPS 162 voice pack set_id; 1201 = English (Female)

    # scalar-protocol fields
    boost_iq: bool = False  # scalar DPS 118
    volume: int = 0  # percent (novel: DPS 161; scalar: DPS 111 0-10, x10)
    cleaning_pattern: str = (
        "Arranged"  # scalar DPS 154: Arranged/Random
    )
    auto_return: bool = False  # DPS 135
    activity_log_upload: bool = False  # DPS 142
    # Read-only: scalar DPS 151, legacy from the et=3 Tuya cloud timer list.
    schedules: list[dict[str, Any]] = field(default_factory=list)

    # Device settings, DPS 176 UnisettingResponse
    wifi_signal: float = -100.0  # dBm, converted from the reported 0-100%
    child_lock: bool = False
    dnd_enabled: bool = False
    dnd_start_hour: int = 22
    dnd_start_minute: int = 0
    dnd_end_hour: int = 8
    dnd_end_minute: int = 0
    off_peak_enabled: bool = False
    off_peak_start_hour: int = 21
    off_peak_start_minute: int = 0
    off_peak_end_hour: int = 7
    off_peak_end_minute: int = 0

    # Device network info, DPS 169 DeviceInfo proto
    device_mac: str = ""
    wifi_ssid: str = ""
    wifi_ip: str = ""
    dock_firmware_version: str = ""
    product_name: str = ""

    # DPS 179, no known proto definition; raw firmware-internal grid coordinates
    robot_position_x: int = 0
    robot_position_y: int = 0

    installed_version: str = ""
    latest_version: str = ""
    release_summary: str = ""
    release_url: str = ""
    update_in_progress: bool = False
    auto_update_enabled: bool = False
    firmware_modules: list[dict[str, Any]] = field(default_factory=list)

    raw_dps: dict[str, Any] = field(default_factory=dict)

    # Optional fields ever seen from the device; sensors use it for availability.
    received_fields: set[str] = field(default_factory=set)


def track_received_field(
    state: VacuumState, changes: dict[str, Any], field_name: str
) -> None:
    """Record in *changes* that a field has been received from the device."""
    if field_name not in state.received_fields:
        current = changes.get("received_fields", state.received_fields).copy()
        current.add(field_name)
        changes["received_fields"] = current
