from __future__ import annotations

import logging
from dataclasses import replace
from typing import Any

from google.protobuf.json_format import MessageToDict

from ..const import (
    DOCK_ACTIVITY_STATES,
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


def _track_field(state: VacuumState, changes: dict[str, Any], field_name: str) -> None:
    """Track that a field has been received from the device.

    This is used by sensors to determine availability.
    Only updates if the field isn't already tracked.
    """
    if field_name not in state.received_fields:
        _LOGGER.debug("Tracking new field for availability: %s", field_name)
        # Get current set from changes if already modified, else from state
        current = changes.get("received_fields", state.received_fields).copy()
        current.add(field_name)
        changes["received_fields"] = current


def update_state(
    state: VacuumState, dps: dict[str, Any]
) -> tuple[VacuumState, dict[str, Any]]:
    """Update VacuumState with new DPS data.

    Returns:
        A tuple of (new_state, changes_dict) where changes_dict contains
        only the fields that were explicitly set from this DPS message.
        This allows callers to distinguish between a field being actively
        set vs inherited from previous state.
    """
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
            _LOGGER.debug("Decoded StationResponse: %s", station)
            new_dock_status = _map_dock_status(station)
            # Debouncing is handled in coordinator, not here
            changes["dock_status"] = new_dock_status
            _track_field(state, changes, "dock_status")

            if station.HasField("clean_water"):
                changes["station_clean_water"] = station.clean_water.value
                _track_field(state, changes, "station_clean_water")

            # Auto Empty Config
            if station.HasField("auto_cfg_status"):
                changes["dock_auto_cfg"] = MessageToDict(
                    station.auto_cfg_status, preserving_proto_field_name=True
                )
        except Exception as e:
            _LOGGER.warning("Error parsing Station Status: %s", e, exc_info=True)

    # Process Work Status
    if DPS_MAP["WORK_STATUS"] in dps:
        value = dps[DPS_MAP["WORK_STATUS"]]
        try:
            work_status = decode(WorkStatus, value)
            _LOGGER.debug("Decoded WorkStatus: %s", work_status)
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
            # Many robots (like X10 Pro Omni) do not send trigger field
            # for specific cleaning modes
            if trigger_source == "unknown" and work_status.HasField("mode"):
                mode_val = work_status.mode.value
                # SELECT_ROOM (1), SELECT_ZONE (2), SPOT (3), FAST_MAPPING (4),
                # GLOBAL_CRUISE (5), ZONES_CRUISE (6), POINT_CRUISE (7),
                # SCENE (8), SMART_FOLLOW (9)
                if mode_val in (1, 2, 3, 4, 5, 6, 7, 8, 9):
                    trigger_source = "app"

            changes["trigger_source"] = trigger_source

            # Fallback/Override if cleaning.scheduled_task is explicit
            if work_status.HasField("cleaning") and work_status.cleaning.scheduled_task:
                changes["trigger_source"] = "schedule"

            # Update dock_status from WorkStatus if available
            # This helps clear "stuck" states (like Drying) if StationResponse
            # stops updating but WorkStatus continues to report (e.g. as Charging/Idle).
            if work_status.HasField("station"):
                st = work_status.station

                # Track if any dock activity is detected in this message
                has_dock_activity = False

                # Washing / Drying
                if st.HasField("washing_drying_system"):
                    has_dock_activity = True
                    # 0=WASHING, 1=DRYING
                    if st.washing_drying_system.state == 1:
                        changes["dock_status"] = "Drying"
                    else:
                        changes["dock_status"] = "Washing"

                # Dust Collection
                if st.HasField("dust_collection_system"):
                    has_dock_activity = True
                    # 0=EMPTYING
                    changes["dock_status"] = "Emptying dust"

                # Water Injection
                if st.HasField("water_injection_system"):
                    has_dock_activity = True
                    # 0=ADDING, 1=EMPTYING
                    if st.water_injection_system.state == 0:
                        changes["dock_status"] = "Adding clean water"

                # Reset to Idle if station field is present but no activity
                if not has_dock_activity:
                    current_dock = changes.get("dock_status", state.dock_status)
                    if current_dock in DOCK_ACTIVITY_STATES:
                        changes["dock_status"] = "Idle"

            else:
                # No station field - if charging and was in dock activity, reset to Idle
                if work_status.state == 3:  # CHARGING
                    current_dock = changes.get("dock_status", state.dock_status)
                    if current_dock in DOCK_ACTIVITY_STATES:
                        changes["dock_status"] = "Idle"

            # Process Current Scene
            # 1. If explicit scene info provided, use it.
            if work_status.HasField("current_scene"):
                changes["current_scene_id"] = work_status.current_scene.id
                changes["current_scene_name"] = work_status.current_scene.name

            # 2. If explicit Mode provided and it's NOT Scene (8), clear it.
            # 8 = SCENE mode
            elif work_status.HasField("mode") and work_status.mode.value != 8:
                changes["current_scene_id"] = 0
                changes["current_scene_name"] = None

            # 3. If State is explicitly Charging (3) or Go Home (7), clear it.
            # We avoid clearing on 0 (Standby) because partial updates might default to 0.
            elif work_status.state in [3, 7]:
                changes["current_scene_id"] = 0
                changes["current_scene_name"] = None

        except Exception as e:
            _LOGGER.warning("Error parsing Work Status: %s", e, exc_info=True)

    for key, value in dps.items():
        # Specialized keys are handled in the decode loop above
        if key in (DPS_MAP["WORK_STATUS"], DPS_MAP["STATION_STATUS"]):
            continue

        try:
            if key == DPS_MAP["BATTERY_LEVEL"]:
                changes["battery_level"] = int(value)

            elif key == DPS_MAP["CLEAN_SPEED"]:
                changes["fan_speed"] = _map_clean_speed(value)

            elif key == DPS_MAP["ERROR_CODE"]:
                error_proto = decode(ErrorCode, value)
                _LOGGER.debug("Decoded ErrorCode: %s", error_proto)
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
                _LOGGER.debug("Received ACCESSORIES_STATUS: %s", value)
                changes["accessories"] = _parse_accessories(state.accessories, value)
                _track_field(state, changes, "accessories")

            elif key == DPS_MAP["CLEANING_STATISTICS"]:
                stats = decode(CleanStatistics, value)
                _LOGGER.debug("Decoded CleanStatistics: %s", stats)
                if stats.HasField("single"):
                    changes["cleaning_time"] = stats.single.clean_duration
                    changes["cleaning_area"] = stats.single.clean_area
                    _track_field(state, changes, "cleaning_stats")

            elif key == DPS_MAP["SCENE_INFO"]:
                _LOGGER.debug("Received SCENE_INFO: %s", value)
                changes["scenes"] = _parse_scene_info(value)

            elif key == DPS_MAP["MAP_DATA"]:
                _LOGGER.debug("Received MAP_DATA: %s", value)
                map_info = _parse_map_data(value)
                if map_info:
                    changes["map_id"] = map_info.get("map_id", 0)
                    changes["rooms"] = map_info.get("rooms", [])
                    _track_field(state, changes, "map_id")

            elif key == DPS_MAP["FIND_ROBOT"]:
                changes["find_robot"] = str(value).lower() == "true"

        except Exception as e:
            _LOGGER.warning("Error parsing DPS %s: %s", key, e, exc_info=True)

    # Log received_fields for debugging sensor availability
    if "received_fields" in changes:
        _LOGGER.debug("Received fields now: %s", changes["received_fields"])

    return replace(state, **changes), changes


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

        # Check if this is a mid-cleaning wash pause vs post-cleaning
        # If cleaning field exists with PAUSED state while dock is washing,
        # this is a mid-cleaning pause, not task completion
        if status.HasField("cleaning") and status.cleaning.state == 1:  # PAUSED
            if dock_status in (
                "Washing",
                "Adding clean water",
                "Recycling waste water",
            ):
                return "Washing Mop"

        # If not resumable and cleaning field is absent, the task is complete
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
            return EUFY_CLEAN_NOVEL_CLEAN_SPEED[idx].value
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
        _LOGGER.debug("Decoded SceneResponse: %s", scene_response)
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
        _LOGGER.debug("Error parsing scene info: %s | Raw: %s", e, value)
        return []


def _parse_map_data(value: Any) -> dict[str, Any] | None:
    """Parse Map Data (Universal or RoomParams) from DPS."""
    # UniversalDataResponse
    try:
        universal_data = decode(UniversalDataResponse, value, has_length=True)
        if universal_data:
            _LOGGER.debug("Decoded UniversalDataResponse: %s", universal_data)
        if universal_data and universal_data.cur_map_room.map_id:
            rooms = [
                {"id": r.id, "name": r.name} for r in universal_data.cur_map_room.data
            ]
            return {"map_id": universal_data.cur_map_room.map_id, "rooms": rooms}
    except Exception as e:
        _LOGGER.debug("UniversalDataResponse parse failed: %s", e)

    # RoomParams
    try:
        room_params = decode(RoomParams, value, has_length=True)
        if room_params:
            _LOGGER.debug("Decoded RoomParams: %s", room_params)
        if room_params and room_params.map_id:
            rooms = [{"id": r.id, "name": r.name} for r in room_params.rooms]
            return {"map_id": room_params.map_id, "rooms": rooms}
    except Exception as e:
        _LOGGER.debug("RoomParams parse failed: %s", e)

    _LOGGER.debug("Failed to parse map data. Raw: %s", value)
    return None


def _parse_accessories(current_state: AccessoryState, value: Any) -> AccessoryState:
    """Parse ConsumableResponse from DPS."""
    try:
        response = decode(ConsumableResponse, value)
        _LOGGER.debug("Decoded ConsumableResponse: %s", response)
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
        _LOGGER.debug("Error parsing accessory info: %s", e)
        return current_state
