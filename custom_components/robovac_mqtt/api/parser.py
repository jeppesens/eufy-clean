from __future__ import annotations

import base64
import logging
import time
from collections.abc import Iterator
from dataclasses import replace
from typing import Any

from google.protobuf.json_format import MessageToDict

from ..const import (
    CARPET_STRATEGY_NAMES,
    CLEANING_INTENSITY_NAMES,
    CLEANING_MODE_NAMES,
    CORNER_CLEANING_NAMES,
    DOCK_ACTIVITY_STATES,
    DPS_MAP,
    DPS_ROBOT_TELEMETRY,
    DPS_UNSETTING_HEIGHT_DETECTION_FIELD,
    DPS_UNSETTING_VIDEO_SWITCH_FIELD,
    EUFY_CLEAN_APP_TRIGGER_MODES,
    EUFY_CLEAN_ERROR_CODES,
    EUFY_CLEAN_NOVEL_CLEAN_SPEED,
    FAN_SUCTION_NAMES,
    HEIGHT_DETECTION_MODES,
    KNOWN_UNPROCESSED_DPS,
    MOP_WATER_LEVEL_NAMES,
    STATION_WATER_LEVEL_NAMES,
    TRIGGER_SOURCE_NAMES,
    WORK_MODE_NAMES,
    WORK_STATE_REMOTE_CTRL,
    CleaningMode,
    MopWaterLevel,
    TriggerSource,
    is_s1_pro,
)
from ..errors import is_advisory_code, s1_error_message
from ..models import AccessoryState, VacuumState, track_received_field
from ..proto.cloud.app_device_info_pb2 import DeviceInfo
from ..proto.cloud.clean_param_pb2 import CleanParamRequest, CleanParamResponse
from ..proto.cloud.clean_statistics_pb2 import CleanStatistics
from ..proto.cloud.consumable_pb2 import ConsumableResponse
from ..proto.cloud.control_pb2 import ModeCtrlRequest
from ..proto.cloud.error_code_pb2 import ErrorCode
from ..proto.cloud.language_pb2 import LanguageResponse
from ..proto.cloud.multi_maps_pb2 import MultiMapsManageResponse
from ..proto.cloud.scene_pb2 import SceneResponse
from ..proto.cloud.station_pb2 import StationResponse
from ..proto.cloud.stream_pb2 import RoomParams
from ..proto.cloud.undisturbed_pb2 import UndisturbedResponse
from ..proto.cloud.unisetting_pb2 import UnisettingResponse
from ..proto.cloud.universal_data_pb2 import UniversalDataResponse
from ..proto.cloud.work_status_pb2 import WorkStatus
from ..utils import decode, decode_varint, deduplicate_names, encode_varint
from .parser_scalar import process_scalar_dps

_LOGGER = logging.getLogger(__name__)

_OFF_PEAK_RESPONSE_FIELD_NUM = 23  # UnisettingResponse field 23 = OffPeakCharging (undocumented)


def _extract_off_peak_charging(raw_b64: str) -> dict[str, int | bool] | None:
    """Extract off-peak charging config from raw UnisettingResponse bytes (field 23).

    Field 23 is not in the compiled proto, so we parse the raw bytes directly.
    Structure: {enable: Switch, begin: TimePoint{hour,minute}, end: TimePoint{hour,minute}}
    """
    raw = base64.b64decode(raw_b64)
    if not raw:
        return None
    _, raw_start = decode_varint(raw, 0)
    raw = raw[raw_start:]

    i = 0
    while i < len(raw):
        tag, i = decode_varint(raw, i)
        field_num = tag >> 3
        wire_type = tag & 7
        if wire_type == 0:
            _, i = decode_varint(raw, i)
        elif wire_type == 2:
            length, i = decode_varint(raw, i)
            data = raw[i : i + length]
            i += length
            if field_num == _OFF_PEAK_RESPONSE_FIELD_NUM:
                return _decode_off_peak_sub(data)
        elif wire_type == 5:
            i += 4
        elif wire_type == 1:
            i += 8
        else:
            break
    return None


def _decode_off_peak_sub(data: bytes) -> dict[str, int | bool]:
    """Decode the OffPeakCharging sub-message bytes."""
    result: dict[str, int | bool] = {
        "enabled": False,
        "begin_hour": 0,
        "begin_minute": 0,
        "end_hour": 0,
        "end_minute": 0,
    }
    i = 0
    while i < len(data):
        tag, i = decode_varint(data, i)
        field_num = tag >> 3
        wire_type = tag & 7
        if wire_type == 2:
            length, i = decode_varint(data, i)
            sub = data[i : i + length]
            i += length
            if field_num == 1:  # Switch{value: bool}
                j = 0
                while j < len(sub):
                    st, j = decode_varint(sub, j)
                    if (st >> 3) == 1 and (st & 7) == 0:
                        v, j = decode_varint(sub, j)
                        result["enabled"] = bool(v)
            elif field_num in (2, 3):  # TimePoint{hour, minute}
                prefix = "begin" if field_num == 2 else "end"
                j = 0
                while j < len(sub):
                    st, j = decode_varint(sub, j)
                    sf = st >> 3
                    if (st & 7) == 0:
                        v, j = decode_varint(sub, j)
                        if sf == 1:
                            result[f"{prefix}_hour"] = v
                        elif sf == 2:
                            result[f"{prefix}_minute"] = v
        elif wire_type == 0:
            _, i = decode_varint(data, i)
        elif wire_type == 5:
            i += 4
        elif wire_type == 1:
            i += 8
        else:
            break
    return result


