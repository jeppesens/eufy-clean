"""Parse legacy (Tuya Cloud) DPS values, plain string/bool/int, into VacuumState."""

from __future__ import annotations

import base64
import json
import logging
from dataclasses import replace
from typing import Any

from ..const import (
    EUFY_CLEAN_ERROR_CODES,
    LEGACY_CHARGING_STATUSES,
    LEGACY_DPS_MAP,
    LEGACY_MAP_ID_DPS,
    LEGACY_SCHEDULE_FAN_LEVELS,
    LEGACY_SCHEDULE_WATER_MODES,
    LEGACY_STAT_DPS_BY_CODE,
    LEGACY_TASK_STATUS_NAMES,
    LEGACY_WORK_MODES,
    LEGACY_WORK_STATUS_MAP,
    WEEKDAY_ABBREVIATIONS,
)
from ..models import VacuumState
from ..profiles import legacy_consumable_fields
from ..utils import parse_weekdays

_LOGGER = logging.getLogger(__name__)


def _resolve_stat_dps(
    schema: dict[str, Any] | None, code: str, default: str
) -> str | None:
    """DPS id carrying ``code`` on this device, or None to read nothing.

    Without a schema fall back to ``default``; with a schema that lacks ``code``
    return None, since that number may mean something else on this model.
    """
    if not schema:
        return default
    for dps_id, desc in schema.items():
        if desc.get("code") == code:
            return dps_id
    return None


def update_state_legacy(
    state: VacuumState,
    dps: dict[str, Any],
    schema: dict[str, Any] | None = None,
) -> tuple[VacuumState, dict[str, Any]]:
    """Parse legacy DPS and return (new_state, changes), as ``parser.update_state``.

    ``schema`` is the device's Tuya DPS schema; when given, statistics DPS are
    located by ``code`` instead of by number.
    """
    changes: dict[str, Any] = {}
    received = set(state.received_fields)
    _LOGGER.debug("Legacy parser: processing %d DPS keys: %s", len(dps), list(dps.keys()))

    raw = dict(state.raw_dps)
    raw.update(dps)
    changes["raw_dps"] = raw

    # by schema code where possible; built-in numbers otherwise
    stat_dps = {
        code: _resolve_stat_dps(schema, code, default)
        for code, default in LEGACY_STAT_DPS_BY_CODE.items()
    }

    for key, value in dps.items():
        if key == LEGACY_DPS_MAP["WORK_STATUS"]:  # "15"
            _process_work_status(value, changes, received)

        elif key == LEGACY_DPS_MAP["BATTERY_LEVEL"]:  # "104"
            _process_battery(value, changes, received)

        elif key == LEGACY_DPS_MAP["CLEAN_SPEED"]:  # "102"
            _process_clean_speed(value, changes, received)

        elif key == LEGACY_DPS_MAP["ERROR_CODE"]:  # "106"
            _process_error_code(value, changes, received)

        elif key == LEGACY_DPS_MAP["FIND_ROBOT"]:  # "103"
            _process_find_robot(value, changes, received)

        elif key == LEGACY_DPS_MAP["WORK_MODE"]:  # "5"
            _process_work_mode(value, changes, received)

        elif key == LEGACY_DPS_MAP["PLAY_PAUSE"]:  # "2"
            _process_play_pause(value, changes, received)

        elif key == stat_dps["ClearTime"]:
            _process_int_dps(value, changes, received, "cleaning_time", "cleaning_stats")

        elif key == stat_dps["ClearArea"]:
            _process_int_dps(value, changes, received, "cleaning_area", "cleaning_stats")

        elif key == stat_dps["ClearTotalTime"]:
            _process_int_dps(
                value, changes, received, "total_cleaning_time", "cleaning_totals"
            )

        elif key == stat_dps["ClearTotalArea"]:
            _process_int_dps(
                value, changes, received, "total_cleaning_area", "cleaning_totals"
            )

        elif key == stat_dps["consumables"]:
            _process_consumables(state, value, changes, received)

        elif key == LEGACY_MAP_ID_DPS:
            _process_map_id(value, changes, received)

    # DPS 122 = pause control position. Reconciled after the loop, and in both
    # directions: DPS 15 reads "Running" all through a paused job, so only 122
    # can move the state back. "Nosweep" (idle position) is ambiguous and is not
    # read as a resume. Read activity from `changes` so a frame that also docked
    # the robot isn't dragged back to cleaning by a stale "Continue".
    pause_ctrl = str(dps.get(LEGACY_DPS_MAP["PAUSE_START"], "")).lower()
    if pause_ctrl:
        activity = changes.get("activity", state.activity)
        if pause_ctrl == "pause":
            if activity == "cleaning":
                changes["activity"] = "paused"
                received.add("activity")
        elif pause_ctrl == "continue" and activity == "paused":
            changes["activity"] = "cleaning"
            received.add("activity")

    if received != state.received_fields:
        changes["received_fields"] = received

    new_state = replace(state, **changes)
    _LOGGER.debug(
        "Legacy parser: %d changes applied: %s",
        len(changes),
        [k for k in changes if k != "raw_dps"],
    )
    return new_state, changes


