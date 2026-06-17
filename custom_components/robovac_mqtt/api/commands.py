from __future__ import annotations

import base64
import json
import logging
from typing import Any, cast

from ..const import (
    CLEAN_EXTENT_MAP,
    CLEAN_TYPE_MAP,
    DPS_MAP,
    EUFY_CLEAN_CONTROL,
    EUFY_CLEAN_NOVEL_CLEAN_SPEED,
    MOP_CORNER_MAP,
    MOP_LEVEL_MAP,
    SCALAR_CLEAN_PATTERN_NAMES,
    SCALAR_DPS,
    SCALAR_WORK_MODE_GO_HOME,
    SCALAR_WORK_MODE_START,
    VOICE_CATALOG,
)
from ..proto.cloud.clean_param_pb2 import CleanParam, CleanParamRequest, Fan
from ..proto.cloud.consumable_pb2 import ConsumableRequest
from ..proto.cloud.control_pb2 import ModeCtrlRequest, SelectRoomsClean
from ..proto.cloud.map_edit_pb2 import MapEditRequest
from ..proto.cloud.station_pb2 import StationRequest
from ..proto.cloud.undisturbed_pb2 import UndisturbedRequest
from ..proto.cloud.unisetting_pb2 import UnisettingRequest
from ..utils import encode, encode_message, encode_varint

_LOGGER = logging.getLogger(__name__)


def _normalize_clean_mode(clean_mode: str) -> str:
    """Normalize a cleaning mode label into a map lookup key."""
    return clean_mode.strip().lower().replace("_", " ")


def build_set_cleaning_mode_command(clean_mode: str) -> dict[str, str]:
    """Build command to set cleaning mode for both auto and room/area cleans."""
    clean_type_val = CLEAN_TYPE_MAP.get(_normalize_clean_mode(clean_mode))
    if clean_type_val is None:
        _LOGGER.warning("Invalid clean_mode '%s' ignored", clean_mode)
        return {}

    param = CleanParam(clean_type={"value": clean_type_val})
    req = CleanParamRequest(clean_param=param, area_clean_param=param)
    value = encode_message(req)
    return {DPS_MAP["CLEANING_PARAMETERS"]: value}


def _build_mode_ctrl(method: int) -> dict[str, str]:
    """Helper for ModeCtrlRequest commands."""
    data: dict[str, Any] = {"method": int(method)}

    # Special handling for methods that require a parameter in the "oneof Param"
    if method == EUFY_CLEAN_CONTROL.START_AUTO_CLEAN:
        # AutoClean message: clean_times=1, force_mapping=False
        data["auto_clean"] = {"clean_times": 1, "force_mapping": False}
    elif method == EUFY_CLEAN_CONTROL.START_SPOT_CLEAN:
        # SpotClean message: clean_times=1
        data["spot_clean"] = {"clean_times": 1}

    value = encode(ModeCtrlRequest, data)
    return {DPS_MAP["PLAY_PAUSE"]: value}


def _build_manual_cmd(cmd_name: str, active: bool = True) -> dict[str, str]:
    """Helper for StationRequest manual commands."""
    value = encode(StationRequest, {"manual_cmd": {cmd_name: active}})
    return {DPS_MAP["GO_HOME"]: value}


def build_set_clean_speed_command(clean_speed: str) -> dict[str, int]:
    """Build command to set fan speed."""
    try:
        speed_lower = clean_speed.lower()
        variants = [s.lower() for s in EUFY_CLEAN_NOVEL_CLEAN_SPEED]

        if speed_lower in variants:
            idx = variants.index(speed_lower)
            return {DPS_MAP["CLEAN_SPEED"]: idx}

    except ValueError:
        pass

    return {}


def build_set_water_level_command(water_level: str) -> dict[str, str]:
    """Build command to set mop water level for both auto and room/area cleans."""
    level_val = MOP_LEVEL_MAP.get(water_level.lower())
    if level_val is None:
        _LOGGER.warning("Invalid water_level '%s' ignored", water_level)
        return {}
    param = CleanParam(mop_mode={"level": level_val})
    req = CleanParamRequest(clean_param=param, area_clean_param=param)
    value = encode_message(req)
    return {DPS_MAP["CLEANING_PARAMETERS"]: value}