def _decode_raw_varints(data: bytes) -> dict[int, int | bytes]:
    """Decode raw protobuf fields from bytes (no schema needed).

    Returns a dict of field_number -> value (int for varints, bytes for
    length-delimited fields).
    """
    fields: dict[int, int | bytes] = {}
    i = 0
    while i < len(data):
        tag, i = decode_varint(data, i)
        fn, wt = tag >> 3, tag & 7
        if wt == 0:  # varint
            val, i = decode_varint(data, i)
            fields[fn] = val
        elif wt == 2:  # length-delimited
            blen, i = decode_varint(data, i)
            fields[fn] = data[i : i + blen]
            i += blen
        else:
            break
    return fields


def _parse_robot_telemetry(value: str) -> dict[str, Any] | None:
    """Parse DPS 179 robot telemetry (no proto definition available).

    Wire format: varint-length-prefixed message containing:
      field 2 (bytes) -> sub-message with field 7 (bytes) -> inner message:
        field 1: uint32  Unix timestamp
        field 2: uint32  battery percentage
        field 3: uint32  unknown (slowly increasing value)
        field 4: uint32  map X coordinate
        field 5: uint32  map Y coordinate
        field 6: bytes   additional data (2 packed varints)

    See docs/DPS_179_TELEMETRY.md for detailed format documentation.
    """
    try:
        raw = base64.b64decode(value)
    except Exception:
        _LOGGER.debug("Failed to decode DPS 179 base64: %.50s", value)
        return None
    _length, pos = decode_varint(raw, 0)
    outer = _decode_raw_varints(raw[pos:])
    sub_bytes = outer.get(2)
    if not isinstance(sub_bytes, bytes):
        return None
    sub = _decode_raw_varints(sub_bytes)
    inner_bytes = sub.get(7)
    if not isinstance(inner_bytes, bytes):
        return None
    inner = _decode_raw_varints(inner_bytes)
    if 4 not in inner or 5 not in inner:
        return None
    return {"x": inner[4], "y": inner[5]}


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
    changes: dict[str, Any] = {}

    # Always update raw_dps
    new_raw_dps = state.raw_dps.copy()
    new_raw_dps.update(dps)
    changes["raw_dps"] = new_raw_dps

    # Dispatch on the DPS protocol, classified cloud-side at init by
    # EufyLogin.checkApiType and carried on state.api_type.
    if state.api_type == "scalar":
        # Plain int/JSON Tuya-style DPS (e.g. T2210/G50), no protobuf.
        process_scalar_dps(state, dps, changes)
    else:
        # Novel: Anker length-prefixed protobuf DPS (X-series; also the
        # default for "legacy"/"unknown", which have no parser of their own).
        _process_station_status(state, dps, changes)
        _process_work_status(state, dps, changes)
        _process_play_pause(state, dps, changes)
        _process_other_dps(state, dps, changes)

    # Log received_fields for debugging sensor availability
    if "received_fields" in changes:
        _LOGGER.debug("Received fields now: %s", changes["received_fields"])

    if "error_code" in changes:
        code = changes["error_code"]
        if code:
            changes["error_message"] = s1_error_message(code, state.device_model) or changes["error_message"]
            changes["last_error_code"] = code
            changes["last_error_message"] = changes["error_message"]

    # A confirmed healthy WorkStatus means a previous S1 fault was recovered.
    # Do not infer recovery from standby/pause, command echoes or manual mode.
    # A newly raised fault in the same packet wins over a healthy status snapshot.
    healthy = (
        is_s1_pro(state.device_model)
        and "status_code" in changes
        and changes["status_code"] != WORK_STATE_REMOTE_CTRL
        and changes.get("activity") in ("cleaning", "returning", "docked")
    )
    new_fault = False
    if healthy:
        try:
            work_status = decode(WorkStatus, dps[DPS_MAP["WORK_STATUS"]])
            healthy = not (
                work_status.HasField("charging") and work_status.charging.state == 2
            ) and not any(
                work_status.HasField(field) and getattr(work_status, field).state == 1
                for field in ("mapping", "cleaning", "go_wash", "go_home", "cruisiing")
            )
        except Exception:
            healthy = False
    if healthy and DPS_MAP["ERROR_CODE"] in dps:
        try:
            new_fault = any(decode(ErrorCode, dps[DPS_MAP["ERROR_CODE"]]).new_code.error)
        except Exception:  # The main parser logs malformed reports; retain the fault.
            new_fault = True
    # Station (EBxx) and advisory (`warn`) codes are not movement faults and the
    # WorkStatus stays healthy while they are up, so only a movement fault clears.
    current = changes.get("error_code", state.error_code)
    warns = changes.get("warn_codes", state.warn_codes)
    codes = changes.get("error_codes", state.error_codes)

    def advisory(code: int) -> bool:
        return is_advisory_code(code, state.device_model, warns)

    keep = [c for c in codes if advisory(c)]  # still up: the robot will not re-push them
    if healthy and not new_fault and current and not (advisory(current) and len(keep) == len(codes)):
        if state.error_code and "last_error_code" not in changes:
            changes["last_error_code"] = state.error_code
            changes["last_error_message"] = state.error_message
        remaining = keep[0] if keep else 0
        changes.update(
            error_code=remaining,
            error_message=(
                (s1_error_message(remaining, state.device_model) or f"Unknown Error ({remaining})")
                if remaining
                else ""
            ),
            error_codes=keep,
        )

    return replace(state, **changes), changes


