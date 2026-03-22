"""Parse legacy (Tuya Cloud) DPS values into VacuumState.

Legacy devices use plain string/bool/int DPS values (no protobuf).
DPS keys: 2 (play/pause), 3 (direction), 5 (work mode), 15 (work status),
101 (go home), 102 (clean speed), 103 (find robot), 104 (battery), 106 (error).
"""

from __future__ import annotations

import logging
from dataclasses import replace
from typing import Any

from ..const import (
    EUFY_CLEAN_ERROR_CODES,
    LEGACY_DPS_MAP,
    LEGACY_WORK_MODES,
    LEGACY_WORK_STATUS_MAP,
)
from ..models import VacuumState

_LOGGER = logging.getLogger(__name__)


def update_state_legacy(
    state: VacuumState, dps: dict[str, Any]
) -> tuple[VacuumState, dict[str, Any]]:
    """Parse legacy DPS dict and return (new_state, changes).

    Same contract as ``api.parser.update_state`` so the coordinator can
    call either one transparently.
    """
    changes: dict[str, Any] = {}
    received = set(state.received_fields)

    # Store raw DPS
    raw = dict(state.raw_dps)
    raw.update(dps)
    changes["raw_dps"] = raw

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

    if received != state.received_fields:
        changes["received_fields"] = received

    new_state = replace(state, **changes)
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

        # Derive task_status from the raw status string
        changes["task_status"] = status_str
        received.add("task_status")

        # Derive charging from activity
        changes["charging"] = activity == "docked" and status_str.lower() in (
            "charging",
            "completed",
        )
        received.add("charging")
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


def _process_play_pause(
    value: Any, changes: dict[str, Any], received: set[str]
) -> None:
    """Derive activity hint from play/pause boolean.

    Only used when work_status is not present in the same DPS update.
    The coordinator will handle ordering; we just record the hint.
    """
    received.add("play_pause")
    # If play_pause is True and we haven't already set activity from work_status,
    # we don't override -- work_status is the authoritative source.
    # This field is mainly useful for confirming command delivery.