def build_set_cleaning_intensity_command(cleaning_intensity: str) -> dict[str, str]:
    """Build command to set cleaning intensity for both auto and room/area cleans."""
    extent_val = CLEAN_EXTENT_MAP.get(cleaning_intensity.lower())
    if extent_val is None:
        _LOGGER.warning("Invalid cleaning_intensity '%s' ignored", cleaning_intensity)
        return {}

    param = CleanParam(clean_extent={"value": extent_val})
    req = CleanParamRequest(clean_param=param, area_clean_param=param)
    value = encode_message(req)
    return {DPS_MAP["CLEANING_PARAMETERS"]: value}


def build_scene_clean_command(scene_id: int) -> dict[str, str]:
    """Build command to trigger a specific scene."""
    value = encode(
        ModeCtrlRequest,
        {
            "method": EUFY_CLEAN_CONTROL.START_SCENE_CLEAN,
            "scene_clean": {"scene_id": scene_id},
        },
    )
    return {DPS_MAP["PLAY_PAUSE"]: value}


def build_room_clean_command(
    room_ids: list[int], map_id: int = 3, mode: str = "GENERAL"
) -> dict[str, str]:
    """Build command to clean specific rooms."""
    if mode == "CUSTOMIZE":
        proto_mode = SelectRoomsClean.CUSTOMIZE
    else:
        proto_mode = SelectRoomsClean.GENERAL

    rooms_clean = SelectRoomsClean(
        rooms=[
            SelectRoomsClean.Room(id=rid, order=i + 1) for i, rid in enumerate(room_ids)
        ],
        mode=proto_mode,
        clean_times=1,
        map_id=map_id,
    )
    value = encode_message(
        ModeCtrlRequest(
            method=cast(
                ModeCtrlRequest.Method, int(EUFY_CLEAN_CONTROL.START_SELECT_ROOMS_CLEAN)
            ),
            select_rooms_clean=rooms_clean,
        )
    )
    return {DPS_MAP["PLAY_PAUSE"]: value}


def build_set_room_custom_command(
    room_config: list[dict[str, Any]] | list[int],
    map_id: int = 3,
    # Legacy arguments for backward compatibility (used if room_config is list[int])
    fan_speed: str | None = None,
    water_level: str | None = None,
    clean_times: int | None = None,
    clean_mode: str | None = None,
    clean_intensity: str | None = None,
    edge_mopping: bool | None = None,
) -> dict[str, str]:
    """Build command to set custom cleaning parameters for specific rooms.

    Supports two formats for `room_config`:
    1. list[int]: Simple list of room IDs. Applies global params (fan_speed, etc.) to all.
    2. list[dict]: List of room objects {id: 1, fan_speed: "Turbo", ...}.
    """
    rooms_parm = MapEditRequest.RoomsCustom.Parm()

    # Normalize input to list of dicts
    normalized_rooms: list[dict[str, Any]] = []

    if room_config and isinstance(room_config[0], int):
        # Legacy format: [1, 2] + global params
        for r_id in room_config:
            normalized_rooms.append(
                {
                    "id": r_id,
                    "fan_speed": fan_speed,
                    "water_level": water_level,
                    "clean_times": clean_times,
                    "clean_mode": clean_mode,
                    "clean_intensity": clean_intensity,
                    "edge_mopping": edge_mopping,
                }
            )
    elif room_config:
        # New format: [{id: 1, fan_speed: ...}, ...]
        normalized_rooms = cast(list[dict[str, Any]], room_config)

    for room_data in normalized_rooms:
        room_id = room_data.get("id")
        if not room_id:
            continue

        custom_cfg = MapEditRequest.RoomsCustom.Parm.Room.Custom()

        # Extract per-room params
        r_fan_speed = room_data.get("fan_speed")
        r_water_level = room_data.get("water_level")
        r_clean_times = room_data.get("clean_times")
        r_clean_mode = room_data.get("clean_mode")
        r_clean_intensity = room_data.get("clean_intensity")
        r_edge_mopping = room_data.get("edge_mopping")

        # Clean Mode
        if r_clean_mode:
            clean_type_val = CLEAN_TYPE_MAP.get(_normalize_clean_mode(r_clean_mode))
            if clean_type_val is not None:
                custom_cfg.clean_type.value = clean_type_val
            else:
                _LOGGER.warning("Invalid clean_mode '%s' ignored", r_clean_mode)

        # Clean Times (Repeats)
        if r_clean_times:
            custom_cfg.clean_times = int(r_clean_times)

        # Clean Intensity (Extent)
        if r_clean_intensity:
            if r_clean_intensity.lower() in CLEAN_EXTENT_MAP:
                custom_cfg.clean_extent.value = CLEAN_EXTENT_MAP[
                    r_clean_intensity.lower()
                ]
            else:
                _LOGGER.warning(
                    "Invalid clean_intensity '%s' ignored", r_clean_intensity
                )

        # Edge Mopping (Corner Clean)
        if r_edge_mopping is not None:
            if r_edge_mopping in MOP_CORNER_MAP:
                custom_cfg.mop_mode.corner_clean = MOP_CORNER_MAP[r_edge_mopping]
            else:
                _LOGGER.warning("Invalid edge_mopping '%s' ignored", r_edge_mopping)

        # Fan Speed (Suction)
        if r_fan_speed:
            try:
                speed_lower = r_fan_speed.lower()
                variants = [s.lower() for s in EUFY_CLEAN_NOVEL_CLEAN_SPEED]
                if speed_lower in variants:
                    val = variants.index(speed_lower)
                    custom_cfg.fan.suction = cast(Fan.Suction, val)
                else:
                    _LOGGER.warning("Invalid fan_speed '%s' ignored", r_fan_speed)
            except ValueError:
                _LOGGER.warning("Error processing fan_speed '%s'", r_fan_speed)

        # Water Level (Mop Mode)
        if r_water_level:
            if r_water_level.lower() in MOP_LEVEL_MAP:
                custom_cfg.mop_mode.level = MOP_LEVEL_MAP[r_water_level.lower()]
            else:
                _LOGGER.warning("Invalid water_level '%s' ignored", r_water_level)

        # Create Room Message
        room_msg = MapEditRequest.RoomsCustom.Parm.Room()
        room_msg.id = int(room_id)
        room_msg.custom.CopyFrom(custom_cfg)
        rooms_parm.rooms.append(room_msg)

    # Wrap in MapEditRequest
    req = MapEditRequest(
        map_id=int(map_id),
        method=MapEditRequest.SET_ROOMS_CUSTOM,
        rooms_custom=MapEditRequest.RoomsCustom(
            rooms_parm=rooms_parm,
        ),
    )

    value = encode_message(req)
    return {DPS_MAP["MAP_EDIT_REQUEST"]: value}


