"""Build plain-value DPS commands for legacy (Tuya Cloud) devices.

Enum spellings are model-specific and an unrecognised value is dropped silently,
so builders match against the device's Tuya schema range when one is available.
"""

from __future__ import annotations

import base64
import json
import logging
import time
from typing import Any

from ..const import (
    LEGACY_CLEAN_SPEEDS,
    LEGACY_DPS_MAP,
    LEGACY_ROOM_DEFAULT_FAN,
    LEGACY_ROOM_DEFAULT_WATER,
    LEGACY_ROOM_FAN_LEVELS,
    LEGACY_ROOM_WATER_LEVELS,
    LEGACY_SCHEDULE_FAN_LEVELS,
    LEGACY_SCHEDULE_WATER_MODES,
)
from ..profiles import legacy_consumable_reset_key
from ..utils import clamp_clean_times

_LOGGER = logging.getLogger(__name__)

Schema = dict[str, dict[str, Any]]

# DPS 122 is the explicit pause control; without it pause degrades to stop (DPS 2).
_DPS_PAUSE_START = LEGACY_DPS_MAP["PAUSE_START"]

# map operations ride whichever DPS the device calls mapOperations
_DPS_MAP_OPS = LEGACY_DPS_MAP["MAP_OPERATIONS"]

# the map keepalive rides its own write-only "mapData" datapoint
_DPS_MAP_KEEP_ALIVE = LEGACY_DPS_MAP["MAP_KEEP_ALIVE"]

# Schedule cleanMode: the whole-map settings, or each room's own (customRooms).
_SCHEDULE_CLEAN_MODES = ("general", "customize")


def _encode_raw_json(doc: dict[str, Any]) -> tuple[str, int]:
    """Serialise an RPC doc as a Tuya ``raw`` DPS: (base64, JSON byte length)."""
    body = json.dumps(doc, separators=(",", ":")).encode()
    return base64.b64encode(body).decode(), len(body)


