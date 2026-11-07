from __future__ import annotations

import base64
import logging
from dataclasses import replace
from typing import Any

from google.protobuf.json_format import MessageToDict
from google.protobuf.message import Message

from ..const import (
    CARPET_STRATEGY_NAMES,
    CLEANING_INTENSITY_NAMES,
    CLEANING_MODE_NAMES,
    CORNER_CLEANING_NAMES,
    DOCK_ACTIVITY_STATES,
    DPS_MAP,
    DPS_ROBOT_TELEMETRY,
    EUFY_CLEAN_APP_TRIGGER_MODES,
    EUFY_CLEAN_ERROR_CODES,
    EUFY_CLEAN_NOVEL_CLEAN_SPEED,
    FAN_SUCTION_NAMES,
    KNOWN_UNPROCESSED_DPS,
    MOP_WATER_LEVEL_NAMES,
    STATION_WATER_LEVEL_NAMES,
    TRIGGER_SOURCE_NAMES,
    WORK_MODE_NAMES,
)
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
from ..utils import decode, decode_varint, deduplicate_names
from .parser_scalar import process_scalar_dps

_LOGGER = logging.getLogger(__name__)

# Proto fields that identify the user, the device or the home; cleared before a
# decoded message is debug-logged (users attach debug logs to public issues).
_DEVICE_INFO_PRIVATE = (
    "video_sn", "device_mac", "wifi_name", "wifi_ip", "last_user_id",
)
_UNISETTING_PRIVATE = ("wifi_data",)
_WORK_STATUS_PRIVATE = ("current_scene.name",)

# Enum values already reported as unknown, so each is logged once per process.
_UNKNOWN_ENUM_VALUES: set[tuple[str, int]] = set()


def _debug_proto(label: str, message: Message, *private: str) -> None:
    """Debug-log a decoded proto with the ``private`` (dotted) fields cleared."""
    if not _LOGGER.isEnabledFor(logging.DEBUG):
        return
    if private:
        shown = type(message)()
        shown.CopyFrom(message)
        for path in private:
            *parents, leaf = path.split(".")
            target = shown
            for name in parents:
                if not target.HasField(name):
                    break
                target = getattr(target, name)
            else:
                target.ClearField(leaf)
        message = shown
    _LOGGER.debug("Decoded %s: %s", label, message)


def _enum_name(names: dict[Any, str], value: int, label: str, default: str) -> str:
    """``names[value]`` for an int-keyed enum table; ``default`` for a value the
    firmware added after this table, logged once per value at debug."""
    name = names.get(value)
    if name is not None:
        return name
    if (label, value) not in _UNKNOWN_ENUM_VALUES:
        _UNKNOWN_ENUM_VALUES.add((label, value))
        _LOGGER.debug("Unknown %s value %s; using %r", label, value, default)
    return default


_OFF_PEAK_RESPONSE_FIELD_NUM = 23  # UnisettingResponse field 23 = OffPeakCharging (undocumented)