def _process_station_status(
    state: VacuumState, dps: dict[str, Any], changes: dict[str, Any]
) -> None:
    """Process Station Status DPS."""
    if DPS_MAP["STATION_STATUS"] not in dps:
        return

    value = dps[DPS_MAP["STATION_STATUS"]]
    try:
        station = decode(StationResponse, value)
        _LOGGER.debug("Decoded StationResponse: %s", station)
        new_dock_status = _map_dock_status(station)
        # Debouncing is handled in coordinator, not here
        changes["dock_status"] = new_dock_status
        track_received_field(state, changes, "dock_status")

        if station.HasField("clean_water"):
            changes["station_clean_water"] = station.clean_water.value
            track_received_field(state, changes, "station_clean_water")

        # dirty_level / clean_level are proto3 enums without presence, so a dock
        # that never sends them would read as EMPTY. Report each only once it has
        # been on the wire; after that, a frame without it is read as EMPTY.
        sent = {fd.name for fd, _ in station.ListFields()}
        for field_name, key in (
            ("dirty_level", "station_dirty_water"),
            ("clean_level", "station_clean_water_level"),
        ):
            if field_name in sent or key in state.received_fields:
                changes[key] = STATION_WATER_LEVEL_NAMES.get(
                    getattr(station, field_name), "Unknown"
                )
                track_received_field(state, changes, key)

        # Auto Empty Config
        if station.HasField("auto_cfg_status"):
            changes["dock_auto_cfg"] = MessageToDict(
                station.auto_cfg_status, preserving_proto_field_name=True
            )
    except Exception as e:
        _LOGGER.warning("Error parsing Station Status: %s", e, exc_info=True)


def _process_work_status(
    state: VacuumState, dps: dict[str, Any], changes: dict[str, Any]
) -> None:
    """Process Work Status DPS."""
    if DPS_MAP["WORK_STATUS"] not in dps:
        return

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
            if mode_val in EUFY_CLEAN_APP_TRIGGER_MODES:
                trigger_source = "app"

        changes["trigger_source"] = trigger_source

        # Extract Work Mode
        if work_status.HasField("mode"):
            mode_val = work_status.mode.value
            changes["work_mode"] = WORK_MODE_NAMES.get(mode_val, "unknown")
            track_received_field(state, changes, "work_mode")
        elif state.work_mode == "unknown" and changes.get("activity") == "cleaning":
            # If we don't know the mode yet but we are cleaning, default to Auto
            changes["work_mode"] = "Auto"

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
                else:
                    changes["dock_status"] = "Recycling waste water"

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
            if (
                state.active_room_ids
                or state.active_room_names
                or state.active_zone_count
            ):
                changes["active_room_ids"] = []
                changes["active_room_names"] = ""
                changes["active_zone_count"] = 0

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

        # Clear active cleaning targets when the task is actually over.
        # Docked can also mean an in-progress wash/dry cycle, so rely on the
        # derived task_status instead of duplicating that interpretation here.
        activity = changes.get("activity")
        task_status = changes.get("task_status")
        should_clear_targets = (
            activity in ("idle", "error") and state.activity not in ("idle", "error")
        ) or (
            activity == "docked"
            and task_status == "Completed"
            and state.task_status != "Completed"
        )
        if should_clear_targets:
            if state.active_room_ids or state.active_zone_count:
                changes["active_room_ids"] = []
                changes["active_room_names"] = ""
                changes["active_zone_count"] = 0

    except Exception as e:
        _LOGGER.warning("Error parsing Work Status: %s", e, exc_info=True)


