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

    # Device identity (used for the HA device registry).
    device_model: str = ""

    # DPS protocol variant, classified cloud-side by EufyLogin.checkApiType and
    # seeded by the coordinator at init:
    #   "novel"  -> Anker protobuf DPS (X-series, default)
    #   "scalar" -> plain int/JSON Tuya-style DPS over MQTT (e.g. T2210/G50)
    #   "legacy" -> pure Tuya cloud devices (PR #110; no parser here yet)
    api_type: str = "novel"

    # Basic
    activity: str = "idle"  # cleaning, docked, error, etc.
    battery_level: int = 0
    fan_speed: str = "Standard"

    # Error state
    error_code: int = 0
    error_message: str = ""
    charging: bool = False

    # Cleaning Stats
    cleaning_time: int = 0  # seconds
    cleaning_area: int = 0  # m2

    # Advanced Status
    task_status: str = "idle"
    find_robot: bool = False

    # Map
    map_id: int = 0
    map_url: str | None = None
    rooms: list[dict[str, Any]] = field(default_factory=list)
    scenes: list[dict[str, Any]] = field(default_factory=list)

    # Detailed Status
    status_code: int = 0  # Raw status value if needed
    dock_status: str | None = None  # Text description (debounced in coordinator)
    station_clean_water: int = 0  # Percentage?
    station_waste_water: int = 0
    dock_auto_cfg: dict[str, Any] = field(default_factory=dict)
    trigger_source: str = "unknown"
    work_mode: str = "unknown"
    current_scene_id: int = 0
    current_scene_name: str | None = None

    # Active cleaning targets (from DPS 152 echo)
    active_room_ids: list[int] = field(default_factory=list)
    active_room_names: str = ""  # Comma-separated resolved names
    active_zone_count: int = 0

    # Accessories
    accessories: AccessoryState = field(default_factory=AccessoryState)

    # Preferences
    preferences: CleaningPreferences = field(default_factory=CleaningPreferences)
    cleaning_mode: str = "Vacuum"  # Matter-compatible cleaning mode preference
    mop_water_level: str = "Medium"  # Global mop water level from DPS 154

    # Additional DPS 154 fields for enhanced functionality
    cleaning_intensity: str = "Normal"  # Clean extent from DPS 154
    carpet_strategy: str = "Auto Raise"  # Clean carpet strategy from DPS 154
    corner_cleaning: str = "Normal"  # Mop corner cleaning from DPS 154
    smart_mode: bool = False  # Smart mode switch from DPS 154

    # scalar-protocol fields (e.g. T2210/G50)
    boost_iq: bool = False  # BoostIQ auto-carpet-boost (scalar-protocol DPS 118)
    volume: int = 0  # Voice volume 0-100% (scalar-protocol DPS 111, 0-10 *10)
    cleaning_pattern: str = "Arranged"  # Path pattern Arranged/Random (scalar-protocol DPS 154)
    auto_return: bool = False  # "Auto-Return Cleaning" toggle (DPS 135)
    activity_log_upload: bool = False  # Activity-log upload toggle (DPS 142)
    schedules: list[dict[str, Any]] = field(default_factory=list)  # DPS 151 (read-only)

    # Device settings (from DPS 176 UnisettingResponse)
    wifi_signal: float = -100.0  # AP signal strength in dBm (converted from 0-100%)
    child_lock: bool = False  # Children lock switch
    dnd_enabled: bool = False  # Do Not Disturb switch
    dnd_start_hour: int = 22  # Do Not Disturb start hour
    dnd_start_minute: int = 0  # Do Not Disturb start minute
    dnd_end_hour: int = 8  # Do Not Disturb end hour
    dnd_end_minute: int = 0  # Do Not Disturb end minute

    # Device network info (from DPS 169, DeviceInfo proto)
    device_mac: str = ""  # Device MAC address
    wifi_ssid: str = ""  # Connected WiFi network name
    wifi_ip: str = ""  # Device IP address

    # Robot telemetry (from DPS 179, no known proto definition)
    robot_position_x: int = 0  # Raw map X coordinate (firmware-internal grid)
    robot_position_y: int = 0  # Raw map Y coordinate (firmware-internal grid)

    # Raw data for fallback/diagnostics
    raw_dps: dict[str, Any] = field(default_factory=dict)

    # Track which optional fields have ever been received from the device
    # Used by sensors to determine availability (e.g., water level on C20)
    received_fields: set[str] = field(default_factory=set)
