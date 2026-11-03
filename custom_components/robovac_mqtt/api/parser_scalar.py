"""Inbound DPS parsing for scalar (Tuya-style) devices: plain ints and JSON on
their own DPS numbers, with no WorkStatus (DPS 153)."""

from __future__ import annotations

import json
import logging
from dataclasses import replace
from typing import Any

from ..const import (
    EUFY_CLEAN_CLEAN_SPEED,
    EUFY_CLEAN_ERROR_CODES,
    SCALAR_CLEAN_PATTERN_NAMES,
    SCALAR_DPS,
    SCALAR_STATE_NAMES,
    SCALAR_SUCTION_LEVELS,
    WEEKDAY_ABBREVIATIONS,
)
from ..models import VacuumState, track_received_field
from ..utils import parse_weekdays

_LOGGER = logging.getLogger(__name__)

# Scalar DPS keys whose JSON values map onto accessory usage counters.
_SCALAR_ACCESSORY_FIELDS = {
    "dust_filter": "filter_usage",
    "roller_brush": "main_brush_usage",
    "side_brush": "side_brush_usage",
    "sensors": "sensor_usage",
}

# DPS 151 keys weekdays "1".."7" (Mon..Sun).
_SCALAR_SCHEDULE_DAYS = {
    str(i + 1): day for i, day in enumerate(WEEKDAY_ABBREVIATIONS)
}
# DPS 151 "s" is the DPS 102 suction index; "f" the DPS 154 pattern, where
# "general" means the default pattern.
_SCALAR_SUCTION_BY_NAME = {name.lower(): i for i, name in enumerate(SCALAR_SUCTION_LEVELS)}
_SCALAR_DEFAULT_SUCTION = SCALAR_SUCTION_LEVELS.index(EUFY_CLEAN_CLEAN_SPEED.STANDARD)
_SCALAR_DEFAULT_PATTERN = min(SCALAR_CLEAN_PATTERN_NAMES)
_SCALAR_PATTERN_BY_NAME = {
    "general": _SCALAR_DEFAULT_PATTERN,
    **{name.lower(): value for value, name in SCALAR_CLEAN_PATTERN_NAMES.items()},
}


def _g_int(value: Any) -> int | None:
    """Coerce a scalar DPS value to int, or None if not numeric."""
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.lstrip("-").isdigit():
        return int(value)
    return None