def _process_play_pause(
    state: VacuumState, dps: dict[str, Any], changes: dict[str, Any]
) -> None:
    """Process Play/Pause DPS (152) - extract active cleaning targets."""
    if DPS_MAP["PLAY_PAUSE"] not in dps:
        return

    value = dps[DPS_MAP["PLAY_PAUSE"]]
    try:
        mode_ctrl = decode(ModeCtrlRequest, value)
        _LOGGER.debug("Decoded ModeCtrlRequest: %s", mode_ctrl)

        if mode_ctrl.HasField("select_rooms_clean"):
            room_ids = [r.id for r in mode_ctrl.select_rooms_clean.rooms]
            if not room_ids:
                _LOGGER.debug(
                    "Ignoring START_SELECT_ROOMS_CLEAN without room IDs; preserving existing active targets."
                )
                return
            changes["active_room_ids"] = room_ids
            room_lookup = {
                r["id"]: r.get("name", f"Room {r['id']}") for r in state.rooms
            }
            names = [room_lookup.get(rid, f"Room {rid}") for rid in room_ids]
            changes["active_room_names"] = ", ".join(names)
            changes["active_zone_count"] = 0
            changes["current_scene_id"] = 0
            changes["current_scene_name"] = None
            track_received_field(state, changes, "active_room_ids")

        elif mode_ctrl.HasField("select_zones_clean"):
            changes["active_zone_count"] = len(mode_ctrl.select_zones_clean.zones)
            changes["active_room_ids"] = []
            changes["active_room_names"] = ""
            changes["current_scene_id"] = 0
            changes["current_scene_name"] = None
            track_received_field(state, changes, "active_room_ids")

        # Scene: intentionally skipped (already tracked via WorkStatus.current_scene)
        # Control commands (pause/resume/stop): no Param oneof, naturally ignored

    except Exception as e:
        _LOGGER.warning("Error parsing Play/Pause DPS: %s", e, exc_info=True)


