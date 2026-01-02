from __future__ import annotations

import logging
from dataclasses import replace
from typing import Any

from google.protobuf.json_format import MessageToDict

from ..const import (
    DPS_MAP,
    EUFY_CLEAN_ERROR_CODES,
    EUFY_CLEAN_NOVEL_CLEAN_SPEED,
)
from ..models import AccessoryState, VacuumState
from ..proto.cloud.consumable_pb2 import ConsumableResponse
from ..proto.cloud.error_code_pb2 import ErrorCode
from ..proto.cloud.scene_pb2 import SceneResponse
from ..proto.cloud.station_pb2 import StationResponse
from ..proto.cloud.stream_pb2 import RoomParams
from ..proto.cloud.universal_data_pb2 import UniversalDataResponse
from ..proto.cloud.work_status_pb2 import WorkStatus
from ..utils import decode

_LOGGER = logging.getLogger(__name__)


def update_state(state: VacuumState, dps: dict[str, Any]) -> VacuumState:
    """Update VacuumState with new DPS data."""
    # Build a kwargs dict for replace()
    changes: dict[str, Any] = {}

    # Always update raw_dps
    new_raw_dps = state.raw_dps.copy()
    new_raw_dps.update(dps)
    changes["raw_dps"] = new_raw_dps

    for key, value in dps.items():
        try:
            if key == DPS_MAP["BATTERY_LEVEL"]:
                changes["battery_level"] = int(value)

            elif key == DPS_MAP["WORK_STATUS"]:
                work_status = decode(WorkStatus, value)
                _LOGGER.debug(f"Decoded WorkStatus: {work_status}")
                changes["activity"] = _map_work_status(work_status)
                changes["status_code"] = work_status.state

                # Check for charging status
                if work_status.HasField("charging"):
                    # Charging.State.DOING is 0
                    changes["charging"] = work_status.charging.state == 0

            elif key == DPS_MAP["CLEAN_SPEED"]:
                changes["fan_speed"] = _map_clean_speed(value)

            elif key == DPS_MAP["ERROR_CODE"]:
                error_proto = decode(ErrorCode, value)
                _LOGGER.debug(f"Decoded ErrorCode: {error_proto}")
                # Repeated Scalar Field (warn) acts like a list
                if len(error_proto.warn) > 0:
                    code = error_proto.warn[0]
                    changes["error_code"] = code
                    changes["error_message"] = EUFY_CLEAN_ERROR_CODES.get(
                        code, "Unknown Error"
                    )
                else:
                    changes["error_code"] = 0
                    changes["error_message"] = ""

            elif key == DPS_MAP["STATION_STATUS"]:
                station = decode(StationResponse, value)
                _LOGGER.debug(f"Decoded StationResponse: {station}")
                new_dock_status = _map_dock_status(station)
                # Debouncing is handled in coordinator, not here
                changes["dock_status"] = new_dock_status

                if station.HasField("clean_water"):
                    changes["station_clean_water"] = station.clean_water.value

                # Auto Empty Config
                if station.HasField("auto_cfg_status"):
                    changes["dock_auto_cfg"] = MessageToDict(
                        station.auto_cfg_status, preserving_proto_field_name=True
                    )

            elif key == DPS_MAP["ACCESSORIES_STATUS"]:
                _LOGGER.debug(f"Received ACCESSORIES_STATUS: {value}")
                changes["accessories"] = _parse_accessories(state.accessories, value)

            elif key == DPS_MAP["SCENE_INFO"]:
                _LOGGER.debug(f"Received SCENE_INFO: {value}")
                changes["scenes"] = _parse_scene_info(value)

            elif key == DPS_MAP["MAP_DATA"]:
                _LOGGER.debug(f"Received MAP_DATA: {value}")
                map_info = _parse_map_data(value)
                if map_info:
                    changes["map_id"] = map_info.get("map_id", 0)
                    changes["rooms"] = map_info.get("rooms", [])

        except Exception as e:
            _LOGGER.warning(f"Error parsing DPS {key}: {e}", exc_info=True)

    return replace(state, **changes)


def _map_work_status(status: WorkStatus) -> str:
    """Map WorkStatus protobuf to activity string."""
    s = status.state
    if s in (0, 1):
        return "idle"
    if s == 2:
        return "error"
    if s == 3:
        return "docked"
    if s == 4:
        return "cleaning"
    if s == 5:
        if "DRYING" in str(status.go_wash):
            return "docked"
        return "cleaning"
    if s == 6:
        return "cleaning"
    if s == 7:
        return "returning"
    if s == 8:
        return "cleaning"

    return "idle"


def _map_clean_speed(value: Any) -> str:
    """Map clean speed value to string."""
    try:
        if isinstance(value, str) and value.isdigit():
            idx = int(value)
        elif isinstance(value, int):
            idx = value
        else:
            return str(value)

        if 0 <= idx < len(EUFY_CLEAN_NOVEL_CLEAN_SPEED):
            return EUFY_CLEAN_NOVEL_CLEAN_SPEED[idx]
    except Exception:
        pass
    return "Standard"