def build_reset_accessory_command(reset_type: int) -> dict[str, str]:
    """Build command to reset accessory usage."""
    value = encode(ConsumableRequest, {"reset_types": [reset_type]})
    return {DPS_MAP["ACCESSORIES_STATUS"]: value}


def build_set_auto_action_cfg_command(cfg_dict: dict[str, Any]) -> dict[str, str]:
    """Build command to set dock auto-action config."""
    value = encode(StationRequest, {"auto_cfg": cfg_dict})
    return {DPS_MAP["GO_HOME"]: value}


def build_find_robot_command(active: bool) -> dict[str, Any]:
    """Build command to find robot."""
    # false = stop finding, true = start finding
    return {DPS_MAP["FIND_ROBOT"]: active}


# --- scalar command builders (e.g. T2210/G50) ----------------------
# These DPS are scalar-protocol-only plain-int writes (no protobuf), so they are
# model-agnostic. Verified live against a real G50 (see docs/g50_capture/FINDINGS.md).


def build_set_boost_iq_command(active: bool) -> dict[str, Any]:
    """scalar-protocol: toggle BoostIQ auto carpet boost (DPS 118)."""
    return {SCALAR_DPS["BOOST_IQ"]: int(bool(active))}


def build_set_cleaning_pattern_command(pattern: str) -> dict[str, Any]:
    """scalar-protocol: set clean path pattern Arranged(1)/Random(2) (DPS 154)."""
    reverse = {name: value for value, name in SCALAR_CLEAN_PATTERN_NAMES.items()}
    return {SCALAR_DPS["CLEAN_PATTERN"]: reverse.get(pattern, 1)}


def build_set_volume_command(volume_pct: int) -> dict[str, Any]:
    """scalar-protocol: set voice volume (DPS 111, 0-10 = 0-100% in 10% steps)."""
    step = max(0, min(10, round(volume_pct / 10)))
    return {SCALAR_DPS["VOLUME"]: step}