def _process_work_status(
    value: Any, changes: dict[str, Any], received: set[str]
) -> None:
    """Map legacy work status string to activity and task_status."""
    received.add("work_status")

    status_str = str(value)
    activity = LEGACY_WORK_STATUS_MAP.get(status_str)

    if activity:
        changes["activity"] = activity
        received.add("activity")

        # map the few raw enum values that aren't human-readable
        changes["task_status"] = LEGACY_TASK_STATUS_NAMES.get(status_str, status_str)
        received.add("task_status")

        charging = (
            activity == "docked" and status_str.lower() in LEGACY_CHARGING_STATUSES
        )
        changes["charging"] = charging
        received.add("charging")
        _LOGGER.debug(
            "Legacy work_status: '%s' -> activity=%s, charging=%s",
            status_str, activity, charging,
        )
    else:
        _LOGGER.debug("Unknown legacy work status: %s", value)


def _process_battery(
    value: Any, changes: dict[str, Any], received: set[str]
) -> None:
    """Map battery level (plain int)."""
    try:
        changes["battery_level"] = int(value)
        received.add("battery_level")
    except (ValueError, TypeError):
        _LOGGER.debug("Invalid legacy battery value: %s", value)


def _process_clean_speed(
    value: Any, changes: dict[str, Any], received: set[str]
) -> None:
    """Map clean speed (plain string like 'Standard', 'Turbo')."""
    changes["fan_speed"] = str(value)
    received.add("fan_speed")


def _process_error_code(
    value: Any, changes: dict[str, Any], received: set[str]
) -> None:
    """Map error code (plain int)."""
    try:
        code = int(value)
        changes["error_code"] = code
        changes["error_message"] = EUFY_CLEAN_ERROR_CODES.get(code, f"Unknown ({code})")
        received.add("error_code")
    except (ValueError, TypeError):
        _LOGGER.debug("Invalid legacy error code: %s", value)


def _process_find_robot(
    value: Any, changes: dict[str, Any], received: set[str]
) -> None:
    """Map find robot (plain bool)."""
    changes["find_robot"] = bool(value)
    received.add("find_robot")


def _process_work_mode(
    value: Any, changes: dict[str, Any], received: set[str]
) -> None:
    """Map work mode (plain string like 'auto', 'room')."""
    mode_str = str(value)
    display = LEGACY_WORK_MODES.get(mode_str, mode_str)
    changes["work_mode"] = display
    received.add("work_mode")


def _process_int_dps(
    value: Any,
    changes: dict[str, Any],
    received: set[str],
    field_name: str,
    received_key: str,
) -> None:
    """Map a plain numeric DPS onto a VacuumState field (Tuya units already match)."""
    try:
        changes[field_name] = int(value)
    except (ValueError, TypeError):
        _LOGGER.debug("Invalid legacy %s value: %s", field_name, value)
        return
    received.add(received_key)


