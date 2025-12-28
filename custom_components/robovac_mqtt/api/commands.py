from __future__ import annotations

from typing import Any

from ..const import (
    DPS_MAP,
    EUFY_CLEAN_CLEAN_SPEED,
    EUFY_CLEAN_CONTROL,
    EUFY_CLEAN_NOVEL_CLEAN_SPEED,
)
from ..proto.cloud.consumable_pb2 import ConsumableRequest
from ..proto.cloud.control_pb2 import ModeCtrlRequest, SelectRoomsClean
from ..proto.cloud.station_pb2 import StationRequest
from ..utils import encode, encode_message


def _build_mode_ctrl(method: int) -> dict[str, str]:
    """Helper for ModeCtrlRequest commands."""
    value = encode(ModeCtrlRequest, {"method": int(method)})
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
    # SharedConnect logic adds 3 to the ID
    increment = 3
    value = encode(
        ModeCtrlRequest,
        {
            "method": EUFY_CLEAN_CONTROL.START_SCENE_CLEAN,
            "scene_clean": {"scene_id": scene_id + increment},
        },
    )
    return {DPS_MAP["PLAY_PAUSE"]: value}


def build_room_clean_command(room_ids: list[int], map_id: int = 3) -> dict[str, str]:
    """Build command to clean specific rooms."""
    rooms_clean = SelectRoomsClean(
        rooms=[
            SelectRoomsClean.Room(id=rid, order=i + 1) for i, rid in enumerate(room_ids)
        ],
        mode=SelectRoomsClean.Mode.DESCRIPTOR.values_by_name["GENERAL"].number,
        clean_times=1,
        map_id=map_id,
    )
    value = encode_message(
        ModeCtrlRequest(
            method=int(EUFY_CLEAN_CONTROL.START_SELECT_ROOMS_CLEAN),  # type: ignore[arg-type]
            select_rooms_clean=rooms_clean,
        )
    )
    return {DPS_MAP["PLAY_PAUSE"]: value}


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
            kwargs.get("room_ids", []), kwargs.get("map_id", 3)
        )
    if cmd == "set_auto_cfg":
        return build_set_auto_action_cfg_command(kwargs.get("cfg", {}))
    if cmd == "reset_accessory":
        return build_reset_accessory_command(int(kwargs.get("reset_type", 0)))

    return {}