def build_set_volume_novel_command(volume_pct: int) -> dict[str, Any]:
    """novel-protocol: set voice volume (DPS 161, plain int 0-100)."""
    return {DPS_MAP["VOLUME"]: max(0, min(100, volume_pct))}


def build_set_voice_command(set_id: int) -> dict[str, Any]:
    """novel-protocol: set voice language (DPS 162, raw LanguageRequest payload)."""
    entry = VOICE_CATALOG.get(set_id)
    if not entry:
        _LOGGER.warning("Unknown voice set_id %d — command ignored", set_id)
        return {}
    return {DPS_MAP["VOICE_LANGUAGE"]: entry[1]}


def build_set_auto_return_command(active: bool) -> dict[str, Any]:
    """scalar-protocol: toggle "Auto-Return Cleaning" (DPS 135)."""
    return {SCALAR_DPS["AUTO_RETURN"]: int(bool(active))}


def build_set_activity_log_command(active: bool) -> dict[str, Any]:
    """scalar-protocol: toggle activity-log upload (DPS 142)."""
    return {SCALAR_DPS["ACTIVITY_LOG"]: int(bool(active))}


def build_scalar_reset_accessory_command(accessory_key: str) -> dict[str, Any]:
    """scalar-protocol: reset an accessory's life counter to 0 (DPS 150 JSON).

    accessory_key is the DPS 150 field, e.g. "sensors", "dust_filter",
    "side_brush", "roller_brush". Captured from the app's /req.
    """
    if not accessory_key:
        return {}
    return {SCALAR_DPS["ACCESSORIES"]: json.dumps({accessory_key: 0})}


def build_scalar_suction_command(fan_speed: str) -> dict[str, Any]:
    """scalar-protocol: set suction by name (DPS 102, 0=Quiet..3=Max)."""
    levels = [s.value for s in EUFY_CLEAN_NOVEL_CLEAN_SPEED[:4]]
    if fan_speed not in levels:
        return {}
    return {SCALAR_DPS["SUCTION"]: levels.index(fan_speed)}


def build_scalar_child_lock_command(active: bool) -> dict[str, Any]:
    """scalar-protocol: toggle child lock (DPS 139)."""
    return {SCALAR_DPS["CHILD_LOCK"]: int(bool(active))}


def build_scalar_find_robot_command(active: bool) -> dict[str, Any]:
    """scalar-protocol: find-robot start/stop (DPS 103)."""
    return {SCALAR_DPS["FIND_ROBOT"]: int(bool(active))}


def build_scalar_undisturbed_command(
    active: bool, begin_hour: int, begin_minute: int, end_hour: int, end_minute: int
) -> dict[str, Any]:
    """scalar-protocol: set DND (DPS 107 JSON {en, start_t:"HHMM", end_t:"HHMM"})."""
    payload = {
        "en": bool(active),
        "start_t": f"{begin_hour:02d}{begin_minute:02d}",
        "end_t": f"{end_hour:02d}{end_minute:02d}",
    }
    return {SCALAR_DPS["DND"]: json.dumps(payload)}


def _encode_proto_ldelim(field_num: int, data: bytes) -> bytes:
    """Encode a protobuf length-delimited field."""
    tag = (field_num << 3) | 2
    return encode_varint(tag) + encode_varint(len(data)) + data


def _encode_proto_varint_field(field_num: int, value: int) -> bytes:
    """Encode a protobuf varint field, omitting zero (proto3 default)."""
    if value == 0:
        return b""
    return encode_varint((field_num << 3) | 0) + encode_varint(value)


_OFF_PEAK_REQUEST_FIELD_NUM = 22  # Field 22 in UnisettingRequest = OffPeakCharging (field 23 in Response)


def _build_off_peak_sub_bytes(
    enabled: bool, begin_hour: int, begin_minute: int, end_hour: int, end_minute: int
) -> bytes:
    """Build the OffPeakCharging sub-message bytes for DPS 176 field 22."""
    enable_inner = _encode_proto_varint_field(1, 1 if enabled else 0)
    begin_inner = (
        _encode_proto_varint_field(1, begin_hour)
        + _encode_proto_varint_field(2, begin_minute)
    )
    end_inner = (
        _encode_proto_varint_field(1, end_hour)
        + _encode_proto_varint_field(2, end_minute)
    )
    return (
        _encode_proto_ldelim(1, enable_inner)
        + _encode_proto_ldelim(2, begin_inner)
        + _encode_proto_ldelim(3, end_inner)
    )