def _map_dock_status(value: StationResponse) -> str:
    """Map StationResponse to status string."""
    try:
        status = value.status
        _LOGGER.debug(
            f"Dock status raw: state={status.state}, "
            f"collecting_dust={status.collecting_dust}, "
            f"clear_water_adding={status.clear_water_adding}, "
            f"waste_water_recycling={status.waste_water_recycling}, "
            f"disinfectant_making={status.disinfectant_making}, "
            f"cutting_hair={status.cutting_hair}"
        )

        if status.collecting_dust:
            return "Emptying dust"
        if status.clear_water_adding:
            return "Adding clean water"
        if status.waste_water_recycling:
            return "Recycling waste water"
        if status.disinfectant_making:
            return "Making disinfectant"
        if status.cutting_hair:
            return "Cutting hair"

        state = status.state
        state_name = StationResponse.StationStatus.State.Name(state)
        state_string = state_name.strip().lower().replace("_", " ")
        return state_string[:1].upper() + state_string[1:]
    except Exception:
        return "Unknown"


def _parse_scene_info(value: Any) -> list[dict[str, Any]]:
    """Parse SceneResponse from DPS."""
    try:
        scene_response = decode(SceneResponse, value, has_length=True)
        _LOGGER.debug(f"Decoded SceneResponse: {scene_response}")
        if not scene_response or not scene_response.infos:
            return []

        scenes = []
        for scene_info in scene_response.infos:
            if scene_info.name and scene_info.valid:
                scenes.append(
                    {
                        "id": scene_info.id.value if scene_info.HasField("id") else 0,
                        "name": scene_info.name,
                        "type": scene_info.type,
                    }
                )
        return scenes
    except Exception as e:
        _LOGGER.debug(f"Error parsing scene info: {e} | Raw: {value}")
        return []


def _parse_map_data(value: Any) -> dict[str, Any] | None:
    """Parse Map Data (Universal or RoomParams) from DPS."""
    # UniversalDataResponse
    try:
        universal_data = decode(UniversalDataResponse, value, has_length=True)
        if universal_data:
            _LOGGER.debug(f"Decoded UniversalDataResponse: {universal_data}")
        if universal_data and universal_data.cur_map_room.map_id:
            rooms = [
                {"id": r.id, "name": r.name} for r in universal_data.cur_map_room.data
            ]
            return {"map_id": universal_data.cur_map_room.map_id, "rooms": rooms}
    except Exception as e:
        _LOGGER.debug(f"UniversalDataResponse parse failed: {e}")

    # RoomParams
    try:
        room_params = decode(RoomParams, value, has_length=True)
        if room_params:
            _LOGGER.debug(f"Decoded RoomParams: {room_params}")
        if room_params and room_params.map_id:
            rooms = [{"id": r.id, "name": r.name} for r in room_params.rooms]
            return {"map_id": room_params.map_id, "rooms": rooms}
    except Exception as e:
        _LOGGER.debug(f"RoomParams parse failed: {e}")

    _LOGGER.debug(f"Failed to parse map data. Raw: {value}")
    return None


def _parse_accessories(current_state: AccessoryState, value: Any) -> AccessoryState:
    """Parse ConsumableResponse from DPS."""
    try:
        response = decode(ConsumableResponse, value)
        _LOGGER.debug(f"Decoded ConsumableResponse: {response}")
        if not response.HasField("runtime"):
            return current_state

        runtime = response.runtime
        changes: dict[str, Any] = {}

        if runtime.HasField("filter_mesh"):
            changes["filter_usage"] = runtime.filter_mesh.duration
        if runtime.HasField("rolling_brush"):
            changes["main_brush_usage"] = runtime.rolling_brush.duration
        if runtime.HasField("side_brush"):
            changes["side_brush_usage"] = runtime.side_brush.duration
        if runtime.HasField("sensor"):
            changes["sensor_usage"] = runtime.sensor.duration
        if runtime.HasField("scrape"):
            changes["scrape_usage"] = runtime.scrape.duration
        if runtime.HasField("mop"):
            changes["mop_usage"] = runtime.mop.duration
        if runtime.HasField("dustbag"):
            changes["dustbag_usage"] = runtime.dustbag.duration
        if runtime.HasField("dirty_watertank"):
            changes["dirty_watertank_usage"] = runtime.dirty_watertank.duration
        if runtime.HasField("dirty_waterfilter"):
            changes["dirty_waterfilter_usage"] = runtime.dirty_waterfilter.duration

        return replace(current_state, **changes)

    except Exception as e:
        _LOGGER.debug(f"Error parsing accessory info: {e}")
        return current_state