def _extract_off_peak_charging(raw_b64: str) -> dict[str, int | bool] | None:
    """Extract off-peak charging from raw UnisettingResponse bytes (not in the proto)."""
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
    """Decode schema-less protobuf into {field_number: int varint | bytes}."""
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
    """Parse DPS 179 telemetry (no proto): field 2 -> 7 -> {4: map x, 5: map y}.

    Field 7 carries {1: epoch seconds, 2: battery, 4: x, 5: y}; the coordinates
    are zigzag-encoded sint32 in an unknown origin frame.
    """
    try:
        raw = base64.b64decode(value)
    except Exception:
        _LOGGER.debug("Failed to decode DPS 179 base64 (%d chars)", len(str(value)))
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
    """Update VacuumState from DPS data.

    Returns (new_state, changes); changes holds only the fields this message set,
    so callers can tell "actively set" from "inherited".
    """
    changes: dict[str, Any] = {}

    new_raw_dps = state.raw_dps.copy()
    new_raw_dps.update(dps)
    changes["raw_dps"] = new_raw_dps

    # api_type comes from EufyLogin.checkApiType: scalar = plain Tuya-style DPS,
    # novel = Anker length-prefixed protobuf ("unknown" lands here too; the
    # coordinator sends "legacy" to legacy_parser.update_state_legacy instead)
    if state.api_type == "scalar":
        process_scalar_dps(state, dps, changes)
    else:
        _process_station_status(state, dps, changes)
        _process_work_status(state, dps, changes)
        _process_play_pause(state, dps, changes)
        _process_other_dps(state, dps, changes)

    if "received_fields" in changes:
        _LOGGER.debug("Received fields now: %s", changes["received_fields"])

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
        _debug_proto("StationResponse", station)
        new_dock_status = _map_dock_status(station)
        # debounced in the coordinator, not here
        changes["dock_status"] = new_dock_status
        track_received_field(state, changes, "dock_status")

        if station.HasField("clean_water"):
            changes["station_clean_water"] = station.clean_water.value
            track_received_field(state, changes, "station_clean_water")

        # dirty_level is a proto3 enum without presence, so a dock that never
        # sends it would read as EMPTY. Report it only once it has been on the
        # wire; after that, a frame without it is read as EMPTY.
        dirty_level_sent = any(
            fd.name == "dirty_level" for fd, _ in station.ListFields()
        )
        if dirty_level_sent or "station_dirty_water" in state.received_fields:
            changes["station_dirty_water"] = STATION_WATER_LEVEL_NAMES.get(
                station.dirty_level, "Unknown"
            )
            track_received_field(state, changes, "station_dirty_water")

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
        _debug_proto("WorkStatus", work_status, *_WORK_STATUS_PRIVATE)
        changes["activity"] = _map_work_status(work_status)
        changes["status_code"] = work_status.state

        current_dock_status = changes.get("dock_status", state.dock_status)
        changes["task_status"] = _map_task_status(work_status, current_dock_status)

        # the charging sub-message wins over the main state when present
        if work_status.HasField("charging"):
            # Charging.State.DOING is 0
            changes["charging"] = work_status.charging.state == 0
        else:
            changes["charging"] = False

        trigger_source = "unknown"
        if work_status.HasField("trigger"):
            trigger_source = _map_trigger_source(work_status.trigger.source)

        # some models (X10 Pro Omni) omit the trigger field for certain modes
        if trigger_source == "unknown" and work_status.HasField("mode"):
            mode_val = work_status.mode.value
            if mode_val in EUFY_CLEAN_APP_TRIGGER_MODES:
                trigger_source = "app"

        changes["trigger_source"] = trigger_source

        if work_status.HasField("mode"):
            mode_val = work_status.mode.value
            changes["work_mode"] = WORK_MODE_NAMES.get(mode_val, "unknown")
            track_received_field(state, changes, "work_mode")
        elif state.work_mode == "unknown" and changes.get("activity") == "cleaning":
            changes["work_mode"] = "Auto"

        if work_status.HasField("cleaning") and work_status.cleaning.scheduled_task:
            changes["trigger_source"] = "schedule"

        # clears a dock status stuck on e.g. Drying when StationResponse goes quiet
        if work_status.HasField("station"):
            st = work_status.station

            has_dock_activity = False

            if st.HasField("washing_drying_system"):
                has_dock_activity = True
                # 0=WASHING, 1=DRYING
                if st.washing_drying_system.state == 1:
                    changes["dock_status"] = "Drying"
                else:
                    changes["dock_status"] = "Washing"

            if st.HasField("dust_collection_system"):
                has_dock_activity = True
                changes["dock_status"] = "Emptying dust"

            if st.HasField("water_injection_system"):
                has_dock_activity = True
                # 0=ADDING, 1=EMPTYING
                if st.water_injection_system.state == 0:
                    changes["dock_status"] = "Adding clean water"
                else:
                    changes["dock_status"] = "Recycling waste water"

            if not has_dock_activity:
                current_dock = changes.get("dock_status", state.dock_status)
                if current_dock in DOCK_ACTIVITY_STATES:
                    changes["dock_status"] = "Idle"

        else:
            if work_status.state == 3:  # CHARGING
                current_dock = changes.get("dock_status", state.dock_status)
                if current_dock in DOCK_ACTIVITY_STATES:
                    changes["dock_status"] = "Idle"

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

        # mode 8 = SCENE
        elif work_status.HasField("mode") and work_status.mode.value != 8:
            changes["current_scene_id"] = 0
            changes["current_scene_name"] = None

        # 3=charging, 7=go home; not 0 (standby), which partial updates default to
        elif work_status.state in [3, 7]:
            changes["current_scene_id"] = 0
            changes["current_scene_name"] = None

        # docked can mean an in-progress wash/dry, so key off task_status too
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
        _debug_proto("ModeCtrlRequest", mode_ctrl)

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

        # scene comes from WorkStatus.current_scene; control commands have no Param

    except Exception as e:
        _LOGGER.warning("Error parsing Play/Pause DPS: %s", e, exc_info=True)


