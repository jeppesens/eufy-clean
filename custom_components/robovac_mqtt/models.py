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

    # Accessories
    accessories: AccessoryState = field(default_factory=AccessoryState)

    # Preferences
    preferences: CleaningPreferences = field(default_factory=CleaningPreferences)

    # Raw data for fallback/diagnostics
    raw_dps: dict[str, Any] = field(default_factory=dict)