def _process_other_dps(
    state: VacuumState, dps: dict[str, Any], changes: dict[str, Any]
) -> None:
    """Process other DPS items."""
    for key, value in dps.items():
        # Specialized keys are handled in their respective functions
        if key in (
            DPS_MAP["WORK_STATUS"],
            DPS_MAP["STATION_STATUS"],
            DPS_MAP["PLAY_PAUSE"],
        ):
            continue

        try:
            if key == DPS_MAP["BATTERY_LEVEL"]:
                changes["battery_level"] = int(value)
                track_received_field(state, changes, "battery_level")

            elif key == DPS_MAP["CLEAN_SPEED"]:
                changes["fan_speed"] = _map_clean_speed(value)
                track_received_field(state, changes, "fan_speed")
            elif key == DPS_MAP["BOOST_IQ"] and isinstance(value, bool):
                changes["boost_iq"] = value
                track_received_field(state, changes, "boost_iq")

            elif key == DPS_MAP["ERROR_CODE"]:
                error_proto = decode(ErrorCode, value)
                _LOGGER.debug("Decoded ErrorCode: %s", error_proto)
                # Codes arrive in `error` (faults), `new_code.error` (newly raised
                # faults) and `warn` (advisories). error_codes / warn_codes expose
                # the `error` and `warn` lists in full; the headline code is the
                # first non-zero one in that order, so a standing warning can't
                # mask a fault and an empty `error` list can't hide a new one.
                errors = [int(c) for c in error_proto.error]
                warns = [int(c) for c in error_proto.warn]
                changes["error_codes"] = errors
                changes["warn_codes"] = warns
                code = next(
                    (c for c in (*errors, *error_proto.new_code.error, *warns) if c),
                    0,
                )
                if code:
                    changes["error_code"] = code
                    changes["error_message"] = EUFY_CLEAN_ERROR_CODES.get(
                        code, f"Unknown Error ({code})"
                    )
                else:
                    changes["error_code"] = 0
                    changes["error_message"] = ""

            elif key == DPS_MAP["ACCESSORIES_STATUS"]:
                _LOGGER.debug("Received ACCESSORIES_STATUS: %s", value)
                changes["accessories"] = _parse_accessories(state.accessories, value)
                track_received_field(state, changes, "accessories")

            elif key == DPS_MAP["CLEANING_STATISTICS"]:
                stats = decode(CleanStatistics, value)
                _LOGGER.debug("Decoded CleanStatistics: %s", stats)
                if stats.HasField("single"):
                    changes["cleaning_time"] = stats.single.clean_duration
                    # Only update area when > 0 so the last run value persists after docking
                    if stats.single.clean_area > 0:
                        changes["cleaning_area"] = stats.single.clean_area
                    track_received_field(state, changes, "cleaning_stats")
                # user_total resets per owner; robots that only send the
                # lifetime total (S1 Pro) fall back to it.
                totals = (
                    stats.user_total if stats.HasField("user_total")
                    else stats.total if stats.HasField("total")
                    else None
                )
                if totals is not None:
                    changes["total_cleaning_area"] = totals.clean_area
                    changes["total_cleaning_time"] = totals.clean_duration
                    changes["total_cleaning_count"] = totals.clean_count
                    track_received_field(state, changes, "cleaning_totals")

            elif key == DPS_MAP["SCENE_INFO"]:
                _LOGGER.debug("Received SCENE_INFO: %s", value)
                changes["scenes"] = _parse_scene_info(value)

            elif key == DPS_MAP["MAP_DATA"]:
                _LOGGER.debug("Received MAP_DATA: %s", value)
                map_info = _parse_map_data(value)
                if map_info:
                    changes["map_id"] = map_info.get("map_id", 0)
                    changes["rooms"] = map_info.get("rooms", [])
                    track_received_field(state, changes, "map_id")

            elif key == DPS_MAP["CLEANING_PARAMETERS"]:
                _LOGGER.debug("Received CLEANING_PARAMETERS: %s", value)
                _process_cleaning_parameters(state, value, changes)

            elif key == DPS_MAP["FIND_ROBOT"]:
                changes["find_robot"] = str(value).lower() == "true"

            elif key == DPS_MAP["VOLUME"]:
                changes["volume"] = max(0, min(100, int(value)))
                track_received_field(state, changes, "volume")

            elif key == DPS_MAP["VOICE_LANGUAGE"]:
                lang = decode(LanguageResponse, value)
                _LOGGER.debug("Decoded LanguageResponse: %s", lang)
                if lang.current_id > 0:
                    changes["voice_set_id"] = lang.current_id
                    track_received_field(state, changes, "voice")

            elif key == DPS_MAP["MAP_MANAGE"]:
                # DPS 169 carries DeviceInfo proto (not map data despite the name).
                # Contains firmware version, WiFi SSID/IP, station firmware, MAC.
                # Firmware version is already in the HA device registry via
                # coordinator.device_info (sw_version from cloud API), so we
                # only extract network info here.
                info = decode(DeviceInfo, value)
                _LOGGER.debug("Decoded DeviceInfo: %s", info)
                if info.product_name:
                    changes["product_name"] = info.product_name
                if info.device_mac:
                    changes["device_mac"] = info.device_mac
                if info.wifi_name:
                    changes["wifi_ssid"] = info.wifi_name
                    track_received_field(state, changes, "wifi_ssid")
                if info.wifi_ip:
                    changes["wifi_ip"] = info.wifi_ip
                    track_received_field(state, changes, "wifi_ip")
                if info.station.software:
                    changes["dock_firmware_version"] = info.station.software
                    track_received_field(state, changes, "dock_firmware_version")

            elif key == DPS_MAP["MULTI_MAP_MANAGE"]:
                if value is None:
                    _LOGGER.debug("DPS 172: None value (initial state)")
                else:
                    _LOGGER.debug("Received MULTI_MAP_MANAGE (DPS 172): %.100s", value)
                    _parse_multi_map_response(value)

            elif key == DPS_MAP["VIDEO_MANAGER"]:
                if (reply := _parse_video_manager_reply(value)) is not None:
                    changes["video_response"] = (*reply, time.monotonic())

            elif key == DPS_MAP["UNSETTING"]:
                settings = decode(UnisettingResponse, value)
                _LOGGER.debug("Decoded UnisettingResponse: %s", settings)
                # Device reports 0-100%, approximate to dBm for HA convention
                changes["wifi_signal"] = (settings.ap_signal_strength / 2) - 100
                track_received_field(state, changes, "wifi_signal")
                if settings.HasField("children_lock"):
                    changes["child_lock"] = settings.children_lock.value
                    track_received_field(state, changes, "child_lock")
                if (cam := _extract_video_switch(value)) is not None:
                    changes["camera_enabled"] = cam
                    track_received_field(state, changes, "camera_enabled")
                if (mode := _extract_height_detection(value)) is not None:
                    changes["height_detection"] = mode
                    track_received_field(state, changes, "height_detection")
                off_peak = _extract_off_peak_charging(value)
                if off_peak is not None:
                    _LOGGER.debug("DPS 176 off-peak parsed: %s", off_peak)
                    changes["off_peak_enabled"] = off_peak["enabled"]
                    changes["off_peak_start_hour"] = off_peak["begin_hour"]
                    changes["off_peak_start_minute"] = off_peak["begin_minute"]
                    changes["off_peak_end_hour"] = off_peak["end_hour"]
                    changes["off_peak_end_minute"] = off_peak["end_minute"]
                    track_received_field(state, changes, "off_peak_charging")

            elif key == DPS_MAP["UNDISTURBED"]:
                undisturbed = decode(UndisturbedResponse, value)
                _LOGGER.debug("Decoded UndisturbedResponse: %s", undisturbed)
                if undisturbed.HasField("undisturbed"):
                    changes["dnd_enabled"] = undisturbed.undisturbed.sw.value
                    if undisturbed.undisturbed.HasField("begin"):
                        changes["dnd_start_hour"] = undisturbed.undisturbed.begin.hour
                        changes["dnd_start_minute"] = (
                            undisturbed.undisturbed.begin.minute
                        )
                    if undisturbed.undisturbed.HasField("end"):
                        changes["dnd_end_hour"] = undisturbed.undisturbed.end.hour
                        changes["dnd_end_minute"] = undisturbed.undisturbed.end.minute
                    track_received_field(state, changes, "do_not_disturb")

            elif key == DPS_ROBOT_TELEMETRY:
                pos = _parse_robot_telemetry(value)
                _LOGGER.debug(
                    "DPS 179 telemetry: parsed=%s, raw_b64=%.60s...",
                    pos,
                    value,
                )
                if pos:
                    raw_x, raw_y = pos["x"], pos["y"]
                    changes["robot_position_x"] = raw_x
                    changes["robot_position_y"] = raw_y
                    track_received_field(state, changes, "robot_position")

            elif key in KNOWN_UNPROCESSED_DPS:
                _LOGGER.debug(
                    "Known unprocessed DPS %s: %s (value stored in raw_dps)",
                    key,
                    value,
                )

            else:
                _LOGGER.debug("Received unhandled DPS %s: %s", key, value)

        except Exception as e:
            _LOGGER.warning("Error parsing DPS %s: %s", key, e, exc_info=True)


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
            return "Paused"

        # If not resumable and cleaning field is absent, the task is complete
        if status.HasField("station") and status.station.HasField(
            "dust_collection_system"
        ):
            return "Emptying Dust"
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
        if (
            status.HasField("cleaning")
            and status.cleaning.state == 1  # PAUSED
            and not status.HasField("go_wash")
        ):
            return "Paused"
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
    if s in (0, 1):  # 0=Standby, 1=Sleep
        return "idle"
    if s == 2:  # Fault
        return "error"
    if s == 3:  # Charging
        return "docked"
    if s == 4:  # Positioning
        return "cleaning"
    if s == 5:  # Active clean / station wash+dry
        # go_wash.mode: 0=NAVIGATION, 1=WASHING, 2=DRYING
        # When washing or drying (modes 1, 2), the vacuum is physically docked at the station
        # Users expect "docked" status during station-based activities, not "cleaning"
        # "cleaning" implies the device is moving around cleaning floors
        # This aligns with HA's vacuum state model where "docked" includes station activities
        if status.HasField("go_wash") and status.go_wash.mode in (1, 2):
            return "docked"
        if status.HasField("station") and status.station.HasField(
            "washing_drying_system"
        ):
            return "docked"
        # User-initiated pause: cleaning sub-state is PAUSED and robot is NOT
        # navigating back to the dock for a wash (go_wash absent).
        if (
            status.HasField("cleaning")
            and status.cleaning.state == 1  # PAUSED
            and not status.HasField("go_wash")
        ):
            return "paused"
        return "cleaning"
    if s == 6:  # Active clean (alternate)
        return "cleaning"
    if s == 7:  # Go Home
        return "returning"
    if s == 8:  # Active clean (alternate / cruising)
        return "cleaning"
    if s == 9:  # Outside the enum: S1 Pro at its station (wash / empty / dry)
        return "docked"
    if s == 15:  # Paused
        return "paused"
    # Any other state outside the enum: read the sub-states rather than
    # guessing "idle".
    if status.HasField("go_wash"):
        return "docked" if status.go_wash.mode in (1, 2) else "cleaning"
    if status.HasField("go_home"):
        return "returning"
    if status.HasField("cleaning"):
        return "paused" if status.cleaning.state == 1 else "cleaning"

    return "idle"