def build_set_off_peak_charging_command(
    enabled: bool,
    begin_hour: int,
    begin_minute: int,
    end_hour: int,
    end_minute: int,
) -> dict[str, str]:
    """Build command to set off-peak charging schedule (DPS 176 field 23).

    Sends only field 23 — the off-peak charging sub-message.  Including any
    other UnisettingRequest field (e.g. children_lock) risks overwriting device
    state with stale coordinator values, so we keep this minimal.
    """
    off_peak_bytes = _encode_proto_ldelim(
        _OFF_PEAK_REQUEST_FIELD_NUM,
        _build_off_peak_sub_bytes(enabled, begin_hour, begin_minute, end_hour, end_minute),
    )
    prefixed = encode_varint(len(off_peak_bytes)) + off_peak_bytes
    value = base64.b64encode(prefixed).decode()
    _LOGGER.debug("Off-peak command DPS 176 field 22: %s", value)
    return {DPS_MAP["UNSETTING"]: value}


def build_set_child_lock_command(active: bool) -> dict[str, str]:
    """Build command to toggle the child lock setting."""
    value = encode(UnisettingRequest, {"children_lock": {"value": active}})
    return {DPS_MAP["UNSETTING"]: value}


def build_set_undisturbed_command(
    active: bool,
    begin_hour: int,
    begin_minute: int,
    end_hour: int,
    end_minute: int,
) -> dict[str, str]:
    """Build command to update the Do Not Disturb schedule."""
    value = encode(
        UndisturbedRequest,
        {
            "undisturbed": {
                "sw": {"value": active},
                "begin": {"hour": begin_hour, "minute": begin_minute},
                "end": {"hour": end_hour, "minute": end_minute},
            }
        },
    )
    return {DPS_MAP["UNDISTURBED"]: value}