def _process_other_dps(
    state: VacuumState, dps: dict[str, Any], changes: dict[str, Any]
) -> None:
    """Process other DPS items."""
    for key, value in dps.items():
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

            elif key == DPS_MAP["ERROR_CODE"]:
                error_proto = decode(ErrorCode, value)
                _debug_proto("ErrorCode", error_proto)
                # Codes arrive in two lists; prefer `error` so a standing
                # warning can't mask a fault, and expose both in full.
                errors = [int(c) for c in error_proto.error]
                warns = [int(c) for c in error_proto.warn]
                changes["error_codes"] = errors
                changes["warn_codes"] = warns
                if errors or warns:
                    code = errors[0] if errors else warns[0]
                    changes["error_code"] = code
                    changes["error_message"] = EUFY_CLEAN_ERROR_CODES.get(
                        code, "Unknown Error"
                    )
                else:
                    changes["error_code"] = 0
                    changes["error_message"] = ""

            elif key == DPS_MAP["ACCESSORIES_STATUS"]:
                changes["accessories"] = _parse_accessories(state.accessories, value)
                track_received_field(state, changes, "accessories")

            elif key == DPS_MAP["CLEANING_STATISTICS"]:
                stats = decode(CleanStatistics, value)
                _debug_proto("CleanStatistics", stats)
                if stats.HasField("single"):
                    changes["cleaning_time"] = stats.single.clean_duration
                    # keep the last run's area: the device reports 0 after docking
                    if stats.single.clean_area > 0:
                        changes["cleaning_area"] = stats.single.clean_area
                    track_received_field(state, changes, "cleaning_stats")
                if stats.HasField("user_total"):
                    changes["total_cleaning_area"] = stats.user_total.clean_area
                    changes["total_cleaning_time"] = stats.user_total.clean_duration
                    changes["total_cleaning_count"] = stats.user_total.clean_count
                    track_received_field(state, changes, "cleaning_totals")

            elif key == DPS_MAP["SCENE_INFO"]:
                changes["scenes"] = _parse_scene_info(value)

            elif key == DPS_MAP["MAP_DATA"]:
                map_info = _parse_map_data(value)
                if map_info:
                    changes["map_id"] = map_info.get("map_id", 0)
                    changes["rooms"] = map_info.get("rooms", [])
                    track_received_field(state, changes, "map_id")

            elif key == DPS_MAP["CLEANING_PARAMETERS"]:
                _process_cleaning_parameters(state, value, changes)

            elif key == DPS_MAP["FIND_ROBOT"]:
                changes["find_robot"] = str(value).lower() == "true"

            elif key == DPS_MAP["VOLUME"]:
                changes["volume"] = max(0, min(100, int(value)))
                track_received_field(state, changes, "volume")

            elif key == DPS_MAP["VOICE_LANGUAGE"]:
                lang = decode(LanguageResponse, value)
                _debug_proto("LanguageResponse", lang)
                if lang.current_id > 0:
                    changes["voice_set_id"] = lang.current_id
                    track_received_field(state, changes, "voice")

            elif key == DPS_MAP["MAP_MANAGE"]:
                # DPS 169 is DeviceInfo despite the name; firmware already comes
                # from the cloud API
                info = decode(DeviceInfo, value)
                _debug_proto("DeviceInfo", info, *_DEVICE_INFO_PRIVATE)
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
                    _parse_multi_map_response(value)

            elif key == DPS_MAP["UNSETTING"]:
                settings = decode(UnisettingResponse, value)
                _debug_proto("UnisettingResponse", settings, *_UNISETTING_PRIVATE)
                # Device reports 0-100%, approximate to dBm for HA convention
                changes["wifi_signal"] = (settings.ap_signal_strength / 2) - 100
                track_received_field(state, changes, "wifi_signal")
                if settings.HasField("children_lock"):
                    changes["child_lock"] = settings.children_lock.value
                    track_received_field(state, changes, "child_lock")
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
                _debug_proto("UndisturbedResponse", undisturbed)
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
                _LOGGER.debug("DPS 179 telemetry: parsed=%s", pos is not None)
                if pos:
                    raw_x, raw_y = pos["x"], pos["y"]
                    changes["robot_position_x"] = raw_x
                    changes["robot_position_y"] = raw_y
                    track_received_field(state, changes, "robot_position")

            elif key in KNOWN_UNPROCESSED_DPS:
                _LOGGER.debug(
                    "Known unprocessed DPS %s (value stored in raw_dps)", key
                )

            else:
                _LOGGER.debug(
                    "Received unhandled DPS %s (%s)", key, type(value).__name__
                )

        except Exception as e:
            _LOGGER.warning("Error parsing DPS %s: %s", key, e, exc_info=True)