def process_scalar_dps(
    state: VacuumState, dps: dict[str, Any], changes: dict[str, Any]
) -> None:
    """Process scalar DPS; each key is handled alone so one bad value isn't fatal."""
    for key, value in dps.items():
        try:
            if key == SCALAR_DPS["STATE"]:
                code = _g_int(value)
                if code is None:
                    continue
                changes["status_code"] = code
                changes["activity"] = SCALAR_STATE_NAMES.get(code, "idle")
                changes["charging"] = code == 5
                changes["task_status"] = _map_scalar_task_status(code)

            elif key == SCALAR_DPS["BATTERY"]:
                level = _g_int(value)
                if level is not None:
                    changes["battery_level"] = level
                    track_received_field(state, changes, "battery_level")

            elif key == SCALAR_DPS["SUCTION"]:
                idx = _g_int(value)
                if idx is not None and 0 <= idx < len(SCALAR_SUCTION_LEVELS):
                    changes["fan_speed"] = SCALAR_SUCTION_LEVELS[idx]
                    track_received_field(state, changes, "fan_speed")

            elif key == SCALAR_DPS["BOOST_IQ"]:
                b = _g_int(value)
                if b is not None:
                    changes["boost_iq"] = bool(b)
                    track_received_field(state, changes, "boost_iq")

            elif key == SCALAR_DPS["CLEAN_PATTERN"]:
                p = _g_int(value)
                if p is not None and p in SCALAR_CLEAN_PATTERN_NAMES:
                    changes["cleaning_pattern"] = SCALAR_CLEAN_PATTERN_NAMES[p]
                    track_received_field(state, changes, "cleaning_pattern")

            elif key == SCALAR_DPS["VOLUME"]:
                v = _g_int(value)
                if v is not None:
                    changes["volume"] = max(0, min(100, v * 10))
                    track_received_field(state, changes, "volume")

            elif key == SCALAR_DPS["CHILD_LOCK"]:
                c = _g_int(value)
                if c is not None:
                    changes["child_lock"] = bool(c)
                    track_received_field(state, changes, "child_lock")

            elif key == SCALAR_DPS["FIND_ROBOT"]:
                f = _g_int(value)
                if f is not None:
                    changes["find_robot"] = bool(f)

            elif key == SCALAR_DPS["DND"]:
                _process_scalar_dnd(state, value, changes)

            elif key in (SCALAR_DPS["ERROR_CODE"], SCALAR_DPS["ERROR_CODE_ALT"]):
                code = _g_int(value)
                if code:  # non-zero fault wins (106 and 177 are both candidates)
                    changes["error_code"] = code
                    changes["error_message"] = EUFY_CLEAN_ERROR_CODES.get(
                        code, "Unknown Error"
                    )
                elif "error_code" not in changes:  # clear only if nothing set yet
                    changes["error_code"] = 0
                    changes["error_message"] = ""

            elif key == SCALAR_DPS["AUTO_RETURN"]:
                c = _g_int(value)
                if c is not None:
                    changes["auto_return"] = bool(c)
                    track_received_field(state, changes, "auto_return")

            elif key == SCALAR_DPS["ACTIVITY_LOG"]:
                a = _g_int(value)
                if a is not None:
                    changes["activity_log_upload"] = bool(a)
                    track_received_field(state, changes, "activity_log_upload")

            elif key == SCALAR_DPS["SCHEDULE"]:
                changes["schedules"] = _parse_scalar_schedules(value)
                track_received_field(state, changes, "schedules")

            elif key == SCALAR_DPS["CLEAN_TIME"]:
                secs = _g_int(value)  # DPS 109 is already in seconds
                if secs is not None:
                    changes["cleaning_time"] = secs
                    track_received_field(state, changes, "cleaning_stats")

            elif key == SCALAR_DPS["CLEAN_AREA"]:
                area = _g_int(value)  # DPS 110 is in m²
                if area is not None:
                    changes["cleaning_area"] = area
                    track_received_field(state, changes, "cleaning_stats")

            elif key == SCALAR_DPS["ACCESSORIES"]:
                _process_scalar_accessories(state, value, changes)

            else:
                _LOGGER.debug(
                    "scalar-protocol unhandled DPS %s (%s)", key, type(value).__name__
                )

        except Exception as e:
            _LOGGER.warning(
                "Error parsing scalar-protocol DPS %s: %s", key, e, exc_info=True
            )

    # DPS 122 = motion flag (1=stationary, 0=moving); stationary mid-clean means
    # paused. Reconciled after the loop so DPS order doesn't matter.
    pause_flag = dps.get(SCALAR_DPS["PAUSE"])
    if pause_flag is not None:
        activity = changes.get("activity", state.activity)
        if _g_int(pause_flag) == 1 and activity == "cleaning":
            changes["activity"] = "paused"
            changes["task_status"] = "Paused"


def _map_scalar_task_status(code: int) -> str:
    """Map scalar-protocol state int (DPS 15) to a human task-status string."""
    return {
        0: "Standby",
        1: "Standby",
        2: "Cleaning",
        4: "Returning",
        5: "Charging",
        6: "Docked",
        7: "Paused",
    }.get(code, "Standby")


def scalar_schedule_raw_entries(value: Any) -> list[dict[str, Any]]:
    """The raw entries of a DPS 151 value (JSON string or dict)."""
    data = value if isinstance(value, dict) else json.loads(value)
    return list(data.get("l", []))


def _parse_scalar_schedules(value: Any) -> list[dict[str, Any]]:
    """Decode DPS 151 schedule JSON into schedule entries."""
    return [scalar_raw_to_schedule_entry(e) for e in scalar_schedule_raw_entries(value)]


def scalar_raw_to_schedule_entry(raw: dict[str, Any]) -> dict[str, Any]:
    """One DPS 151 entry as a schedule entry.

    Raw entry: {"e":bool, "t":"HHMM", "r":"<day digits 1=Mon..7=Sun>",
                "s":suction 0-3, "f":pattern 1/2, "id":int}.
    """
    t = str(raw.get("t", "")).zfill(4)
    s: Any = raw.get("s")
    f: Any = raw.get("f")
    return {
        "id": raw.get("id"),
        "enabled": bool(raw.get("e")),
        "time": f"{t[:2]}:{t[2:]}" if t.isdigit() and len(t) == 4 else t,
        "days": ", ".join(
            _SCALAR_SCHEDULE_DAYS.get(d, d) for d in str(raw.get("r", ""))
        ),
        "suction": (
            SCALAR_SUCTION_LEVELS[s]
            if isinstance(s, int) and 0 <= s < len(SCALAR_SUCTION_LEVELS)
            else s
        ),
        "pattern": SCALAR_CLEAN_PATTERN_NAMES.get(f, f),
    }