def build_command(
    command: str, api_type: str = "novel", **kwargs: Any
) -> dict[str, Any]:
    """Unified command builder.

    *api_type* ("novel" | "scalar") lets shared commands branch to scalar
    (Tuya-style int/JSON) writes for scalar-protocol devices (e.g. T2210/G50).
    Callers that omit it get the default novel (protobuf) behaviour.
    """
    cmd = command.lower()
    is_scalar = api_type == "scalar"

    if is_scalar:
        # Movement, captured verbatim from the app's /req (see FINDINGS.md):
        #   start/clean -> {"5": 1};  go home -> {"5": 3};
        #   pause -> {"122": 1};  resume -> {"122": 0}.
        # (DPS 2/101 — the Tuya-canonical movement DPs — are ACKed but ignored by
        # the G50 firmware; the app drives DPS 5 + 122 instead.)
        if cmd == "start_auto":
            return {SCALAR_DPS["WORK_MODE"]: SCALAR_WORK_MODE_START}
        if cmd in ("play", "resume"):
            return {SCALAR_DPS["PAUSE"]: 2}
        if cmd in ("pause", "stop"):
            return {SCALAR_DPS["PAUSE"]: 1}
        if cmd in ("return_to_base", "go_home"):
            return {SCALAR_DPS["WORK_MODE"]: SCALAR_WORK_MODE_GO_HOME}
        if cmd == "clean_spot":
            _LOGGER.warning("Spot clean is not yet mapped for scalar devices.")
            return {}
        if cmd == "set_fan_speed":
            return build_scalar_suction_command(kwargs.get("fan_speed", ""))
        if cmd == "set_child_lock":
            return build_scalar_child_lock_command(bool(kwargs.get("active", True)))
        if cmd in ("locate", "find_robot"):
            return build_scalar_find_robot_command(bool(kwargs.get("active", True)))
        if cmd == "set_do_not_disturb":
            return build_scalar_undisturbed_command(
                bool(kwargs.get("active", True)),
                int(kwargs.get("begin_hour", 22)),
                int(kwargs.get("begin_minute", 0)),
                int(kwargs.get("end_hour", 8)),
                int(kwargs.get("end_minute", 0)),
            )
        if cmd == "reset_accessory":
            return build_scalar_reset_accessory_command(kwargs.get("scalar_key", ""))

    # Mode Control
    if cmd == "start_auto":
        return _build_mode_ctrl(EUFY_CLEAN_CONTROL.START_AUTO_CLEAN)
    if cmd in ("play", "resume"):
        return _build_mode_ctrl(EUFY_CLEAN_CONTROL.RESUME_TASK)
    if cmd == "pause":
        return _build_mode_ctrl(EUFY_CLEAN_CONTROL.PAUSE_TASK)
    if cmd == "stop":
        return _build_mode_ctrl(EUFY_CLEAN_CONTROL.STOP_TASK)
    if cmd in ("return_to_base", "go_home"):
        return _build_mode_ctrl(EUFY_CLEAN_CONTROL.START_GOHOME)
    if cmd == "clean_spot":
        return _build_mode_ctrl(EUFY_CLEAN_CONTROL.START_SPOT_CLEAN)
    if cmd in ("locate", "find_robot"):
        return build_find_robot_command(kwargs.get("active", True))

    # Manual Control
    if cmd == "go_dry":
        return _build_manual_cmd("go_dry", True)
    if cmd == "stop_dry":
        return _build_manual_cmd("go_dry", False)
    if cmd == "go_selfcleaning":
        return _build_manual_cmd("go_selfcleaning", True)
    if cmd == "collect_dust":
        return _build_manual_cmd("go_collect_dust", True)

    # Complex
    if cmd == "set_cleaning_mode":
        return build_set_cleaning_mode_command(kwargs.get("clean_mode", ""))
    if cmd == "set_cleaning_intensity":
        return build_set_cleaning_intensity_command(
            kwargs.get("cleaning_intensity", "")
        )
    if cmd == "set_fan_speed":
        return build_set_clean_speed_command(kwargs.get("fan_speed", ""))
    if cmd == "set_water_level":
        return build_set_water_level_command(kwargs.get("water_level", ""))
    if cmd == "scene_clean":
        return build_scene_clean_command(int(kwargs.get("scene_id", 0)))
    if cmd == "room_clean":
        return build_room_clean_command(
            kwargs.get("room_ids", []),
            kwargs.get("map_id", 3),
            kwargs.get("mode", "GENERAL"),
        )
    if cmd == "set_room_custom":
        return build_set_room_custom_command(
            kwargs.get("room_config", []),
            kwargs.get("map_id", 3),
            kwargs.get("fan_speed"),
            kwargs.get("water_level"),
            kwargs.get("clean_times"),
            kwargs.get("clean_mode"),
            kwargs.get("clean_intensity"),
            kwargs.get("edge_mopping"),
        )
    if cmd == "set_auto_cfg":
        return build_set_auto_action_cfg_command(kwargs.get("cfg", {}))
    if cmd == "reset_accessory":
        return build_reset_accessory_command(int(kwargs.get("reset_type", 0)))
    if cmd == "set_child_lock":
        return build_set_child_lock_command(bool(kwargs.get("active", True)))
    if cmd == "set_do_not_disturb":
        return build_set_undisturbed_command(
            bool(kwargs.get("active", True)),
            int(kwargs.get("begin_hour", 22)),
            int(kwargs.get("begin_minute", 0)),
            int(kwargs.get("end_hour", 8)),
            int(kwargs.get("end_minute", 0)),
        )
    if cmd == "set_off_peak_charging":
        return build_set_off_peak_charging_command(
            bool(kwargs.get("active", True)),
            int(kwargs.get("begin_hour", 21)),
            int(kwargs.get("begin_minute", 0)),
            int(kwargs.get("end_hour", 7)),
            int(kwargs.get("end_minute", 0)),
        )

    # scalar commands
    if cmd == "set_boost_iq":
        return build_set_boost_iq_command(bool(kwargs.get("active", True)))
    if cmd == "set_cleaning_pattern":
        return build_set_cleaning_pattern_command(kwargs.get("pattern", ""))
    if cmd == "set_volume":
        if is_scalar:
            return build_set_volume_command(int(kwargs.get("volume", 0)))
        return build_set_volume_novel_command(int(kwargs.get("volume", 0)))
    if cmd == "set_voice":
        return build_set_voice_command(int(kwargs.get("set_id", 1201)))
    if cmd == "set_auto_return":
        return build_set_auto_return_command(bool(kwargs.get("active", True)))
    if cmd == "set_activity_log":
        return build_set_activity_log_command(bool(kwargs.get("active", True)))
    if cmd == "detangle_brush":
        return {SCALAR_DPS["DETANGLE"]: 1}

    return {}