def _map_task_status(status: WorkStatus, dock_status: str | None = None) -> str:
    """Map WorkStatus to detailed task status."""
    s = status.state

    # wash/dry sits inside cleaning state 5, so check it first
    if status.HasField("go_wash"):
        # GoWash.Mode: NAVIGATION=0, WASHING=1, DRYING=2
        gw_mode = status.go_wash.mode
        if gw_mode == 2:
            return "Completed"
        if gw_mode == 1:
            return "Washing Mop"
        if gw_mode == 0 and s == 5:
            return "Returning to Wash"

    # breakpoint.state 0 = an interrupted clean is resumable after recharge
    is_resumable = False
    if status.HasField("breakpoint") and status.breakpoint.state == 0:
        is_resumable = True

    if s == 3:  # Charging
        if is_resumable:
            return "Charging (Resume)"

        # cleaning PAUSED while the dock washes = mid-clean pause, not completion
        if status.HasField("cleaning") and status.cleaning.state == 1:  # PAUSED
            if dock_status in (
                "Washing",
                "Adding clean water",
                "Recycling waste water",
            ):
                return "Washing Mop"
            return "Paused"

        if status.HasField("station") and status.station.HasField(
            "dust_collection_system"
        ):
            return "Emptying Dust"
        return "Completed"

    if s == 7:  # Returning / Go Home
        # GoHome.mode: 0=COMPLETE_TASK, 1=COLLECT_DUST
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

    if s == 15:  # Stop / Pause
        return "Paused"

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
        # go_wash.mode 1=WASHING, 2=DRYING happen on the dock; HA calls that docked
        if status.HasField("go_wash") and status.go_wash.mode in (1, 2):
            return "docked"
        if status.HasField("station") and status.station.HasField(
            "washing_drying_system"
        ):
            return "docked"
        # user pause: PAUSED without go_wash (go_wash means heading in to wash)
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
    if s == 15:  # Paused
        return "paused"

    return "idle"


