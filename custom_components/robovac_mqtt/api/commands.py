from __future__ import annotations

from typing import Any

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
            method=ModeCtrlRequest.Method(
                int(EUFY_CLEAN_CONTROL.START_SELECT_ROOMS_CLEAN)
            ),
            select_rooms_clean=rooms_clean,
        )
    )
    return {DPS_MAP["PLAY_PAUSE"]: value}


def build_set_room_custom_command(
    room_ids: list[int],
    map_id: int = 3,
    fan_speed: str | None = None,
    water_level: str | None = None,
    clean_times: int | None = None,
    clean_mode: str | None = None,
    clean_intensity: str | None = None,
    edge_mopping: bool | None = None,
) -> dict[str, str]:
    """Build command to set custom parameters for specific rooms.

    This sends a MapEditRequest (Method 5: SET_ROOMS_CUSTOM).
    It is typically sent immediately before starting a room clean with mode=CUSTOMIZE.
    """
    # 1. Prepare common custom config
    custom_cfg = MapEditRequest.RoomsCustom.Parm.Room.Custom()

    # Clean Mode
    if clean_mode and clean_mode.lower() in CLEAN_TYPE_MAP:
        custom_cfg.clean_type.value = CLEAN_TYPE_MAP[clean_mode.lower()]

    # Clean Intensity (Extent)
    if clean_intensity and clean_intensity.lower() in CLEAN_EXTENT_MAP:
        custom_cfg.clean_extent.value = CLEAN_EXTENT_MAP[clean_intensity.lower()]

    # Edge Mopping (Corner Clean)
    if edge_mopping is not None and edge_mopping in MOP_CORNER_MAP:
        custom_cfg.mop_mode.corner_clean = MOP_CORNER_MAP[edge_mopping]

    # Fan Speed (Suction)
    # Keeping existing logic for Fan Speed as it uses a list index lookup from `EUFY_CLEAN_NOVEL_CLEAN_SPEED`
    if fan_speed:
        try:
            speed_lower = fan_speed.lower()
            variants = [s.lower() for s in EUFY_CLEAN_NOVEL_CLEAN_SPEED]
            if speed_lower in variants:
                val = variants.index(speed_lower)
                custom_cfg.fan.suction = Fan.Suction(val)
        except ValueError:
            pass

    # Water Level (Mop Mode)
    if water_level and water_level.lower() in MOP_LEVEL_MAP:
        custom_cfg.mop_mode.level = MOP_LEVEL_MAP[water_level.lower()]

    # Clean Times
    if clean_times is not None and clean_times > 0:
        custom_cfg.clean_times = clean_times

    # 2. Build Room Params List
    # We apply the SAME custom config to all selected rooms for now,
    # because the HA service call typically comes with one set of params for the action.
    rooms_parm = MapEditRequest.RoomsCustom.Parm()
    for rid in room_ids:
        r = rooms_parm.rooms.add()
        r.id = rid
        r.custom.CopyFrom(custom_cfg)

    # 3. Build MapEditRequest
    req = MapEditRequest(
        method=MapEditRequest.SET_ROOMS_CUSTOM,
        map_id=map_id,
        rooms_custom=MapEditRequest.RoomsCustom(
            rooms_parm=rooms_parm,
            # We might need to set condition=GENERAL (0) or others, default is 0
        ),
    )

    # 4. Return encoded command on DPS 170
    # Note: Using encode_message might produce a different result than encode if wrappers are involved.
    # The existing commands use `encode` or `encode_message`.
    # `encode` takes (Type, dict_data), `encode_message` takes (proto_message).
    # Since we built the object, we use `encode_message`.
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
            kwargs.get("room_ids", []),
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
