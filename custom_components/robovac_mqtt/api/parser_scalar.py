"""Inbound DPS parsing for scalar (Tuya-style) protocol devices.

Scalar devices (e.g. T2210/G50) send plain ints and JSON instead of the
X-series protobuf blobs, on a different set of DPS numbers, and emit NO
WorkStatus (DPS 153). api/parser.update_state dispatches here when
state.api_type == "scalar". See docs/g50_capture/FINDINGS.md for the
captured DPS schema.
"""

from __future__ import annotations

import json
import logging
from dataclasses import replace
from typing import Any

from ..const import (
    EUFY_CLEAN_ERROR_CODES,
    EUFY_CLEAN_NOVEL_CLEAN_SPEED,
    SCALAR_CLEAN_PATTERN_NAMES,
    SCALAR_DPS,
    SCALAR_STATE_NAMES,
)
from ..models import VacuumState, track_received_field

_LOGGER = logging.getLogger(__name__)

# Scalar DPS keys whose JSON values map onto accessory usage counters.
_SCALAR_ACCESSORY_FIELDS = {
    "dust_filter": "filter_usage",
    "roller_brush": "main_brush_usage",
    "side_brush": "side_brush_usage",
    "sensors": "sensor_usage",
}

_SCALAR_SCHEDULE_DAYS = {
    "1": "Mon",
    "2": "Tue",
    "3": "Wed",
    "4": "Thu",
    "5": "Fri",
    "6": "Sat",
    "7": "Sun",
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
    """Process DPS for scalar/JSON devices (e.g. T2210/G50).

    Each DPS is handled independently so one bad value never aborts the batch.
    """
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
                if idx is not None and 0 <= idx < 4:
                    changes["fan_speed"] = EUFY_CLEAN_NOVEL_CLEAN_SPEED[idx].value
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
                scheds = _parse_scalar_schedules(value)
                if scheds is not None:
                    changes["schedules"] = scheds
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
                _LOGGER.debug("scalar-protocol unhandled DPS %s: %s", key, value)

        except Exception as e:
            _LOGGER.warning(
                "Error parsing scalar-protocol DPS %s: %s", key, e, exc_info=True
            )

    # DPS 122 is a motion flag (1=stationary, 0=moving). A stationary robot that
    # is otherwise mid-clean is paused — reconcile after the loop so it doesn't
    # matter whether 122 or 15 was processed first.
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


def _parse_scalar_schedules(value: Any) -> list[dict[str, Any]] | None:
    """Decode the DPS 151 schedule JSON into friendly read-only entries.

    Raw entry: {"e":bool, "t":"HHMM", "r":"<day digits 1=Mon..7=Sun>",
                "s":suction 0-3, "f":pattern 1/2, "id":int}.
    """
    data = value if isinstance(value, dict) else json.loads(value)
    out: list[dict[str, Any]] = []
    for e in data.get("l", []):
        t = str(e.get("t", "")).zfill(4)
        s = e.get("s")
        f = e.get("f")
        out.append(
            {
                "id": e.get("id"),
                "enabled": bool(e.get("e")),
                "time": f"{t[:2]}:{t[2:]}" if t.isdigit() and len(t) == 4 else t,
                "days": ", ".join(
                    _SCALAR_SCHEDULE_DAYS.get(d, d) for d in str(e.get("r", ""))
                ),
                "suction": (
                    EUFY_CLEAN_NOVEL_CLEAN_SPEED[s].value
                    if isinstance(s, int) and 0 <= s < 4
                    else s
                ),
                "pattern": SCALAR_CLEAN_PATTERN_NAMES.get(f, f),
            }
        )
    return out


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
    """Parse scalar-protocol accessory usage-counter JSON (DPS 150) into AccessoryState.

    Stores raw usage counters; conversion to % remaining happens in the sensor
    layer (per-accessory max life). See docs/g50_capture/FINDINGS.md.
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