def _decode_raw_json(value: Any) -> dict[str, Any] | None:
    """Decode a Tuya ``raw`` DPS carrying JSON, base64-encoded or already plain."""
    if isinstance(value, dict):
        return value
    if not isinstance(value, str) or not value:
        return None
    candidates = [value]
    try:
        candidates.append(base64.b64decode(value, validate=True).decode())
    except Exception:  # noqa: BLE001 - not base64; the plain attempt still runs
        pass
    for candidate in candidates:
        try:
            decoded = json.loads(candidate)
        except (ValueError, TypeError):
            continue
        if isinstance(decoded, dict):
            return decoded
    return None


def _process_consumables(
    state: VacuumState, value: Any, changes: dict[str, Any], received: set[str]
) -> None:
    """Map DPS 116 accessory hours-used onto AccessoryState."""
    doc = _decode_raw_json(value)
    if not isinstance(doc, dict):
        _LOGGER.debug("Unparsable legacy consumables payload: %s", value)
        return
    consumable = doc.get("consumable")
    durations = consumable.get("duration") if isinstance(consumable, dict) else None
    if not isinstance(durations, dict):
        _LOGGER.debug("Legacy consumables payload has no duration map: %s", doc)
        return

    updates: dict[str, int] = {}
    for dps_key, field_name in legacy_consumable_fields().items():
        raw = durations.get(dps_key)
        if raw is None:
            continue
        try:
            updates[field_name] = int(raw)
        except (ValueError, TypeError):
            _LOGGER.debug("Invalid legacy consumable %s: %s", dps_key, raw)
    if not updates:
        return

    changes["accessories"] = replace(state.accessories, **updates)
    received.add("accessories")


def _process_map_id(value: Any, changes: dict[str, Any], received: set[str]) -> None:
    """Read the map id from DPS 125 into ``VacuumState.map_id``.

    ``cid`` is the ``mapId`` other commands reference; it is not a ``tuyaMapId``
    and does not track the active map.
    """
    doc = _decode_raw_json(value)
    if doc is None:
        return
    raw = doc.get("cid", doc.get("defaultID"))
    if raw is None:
        return
    try:
        map_id = int(raw)
    except (TypeError, ValueError):
        _LOGGER.debug("Legacy map id payload has no usable cid: %s", doc)
        return
    changes["map_id"] = map_id
    received.add("map_id")


def _process_play_pause(
    value: Any, changes: dict[str, Any], received: set[str]
) -> None:
    """Record that play/pause was seen; work_status stays the activity source."""
    received.add("play_pause")


# Tuya's `loops` mask is Sunday-first (index 0 = Sunday), unlike scalar DPS 151.
_LOOPS_DAYS = (WEEKDAY_ABBREVIATIONS[-1], *WEEKDAY_ABBREVIATIONS[:-1])  # Sun..Sat
# Schedule levels read case-insensitively, water in either spelling.
_SCHEDULE_FAN_BY_WIRE = {level.lower(): level for level in LEGACY_SCHEDULE_FAN_LEVELS}
_SCHEDULE_WATER_BY_WIRE = {
    spelling.lower(): level
    for level, wire in LEGACY_SCHEDULE_WATER_MODES.items()
    for spelling in (level, wire)
}


def _decode_loops(loops: Any) -> str:
    """Human days from a Sunday-first ``loops`` mask; empty/all-zero = one-shot."""
    mask = str(loops or "")
    if not mask or set(mask) <= {"0"}:
        return "Once"
    if mask[:7] == "1111111":
        return "Every day"
    selected = {
        _LOOPS_DAYS[i]
        for i, ch in enumerate(mask[: len(_LOOPS_DAYS)])
        if ch == "1"
    }
    days = [day for day in WEEKDAY_ABBREVIATIONS if day in selected]
    return ", ".join(days) if days else "Once"