def _map_trigger_source(value: int) -> str:
    """Map Trigger.Source to string.

    0: UNKNOWN
    1: APP
    2: KEY
    3: TIMING
    4: ROBOT
    5: REMOTE_CTRL
    """
    return TRIGGER_SOURCE_NAMES.get(TriggerSource(value), "unknown")


def _parse_video_manager_reply(value: Any) -> tuple[int, int] | None:
    """Return ``(method, result)`` from a DP 181 VideoMgrResponse, or None.

    ``result`` 0 (absent on the wire) is success; 1 means the robot refused.
    """
    try:
        raw = base64.b64decode(value)
        length, pos = decode_varint(raw, 0)
        end = min(len(raw), pos + length)
        while pos < end:
            key, pos = decode_varint(raw, pos)
            if key & 7 != 2:
                return None
            size, pos = decode_varint(raw, pos)
            if key >> 3 == 1:  # control
                method = result = 0
                inner, stop = pos, pos + size
                while inner < stop:
                    inner_key, inner = decode_varint(raw, inner)
                    if inner_key & 7 != 0:
                        return None
                    number, inner = decode_varint(raw, inner)
                    if inner_key >> 3 == 1:
                        method = number
                    elif inner_key >> 3 == 3:
                        result = number
                return method, result
            pos += size
    except (ValueError, TypeError, IndexError):
        return None
    return None


def _iter_unsetting_fields(value: Any) -> Iterator[tuple[int, int, bytes]]:
    """Walk a DPS 176 payload, yielding ``(field, wire_type, raw)`` for each entry.

    The S1 Pro packs settings into fields 104-107 that the bundled
    ``UnisettingResponse`` does not define, so these are read off the wire.
    """
    raw = base64.b64decode(value)
    length, pos = decode_varint(raw, 0)
    end = min(len(raw), pos + length)
    while pos < end:
        key, pos = decode_varint(raw, pos)
        field, wire = key >> 3, key & 7
        if wire == 0:
            number, pos = decode_varint(raw, pos)
            yield field, wire, encode_varint(number)
        elif wire == 2:
            size, pos = decode_varint(raw, pos)
            yield field, wire, raw[pos : pos + size]
            pos += size
        elif wire == 5:
            yield field, wire, raw[pos : pos + 4]
            pos += 4
        elif wire == 1:
            yield field, wire, raw[pos : pos + 8]
            pos += 8
        else:
            return


