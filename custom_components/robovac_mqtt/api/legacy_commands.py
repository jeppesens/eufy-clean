"""Build plain-value DPS commands for legacy (Tuya Cloud) devices.

Legacy devices use simple string/bool/int DPS values instead of protobuf.
Only a subset of novel commands are supported.
"""

from __future__ import annotations

import logging
from typing import Any

from ..const import LEGACY_CLEAN_SPEEDS, LEGACY_DPS_MAP

_LOGGER = logging.getLogger(__name__)


def build_legacy_command(command: str, **kwargs: Any) -> dict[str, Any]:
    """Build a DPS command dict for legacy devices.

    Returns an empty dict for unsupported commands.
    """
    builder = _COMMAND_BUILDERS.get(command)
    if builder is None:
        _LOGGER.debug("Unsupported legacy command: %s", command)
        return {}
    result = builder(**kwargs)
    _LOGGER.debug("Legacy command %s built: %s", command, result)
    return result


def _build_start_auto(**kwargs: Any) -> dict[str, Any]:
    return {
        LEGACY_DPS_MAP["PLAY_PAUSE"]: True,
        LEGACY_DPS_MAP["WORK_MODE"]: "auto",
    }


def _build_play(**kwargs: Any) -> dict[str, Any]:
    return {LEGACY_DPS_MAP["PLAY_PAUSE"]: True}


def _build_pause(**kwargs: Any) -> dict[str, Any]:
    return {LEGACY_DPS_MAP["PLAY_PAUSE"]: False}


def _build_stop(**kwargs: Any) -> dict[str, Any]:
    return {LEGACY_DPS_MAP["PLAY_PAUSE"]: False}


def _build_return_to_base(**kwargs: Any) -> dict[str, Any]:
    return {LEGACY_DPS_MAP["GO_HOME"]: True}


def _build_find_robot(**kwargs: Any) -> dict[str, Any]:
    active = kwargs.get("active", True)
    return {LEGACY_DPS_MAP["FIND_ROBOT"]: bool(active)}


def _build_set_fan_speed(**kwargs: Any) -> dict[str, Any]:
    fan_speed = kwargs.get("fan_speed")
    if fan_speed is None:
        _LOGGER.warning("set_fan_speed: missing fan_speed argument")
        return {}
    if fan_speed not in LEGACY_CLEAN_SPEEDS:
        _LOGGER.warning("set_fan_speed: unknown speed '%s'", fan_speed)
        return {}
    return {LEGACY_DPS_MAP["CLEAN_SPEED"]: fan_speed}


def _build_clean_spot(**kwargs: Any) -> dict[str, Any]:
    return {
        LEGACY_DPS_MAP["PLAY_PAUSE"]: True,
        LEGACY_DPS_MAP["WORK_MODE"]: "Spot",
    }


def _build_room_clean(**kwargs: Any) -> dict[str, Any]:
    """Legacy room clean — no room IDs supported, just sets mode."""
    if kwargs.get("room_ids"):
        _LOGGER.warning(
            "room_clean: room_ids parameter is not supported on legacy devices; "
            "starting full room clean instead"
        )
    return {
        LEGACY_DPS_MAP["PLAY_PAUSE"]: True,
        LEGACY_DPS_MAP["WORK_MODE"]: "room",
    }


def _build_edge_clean(**kwargs: Any) -> dict[str, Any]:
    return {
        LEGACY_DPS_MAP["PLAY_PAUSE"]: True,
        LEGACY_DPS_MAP["WORK_MODE"]: "Edge",
    }


# Command name -> builder function
_COMMAND_BUILDERS: dict[str, Any] = {
    "start_auto": _build_start_auto,
    "play": _build_play,
    "resume": _build_play,
    "pause": _build_pause,
    "stop": _build_stop,
    "return_to_base": _build_return_to_base,
    "go_home": _build_return_to_base,
    "find_robot": _build_find_robot,
    "set_fan_speed": _build_set_fan_speed,
    "clean_spot": _build_clean_spot,
    "room_clean": _build_room_clean,
    "edge_clean": _build_edge_clean,
}
