from __future__ import annotations

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
)
from ..proto.cloud.clean_param_pb2 import Fan
from ..proto.cloud.consumable_pb2 import ConsumableRequest
from ..proto.cloud.control_pb2 import AutoClean, ModeCtrlRequest, SelectRoomsClean
from ..proto.cloud.map_edit_pb2 import MapEditRequest
from ..proto.cloud.station_pb2 import StationRequest
from ..utils import encode, encode_message

_LOGGER = logging.getLogger(__name__)


def _build_mode_ctrl(method: int) -> dict[str, str]:
    """Helper for ModeCtrlRequest commands."""
    data: dict[str, Any] = {"method": int(method)}

    # Special handling for START_AUTO_CLEAN to ensure non-empty payload
    if method == EUFY_CLEAN_CONTROL.START_AUTO_CLEAN:
        data["auto_clean"] = AutoClean(clean_times=1, force_mapping=False)

    value = encode(ModeCtrlRequest, data)
    return {DPS_MAP["PLAY_PAUSE"]: value}


def _build_manual_cmd(cmd_name: str, active: bool = True) -> dict[str, str]:
    """Helper for StationRequest manual commands."""
    value = encode(StationRequest, {"manual_cmd": {cmd_name: active}})
    return {DPS_MAP["GO_HOME"]: value}


def build_set_clean_speed_command(clean_speed: str) -> dict[str, str]:
    """Build command to set fan speed."""
    try:
        speed_lower = clean_speed.lower()
        variants = [s.lower() for s in EUFY_CLEAN_NOVEL_CLEAN_SPEED]

        if speed_lower in variants:
            idx = variants.index(speed_lower)
            return {DPS_MAP["CLEAN_SPEED"]: str(idx) if isinstance(idx, int) else idx}

    except ValueError:
        pass

    return {}


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
            clean_type_val = CLEAN_TYPE_MAP.get(r_clean_mode.lower())
            if clean_type_val:
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


def build_command(command: str, **kwargs: Any) -> dict[str, str]:
    """Unified command builder."""
    cmd = command.lower()

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
    if cmd == "locate":
        # Placeholder
        return {}

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
    if cmd == "set_fan_speed":
        return build_set_clean_speed_command(kwargs.get("fan_speed", ""))
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

    return {}