def _map_trigger_source(value: int) -> str:
    """Map Trigger.Source to string."""
    return _enum_name(TRIGGER_SOURCE_NAMES, value, "Trigger.Source", "unknown")


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
        _LOGGER.debug("Decoded SceneResponse: %d scenes", len(scene_response.infos))
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
        _LOGGER.debug("Error parsing scene info: %s", e)
        return []


def _deduplicate_room_names(rooms: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Suffix duplicate room names: two "Kitchen" become "Kitchen", "Kitchen (2)"."""
    names = [room["name"] for room in rooms]
    deduped = deduplicate_names(names)
    return [{**room, "name": name} for room, name in zip(rooms, deduped)]


def _parse_map_data(value: Any) -> dict[str, Any] | None:
    """Parse Map Data (Universal or RoomParams) from DPS."""
    try:
        universal_data = decode(UniversalDataResponse, value, has_length=True)
        if universal_data:
            _LOGGER.debug(
                "Decoded UniversalDataResponse: map %d, %d rooms",
                universal_data.cur_map_room.map_id,
                len(universal_data.cur_map_room.data),
            )
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

    try:
        room_params = decode(RoomParams, value, has_length=True)
        if room_params:
            _LOGGER.debug(
                "Decoded RoomParams: map %d, %d rooms",
                room_params.map_id,
                len(room_params.rooms),
            )
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

    _LOGGER.debug("Failed to parse map data (%d chars)", len(str(value)))
    return None


def _parse_multi_map_response(value: Any) -> dict[str, Any] | None:
    """Log DPS 172 response metadata; pixel data only arrives over P2P, not MQTT."""
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
        _debug_proto("ConsumableResponse", response)
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


def _process_cleaning_parameters(
    state: VacuumState, value: Any, changes: dict[str, Any]
) -> None:
    """Process Cleaning Parameters DPS (154)."""
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

    if clean_param.HasField("clean_type"):
        mode_val = clean_param.clean_type.value
        changes["cleaning_mode"] = _enum_name(
            CLEANING_MODE_NAMES, mode_val, "CleanType", "Vacuum"
        )
        track_received_field(state, changes, "cleaning_mode")

    if clean_param.HasField("fan"):
        fan_val = clean_param.fan.suction
        changes["fan_speed"] = FAN_SUCTION_NAMES.get(fan_val, "Standard")
        track_received_field(state, changes, "fan_speed")
        _LOGGER.debug(
            "DPS 154: Extracted fan speed %s (value: %s)", changes["fan_speed"], fan_val
        )

    if clean_param.HasField("mop_mode"):
        level_val = clean_param.mop_mode.level
        changes["mop_water_level"] = _enum_name(
            MOP_WATER_LEVEL_NAMES, level_val, "MopMode.level", "Medium"
        )
        track_received_field(state, changes, "mop_water_level")
        _LOGGER.debug(
            "DPS 154: Extracted mop water level %s (value: %s)",
            changes["mop_water_level"],
            level_val,
        )
    else:
        _LOGGER.debug("DPS 154: mop_mode not present in cleaning parameters")

    if clean_param.HasField("mop_mode"):
        corner_val = clean_param.mop_mode.corner_clean
        changes["corner_cleaning"] = CORNER_CLEANING_NAMES.get(corner_val, "Normal")
        track_received_field(state, changes, "corner_cleaning")
        _LOGGER.debug(
            "DPS 154: Extracted corner cleaning %s (value: %s)",
            changes["corner_cleaning"],
            corner_val,
        )

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

    if clean_param.HasField("clean_carpet"):
        carpet_val = clean_param.clean_carpet.strategy
        changes["carpet_strategy"] = CARPET_STRATEGY_NAMES.get(carpet_val, "Auto Raise")
        track_received_field(state, changes, "carpet_strategy")
        _LOGGER.debug(
            "DPS 154: Extracted carpet strategy %s (value: %s)",
            changes["carpet_strategy"],
            carpet_val,
        )

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
