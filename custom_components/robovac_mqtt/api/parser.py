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
from ..proto.cloud.clean_statistics_pb2 import CleanStatistics
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

    # Process Station Status first to ensure dock_status is up to date for task mapping
    if DPS_MAP["STATION_STATUS"] in dps:
        value = dps[DPS_MAP["STATION_STATUS"]]
        try:
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
        except Exception as e:
            _LOGGER.warning(f"Error parsing Station Status: {e}", exc_info=True)

    # Process Work Status
    if DPS_MAP["WORK_STATUS"] in dps:
        value = dps[DPS_MAP["WORK_STATUS"]]
        try:
            work_status = decode(WorkStatus, value)
            _LOGGER.debug(f"Decoded WorkStatus: {work_status}")
            changes["activity"] = _map_work_status(work_status)
            changes["status_code"] = work_status.state

            # Use current or updated dock status
            current_dock_status = changes.get("dock_status", state.dock_status)
            changes["task_status"] = _map_task_status(work_status, current_dock_status)

            # Check for charging status
            # If the charging sub-message exists, we trust it regardless of main state
            if work_status.HasField("charging"):
                # Charging.State.DOING is 0
                changes["charging"] = work_status.charging.state == 0
            else:
                changes["charging"] = False

            # Check for trigger source
            trigger_source = "unknown"
            if work_status.HasField("trigger"):
                trigger_source = _map_trigger_source(work_status.trigger.source)

            # Infer trigger source from Work Mode if unknown
            # Many robots (like X10 Pro Omni) do not send trigger field for specific cleaning modes
            if trigger_source == "unknown" and work_status.HasField("mode"):
                mode_val = work_status.mode.value
                # SELECT_ROOM (1), SELECT_ZONE (2), SPOT (3), FAST_MAPPING (4),
                # GLOBAL_CRUISE (5), ZONES_CRUISE (6), POINT_CRUISE (7), SCENE (8), SMART_FOLLOW (9)
                if mode_val in (1, 2, 3, 4, 5, 6, 7, 8, 9):
                    trigger_source = "app"

            changes["trigger_source"] = trigger_source

            # Fallback/Override if cleaning.scheduled_task is explicit
            if work_status.HasField("cleaning") and work_status.cleaning.scheduled_task:
                changes["trigger_source"] = "schedule"

            # Update dock_status from WorkStatus if available
            # This helps clear "stuck" states (like Drying) if StationResponse stops updating
            # but WorkStatus continues to report (e.g. as Charging/Idle).
            if work_status.HasField("station"):
                st = work_status.station
                current_dock = changes.get("dock_status", state.dock_status)

                # Washing / Drying
                if st.HasField("washing_drying_system"):
                    # 0=WASHING, 1=DRYING
                    if st.washing_drying_system.state == 1:
                        changes["dock_status"] = "Drying"
                    else:
                        changes["dock_status"] = "Washing"
                elif current_dock in ("Washing", "Drying"):
                    # If field missing but we were washing/drying, assume done
                    changes["dock_status"] = "Idle"

                # Dust Collection
                if st.HasField("dust_collection_system"):
                    # 0=EMPTYING
                    changes["dock_status"] = "Emptying dust"
                elif current_dock == "Emptying dust":
                    changes["dock_status"] = "Idle"

                # Water Injection
                if st.HasField("water_injection_system"):
                    # 0=ADDING, 1=EMPTYING
                    if st.water_injection_system.state == 0:
                        changes["dock_status"] = "Adding clean water"
                elif current_dock == "Adding clean water":
                    # Only clear if we were adding water
                    changes["dock_status"] = "Idle"

        except Exception as e:
            _LOGGER.warning(f"Error parsing Work Status: {e}", exc_info=True)

    for key, value in dps.items():
        # specialized keys handled above, skip them here?
        if key in (DPS_MAP["WORK_STATUS"], DPS_MAP["STATION_STATUS"]):
            continue

        try:
            if key == DPS_MAP["BATTERY_LEVEL"]:
                changes["battery_level"] = int(value)

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

            elif key == DPS_MAP["ACCESSORIES_STATUS"]:
                _LOGGER.debug(f"Received ACCESSORIES_STATUS: {value}")
                changes["accessories"] = _parse_accessories(state.accessories, value)

            elif key == DPS_MAP["CLEANING_STATISTICS"]:
                stats = decode(CleanStatistics, value)
                _LOGGER.debug(f"Decoded CleanStatistics: {stats}")
                if stats.HasField("single"):
                    changes["cleaning_time"] = stats.single.clean_duration
                    changes["cleaning_area"] = stats.single.clean_area

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


def _map_task_status(status: WorkStatus, dock_status: str | None = None) -> str:
    """Map WorkStatus to detailed task status."""
    s = status.state

    # Check for specific Wash/Dry states first (usually inside Cleaning state 5)
    if status.HasField("go_wash"):
        # GoWash.Mode: NAVIGATION=0, WASHING=1, DRYING=2
        gw_mode = status.go_wash.mode
        if gw_mode == 2:
            return "Completed"
        if gw_mode == 1:
            return "Washing Mop"
        if gw_mode == 0 and s == 5:
            return "Returning to Wash"

    # Check for Breakpoint (Recharge & Resume)
    # Usually State 7 (Returning) or 3 (Charging)
    is_resumable = False
    if status.HasField("breakpoint") and status.breakpoint.state == 0:
        is_resumable = True

    if s == 3:  # Charging
        if is_resumable:
            return "Charging (Resume)"

        # If not resumable the task is effectively done.
        return "Completed"

    if s == 7:  # Returning / Go Home
        # Distinguish between "Finished" and "Recharge needed"
        # However, GoHome mode 0 is "COMPLETE_TASK" and 1 is "COLLECT_DUST"
        if is_resumable:
            return "Returning to Charge"
        if status.HasField("go_home"):
            gh_mode = status.go_home.mode
            if gh_mode == 1:
                return "Returning to Empty"
        return "Returning"

    if s == 5:  # Cleaning
        return "Cleaning"

    if s == 4:
        return "Positioning"

    if s == 2:
        return "Error"

    if s == 6:
        return "Remote Control"

    if s == 15:  # Stop / Pause?
        return "Paused"

    # Fallback mappings from basic map
    return _map_work_status(status).title()


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


def _map_trigger_source(value: int) -> str:
    """Map Trigger.Source to string."""
    # 0: UNKNOWN
    # 1: APP
    # 2: KEY
    # 3: TIMING
    # 4: ROBOT
    # 5: REMOTE_CTRL
    if value == 1:
        return "app"
    if value == 2:
        return "button"
    if value == 3:
        return "schedule"
    if value == 4:
        return "robot"
    if value == 5:
        return "remote_control"
    return "unknown"


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