def encode_scalar_repeat(days: list[str] | str | None) -> str:
    """Encode day names into a DPS 151 repeat string (1=Mon..7=Sun).

    A string of digits 1-7 passes through sorted; anything else goes through
    ``parse_weekdays`` (ValueError on an unknown word).
    """
    if isinstance(days, str) and days.strip().isdigit() and set(days.strip()) <= set(
        _SCALAR_SCHEDULE_DAYS
    ):
        return "".join(sorted(set(days.strip())))
    return "".join(str(i + 1) for i in sorted(parse_weekdays(days)))


def build_scalar_schedule_payload(raw_entries: list[dict[str, Any]]) -> str:
    """Build DPS 151 schedule JSON string from raw schedule entries."""
    return json.dumps({"l": raw_entries}, separators=(",", ":"))


def scalar_suction_to_int(suction: str | int | None) -> int | None:
    """DPS 102 index (0=Quiet..3=Max) of a suction name or index; None if unknown."""
    if isinstance(suction, int) and not isinstance(suction, bool):
        return suction if 0 <= suction < len(SCALAR_SUCTION_LEVELS) else None
    return _SCALAR_SUCTION_BY_NAME.get(str(suction or "").strip().lower())


def scalar_pattern_to_int(pattern: str | int | None) -> int | None:
    """DPS 151 ``f`` of a pattern name, ``general`` or number; None if unknown."""
    if isinstance(pattern, str) and pattern.strip().isdigit():
        pattern = int(pattern.strip())
    if isinstance(pattern, int) and not isinstance(pattern, bool):
        return pattern if pattern in SCALAR_CLEAN_PATTERN_NAMES else None
    return _SCALAR_PATTERN_BY_NAME.get(str(pattern or "").strip().lower())


def _scalar_level(value: Any, known: int | None, default: int) -> int:
    """A DPS 151 ``s``/``f`` number: the known one, an unnamed int as is, else default."""
    if known is not None:
        return known
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return default


def schedule_entry_to_scalar_raw(entry: dict[str, Any]) -> dict[str, Any]:
    """Convert parsed schedule entry dict back into raw scalar DPS 151 dict.

    Raises ValueError on a day the entry cannot be encoded with.
    """
    suction = entry.get("suction")
    pattern = entry.get("pattern")
    return {
        "id": entry.get("id"),
        "e": bool(entry.get("enabled", True)),
        "t": str(entry.get("time", "")).replace(":", ""),
        "r": encode_scalar_repeat(entry.get("days", "")),
        "s": _scalar_level(
            suction, scalar_suction_to_int(suction), _SCALAR_DEFAULT_SUCTION
        ),
        "f": _scalar_level(
            pattern, scalar_pattern_to_int(pattern), _SCALAR_DEFAULT_PATTERN
        ),
    }


def _process_scalar_dnd(
    state: VacuumState, value: Any, changes: dict[str, Any]
) -> None:
    """Parse scalar-protocol DND JSON: {"en":bool,"start_t":"HHMM","end_t":"HHMM"}."""
    data = value if isinstance(value, dict) else json.loads(value)
    if "en" in data:
        changes["dnd_enabled"] = bool(data["en"])
    start = str(data.get("start_t", "")).zfill(4)
    end = str(data.get("end_t", "")).zfill(4)
    if start.isdigit() and len(start) == 4:
        changes["dnd_start_hour"] = int(start[:2])
        changes["dnd_start_minute"] = int(start[2:])
    if end.isdigit() and len(end) == 4:
        changes["dnd_end_hour"] = int(end[:2])
        changes["dnd_end_minute"] = int(end[2:])
    track_received_field(state, changes, "do_not_disturb")


def _process_scalar_accessories(
    state: VacuumState, value: Any, changes: dict[str, Any]
) -> None:
    """Parse accessory usage JSON (DPS 150) into AccessoryState.

    Stores raw counters; the sensor layer converts them to % remaining.
    """
    data = value if isinstance(value, dict) else json.loads(value)
    accessory_changes = {
        field: int(data[json_key])
        for json_key, field in _SCALAR_ACCESSORY_FIELDS.items()
        if json_key in data
    }
    if accessory_changes:
        changes["accessories"] = replace(state.accessories, **accessory_changes)
        track_received_field(state, changes, "accessories")