def _extract_video_switch(value: Any) -> bool | None:
    """Read the camera switch (field 104) out of a DPS 176 payload.

    The field holds a bool wrapper: an absent or empty submessage is the proto3
    default, i.e. the camera is off.
    """
    try:
        for field, _wire, raw in _iter_unsetting_fields(value):
            if field == DPS_UNSETTING_VIDEO_SWITCH_FIELD:
                return bool(raw) and raw != b"\x08\x00"
    except (ValueError, TypeError, IndexError):
        return None
    return None


def _extract_height_detection(value: Any) -> str | None:
    """Pull the height-detection mode (field 107) out of a DPS 176 payload."""
    try:
        for field, wire, raw in _iter_unsetting_fields(value):
            if field == DPS_UNSETTING_HEIGHT_DETECTION_FIELD and wire == 0:
                return HEIGHT_DETECTION_MODES.get(decode_varint(raw, 0)[0])
    except (ValueError, TypeError, IndexError):
        return None
    return None


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
    except Exception as e:
        _LOGGER.debug("Error mapping clean speed: %s", e)
    return "Standard"


def _map_dock_status(value: StationResponse) -> str:
    """Map StationResponse to status string."""
    try:
        status = value.status
        _LOGGER.debug(
            "Dock status raw: state=%s, collecting_dust=%s, clear_water_adding=%s, "
            "waste_water_recycling=%s, disinfectant_making=%s, cutting_hair=%s",
            status.state,
            status.collecting_dust,
            status.clear_water_adding,
            status.waste_water_recycling,
            status.disinfectant_making,
            status.cutting_hair,
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
    except Exception as e:
        _LOGGER.debug("Error mapping dock status: %s", e)
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


def _deduplicate_room_names(rooms: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Ensure room names are unique by appending a suffix to duplicates.

    e.g. two rooms named "Kitchen" become "Kitchen" and "Kitchen (2)".
    """
    names = [room["name"] for room in rooms]
    deduped = deduplicate_names(names)
    return [{**room, "name": name} for room, name in zip(rooms, deduped)]


def _parse_map_data(value: Any) -> dict[str, Any] | None:
    """Parse Map Data (Universal or RoomParams) from DPS."""
    # UniversalDataResponse
    try:
        universal_data = decode(UniversalDataResponse, value, has_length=True)
        if universal_data:
            _LOGGER.debug("Decoded UniversalDataResponse: %s", universal_data)
        if universal_data and (
            universal_data.cur_map_room.map_id or universal_data.cur_map_room.data
        ):
            rooms = []
            for r in universal_data.cur_map_room.data:
                name = (r.name or "").strip() or f"Room {r.id}"
                rooms.append({"id": r.id, "name": name})
            return {
                "map_id": universal_data.cur_map_room.map_id,
                "rooms": _deduplicate_room_names(rooms),
            }
    except Exception as e:
        _LOGGER.debug("UniversalDataResponse parse failed: %s", e)

    # RoomParams
    try:
        room_params = decode(RoomParams, value, has_length=True)
        if room_params:
            _LOGGER.debug("Decoded RoomParams: %s", room_params)
        if room_params and (room_params.map_id or room_params.rooms):
            rooms = []
            for rm in room_params.rooms:
                name = (rm.name or "").strip() or f"Room {rm.id}"
                rooms.append({"id": rm.id, "name": name})
            return {
                "map_id": room_params.map_id,
                "rooms": _deduplicate_room_names(rooms),
            }
    except Exception as e:
        _LOGGER.debug("RoomParams parse failed: %s", e)

    _LOGGER.debug("Failed to parse map data. Raw: %s", value)
    return None


def _parse_multi_map_response(value: Any) -> dict[str, Any] | None:
    """Parse MultiMapsManageResponse from DPS 172.

    Note: MAP_GET_ALL/MAP_GET_ONE responses with pixel data are only
    delivered via P2P, not cloud MQTT. This handler logs the response
    metadata for diagnostics but currently cannot extract pixel data.
    """
    try:
        resp = decode(MultiMapsManageResponse, value)
        _LOGGER.debug(
            "Decoded MultiMapsManageResponse: method=%s, result=%s",
            resp.method,
            resp.result,
        )
        return None
    except Exception as e:
        _LOGGER.debug("MultiMapsManageResponse parse failed: %s", e)
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

        def hours(field: str) -> int:
            # MQTT firmware reports whole hours; Tuya-transport firmware (S1 Pro)
            # reports minutes in a different field.
            duration = getattr(runtime, field)
            return round(duration.duration_min / 60) if duration.duration_min else duration.duration

        for field, usage in (
            ("filter_mesh", "filter_usage"),
            ("rolling_brush", "main_brush_usage"),
            ("side_brush", "side_brush_usage"),
            ("sensor", "sensor_usage"),
            ("scrape", "scrape_usage"),
            ("mop", "mop_usage"),
            ("dustbag", "dustbag_usage"),
            ("dirty_watertank", "dirty_watertank_usage"),
            ("dirty_waterfilter", "dirty_waterfilter_usage"),
        ):
            if runtime.HasField(field):
                changes[usage] = hours(field)

        return replace(current_state, **changes)

    except Exception as e:
        _LOGGER.debug("Error parsing accessory info: %s", e)
        return current_state


def _process_cleaning_parameters(
    state: VacuumState, value: Any, changes: dict[str, Any]
) -> None:
    """Process Cleaning Parameters DPS (154)."""
    # Try decoding as Response first, then Request
    clean_param = None
    try:
        response = decode(CleanParamResponse, value, has_length=True)
        if response and response.HasField("clean_param"):
            clean_param = response.clean_param
        elif response and response.HasField("running_clean_param"):
            clean_param = response.running_clean_param
        elif response and response.HasField("area_clean_param"):
            clean_param = response.area_clean_param
    except Exception as e:
        _LOGGER.debug("Failed to decode CleanParamResponse from DPS 154: %s", e)

    if not clean_param:
        try:
            request = decode(CleanParamRequest, value, has_length=True)
            if request and request.HasField("clean_param"):
                clean_param = request.clean_param
            elif request and request.HasField("area_clean_param"):
                clean_param = request.area_clean_param
        except Exception as e:
            _LOGGER.debug("Failed to decode CleanParamRequest from DPS 154: %s", e)

    if not clean_param:
        _LOGGER.debug("Could not decode Cleaning Parameters from DPS 154")
        return

    # Extract Cleaning Mode
    if clean_param.HasField("clean_type"):
        mode_val = clean_param.clean_type.value
        changes["cleaning_mode"] = CLEANING_MODE_NAMES.get(
            CleaningMode(mode_val), "Vacuum"
        )
        track_received_field(state, changes, "cleaning_mode")

    # Extract Fan Speed (available on newer devices in DPS 154)
    if clean_param.HasField("fan"):
        fan_val = clean_param.fan.suction
        changes["fan_speed"] = FAN_SUCTION_NAMES.get(fan_val, "Standard")
        track_received_field(state, changes, "fan_speed")
        _LOGGER.debug(
            "DPS 154: Extracted fan speed %s (value: %s)", changes["fan_speed"], fan_val
        )

    # Extract Mop Water Level
    if clean_param.HasField("mop_mode"):
        level_val = clean_param.mop_mode.level
        changes["mop_water_level"] = MOP_WATER_LEVEL_NAMES.get(
            MopWaterLevel(level_val), "Medium"
        )
        track_received_field(state, changes, "mop_water_level")
        _LOGGER.debug(
            "DPS 154: Extracted mop water level %s (value: %s)",
            changes["mop_water_level"],
            level_val,
        )
    else:
        _LOGGER.debug("DPS 154: mop_mode not present in cleaning parameters")

    # Extract Corner Cleaning Mode
    if clean_param.HasField("mop_mode"):
        corner_val = clean_param.mop_mode.corner_clean
        changes["corner_cleaning"] = CORNER_CLEANING_NAMES.get(corner_val, "Normal")
        track_received_field(state, changes, "corner_cleaning")
        _LOGGER.debug(
            "DPS 154: Extracted corner cleaning %s (value: %s)",
            changes["corner_cleaning"],
            corner_val,
        )

    # Extract Cleaning Intensity
    if clean_param.HasField("clean_extent"):
        extent_val = clean_param.clean_extent.value
        changes["cleaning_intensity"] = CLEANING_INTENSITY_NAMES.get(
            extent_val, "Normal"
        )
        track_received_field(state, changes, "cleaning_intensity")
        _LOGGER.debug(
            "DPS 154: Extracted cleaning intensity %s (value: %s)",
            changes["cleaning_intensity"],
            extent_val,
        )

    # Extract Carpet Strategy
    if clean_param.HasField("clean_carpet"):
        carpet_val = clean_param.clean_carpet.strategy
        changes["carpet_strategy"] = CARPET_STRATEGY_NAMES.get(carpet_val, "Auto Raise")
        track_received_field(state, changes, "carpet_strategy")
        _LOGGER.debug(
            "DPS 154: Extracted carpet strategy %s (value: %s)",
            changes["carpet_strategy"],
            carpet_val,
        )

    # Extract Smart Mode Switch
    if clean_param.HasField("smart_mode_sw"):
        changes["smart_mode"] = clean_param.smart_mode_sw.value
        track_received_field(state, changes, "smart_mode")
        _LOGGER.debug("DPS 154: Extracted smart mode %s", changes["smart_mode"])

    if _LOGGER.isEnabledFor(logging.DEBUG):
        tracked_fields = {
            "cleaning_mode",
            "fan_speed",
            "mop_water_level",
            "corner_cleaning",
            "cleaning_intensity",
            "carpet_strategy",
            "smart_mode",
        }
        field_count = sum(1 for k in changes if k in tracked_fields)
        _LOGGER.debug(
            "DPS 154: Successfully processed cleaning parameters - extracted %d fields",
            field_count,
        )