def _map_operation(method: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
    """Wrap a DPS 124 request in the envelope the firmware requires.

    The epoch-ms ``timestamp`` is mandatory: without it the document is dropped
    silently. ``fastMapping`` takes no arguments and omits ``data``.
    """
    doc: dict[str, Any] = {"method": method}
    if data is not None:
        doc["data"] = data
    doc["timestamp"] = int(time.time() * 1000)
    return doc


def _map_command(
    method: str, data: dict[str, Any] | None = None, schema: Schema | None = None
) -> dict[str, Any]:
    """Build the DPS write for one map operation."""
    encoded, body_len = _encode_raw_json(_map_operation(method, data))
    declared = (schema or {}).get(_DPS_MAP_OPS, {}).get("maxlen")
    if declared and body_len > declared:
        # the declared cap is advisory — larger documents are accepted
        _LOGGER.debug(
            "%s: %d-byte payload exceeds the %d bytes DPS %s declares; sending "
            "anyway", method, body_len, declared, _DPS_MAP_OPS,
        )
    return {_DPS_MAP_OPS: encoded}


def _int_list(values: Any, label: str) -> list[int] | None:
    """Coerce a caller-supplied id list to ints, or complain and return None."""
    if not values:
        return None
    try:
        return [int(value) for value in values]
    except (TypeError, ValueError):
        _LOGGER.warning("%s: expected integers, got %s", label, values)
        return None


def _enum_value(schema: Schema | None, dps: str, *candidates: str) -> str | None:
    """Spelling of an enum value this device accepts, tried in order; else None.

    With no schema the first candidate is returned unchanged.
    """
    allowed = (schema or {}).get(dps, {}).get("range")
    if not allowed:
        return candidates[0] if candidates else None
    lowered = {str(value).lower(): value for value in allowed}
    for candidate in candidates:
        if candidate in allowed:
            return candidate
        match = lowered.get(candidate.lower())
        if match is not None:
            return match
    return None


def build_legacy_command(
    command: str, schema: Schema | None = None, **kwargs: Any
) -> dict[str, Any]:
    """Build a DPS command dict for legacy devices; {} when unsupported."""
    builder = _COMMAND_BUILDERS.get(command)
    if builder is None:
        _LOGGER.debug("Unsupported legacy command: %s", command)
        return {}
    result = builder(schema=schema, **kwargs)
    # DPS keys only: values can carry room names or the device id.
    _LOGGER.debug("Legacy command %s built for DPS %s", command, sorted(result))
    return result


def _mode_command(
    schema: Schema | None, label: str, *candidates: str
) -> dict[str, Any]:
    """Start a clean in the given work mode, if the device supports it."""
    mode = _enum_value(schema, LEGACY_DPS_MAP["WORK_MODE"], *candidates)
    if mode is None:
        _LOGGER.warning(
            "%s: this device does not support any of %s (accepted modes: %s)",
            label,
            ", ".join(candidates),
            (schema or {}).get(LEGACY_DPS_MAP["WORK_MODE"], {}).get("range"),
        )
        return {}
    return {
        LEGACY_DPS_MAP["PLAY_PAUSE"]: True,
        LEGACY_DPS_MAP["WORK_MODE"]: mode,
    }


def _build_start_auto(schema: Schema | None = None, **kwargs: Any) -> dict[str, Any]:
    return _mode_command(schema, "start_auto", "auto")


def _pause_control(schema: Schema | None, *candidates: str) -> str | None:
    """Pause/resume value to write, or None when the schema declares no DPS 122."""
    if not schema or _DPS_PAUSE_START not in schema:
        return None
    return _enum_value(schema, _DPS_PAUSE_START, *candidates)


def _build_play(schema: Schema | None = None, **kwargs: Any) -> dict[str, Any]:
    resume = _pause_control(schema, "Continue")
    if resume is not None:
        return {_DPS_PAUSE_START: resume}
    return {LEGACY_DPS_MAP["PLAY_PAUSE"]: True}


def _build_pause(schema: Schema | None = None, **kwargs: Any) -> dict[str, Any]:
    # without DPS 122 the only lever is DPS 2 False, which stops rather than pauses
    pause = _pause_control(schema, "Pause")
    if pause is not None:
        return {_DPS_PAUSE_START: pause}
    return {LEGACY_DPS_MAP["PLAY_PAUSE"]: False}


def _build_stop(schema: Schema | None = None, **kwargs: Any) -> dict[str, Any]:
    return {LEGACY_DPS_MAP["PLAY_PAUSE"]: False}


def _build_return_to_base(
    schema: Schema | None = None, **kwargs: Any
) -> dict[str, Any]:
    return {LEGACY_DPS_MAP["GO_HOME"]: True}


def _build_find_robot(schema: Schema | None = None, **kwargs: Any) -> dict[str, Any]:
    active = kwargs.get("active", True)
    return {LEGACY_DPS_MAP["FIND_ROBOT"]: bool(active)}


def _build_set_fan_speed(
    schema: Schema | None = None, **kwargs: Any
) -> dict[str, Any]:
    fan_speed = kwargs.get("fan_speed")
    if fan_speed is None:
        _LOGGER.warning("set_fan_speed: missing fan_speed argument")
        return {}
    speed_dps = LEGACY_DPS_MAP["CLEAN_SPEED"]
    allowed = (schema or {}).get(speed_dps, {}).get("range") or LEGACY_CLEAN_SPEEDS
    resolved = _enum_value(schema, speed_dps, fan_speed) if schema else fan_speed
    if resolved is None or resolved not in allowed:
        _LOGGER.warning(
            "set_fan_speed: unknown speed '%s' (accepted: %s)", fan_speed, allowed
        )
        return {}
    return {speed_dps: resolved}


def _build_clean_spot(schema: Schema | None = None, **kwargs: Any) -> dict[str, Any]:
    return _mode_command(schema, "clean_spot", "Spot", "spot")


def _build_room_clean(schema: Schema | None = None, **kwargs: Any) -> dict[str, Any]:
    """Clean named rooms via ``selectRoomsClean`` (DPS 124); no ids = ``room`` mode."""
    room_ids = kwargs.get("room_ids")
    if not room_ids:
        return _mode_command(schema, "room_clean", "room")

    ids = _int_list(room_ids, "room_clean: room_ids")
    if ids is None:
        return {}

    if not _supports_map_ops(schema, "room_clean"):
        return _mode_command(schema, "room_clean", "room")

    return _map_command(
        "selectRoomsClean",
        {"roomIds": ids, "cleanTimes": clamp_clean_times(kwargs.get("clean_times"))},
        schema,
    )


def _build_zone_clean(schema: Schema | None = None, **kwargs: Any) -> dict[str, Any]:
    """Clean free-form rectangles (``selectZonesClean`` on DPS 124).

    ``zones`` are 4-corner quads in the map blob's 0.5 cm frame, not the render's
    world-cm frame; the coordinator converts. Each zone is sent with flattened
    ``x0,y0..x3,y3`` keys plus ``type``/``cleanTimes``, not nested points.
    """
    zones = kwargs.get("zones")
    if not zones:
        _LOGGER.warning("zone_clean: no zones supplied; nothing sent")
        return {}

    if not _supports_map_ops(schema, "zone_clean"):
        return {}

    clean_times = clamp_clean_times(kwargs.get("clean_times"))
    payload: list[dict[str, Any]] = []
    for quad in zones:
        pts = list(quad)
        if len(pts) != 4 or any(len(p) != 2 for p in pts):
            _LOGGER.warning(
                "zone_clean: each zone must be 4 (x, y) corners, got %s; "
                "refusing the whole request rather than cleaning the wrong area",
                quad,
            )
            return {}
        entry: dict[str, Any] = {}
        for index, (x, y) in enumerate(pts):
            entry[f"x{index}"] = int(round(x))
            entry[f"y{index}"] = int(round(y))
        entry["type"] = "sweep"
        entry["cleanTimes"] = clean_times
        payload.append(entry)

    return _map_command("selectZonesClean", {"zones": payload}, schema)


def _flatten_points(points: list[tuple[int, int]]) -> dict[str, int]:
    """``[(x, y), ...]`` -> ``{"x0": …, "y0": …, "x1": …}``.

    Vertex count varies by shape: four for a rectangular zone, two for a wall.
    """
    entry: dict[str, int] = {}
    for index, (x, y) in enumerate(points):
        entry[f"x{index}"] = int(round(x))
        entry[f"y{index}"] = int(round(y))
    return entry


def _build_set_nogo_zones(schema: Schema | None = None, **kwargs: Any) -> dict[str, Any]:
    """Replace the map's restricted geometry (``setNogoZones`` on DPS 124).

    Args: ``forbidden_zones`` (4 points), ``virtual_walls`` (2), ``ban_mop_zones``
    (4), all in the map blob's 0.5 cm frame; the coordinator converts.

    REPLACE-ALL across all three lists at once, and it fails silently: passing
    only new no-go zones erases the existing walls and no-mop zones. All three
    empty is legitimate (it clears everything), so empty is not a no-op here.
    """
    if not _supports_map_ops(schema, "set_nogo_zones"):
        return {}

    def shapes(key: str, expected: int) -> list[dict[str, int]]:
        out: list[dict[str, int]] = []
        for shape in kwargs.get(key) or []:
            points = [tuple(p) for p in shape]
            if len(points) != expected or any(len(p) != 2 for p in points):
                _LOGGER.warning(
                    "set_nogo_zones: each %s needs %d (x, y) points, got %s; skipped",
                    key, expected, shape,
                )
                continue
            out.append(_flatten_points(points))
        return out

    return _map_command(
        "setNogoZones",
        {
            "forbiddenZones": shapes("forbidden_zones", 4),
            "virtualWallZones": shapes("virtual_walls", 2),
            "banMopZones": shapes("ban_mop_zones", 4),
        },
        schema,
    )


def _supports_map_ops(schema: Schema | None, label: str) -> bool:
    """Whether this device declares the mapOperations datapoint at all."""
    if schema and _DPS_MAP_OPS not in schema:
        _LOGGER.warning(
            "%s: this device has no DPS %s (mapOperations)", label, _DPS_MAP_OPS
        )
        return False
    return True


def _build_fast_mapping(schema: Schema | None = None, **kwargs: Any) -> dict[str, Any]:
    """Run an exploration pass that builds the map without cleaning."""
    if not _supports_map_ops(schema, "fast_mapping"):
        return {}
    return _map_command("fastMapping", None, schema)


def _room_level(value: Any, levels: tuple[str, ...], label: str) -> str | None:
    """Resolve a per-room fan/water setting (blob index or name) to its string."""
    if isinstance(value, bool):
        _LOGGER.warning("%s: expected a level, got %r", label, value)
        return None
    if isinstance(value, int):
        if 0 <= value < len(levels):
            return levels[value]
        _LOGGER.warning("%s: index %d outside %s", label, value, levels)
        return None
    if isinstance(value, str):
        lowered = {level.lower(): level for level in levels}
        if value.lower() in lowered:
            return lowered[value.lower()]
    _LOGGER.warning("%s: unknown level %r (accepted: %s)", label, value, levels)
    return None


def _room_property(entry: Any) -> dict[str, Any] | None:
    """Build one ``customRooms`` entry (``id`` or ``room_id``); one bad entry voids all."""
    if not isinstance(entry, dict):
        _LOGGER.warning("set_room_custom: entry needs a room_id: %r", entry)
        return None
    # room id 0 is a real room id here — compare against None, never truthiness
    raw_id = entry.get("room_id")
    if raw_id is None:
        raw_id = entry.get("id")
    if raw_id is None:
        _LOGGER.warning("set_room_custom: entry needs a room_id: %r", entry)
        return None
    try:
        room_id = int(raw_id)
    except (TypeError, ValueError):
        _LOGGER.warning("set_room_custom: bad room_id %r", raw_id)
        return None

    prop: dict[str, Any] = {"roomId": room_id}
    if (fan := entry.get("fan_speed")) is not None:
        level = _room_level(fan, LEGACY_ROOM_FAN_LEVELS, f"room {room_id} fan_speed")
        if level is None:
            return None
        prop["cleanLevel"] = level
    if (water := entry.get("water_level")) is not None:
        level = _room_level(
            water, LEGACY_ROOM_WATER_LEVELS, f"room {room_id} water_level"
        )
        if level is None:
            return None
        prop["waterMode"] = level
    if (times := entry.get("clean_times")) is not None:
        try:
            times = int(times)
        except (TypeError, ValueError):
            _LOGGER.warning("set_room_custom: bad clean_times %r", times)
            return None
        prop["cleanTimes"] = clamp_clean_times(times)
    return prop


def _map_id_of(kwargs: dict[str, Any], label: str) -> int | None:
    """Read the map id these room documents must be addressed to."""
    map_id = kwargs.get("map_id")
    if map_id is None:
        _LOGGER.warning("%s: needs a map_id", label)
        return None
    try:
        return int(map_id)
    except (TypeError, ValueError):
        _LOGGER.warning("%s: bad map_id %r", label, map_id)
        return None


def _build_set_room_custom(
    schema: Schema | None = None, **kwargs: Any
) -> dict[str, Any]:
    """Set per-room suction/water/repeat overrides.

    ``customRooms`` is replace-all: the firmware collapses every room missing from
    ``property``, so the document must name each room that keeps an override.
    Callers assert that with ``complete=True`` (dict entries only); without it the
    document is refused, since a partial one applies cleanly and wipes the rest.
    """
    if not _supports_map_ops(schema, "set_room_custom"):
        return {}
    map_id = _map_id_of(kwargs, "set_room_custom")
    if map_id is None:
        return {}

    entries = kwargs.get("room_config")
    if not entries:
        _LOGGER.warning("set_room_custom: no room_config supplied")
        return {}
    if not kwargs.get("complete"):
        _LOGGER.warning(
            "set_room_custom: refusing a room_config that was not declared "
            "complete — customRooms is replace-all and would collapse every "
            "room missing from it; route per-room settings through "
            "async_set_room_configs"
        )
        return {}
    if not all(isinstance(entry, dict) for entry in entries):
        _LOGGER.warning(
            "set_room_custom: room_config must be per-room dicts, not bare ids: %r",
            entries,
        )
        return {}
    properties = [_room_property(entry) for entry in entries]
    if any(prop is None for prop in properties):
        return {}

    return _map_command(
        "customRooms",
        {
            "mapId": map_id,
            "active": bool(kwargs.get("active", True)),
            "property": properties,
        },
        schema,
    )


def _build_set_custom_clean(
    schema: Schema | None = None, **kwargs: Any
) -> dict[str, Any]:
    """Toggle per-room custom cleaning; ``mapId``/``active`` alone is intended here."""
    if not _supports_map_ops(schema, "set_custom_clean"):
        return {}
    map_id = _map_id_of(kwargs, "set_custom_clean")
    if map_id is None:
        return {}
    return _map_command(
        "customRooms",
        {"mapId": map_id, "active": bool(kwargs.get("active", True))},
        schema,
    )


def _build_set_room_order(
    schema: Schema | None = None, **kwargs: Any
) -> dict[str, Any]:
    """Set the clean order from a full ordered id list; replace-all, 1-based."""
    if not _supports_map_ops(schema, "set_room_order"):
        return {}
    map_id = _map_id_of(kwargs, "set_room_order")
    if map_id is None:
        return {}
    ids = _int_list(kwargs.get("room_ids"), "set_room_order: room_ids")
    if not ids:
        _LOGGER.warning("set_room_order: needs the full ordered room_ids list")
        return {}
    return _map_command(
        "globalRooms",
        {
            "mapId": map_id,
            "property": [
                {"roomId": room_id, "cleanOrder": position}
                for position, room_id in enumerate(ids, start=1)
            ],
        },
        schema,
    )


def _build_rename_room(schema: Schema | None = None, **kwargs: Any) -> dict[str, Any]:
    """Rename one room; unlike the other room documents this is not replace-all."""
    if not _supports_map_ops(schema, "rename_room"):
        return {}
    room_id = kwargs.get("room_id")
    name = kwargs.get("name")
    if room_id is None or not name:
        _LOGGER.warning("rename_room: needs room_id and name")
        return {}
    try:
        room_id = int(room_id)
    except (TypeError, ValueError):
        _LOGGER.warning("rename_room: bad room_id %r", room_id)
        return {}
    return _map_command("renameRoom", {"roomId": room_id, "newName": str(name)}, schema)


def build_map_keepalive(
    device_id: str, schema: Schema | None = None
) -> dict[str, str]:
    """Renew the live pose/trail stream, which the device closes mid-clean.

    Writes a raw ``{"type", "id", "timestamp"}`` to DPS 121 — not the DPS 124
    envelope, but the epoch-ms timestamp is still mandatory.
    """
    if schema and _DPS_MAP_KEEP_ALIVE not in schema:
        _LOGGER.debug(
            "map_keepalive: this device has no DPS %s (mapData)",
            _DPS_MAP_KEEP_ALIVE,
        )
        return {}
    encoded, _ = _encode_raw_json(
        {
            "type": "mapData",
            "id": device_id,
            "timestamp": int(time.time() * 1000),
        }
    )
    return {_DPS_MAP_KEEP_ALIVE: encoded}


def build_legacy_schedule_dps(
    *,
    map_id: int,
    suction: str | int | None = None,
    water: str | int | None = None,
    mode: str | None = None,
    rooms: list[int] | None = None,
    clean_times: int | None = None,
    schema: Schema | None = None,
) -> dict[str, str]:
    """DPS 124 document a cleaning-schedule timer replays.

    Document shape as the eufy app stores it: all six ``data`` fields, rooms as
    ``property[].roomId``, plus the map-operation ``timestamp``. Unset levels
    and mode take the middle level and ``general``; no rooms is a whole-house
    clean. Raises ValueError on a level or mode outside the schedule vocabulary.
    """
    clean_mode = str(mode or _SCHEDULE_CLEAN_MODES[0]).strip().lower()
    if clean_mode not in _SCHEDULE_CLEAN_MODES:
        raise ValueError(
            f"unknown schedule mode {mode!r} (accepted: {', '.join(_SCHEDULE_CLEAN_MODES)})"
        )
    fan = _room_level(
        LEGACY_ROOM_DEFAULT_FAN if suction is None else suction,
        LEGACY_SCHEDULE_FAN_LEVELS,
        "schedule suction",
    )
    water_level = _room_level(
        LEGACY_ROOM_DEFAULT_WATER if water is None else water,
        tuple(LEGACY_SCHEDULE_WATER_MODES),
        "schedule wash",
    )
    if fan is None or water_level is None:
        raise ValueError(
            f"unknown schedule level: suction {suction!r} (accepted: "
            f"{', '.join(LEGACY_SCHEDULE_FAN_LEVELS)}), wash {water!r} (accepted: "
            f"{', '.join(LEGACY_SCHEDULE_WATER_MODES)})"
        )
    room_ids = [int(room) for room in rooms or []]
    return _map_command(
        "scheduleRoomsClean" if room_ids else "scheduleAutoClean",
        {
            "mapId": int(map_id),
            "cleanMode": clean_mode,
            "cleanLevel": fan,
            "waterMode": LEGACY_SCHEDULE_WATER_MODES[water_level],
            "property": [{"roomId": room_id} for room_id in room_ids],
            "cleanTimes": clamp_clean_times(clean_times),
        },
        schema,
    )


def _build_edge_clean(schema: Schema | None = None, **kwargs: Any) -> dict[str, Any]:
    return _mode_command(schema, "edge_clean", "Edge", "edge")


def _build_reset_accessory(schema: Schema | None = None, **kwargs: Any) -> dict[str, Any]:
    """Reset a consumable counter: base64 JSON {"consumable": {"reset": [key]}}."""
    legacy_key = kwargs.get("legacy_key")
    if not legacy_key:
        reset_type = kwargs.get("reset_type")
        if reset_type is not None:
            try:
                legacy_key = legacy_consumable_reset_key(int(reset_type))
            except (TypeError, ValueError):
                pass
    if not legacy_key:
        _LOGGER.warning("reset_accessory: unknown accessory %s", kwargs)
        return {}

    dps = LEGACY_DPS_MAP["CONSUMABLES"]
    if schema:
        for dps_id, desc in schema.items():
            if desc.get("code") == "consumables":
                dps = dps_id
                break

    doc = {"consumable": {"reset": [legacy_key]}}
    encoded, _ = _encode_raw_json(doc)
    return {dps: encoded}


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
    "set_nogo_zones": _build_set_nogo_zones,
    "zone_clean": _build_zone_clean,
    "edge_clean": _build_edge_clean,
    "reset_accessory": _build_reset_accessory,
    # Map operations, all carried as timestamped JSON on DPS 124.
    "fast_mapping": _build_fast_mapping,
    "set_room_custom": _build_set_room_custom,
    "set_custom_clean": _build_set_custom_clean,
    "set_room_order": _build_set_room_order,
    "rename_room": _build_rename_room,
}
