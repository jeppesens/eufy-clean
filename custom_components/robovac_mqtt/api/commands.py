from __future__ import annotations

import base64
import json
import logging
from typing import Any, cast

from ..const import (
    AUTO_CLEAN_TIMES_MAX,
    AUTO_CLEAN_TIMES_MIN,
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
from ..proto.cloud.common_pb2 import Point, Quadrangle
from ..proto.cloud.consumable_pb2 import ConsumableRequest
from ..proto.cloud.control_pb2 import (
    ModeCtrlRequest,
    SelectRoomsClean,
    SelectZonesClean,
)
from ..proto.cloud.map_edit_pb2 import MapEditRequest
from ..proto.cloud.multi_maps_pb2 import MultiMapsManageRequest
from ..proto.cloud.station_pb2 import StationRequest
from ..proto.cloud.undisturbed_pb2 import UndisturbedRequest
from ..proto.cloud.unisetting_pb2 import UnisettingRequest
from ..utils import (
    clamp_clean_times,
    encode,
    encode_message,
    encode_varint,
    valid_time_window,
)

_LOGGER = logging.getLogger(__name__)


def _normalize_clean_mode(clean_mode: str) -> str:
    """Normalize a cleaning mode label into a map lookup key."""
    return str(clean_mode).strip().lower().replace("_", " ")


def _time_window_ok(label: str, *hours_minutes: int) -> bool:
    """Warn and return False unless the window is two real clock times."""
    if valid_time_window(*hours_minutes):
        return True
    _LOGGER.warning("%s: time %02d:%02d-%02d:%02d out of range; ignored", label, *hours_minutes)
    return False


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


def _build_mode_ctrl(method: int, clean_times: int = 1) -> dict[str, str]:
    """Helper for ModeCtrlRequest commands."""
    data: dict[str, Any] = {"method": int(method)}

    # these methods need their Param oneof filled in
    if method == EUFY_CLEAN_CONTROL.START_AUTO_CLEAN:
        passes = min(max(clean_times, AUTO_CLEAN_TIMES_MIN), AUTO_CLEAN_TIMES_MAX)
        if passes != clean_times:
            _LOGGER.warning(
                "start_auto: clean_times %d out of range %d-%d, using %d",
                clean_times,
                AUTO_CLEAN_TIMES_MIN,
                AUTO_CLEAN_TIMES_MAX,
                passes,
            )
        data["auto_clean"] = {"clean_times": passes, "force_mapping": False}
    elif method == EUFY_CLEAN_CONTROL.START_SPOT_CLEAN:
        data["spot_clean"] = {"clean_times": 1}

    value = encode(ModeCtrlRequest, data)
    return {DPS_MAP["PLAY_PAUSE"]: value}


def _build_manual_cmd(cmd_name: str, active: bool = True) -> dict[str, str]:
    """Helper for StationRequest manual commands."""
    value = encode(StationRequest, {"manual_cmd": {cmd_name: active}})
    return {DPS_MAP["GO_HOME"]: value}


def build_set_clean_speed_command(clean_speed: str) -> dict[str, int]:
    """Build command to set fan speed."""
    speed_lower = str(clean_speed).lower()
    variants = [s.lower() for s in EUFY_CLEAN_NOVEL_CLEAN_SPEED]
    if speed_lower in variants:
        return {DPS_MAP["CLEAN_SPEED"]: variants.index(speed_lower)}
    return {}


def build_set_water_level_command(water_level: str) -> dict[str, str]:
    """Build command to set mop water level for both auto and room/area cleans."""
    level_val = MOP_LEVEL_MAP.get(str(water_level).lower())
    if level_val is None:
        _LOGGER.warning("Invalid water_level '%s' ignored", water_level)
        return {}
    param = CleanParam(mop_mode={"level": level_val})
    req = CleanParamRequest(clean_param=param, area_clean_param=param)
    value = encode_message(req)
    return {DPS_MAP["CLEANING_PARAMETERS"]: value}


def build_set_cleaning_intensity_command(cleaning_intensity: str) -> dict[str, str]:
    """Build command to set cleaning intensity for both auto and room/area cleans."""
    extent_val = CLEAN_EXTENT_MAP.get(str(cleaning_intensity).lower())
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


def build_zone_clean_command(
    zones_cm: list[list[tuple[int, int]]],
    map_id: int = 3,
    clean_times: int = 1,
) -> dict[str, str]:
    """Build a select-zones clean.

    *zones_cm* is a list of quads, each four ``(x, y)`` corners in cm in the
    device's world frame, ordered around the rectangle.
    """
    proto_zones: list[SelectZonesClean.Zone] = []
    for quad in zones_cm:
        if len(quad) != 4:
            _LOGGER.warning(
                "Zone needs exactly 4 corner points, got %d — skipped", len(quad)
            )
            continue
        pts = [Point(x=int(round(px)), y=int(round(py))) for px, py in quad]
        proto_zones.append(
            SelectZonesClean.Zone(
                quadrangle=Quadrangle(p0=pts[0], p1=pts[1], p2=pts[2], p3=pts[3]),
                clean_times=clamp_clean_times(clean_times),
            )
        )

    if not proto_zones:
        return {}

    value = encode_message(
        ModeCtrlRequest(
            method=cast(
                ModeCtrlRequest.Method, int(EUFY_CLEAN_CONTROL.START_SELECT_ZONES_CLEAN)
            ),
            select_zones_clean=SelectZonesClean(
                zones=proto_zones,
                map_id=int(map_id),
            ),
        )
    )
    return {DPS_MAP["PLAY_PAUSE"]: value}


def build_map_load_command(cloud_mapid: int, seq: int = 1) -> dict[str, str]:
    """Switch the active map to a saved multi-map by id (DPS 172).

    *cloud_mapid* is the ``map_id`` from incoming MAP_DATA; *seq* is echoed in the
    ack. The map and room list switch at once, but the robot's coordinate frame
    stays on the old map until it moves and re-localizes — so coordinate-based
    targeting (zones, tap-a-point) is stale until then; use a room id instead.
    """
    if int(cloud_mapid) <= 0:
        _LOGGER.warning("map_load ignored: cloud_mapid must be a positive map id")
        return {}
    req = MultiMapsManageRequest(
        method=MultiMapsManageRequest.MAP_LOAD,
        seq=int(seq),
        common=MultiMapsManageRequest.Common(cloud_mapid=int(cloud_mapid)),
    )
    return {DPS_MAP["MULTI_MAP_MANAGE"]: encode_message(req)}


def build_set_room_custom_command(
    room_config: list[dict[str, Any]] | list[int],
    map_id: int = 3,
    # only used when room_config is list[int]
    fan_speed: str | None = None,
    water_level: str | None = None,
    clean_times: int | None = None,
    clean_mode: str | None = None,
    clean_intensity: str | None = None,
    edge_mopping: bool | None = None,
) -> dict[str, str]:
    """Set custom cleaning parameters for specific rooms.

    ``room_config`` is either list[int] room ids (the global params below apply to
    all of them) or list[dict] ``{id: 1, fan_speed: "Turbo", ...}`` per room.
    """
    rooms_parm = MapEditRequest.RoomsCustom.Parm()

    normalized_rooms: list[dict[str, Any]] = []

    if room_config and isinstance(room_config[0], int):
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
        normalized_rooms = cast(list[dict[str, Any]], room_config)

    for room_data in normalized_rooms:
        room_id = room_data.get("id")
        # Room id 0 is a real id on some maps (e.g. T2080A after room merges),
        # so only skip when the id is actually missing — a falsy check would
        # silently drop room 0 from the customization payload.
        if room_id is None:
            continue

        custom_cfg = MapEditRequest.RoomsCustom.Parm.Room.Custom()

        r_fan_speed = room_data.get("fan_speed")
        r_water_level = room_data.get("water_level")
        r_clean_times = room_data.get("clean_times")
        r_clean_mode = room_data.get("clean_mode")
        r_clean_intensity = room_data.get("clean_intensity")
        r_edge_mopping = room_data.get("edge_mopping")

        if r_clean_mode:
            clean_type_val = CLEAN_TYPE_MAP.get(_normalize_clean_mode(r_clean_mode))
            if clean_type_val is not None:
                custom_cfg.clean_type.value = clean_type_val
            else:
                _LOGGER.warning("Invalid clean_mode '%s' ignored", r_clean_mode)

        if r_clean_times:
            custom_cfg.clean_times = clamp_clean_times(r_clean_times)

        if r_clean_intensity:
            if (extent := str(r_clean_intensity).lower()) in CLEAN_EXTENT_MAP:
                custom_cfg.clean_extent.value = CLEAN_EXTENT_MAP[extent]
            else:
                _LOGGER.warning(
                    "Invalid clean_intensity '%s' ignored", r_clean_intensity
                )

        if r_edge_mopping is not None:
            if r_edge_mopping in MOP_CORNER_MAP:
                custom_cfg.mop_mode.corner_clean = MOP_CORNER_MAP[r_edge_mopping]
            else:
                _LOGGER.warning("Invalid edge_mopping '%s' ignored", r_edge_mopping)

        if r_fan_speed:
            speed_lower = str(r_fan_speed).lower()
            variants = [s.lower() for s in EUFY_CLEAN_NOVEL_CLEAN_SPEED]
            if speed_lower in variants:
                val = variants.index(speed_lower)
                custom_cfg.fan.suction = cast(Fan.Suction, val)
            else:
                _LOGGER.warning("Invalid fan_speed '%s' ignored", r_fan_speed)

        if r_water_level:
            if (level := str(r_water_level).lower()) in MOP_LEVEL_MAP:
                custom_cfg.mop_mode.level = MOP_LEVEL_MAP[level]
            else:
                _LOGGER.warning("Invalid water_level '%s' ignored", r_water_level)

        room_msg = MapEditRequest.RoomsCustom.Parm.Room()
        room_msg.id = int(room_id)
        room_msg.custom.CopyFrom(custom_cfg)
        rooms_parm.rooms.append(room_msg)

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
    return {DPS_MAP["FIND_ROBOT"]: active}


# scalar-protocol builders: plain int/JSON DPS writes, no protobuf.


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
    """scalar-protocol: reset an accessory life counter to 0 (DPS 150 JSON).

    accessory_key is the DPS 150 field: "sensors", "dust_filter", "side_brush", ...
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
    if not _time_window_ok(
        "set_do_not_disturb", begin_hour, begin_minute, end_hour, end_minute
    ):
        return {}
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


_OFF_PEAK_REQUEST_FIELD_NUM = 22  # UnisettingRequest field 22 = OffPeakCharging (23 in the Response)


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
    """Set the off-peak charging schedule (DPS 176).

    Sends only the off-peak sub-message: any other UnisettingRequest field would
    overwrite device state with stale coordinator values.
    """
    if not _time_window_ok(
        "set_off_peak_charging", begin_hour, begin_minute, end_hour, end_minute
    ):
        return {}
    off_peak_bytes = _encode_proto_ldelim(
        _OFF_PEAK_REQUEST_FIELD_NUM,
        _build_off_peak_sub_bytes(enabled, begin_hour, begin_minute, end_hour, end_minute),
    )
    prefixed = encode_varint(len(off_peak_bytes)) + off_peak_bytes
    value = base64.b64encode(prefixed).decode()
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
    if not _time_window_ok(
        "set_do_not_disturb", begin_hour, begin_minute, end_hour, end_minute
    ):
        return {}
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
    """Unified command builder; *api_type* "scalar" branches to plain int/JSON writes."""
    cmd = command.lower()
    is_scalar = api_type == "scalar"

    if is_scalar:
        # movement rides DPS 5 (work mode) + 122 (pause); DPS 2/101, the
        # Tuya-canonical movement DPs, are ACKed but ignored by this firmware
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

    if cmd == "start_auto":
        return _build_mode_ctrl(
            EUFY_CLEAN_CONTROL.START_AUTO_CLEAN, int(kwargs.get("clean_times", 1))
        )
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

    if cmd == "go_dry":
        return _build_manual_cmd("go_dry", True)
    if cmd == "stop_dry":
        return _build_manual_cmd("go_dry", False)
    if cmd == "go_selfcleaning":
        return _build_manual_cmd("go_selfcleaning", True)
    if cmd == "collect_dust":
        return _build_manual_cmd("go_collect_dust", True)

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
    if cmd == "zone_clean":
        return build_zone_clean_command(
            kwargs.get("zones_cm", []),
            kwargs.get("map_id", 3),
            kwargs.get("clean_times", 1),
        )
    if cmd == "map_load":
        return build_map_load_command(
            int(kwargs.get("cloud_mapid", 0)),
            int(kwargs.get("seq", 1)),
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