def encode_legacy_loops(days: list[str] | str | None) -> str:
    """Encode day names into a 7-char Sunday-first Tuya ``loops`` mask.

    A 7-char 0/1 mask, alone or as the only list item, passes through; anything
    else goes through ``parse_weekdays`` (ValueError on an unknown word).
    """
    mask = days[0] if isinstance(days, list) and len(days) == 1 else days
    if isinstance(mask, str) and len(mask.strip()) == 7 and set(mask.strip()) <= {"0", "1"}:
        return mask.strip()
    selected = {WEEKDAY_ABBREVIATIONS[i] for i in parse_weekdays(days)}
    return "".join("1" if day in selected else "0" for day in _LOOPS_DAYS)


def _parse_legacy_timer(timer: dict[str, Any]) -> dict[str, Any]:
    """Turn one Tuya timer object into a read-only schedule entry."""
    entry: dict[str, Any] = {
        "id": timer.get("timerId"),
        "enabled": timer.get("status") == 1,
        "time": timer.get("time"),
        "days": _decode_loops(timer.get("loops")),
        "loops": timer.get("loops"),
    }
    if timer.get("timezoneId"):
        entry["timezone"] = timer["timezoneId"]

    # DPS 124 = base64 JSON schedule*Clean doc with the clean parameters
    dps_obj = timer.get("dps")
    action = _decode_raw_json(dps_obj.get("124") if isinstance(dps_obj, dict) else None)
    if action:
        if method := action.get("method"):
            entry["action"] = method
        data = action.get("data") or {}
        if "mapId" in data:
            entry["map_id"] = data["mapId"]
        if "cleanLevel" in data:
            entry["suction"] = _SCHEDULE_FAN_BY_WIRE.get(
                str(data["cleanLevel"]).lower(), data["cleanLevel"]
            )
        if "waterMode" in data:
            entry["water"] = _SCHEDULE_WATER_BY_WIRE.get(
                str(data["waterMode"]).lower(), data["waterMode"]
            )
        if "cleanMode" in data:
            entry["mode"] = data["cleanMode"]
        if "cleanTimes" in data:
            entry["clean_times"] = data["cleanTimes"]
        rooms = [
            prop["roomId"]
            for prop in data.get("property") or []
            if isinstance(prop, dict) and prop.get("roomId") is not None
        ] or data.get("roomIds")
        if rooms:
            entry["rooms"] = rooms
    return entry


def parse_legacy_schedules(response: Any) -> list[dict[str, Any]]:
    """Decode a ``tuya.m.timer.all.list`` (et=3) response into schedule entries.

    Legacy schedules live in Tuya cloud, not on a DPS. Entries mirror the scalar
    ``schedules`` shape so both protocols feed one sensor; malformed input gives [].
    """
    if isinstance(response, dict):
        res = response.get("result", response)
        if isinstance(res, dict):
            response = (
                res.get("category")
                or res.get("list")
                or res.get("timers")
                or res.get("groups")
                or []
            )
        elif isinstance(res, list):
            response = res
        else:
            return []
    if not isinstance(response, list):
        return []

    entries: list[dict[str, Any]] = []
    for item in response:
        if not isinstance(item, dict):
            continue
        if "groups" in item:
            for group in item.get("groups") or []:
                if isinstance(group, dict):
                    for timer in group.get("timers") or []:
                        if isinstance(timer, dict):
                            entries.append(_parse_legacy_timer(timer))
        elif "timers" in item:
            for timer in item.get("timers") or []:
                if isinstance(timer, dict):
                    entries.append(_parse_legacy_timer(timer))
        elif "timerId" in item or "time" in item:
            entries.append(_parse_legacy_timer(item))

    entries.sort(key=lambda e: (e.get("time") or ""))
    seen_ids: set[Any] = set()
    deduped: list[dict[str, Any]] = []
    for entry in entries:
        tid = entry.get("id")
        if tid is not None:
            if tid in seen_ids:
                continue
            seen_ids.add(tid)
        deduped.append(entry)
    return deduped
