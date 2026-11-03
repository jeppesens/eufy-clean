from __future__ import annotations

import asyncio
import base64
import json
import logging
import math
import re
import ssl
import time
import zlib
from collections.abc import Callable, Sequence
from dataclasses import replace
from datetime import timedelta
from functools import partial
from typing import Any

from homeassistant.components.persistent_notification import (
    async_create as pn_async_create,
)
from homeassistant.components.persistent_notification import (
    async_dismiss as pn_async_dismiss,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.device_registry import (
    CONNECTION_NETWORK_MAC,
    DeviceInfo,
    format_mac,
)
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_call_later, async_track_time_interval
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api.client import EufyCleanClient, is_certificate_rejection
from .api.cloud import EufyLogin, EufyLoginError
from .api.commands import build_command
from .api.legacy_commands import (
    build_legacy_command,
    build_legacy_schedule_dps,
    build_map_keepalive,
)
from .api.legacy_parser import (
    encode_legacy_loops,
    parse_legacy_schedules,
    update_state_legacy,
)
from .api.local_tuya import LocalTuyaClient, LocalTuyaError
from .api.map_geometry import build_map_static
from .api.map_stream import (
    _TUYA_UNITS_PER_CELL,
    MapData,
    map_data_from_tuya_map,
    parse_biz_protocol41,
    render_map_png,
    room_polygons_to_cells,
    try_decode_as_dynamic_data,
    try_extract_map_data,
    try_extract_map_description,
)
from .api.parser import update_state
from .api.parser_scalar import (
    build_scalar_schedule_payload,
    scalar_pattern_to_int,
    scalar_raw_to_schedule_entry,
    scalar_schedule_raw_entries,
    scalar_suction_to_int,
    schedule_entry_to_scalar_raw,
)
from .api.tuya_cloud import TuyaCallProbe
from .api.tuya_mqtt import (
    MMI_BAN_MOP_ZONES,
    MMI_CUSTOM_ROOM,
    MMI_CUSTOM_ROOMS_ENABLED,
    MMI_DOCK_POSE,
    MMI_FORBIDDEN_ZONES,
    MMI_GLOBAL_ROOM,
    MMI_PARAM,
    MMI_ROOM,
    MMI_ROOM_NAME,
    MMI_VIRTUAL_WALL,
    TuyaMobileMQTT,
    build_connect_params,
    decode_custom_rooms_enabled,
    decode_dock_pose,
    decode_forbidden_zones,
    decode_map_param,
    decode_room_clean_order,
    decode_room_custom,
    decode_room_names,
    decode_room_polygons,
    decode_virtual_walls,
    random_device_id44,
)
from .api.tuya_storage import TuyaMapStorage
from .auth_store import AuthStore
from .const import (
    CONF_LOCAL_DEVICES,
    CONF_LOCAL_VERSION,
    CONF_MAP_MAX_PX,
    CONF_NOTIFY_DESKTOP,
    CONF_NOTIFY_MOBILE_SERVICE,
    CONF_ROBOT_STYLE,
    CONF_TRAIL_COLOR,
    DEFAULT_MAP_MAX_PX,
    DEFAULT_NOTIFY_DESKTOP,
    DEFAULT_NOTIFY_MOBILE_SERVICE,
    DEFAULT_ROBOT_STYLE,
    DEFAULT_TRAIL_COLOR,
    DOMAIN,
    LEGACY_CLEAN_SPEEDS,
    LEGACY_DPS_MAP,
    LEGACY_ROOM_DEFAULT_FAN,
    LEGACY_ROOM_DEFAULT_WATER,
    LEGACY_ROOM_FAN_LEVELS,
    LEGACY_ROOM_WATER_LEVELS,
)
from .entity import has_firmware_api
from .models import VacuumState
from .profiles import DeviceProfile, get_device_profile

_LOGGER = logging.getLogger(__name__)

_CLOUD_POLL_INTERVAL = timedelta(seconds=30)
_MAX_BACKOFF_INTERVAL = timedelta(minutes=5)
_FAILURE_THRESHOLD = 5
# Min gap between fetches of the same failing cid.
_MAP_REFRESH_RETRY_COOLDOWN = 300.0

# Legacy live-pose placement: col = dock_col + x/10, row = dock_row - y/10.
# (col, row): pose origin is the robot centre, the map's the dock contacts.
_LEGACY_POSE_DOCK_OFFSET = (4, 2)

# A dock jump beyond this is a map FRAME change, not a move.
_LEGACY_DOCK_MAX_SHIFT_CELLS = 20

# Max cm between poses drawn as one segment; beyond it, a jump.
_LEGACY_TRAIL_MAX_STEP_CM = 250
# Rejections tolerated before taking the point anyway.
_LEGACY_TRAIL_MAX_REJECTS = 3

# A dock visit from one of these is a pause; keep the trail.
_ACTIVE_ACTIVITIES = ("cleaning", "returning", "paused")
# How long a pause still counts as the same session.
_DOCK_PAUSE_MAX_SECONDS = 600

# Each legacy coordinator renews the account's shared Thing session on this
# timer; a tick within MIN_AGE of a sibling's renewal skips the login, so an
# account logs in at most twice per interval however many robots it has.
_TUYA_SESSION_REFRESH_INTERVAL = timedelta(minutes=90)
_TUYA_SESSION_MIN_AGE = _TUYA_SESSION_REFRESH_INTERVAL.total_seconds() / 2
# The publish window decays mid-clean; only cloud contact renews it.
_LEGACY_MAP_KEEPALIVE_INTERVAL = timedelta(seconds=30)
# Activities whose 0x67 frames are live trail, not a replay.
_LEGACY_TRAIL_ACTIVITIES = ("cleaning", "returning")
_RESTRICTED_LABELS = {
    MMI_FORBIDDEN_ZONES: "no-go zones",
    MMI_BAN_MOP_ZONES: "no-mop zones",
    MMI_VIRTUAL_WALL: "virtual walls",
}
# A failed send re-logins; cap retries to avoid a storm.
_LEGACY_MAP_KEEPALIVE_MAX_FAILURES = 3

# Asked from the robot STOPPING; `cid` misses rewrites.
_LEGACY_MAP_POST_CLEAN_CHECKS = (timedelta(seconds=90), timedelta(minutes=30))
# Same login-storm cap as the keepalive.
_LEGACY_MAP_FRESHNESS_MAX_FAILURES = 3

# 2 Hz ceiling; coalesces, so `from` stays contiguous.
_MAP_EVENT_MIN_INTERVAL = 0.5
# Min gap between legacy schedule fetches that were not asked for explicitly.
_SCHEDULE_REFRESH_RETRY_COOLDOWN = 300.0
# Max seconds between a map-state change and its write to .storage.
_MAP_STATE_SAVE_DELAY = 30.0
# biz/ frames at least this long (hex chars) are decoded in the executor.
_BIZ_INLINE_HEX_MAX = 200
# The transport must stay down this long before entities go unavailable.
_CONNECTION_LOSS_GRACE = 60.0
# Connection attempts in a row on which the broker rejected the client
# identity before one warning is logged; each multiple of it asks EufyLogin
# for replacement credentials.
_AUTH_FAILURE_WARN_AFTER = 3


# Days of a schedule created without any.
_NEW_SCHEDULE_DAYS = "Every day"

# Undocumented; every combination is tried, the winner memoized.
_TIMER_CLIENTS = ("tuya_thing_client", "tuya_client")
_TIMER_PARAM_SHAPES = ("biz_device", "dev", "biz")


def _version_token_mtime(token: str | None) -> float | None:
    """Epoch seconds in a version token ``"<mtime>:<path>"``; None if unparsable."""
    if not token:
        return None
    head = token.split(":", 1)[0]
    try:
        return float(head)
    except ValueError:
        return None


def _finite(value: Any, what: str) -> float:
    """``value`` as a finite float; ServiceValidationError otherwise."""
    try:
        number = float(value)
    except (TypeError, ValueError) as err:
        raise ServiceValidationError(f"{what} must be a number, got {value!r}") from err
    if not math.isfinite(number):
        raise ServiceValidationError(f"{what} must be finite, got {value!r}")
    return number


def _decode_biz_frame(hex_data: str, map_candidate: bool) -> tuple[str, Any] | None:
    """Decode one large biz/ frame (blocking): ``("desc", (id, name))`` or ``("map", MapData)``."""
    desc = try_extract_map_description(hex_data)
    if desc is not None:
        return "desc", desc
    if map_candidate:
        map_data = try_extract_map_data(hex_data)
        if map_data is not None:
            return "map", map_data
    return None


def _timer_params(shape: str, device_id: str, **fields: Any) -> dict[str, Any]:
    """Build one parameter shape for a Tuya timer action."""
    if shape == "dev":
        return {"devId": device_id, **fields}
    base: dict[str, Any] = {"bizId": device_id}
    if shape == "biz_device":
        base["type"] = "device"
    return {**base, **fields}


def _robot_status_badge(
    dock: str | None, activity: str | None, battery: int | None
) -> str | None:
    """The map's robot badge for a dock status, activity and battery level."""
    if dock == "Washing":
        return "washing"
    if dock == "Drying":
        return "drying"
    if dock == "Emptying dust":
        return "emptying"
    if dock in ("Adding clean water", "Recycling waste water", "Making disinfectant", "Cutting hair"):
        return "station"
    if activity in ("docked", "idle"):
        # "idle" covers sleep/standby in the dock.
        if battery is not None and battery >= 100:
            return None  # full battery — no charging badge
        return "charging"
    return None


def _px_dist(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Euclidean distance between two pixel coords."""
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5


def _normalize_schedule_time(value: str) -> str:
    """Normalize ``HH:MM:SS`` / ``HH:MM`` / ``HHMM`` to canonical ``HH:MM``."""
    raw = str(value).strip()
    hour = minute = None
    if ":" in raw:
        parts = raw.split(":")
        if len(parts) in (2, 3) and parts[0].isdigit() and parts[1].isdigit():
            hour, minute = int(parts[0]), int(parts[1])
    elif len(raw) == 4 and raw.isdigit():
        hour, minute = int(raw[:2]), int(raw[2:])
    if hour is None or minute is None or not 0 <= hour <= 23 or not 0 <= minute <= 59:
        raise ServiceValidationError(
            f"Invalid time format: {value!r}. Expected 'HH:MM'."
        )
    return f"{hour:02d}:{minute:02d}"


def _as_normalized_points(shape: Any) -> list[tuple[float, float]] | None:
    """``[[x, y], ...]`` -> a point list; ``None`` for the flat four-number form."""
    if isinstance(shape, (str, bytes)) or not isinstance(shape, (list, tuple)):
        return None
    points: list[tuple[float, float]] = []
    for item in shape:
        if isinstance(item, (str, bytes)) or not isinstance(item, (list, tuple)):
            return None
        if len(item) != 2:
            return None
        try:
            points.append((float(item[0]), float(item[1])))
        except (TypeError, ValueError):
            return None
    return points or None


def _shapes_sig(shapes: Any) -> tuple:
    """A hashable content signature for a list of point-list shapes."""
    return tuple(
        tuple((round(float(p[0]), 1), round(float(p[1]), 1)) for p in shape)
        for shape in shapes
    )


def _drop_indices(shapes: list, indices: Any, label: str) -> list:
    """Return *shapes* without the entries named by *indices*."""
    if not indices:
        return shapes
    try:
        wanted = {int(i) for i in indices}
    except (TypeError, ValueError) as err:
        raise HomeAssistantError(
            f"set_nogo_zones: 'remove_{label}' must be a list of indices"
        ) from err
    out_of_range = sorted(i for i in wanted if not 0 <= i < len(shapes))
    if out_of_range:
        raise HomeAssistantError(
            f"set_nogo_zones: remove_{label} index {out_of_range} is outside the "
            f"{len(shapes)} shape(s) this map has — nothing was sent"
        )
    return [shape for index, shape in enumerate(shapes) if index not in wanted]


def _move_shapes(shapes: list, moves: Any, label: str) -> list:
    """Apply ``{index, dx, dy, rotate}`` transforms to world-cm point lists.

    Stays in world cm (isotropic, no aspect correction) so shapes off the map edge
    survive; ``dx``/``dy`` cm, ``rotate`` radians CCW about the centroid.
    """
    if not moves:
        return shapes
    out = [list(shape) for shape in shapes]
    for move in moves:
        if not isinstance(move, dict):
            raise HomeAssistantError(
                f"set_nogo_zones: each move_{label} entry must be a mapping with an "
                "'index', got " + repr(move)
            )
        try:
            index = int(move["index"])
        except (KeyError, TypeError, ValueError) as err:
            raise HomeAssistantError(
                f"set_nogo_zones: malformed move_{label} entry {move!r}"
            ) from err
        dx = _finite(move.get("dx", 0.0), f"set_nogo_zones: move_{label} dx")
        dy = _finite(move.get("dy", 0.0), f"set_nogo_zones: move_{label} dy")
        angle = _finite(move.get("rotate", 0.0), f"set_nogo_zones: move_{label} rotate")
        if not 0 <= index < len(out):
            raise HomeAssistantError(
                f"set_nogo_zones: move_{label} index {index} is outside the "
                f"{len(out)} shape(s) this map has — nothing was sent"
            )
        points = out[index]
        if not points:
            continue
        cx = sum(p[0] for p in points) / len(points)
        cy = sum(p[1] for p in points) / len(points)
        cos_a = math.cos(angle)
        sin_a = math.sin(angle)
        out[index] = [
            (
                cx + (p[0] - cx) * cos_a - (p[1] - cy) * sin_a + dx,
                cy + (p[0] - cx) * sin_a + (p[1] - cy) * cos_a + dy,
            )
            for p in points
        ]
    return out


def _index_set(values: Any) -> set[int]:
    """Best-effort index set from ints or move entries, for the overlap check only."""
    found: set[int] = set()
    for value in values or []:
        raw = value.get("index") if isinstance(value, dict) else value
        try:
            found.add(int(raw))
        except (TypeError, ValueError):
            continue
    return found


def _safe_storage_key(device_id: str) -> str:
    """Make a cloud-supplied device id safe to use as a .storage filename."""
    cleaned = re.sub(r"[^A-Za-z0-9_.-]", "_", str(device_id))
    # A key of dots still traverses; a leading dot hides the file.
    cleaned = cleaned.lstrip(".") or "unknown"
    return cleaned[:64]


class EufyCleanCoordinator(DataUpdateCoordinator[VacuumState]):
    """Coordinator to manage Eufy Clean device connection and state."""

    def __init__(
        self,
        hass: HomeAssistant,
        eufy_login: EufyLogin,
        device_info: dict[str, Any],
        config_entry: ConfigEntry | None = None,
    ) -> None:
        """Initialize coordinator."""
        self.entry_id = config_entry.entry_id if config_entry else ""
        self.device_id = device_info["deviceId"]
        self.device_model = device_info["deviceModel"]
        # "novel" protobuf / "scalar" Tuya-int / "legacy"
        self.api_type: str = device_info.get("apiType", "novel")
        self.device_name = device_info["deviceName"]
        self.serial_number = device_info.get("deviceId")
        self.firmware_version = device_info.get("softVersion")
        self.eufy_login = eufy_login

        # "mqtt" (AIOT push), "local" (LAN push), "cloud" (REST poll).
        if device_info.get("connection_type"):
            self.connection_type: str = device_info["connection_type"]
        elif device_info.get("mqtt", True):
            self.connection_type = "mqtt"
        else:
            self.connection_type = "cloud"

        self._local_key: str | None = device_info.get("local_key")
        self._local_host: str | None = device_info.get("local_host")
        self._local_version: float = float(device_info.get("local_version", 3.3))
        # {dps_id: {code, mode, type, range}}; empty for AIOT/MQTT.
        self.tuya_schema: dict[str, dict[str, Any]] = dict(
            device_info.get("tuya_schema") or {}
        )
        # For transports with no room list; empty means P2P names.
        self.room_name_overrides: dict[int, str] = dict(
            device_info.get("room_name_overrides") or {}
        )
        # Manual map-id override for room/zone clean commands. Needed on
        # devices whose UniversalData DPS reports the cloud map id while the
        # firmware only accepts the local map id (see CONF_MAP_ID in const.py).
        self.map_id_override: int | None = device_info.get("map_id_override")
        # Per-map overrides keyed by the map id the device reports.
        self.map_id_overrides: dict[int, int] = dict(
            device_info.get("map_id_overrides") or {}
        )

        update_interval = _CLOUD_POLL_INTERVAL if self.connection_type == "cloud" else None

        _LOGGER.debug(
            "Coordinator created: device=%s, model=%s, api_type=%s, connection=%s, poll=%s",
            self.device_id, self.device_model, self.api_type, self.connection_type, update_interval,
        )

        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{self.device_name}",
            config_entry=config_entry,
            update_interval=update_interval,
        )

        self.client: EufyCleanClient | LocalTuyaClient | None = None
        self.data = VacuumState(device_model=self.device_model, api_type=self.api_type)
        self._consecutive_cloud_failures: int = 0
        self._base_poll_interval: timedelta | None = update_interval
        self._dock_idle_cancel: CALLBACK_TYPE | None = (
            None
        )
        self._segment_update_cancel: CALLBACK_TYPE | None = (
            None
        )
        self._pending_dock_status: str | None = None
        self.last_seen_segments: list[Any] | None = None
        # {cloud_mapid: name}, from biz/ MapDescription frames.
        self.last_seen_maps: dict[int, str] = {}
        # device_id is cloud-supplied; Store.path does not sanitize it.
        self._store = Store(hass, 1, f"{DOMAIN}.{_safe_storage_key(self.device_id)}")
        # A delayed map-state write is pending (see _schedule_map_state_save).
        self._map_state_save_armed = False
        self._map_data_chan_id: int | None = None
        self._map_data: MapData | None = None
        self._map_storage: TuyaMapStorage | None = None
        # DPS 125 "cid" at the last fetch: a signal, not a selector.
        self._fetched_map_cid: int | None = None
        # Map held with no cid: adopt the next rather than re-fetch.
        self._adopt_next_map_cid = False
        # async_load_storage runs AFTER the first DPS parse.
        self._storage_loaded = False
        self._robot_pixel: tuple[float, float] | None = None
        self._current_room: tuple[int, str | None] | None = None
        self._robot_trail: list[tuple[float, float]] = []
        # Per trail entry: 0 = cleaning, 1 = transit (0x67 only).
        self._robot_trail_types: list[int] = []
        # As sent: dock-relative 0.5 cm, the frame map growth spares.
        self._robot_trail_raw: list[tuple[int, int, int]] = []
        # Raw points the grid cannot hold; the first has no raw twin.
        self._trail_unplaced: int = 0
        # Replaced wholesale, never appended to.
        self._previous_trail: list[tuple[float, float]] = []
        self._dock_pixel: tuple[float, float] | None = None
        # While empty, _notify_map_* builds nothing.
        self._map_listeners: list[Callable[[dict[str, Any]], None]] = []
        self._map_flush_cancel: CALLBACK_TYPE | None = None
        self._last_map_event: float = 0.0
        self._map_pose_dirty: bool = False
        self._map_trail_reset: bool = False
        # The next event's "from"; re-baselined on first subscribe.
        self._map_trail_sent: int = 0
        self._map_sent_dock: tuple[float, float] | None = None
        # CONTENT signature: _map_data is replaced per frame.
        self._map_geometry_sig: tuple | None = None
        # Live m/m/i metadata, in the same 0.5 cm frame as the pose.
        self._legacy_room_polygons: dict[int, list[tuple[int, int]]] = {}
        # Off the stream; ts is wall-clock, vs the blob mtime.
        self._legacy_room_names: dict[int, str] = {}
        self._legacy_room_custom: dict[int, dict[str, int]] = {}
        self._legacy_rooms_ts: float = 0.0
        # Blob tag 9 / live 0x71; None until either has said.
        self.legacy_custom_clean_enabled: bool | None = None
        self._legacy_dock_pose: dict[str, int] | None = None
        # Last dock cell the STREAM placed; never the blob copy.
        self._legacy_dock_cell: tuple[float, float] | None = None
        # {channel: (shapes, epoch_s)}; a re-fetch must not revert an edit.
        self._legacy_live_geometry: dict[int, tuple[list[Any], float]] = {}
        self._legacy_map_param: dict[str, int] | None = None
        # The device's own 0x64 (w, h, origin_x, origin_y) while it differs from
        # ours; live coordinates difference against it.
        self._map_frame_divergence: tuple[int, int, int, int] | None = None
        self._param_refetch_ts: float = -_MAP_REFRESH_RETRY_COOLDOWN
        # 0x67 frame byte-offset; goes backwards on a re-stream.
        self._trail_prev_counter: int | None = None
        self._trail_reject_streak: int = 0
        self._dock_arrival_time: float | None = None
        self._last_robot_render: float = 0.0
        # Rendering is LAZY: on a camera read, not on a map change.
        self.map_image: bytes | None = None
        self._map_frame_dirty: bool = False
        # Bumped on frame CONTENT, not on render: the card's `?v=`.
        self.map_revision: int = 0
        # GEOMETRY only; clients key their static layer on it.
        self.map_geometry_revision: int = 0
        self._map_static_geometry: tuple[int, dict[str, Any]] | None = None
        self._tuya_mqtt: TuyaMobileMQTT | None = None
        self._tuya_mqtt_device_id44: str = random_device_id44()
        self._tuya_mqtt_refresh_cancel: CALLBACK_TYPE | None = None
        # The sid the subscriber connected with; the shared session may move on.
        self._tuya_mqtt_sid: str | None = None
        self._tuya_mqtt_lock = asyncio.Lock()
        self._tuya_session_thing: Any = None
        self._tuya_session_unsub: Callable[[], None] | None = None
        # DPS 121 keepalive; renews the live pose/trail window.
        self._map_keepalive_cancel: CALLBACK_TYPE | None = None
        self._map_keepalive_failures: int = 0
        self._map_freshness_cancels: list[CALLBACK_TYPE] = []
        self._map_freshness_failures: int = 0
        # None is 'unknown', not 'unchanged'.
        self._map_version: str | None = None
        self._render_task: asyncio.Task | None = None
        self._render_pending: bool = False
        # In memory so the 30 s save is a write, not read-modify.
        self._store_data: dict[str, Any] | None = None
        self._store_load_lock = asyncio.Lock()
        self._last_notified_error_code: int = 0
        self._sched_refresh_in_progress: bool = False
        self._sched_attempt_ts: float = -_SCHEDULE_REFRESH_RETRY_COOLDOWN
        # Set first in teardown; every await that can start something checks it.
        self._closing: bool = False
        # Bumped per novel map frame sent to the executor; stale results drop.
        self._biz_decode_seq: int = 0
        self._biz_applied_seq: int = 0
        self._connection_loss_cancel: CALLBACK_TYPE | None = None
        self._transport_available: bool = True
        self._auth_failures: int = 0
        # The MQTT credentials the current client uses.
        self._mqtt_credentials: dict[str, Any] | None = None
        self._mqtt_credentials_replacing: bool = False
        self._map_refresh_in_progress: bool = False
        self._map_attempt_cid: int | None = None
        self._map_attempt_ts: float = 0.0
        self.selected_schedule_id: int | str | None = None
        self._tuya_probe = TuyaCallProbe(self.device_name)

        if dps := device_info.get("dps"):
            self.data, _ = self._parse_dps(dps)
            # Prefer the device's own name (DPS 169) over a placeholder.
            if self.data.product_name and self.device_name.lower() in (
                "robovac", "eufy robovac", ""
            ):
                self.device_name = self.data.product_name

    def _parse_dps(self, dps: dict[str, Any]) -> tuple[VacuumState, dict[str, Any]]:
        """Dispatch DPS parsing based on api_type."""
        if self.api_type == "legacy":
            return update_state_legacy(self.data, dps, self.tuya_schema)
        return update_state(self.data, dps)

    def resolve_map_id(self) -> int:
        """Return the map id to use in room/zone clean commands.

        Priority: the user's override for the reported map, then their
        override for all maps (both from the options flow), then the last
        device-reported map id, then 1 (the firmware default for the first
        saved map). Before any map id is reported, a single per-map override
        is used instead of that 1. Overrides exist because some devices
        (T2080A) report their cloud map id, which room commands reject.
        """
        reported = self.data.map_id
        if reported in self.map_id_overrides:
            return self.map_id_overrides[reported]
        if self.map_id_overrides:
            # Warn even when the all-maps override applies: without an Active
            # Map sensor (Tuya transports) the log is the only place the user
            # sees which reported id needs a line.
            if reported:
                _LOGGER.warning(
                    "Map %s has no map id override; if room cleans fail, add a "
                    "'%s: <local id>' line to the device options",
                    reported,
                    reported,
                )
            else:
                _LOGGER.warning(
                    "No map id reported yet, so the per-map map id overrides "
                    "can't be matched"
                )
        if self.map_id_override:
            return self.map_id_override
        if not reported and len(self.map_id_overrides) == 1:
            # Nothing reported yet (e.g. just after setup): the user's only
            # per-map line is a better guess than the first-map default.
            return next(iter(self.map_id_overrides.values()))
        return reported or 1

    def build_device_command(self, command: str, **kwargs: Any) -> dict[str, Any]:
        """Build a DPS command dict appropriate for this device's API type."""
        if self.api_type == "legacy":
            if command == "zone_clean" and "zones_cm" in kwargs:
                kwargs["zones"] = self._zone_quads_to_blob_units(
                    kwargs.pop("zones_cm")
                )
                kwargs.pop("map_id", None)  # not part of the selectZonesClean doc
            return build_legacy_command(command, schema=self.tuya_schema, **kwargs)
        return build_command(command, api_type=self.api_type, **kwargs)

    def _zone_quads_to_blob_units(
        self, quads_cm: Sequence[Sequence[tuple[float, float]]]
    ) -> list[list[tuple[int, int]]]:
        """World-cm quads -> the map blob's 0.5 cm frame, for DPS 124."""
        md = self._map_data
        if md is None:
            return []
        res = md.resolution or 5
        out: list[list[tuple[int, int]]] = []
        for quad in quads_cm:
            corners: list[tuple[int, int]] = []
            for wx, wy in quad:
                col = (wx - md.origin_x) / res
                row_stored = (wy - md.origin_y) / res
                bx = col * _TUYA_UNITS_PER_CELL - md.origin_x
                by = (md.height - 1 - row_stored) * _TUYA_UNITS_PER_CELL - md.origin_y
                corners.append((round(bx), round(by)))
            out.append(corners)
        return out

    @property
    def trail_color(self) -> tuple[int, int, int]:
        """The configured trail colour as an RGB tuple (the option stores a list)."""
        entry = self.hass.config_entries.async_get_entry(self.entry_id)
        opts = entry.options if entry else {}
        return tuple(opts.get(CONF_TRAIL_COLOR, DEFAULT_TRAIL_COLOR))

    @property
    def snapshot_previous_trail(self) -> list[tuple[float, float]]:
        """The previous run to hand a client; empty unless it is all there is."""
        if self._robot_trail or self.data.activity in _ACTIVE_ACTIVITIES:
            return []
        return self._previous_trail

    def _blob_units_to_shapes_cm(
        self, shapes: list[list[tuple[int, int]]]
    ) -> list[list[tuple[float, float]]]:
        """The map blob's 0.5 cm frame -> world cm, for geometry pushed live."""
        md = self._map_data
        if md is None:
            return []
        res = md.resolution or 5
        out: list[list[tuple[float, float]]] = []
        for shape in shapes:
            points: list[tuple[float, float]] = []
            for bx, by in shape:
                column = (bx + md.origin_x) / _TUYA_UNITS_PER_CELL
                row = md.height - 1 - (by + md.origin_y) / _TUYA_UNITS_PER_CELL
                points.append(
                    (md.origin_x + column * res, md.origin_y + row * res)
                )
            out.append(points)
        return out

    @property
    def profile(self) -> DeviceProfile:
        """Return this device's consumable and capability profile."""
        return get_device_profile(self.device_model, self.api_type)

    @property
    def legacy_fan_speeds(self) -> list[str]:
        """Suction levels this legacy device accepts."""
        speeds = self.tuya_schema.get(LEGACY_DPS_MAP["CLEAN_SPEED"], {}).get("range")
        return list(speeds) if speeds else list(LEGACY_CLEAN_SPEEDS)

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info."""
        info = DeviceInfo(
            identifiers={(DOMAIN, self.device_id)},
            name=self.device_name,
            manufacturer="Eufy",
            model=self.device_model,
            serial_number=self.serial_number,
            sw_version=self.firmware_version,
        )
        if mac := self.data.device_mac:
            info["connections"] = {(CONNECTION_NETWORK_MAC, format_mac(mac))}
        return info

    async def initialize(self) -> None:
        """Initialize connection to the device."""
        _LOGGER.debug("Initializing %s via %s", self.device_name, self.connection_type)
        if self.connection_type == "cloud":
            await self._initialize_cloud()
        elif self.connection_type == "local":
            await self._initialize_local()
        else:
            await self._initialize_mqtt()

        has_tuya_client = (
            getattr(self.eufy_login, "tuya_thing_client", None)
            or getattr(self.eufy_login, "tuya_client", None)
        )
        if has_firmware_api(self) and self.config_entry:
            self.config_entry.async_create_background_task(
                self.hass,
                self.async_check_firmware_updates(),
                f"{DOMAIN}_{self.device_id}_fw_check",
            )
        if has_tuya_client and self.config_entry:
            # Legacy schedules live in Tuya cloud, not on any DPS.
            if self.api_type == "legacy":
                self.config_entry.async_create_background_task(
                    self.hass,
                    self.async_refresh_legacy_schedules(),
                    f"{DOMAIN}_{self.device_id}_sched_fetch",
                )
                # Live pose/trail ride Tuya mobile-MQTT; no DPS carries it.
                self.config_entry.async_create_background_task(
                    self.hass,
                    self.async_start_legacy_pose_stream(),
                    f"{DOMAIN}_{self.device_id}_pose_stream",
                )

    async def _fall_back_to_cloud(self) -> None:
        """Switch this coordinator to cloud polling and initialize it."""
        self.connection_type = "cloud"
        self.update_interval = _CLOUD_POLL_INTERVAL
        self._base_poll_interval = _CLOUD_POLL_INTERVAL
        await self._initialize_cloud()

    async def _initialize_local(self) -> None:
        """Initialize a direct local-Tuya socket, falling back to cloud polling."""
        if not self._local_key or not self._local_host:
            _LOGGER.warning(
                "Local Tuya requested for %s but local_key/host missing; "
                "falling back to cloud polling",
                self.device_name,
            )
            await self._fall_back_to_cloud()
            return

        _LOGGER.info(
            "Initializing local Tuya for %s (protocol %s)",
            self.device_name, self._local_version,
        )
        client = LocalTuyaClient(
            device_id=self.device_id,
            local_key=self._local_key,
            host=self._local_host,
            version=self._local_version,
        )
        self.client = client
        if hasattr(client, "set_on_dps"):
            client.set_on_dps(self._handle_dps)
        else:
            client.set_on_message(self._handle_mqtt_message)
        try:
            await client.connect()
        except (LocalTuyaError, OSError, TimeoutError) as e:
            _LOGGER.warning(
                "Local Tuya connect failed for %s (%s); falling back to cloud polling",
                self.device_name, e,
            )
            await self._async_drop_client()
            await self._fall_back_to_cloud()
            return
        try:
            # connect() probes protocol versions; persist what worked.
            if client.version != self._local_version:
                _LOGGER.info(
                    "Local Tuya for %s negotiated protocol %s; storing it in options",
                    self.device_name, client.version,
                )
                self._local_version = client.version
                self._persist_local_version(client.version)
            # After connect(): trail restore keys on the activity status() sets.
            await self.async_load_storage()
            await self.async_ensure_legacy_map()
        except BaseException:
            # The listener and heartbeat tasks run until disconnect().
            await self._async_drop_client()
            raise

    def _persist_local_version(self, version: float) -> None:
        """Write an auto-detected protocol version into this device's options."""
        entry = self.hass.config_entries.async_get_entry(self.entry_id)
        if entry is None:
            return
        devices = {
            dev_id: dict(override)
            for dev_id, override in entry.options.get(CONF_LOCAL_DEVICES, {}).items()
        }
        device = devices.setdefault(self.device_id, {})
        if device.get(CONF_LOCAL_VERSION) == version:
            return
        device[CONF_LOCAL_VERSION] = version
        self.hass.config_entries.async_update_entry(
            entry, options={**entry.options, CONF_LOCAL_DEVICES: devices}
        )

    async def _async_drop_client(self) -> None:
        """Disconnect and forget the transport client; never raises."""
        client, self.client = self.client, None
        if client is None:
            return
        try:
            await client.disconnect()
        except Exception as e:  # noqa: BLE001 - cleanup must not mask the cause
            _LOGGER.debug("Error disconnecting %s: %s", self.device_name, e)

    async def _initialize_mqtt(self) -> None:
        """Initialize MQTT connection."""
        try:
            if not self.eufy_login.mqtt_credentials:
                await self.eufy_login.checkLogin()

            creds = self.eufy_login.mqtt_credentials
            if not creds:
                raise UpdateFailed("Failed to retrieve MQTT credentials")

            # Before connect(): pushes are parsed against the stored state.
            await self.async_load_storage()
            await self._async_connect_mqtt_at_setup(creds)

        except BaseException as e:
            _LOGGER.error(
                "Failed to initialize MQTT coordinator for %s: %s", self.device_name, e
            )
            # The client wrote its certificate and key to temp files.
            await self._async_drop_client()
            raise

    async def _async_connect_mqtt(self, creds: dict[str, Any]) -> EufyCleanClient:
        """Create the MQTT client for ``creds``, connect it and return it."""
        self._mqtt_credentials = creds
        client = self.client = EufyCleanClient(
            device_id=self.device_id,
            user_id=creds["user_id"],
            app_name=creds["app_name"],
            thing_name=creds["thing_name"],
            access_key="",
            ticket="",
            openudid=self.eufy_login.openudid,
            certificate_pem=creds["certificate_pem"],
            private_key=creds["private_key"],
            device_model=self.device_model,
            endpoint=creds["endpoint_addr"],
        )

        client.set_on_message(self._handle_mqtt_message)
        client.set_on_biz_message(self._handle_biz_message)
        if hasattr(client, "set_connection_listener"):
            client.set_connection_listener(self._on_connection_change)
        await client.connect()
        return client

    async def _async_connect_mqtt_at_setup(self, creds: dict[str, Any]) -> None:
        """Connect; a certificate the broker rejects in the TLS handshake is
        replaced once (EufyLogin bounds the logins) and the connect retried.

        With TLS 1.3 the alert comes after connect() and is counted like a
        refused CONNACK instead.
        """
        for attempt in range(2):
            try:
                await self._async_connect_mqtt(creds)
                return
            except ssl.SSLError as err:
                if not is_certificate_rejection(err):
                    raise
                _LOGGER.warning(
                    "%s: the MQTT broker rejected the client certificate (%s)",
                    self.device_name, err,
                )
                await self._async_drop_client()
                # also drops the rejected ones from the cache
                fresh = await self._async_new_mqtt_credentials(creds)
                if fresh is None or attempt:
                    raise
                creds = fresh

    async def _async_save_auth_cache(self) -> None:
        """Persist the account's auth cache (no-op without a config entry)."""
        cache = self.eufy_login.auth_cache
        if cache is not None and self.config_entry is not None:
            await AuthStore(self.hass, self.entry_id).async_save(cache)

    async def _async_new_mqtt_credentials(
        self, rejected: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Credentials to replace ``rejected`` with, or None for none now.

        A refused account login starts re-authentication.
        """
        try:
            fresh = await self.eufy_login.replace_rejected_mqtt_credentials(
                rejected, self._async_save_auth_cache
            )
        except EufyLoginError as err:
            _LOGGER.warning(
                "%s: the Eufy login was refused (%s); re-authentication needed",
                self.device_name, err,
            )
            if self.config_entry is not None:
                self.config_entry.async_start_reauth(self.hass)
            return None
        return self.eufy_login.mqtt_credentials if fresh else None

    async def _async_replace_rejected_credentials(self) -> None:
        """Reconnect with new MQTT credentials when the broker keeps rejecting ours."""
        rejected = self._mqtt_credentials
        try:
            if rejected is None:
                return
            creds = await self._async_new_mqtt_credentials(rejected)
            if not creds or self._is_closing():
                return
            old = self.client
            if old is not None and hasattr(old, "set_connection_listener"):
                # its disconnect must not count against the new credentials
                old.set_connection_listener(None)
            await self._async_drop_client()
            self._auth_failures = 0
            try:
                client = await self._async_connect_mqtt(creds)
            except Exception as err:  # noqa: BLE001 - setup retries the transport
                await self._async_drop_client()
                if self._is_closing():
                    return
                _LOGGER.warning(
                    "%s: reconnecting with new MQTT credentials failed (%s); "
                    "reloading the entry",
                    self.device_name, err,
                )
                if self.config_entry is not None:
                    self.hass.config_entries.async_schedule_reload(self.entry_id)
                return
            if self._is_closing():
                # teardown may have run while connect() did; the client's
                # disconnect() does nothing until connect() has returned
                if self.client is client:
                    self.client = None
                try:
                    await client.disconnect()
                except Exception as err:  # noqa: BLE001 - cleanup must not raise
                    _LOGGER.debug("Error disconnecting %s: %s", self.device_name, err)
        finally:
            self._mqtt_credentials_replacing = False

    async def _initialize_cloud(self) -> None:
        """Initialize cloud polling connection."""
        _LOGGER.info(
            "Initializing cloud polling for %s (interval: %s)",
            self.device_name,
            _CLOUD_POLL_INTERVAL,
        )
        await self.async_load_storage()
        await self.async_ensure_legacy_map()

    @callback
    def _spawn(self, coro: Any, name: str) -> None:
        """Run ``coro`` as a task the config entry cancels on unload."""
        if self._is_closing():
            coro.close()
            return
        entry = self.config_entry
        if entry is not None and hasattr(entry, "async_create_background_task"):
            entry.async_create_background_task(
                self.hass, coro, f"{DOMAIN}_{self.device_id}_{name}"
            )
            return
        task = self.hass.async_create_task(coro, eager_start=False)
        if not isinstance(task, asyncio.Task):
            coro.close()

    def _is_closing(self) -> bool:
        """Teardown has started; a method so the flag is re-read after every await."""
        return self._closing

    def _maybe_refresh_legacy_schedules(self) -> None:
        """Fetch legacy cleaning schedules if not yet loaded, at most every 5 min."""
        if self.api_type != "legacy" or "schedules" in self.data.received_fields:
            return
        if self._sched_refresh_in_progress or self._is_closing():
            return
        if not (
            getattr(self.eufy_login, "tuya_thing_client", None)
            or getattr(self.eufy_login, "tuya_client", None)
        ):
            return
        now = time.monotonic()
        if now - self._sched_attempt_ts < _SCHEDULE_REFRESH_RETRY_COOLDOWN:
            return
        self._sched_attempt_ts = now
        self._spawn(self.async_refresh_legacy_schedules(), "sched_fetch")

    def _maybe_refresh_legacy_map(self, state: VacuumState) -> None:
        """Re-fetch the map in the background when the device changes map."""
        if self.api_type != "legacy" or not state.map_id:
            return
        if not self._storage_loaded:
            # .storage is unread, so every cid looks new.
            return
        if state.map_id == self._fetched_map_cid:
            return
        if self._adopt_next_map_cid:
            # We hold this map, we just had no cid to name it by.
            self._adopt_next_map_cid = False
            self._fetched_map_cid = state.map_id
            return
        # _fetched_map_cid is set only on success, so a failing download would
        # re-spawn a task per message.
        if self._map_refresh_in_progress:
            return
        # A new cid passes straight through; a failing one waits.
        now = time.monotonic()
        if (
            state.map_id == self._map_attempt_cid
            and now - self._map_attempt_ts < _MAP_REFRESH_RETRY_COOLDOWN
        ):
            return
        self._map_attempt_cid = state.map_id
        self._map_attempt_ts = now
        self._spawn(self.async_refresh_legacy_map(), "map_refresh")

    def _ensure_map_storage(self) -> TuyaMapStorage | None:
        """The Tuya storage client for this device, built once, or None."""
        if self.api_type != "legacy":
            return None
        if self._map_storage is None:
            tuya_client = getattr(
                self.eufy_login, "tuya_thing_client", None
            ) or getattr(self.eufy_login, "tuya_client", None)
            if tuya_client is None:
                return None
            self._map_storage = TuyaMapStorage(
                tuya_client,
                async_get_clientsession(self.hass),
                run_in_executor=self.hass.async_add_executor_job,
            )
        return self._map_storage

    async def async_ensure_legacy_map(self) -> bool:
        """Startup map load: download the blob only when it is not the one we hold."""
        if self.api_type != "legacy":
            return False
        if self._map_data is None or self._map_version is None:
            return await self.async_refresh_legacy_map()
        if not self.data.rooms:
            # The blob's room list is what makes rooms selectable.
            return await self.async_refresh_legacy_map()
        if self.data.map_id and self._fetched_map_cid is not None and (
            self.data.map_id != self._fetched_map_cid
        ):
            # A different map; the version token cannot answer that.
            return await self.async_refresh_legacy_map()
        storage = self._ensure_map_storage()
        if storage is None:
            return False
        try:
            version = await storage.async_map_version(self.device_id)
        except Exception:  # noqa: BLE001 - a failed check just means "download"
            _LOGGER.debug("%s: startup map version check failed",
                          self.device_name, exc_info=True)
            version = None
        if version is None or version != self._map_version:
            return await self.async_refresh_legacy_map()
        _LOGGER.debug(
            "%s: restored map is current (mtime %s); skipping the blob download",
            self.device_name, _version_token_mtime(version),
        )
        # Adopt the first cid rather than re-download a map we hold.
        self._adopt_next_map_cid = self._fetched_map_cid is None
        self._rerender_map()
        return True

    async def async_refresh_legacy_map(self, map_id: int | None = None) -> bool:
        """Fetch this legacy device's map from Tuya cloud storage."""
        if self._ensure_map_storage() is None:
            return False

        # The guard must span the INSTALL too, or a concurrent trigger installs
        # the older blob under the newer version.
        if self._map_refresh_in_progress:
            return False
        self._map_refresh_in_progress = True
        try:
            return await self._async_install_legacy_map(map_id)
        finally:
            self._map_refresh_in_progress = False

    async def _async_install_legacy_map(self, map_id: int | None) -> bool:
        """Download and install one legacy map blob. Serialised by its caller."""
        storage = self._map_storage
        if storage is None:
            return False
        tuya_map = await storage.async_fetch_map(self.device_id, map_id)
        if tuya_map is None or self._is_closing():
            return False

        # With no cid yet, arm the adopt flag or the first reads as a change.
        if self.data.map_id:
            self._fetched_map_cid = self.data.map_id
            self._adopt_next_map_cid = False
        else:
            self._adopt_next_map_cid = True
        # Seed change-detection from the listing served here.
        # Per-cell Python; keep it off the event loop.
        map_data = await self.hass.async_add_executor_job(map_data_from_tuya_map, tuya_map)
        if self._is_closing():
            return False
        self._map_version = storage.last_map_version
        self._set_map_data(map_data)
        # The blob has no outlines; a re-fetch would drop the stream's.
        self._apply_legacy_room_polygons()
        # ...and can be older than the zones just edited.
        self._carry_live_geometry_onto(map_data)
        # The only dock anchor until a live pose arrives.
        if map_data.dock_pixel is not None:
            self._dock_pixel = map_data.dock_pixel
            self._notify_map_pose()
        # ...but stale once 0x75 arrives, and the pose hangs off it.
        self._apply_legacy_dock_pose()
        rooms = tuya_map.as_entity_rooms()
        if rooms != self.data.rooms:
            self.data = replace(self.data, rooms=rooms)
            self.async_update_listeners()
            async_dispatcher_send(self.hass, f"{DOMAIN}_{self.device_id}_rooms_updated")
        # Also carried live by 0x71; the newer wins.
        if self.legacy_custom_clean_enabled is None or (
            not self._live_rooms_are_newer_than_blob()
        ):
            self.legacy_custom_clean_enabled = tuya_map.custom_clean_enabled
        # ...and its rows and names can lag, like the zones.
        self._carry_live_rooms_onto(map_data)
        # _set_map_data published geometry BEFORE the carry-overs.
        self._notify_map_geometry()
        self._rerender_map()
        _LOGGER.info(
            "%s: loaded map %d from Tuya storage with %d rooms",
            self.device_name, tuya_map.map_id, len(rooms),
        )
        return True

    async def async_start_legacy_pose_stream(self) -> None:
        """Start the Tuya mobile-MQTT subscriber for the live robot pose."""
        if self.api_type != "legacy":
            return
        thing = getattr(self.eufy_login, "tuya_thing_client", None)
        if thing is None or self._is_closing():
            return
        try:
            if not getattr(thing, "sid", None):
                await thing.login()
            await self._connect_tuya_mqtt(thing)
        except Exception:  # noqa: BLE001
            _LOGGER.debug("legacy pose stream start failed for %s",
                          self.device_name, exc_info=True)
        if self._is_closing():
            return
        # Armed even after a failure: this timer is the only retry.
        if self._tuya_mqtt_refresh_cancel is None:
            self._tuya_mqtt_refresh_cancel = async_track_time_interval(
                self.hass, self._async_refresh_legacy_pose_stream,
                _TUYA_SESSION_REFRESH_INTERVAL,
            )

    async def _connect_tuya_mqtt(self, thing: Any, only_if_stale: bool = False) -> bool:
        """Build the CONNECT params from the Thing session and (re)connect.

        Returns whether a subscriber was started. ``only_if_stale`` reconnects
        only a running subscriber whose sid the session has replaced. Arms the
        DPS 121 keepalive with the first one, whichever path starts it.
        """
        self._follow_tuya_session(thing)
        # Serialised: a session change can land while a connect awaits stop().
        async with self._tuya_mqtt_lock:
            if only_if_stale and (
                self._tuya_mqtt is None or self._tuya_mqtt_sid == thing.sid
            ):
                return False
            params = build_connect_params(
                thing, self.device_id, self._tuya_mqtt_device_id44
            )
            if params is None:
                _LOGGER.debug(
                    "legacy pose stream: incomplete session (no partnerId/sid) for %s",
                    self.device_name,
                )
                return False
            if self._is_closing():
                return False
            if self._tuya_mqtt is not None:
                # stop() joins paho's network thread; never on the loop.
                previous, self._tuya_mqtt = self._tuya_mqtt, None
                await self.hass.async_add_executor_job(previous.stop)
                if self._is_closing():
                    return False
            self._tuya_mqtt_sid = thing.sid
            self._tuya_mqtt = TuyaMobileMQTT(
                params,
                on_pose=self._on_legacy_pose_threadsafe,
                on_trail=self._on_legacy_trail_threadsafe,
                on_meta=self._on_legacy_meta_threadsafe,
            )
            self._tuya_mqtt.start()
        if self._map_keepalive_cancel is None:
            self._map_keepalive_cancel = async_track_time_interval(
                self.hass, self._async_legacy_map_keepalive,
                _LEGACY_MAP_KEEPALIVE_INTERVAL,
            )
        return True

    def _follow_tuya_session(self, thing: Any) -> None:
        """Reconnect the subscriber whenever the shared Thing session changes sid."""
        if thing is self._tuya_session_thing or self._is_closing():
            return
        if self._tuya_session_unsub is not None:
            self._tuya_session_unsub()
        self._tuya_session_thing = thing
        self._tuya_session_unsub = thing.add_session_listener(
            partial(self._on_tuya_session_changed, thing)
        )

    @callback
    def _on_tuya_session_changed(self, thing: Any) -> None:
        """Another login (any robot's refresh, a request's retry) replaced the sid."""
        if self._is_closing() or self._tuya_mqtt is None:
            return
        self._spawn(
            self._connect_tuya_mqtt(thing, only_if_stale=True), "tuya_mqtt_resync"
        )

    async def _async_refresh_legacy_pose_stream(self, _now: Any = None) -> None:
        """Renew the shared Thing session and keep the pose subscriber on it (timer)."""
        thing = getattr(self.eufy_login, "tuya_thing_client", None)
        if thing is None or self._is_closing():
            return
        try:
            # force: this timer exists for a NEW sid, unless another robot's
            # tick renewed the shared session recently.
            await thing.login(force=True, min_age=_TUYA_SESSION_MIN_AGE)
            await self._connect_tuya_mqtt(
                thing, only_if_stale=self._tuya_mqtt is not None
            )
        except Exception:  # noqa: BLE001
            _LOGGER.debug("legacy pose stream refresh failed for %s",
                          self.device_name, exc_info=True)

    @callback
    def _cancel_legacy_map_freshness_checks(self) -> None:
        """Drop any armed post-clean freshness checks."""
        for cancel in self._map_freshness_cancels:
            cancel()
        self._map_freshness_cancels = []

    @callback
    def _schedule_legacy_map_freshness_checks(self) -> None:
        """Arm the post-clean stored-map freshness checks (legacy devices only)."""
        if self.api_type != "legacy":
            return
        self._cancel_legacy_map_freshness_checks()
        # A fresh clean must not inherit a parked failure count.
        self._map_freshness_failures = 0
        for delay in _LEGACY_MAP_POST_CLEAN_CHECKS:
            self._map_freshness_cancels.append(
                async_call_later(self.hass, delay, self._async_legacy_map_freshness)
            )

    async def _async_legacy_map_freshness(self, _now: Any = None) -> None:
        """Re-fetch the basemap when the device has rewritten it."""
        if self.api_type != "legacy":
            return
        if self._map_freshness_failures >= _LEGACY_MAP_FRESHNESS_MAX_FAILURES:
            return
        if self._map_storage is None or self._map_refresh_in_progress:
            return
        try:
            version = await self._map_storage.async_map_version(self.device_id)
        except Exception:  # noqa: BLE001 - best-effort, never disturbs the clean
            self._map_freshness_failures += 1
            _LOGGER.debug(
                "%s: map freshness check failed (%d/%d)",
                self.device_name,
                self._map_freshness_failures,
                _LEGACY_MAP_FRESHNESS_MAX_FAILURES,
                exc_info=True,
            )
            return
        self._map_freshness_failures = 0
        # None means "could not tell", never "unchanged".
        if self._map_frame_divergence is not None:
            # An "unchanged" listing does not fix a diverged grid.
            _LOGGER.debug(
                "%s: map frame still diverged (device %s); fetching regardless of"
                " mtime %s",
                self.device_name, self._map_frame_divergence,
                _version_token_mtime(version),
            )
            await self.async_refresh_legacy_map()
            return
        if version is None or version == self._map_version:
            _LOGGER.debug(
                "%s: map freshness tick — %s (cid %s); no download",
                self.device_name,
                "version unknown" if version is None else "unchanged",
                self.data.map_id,
            )
            return
        _LOGGER.debug(
            "%s: stored map changed (mtime %s -> %s) at cid %s; re-fetching",
            self.device_name, _version_token_mtime(self._map_version),
            _version_token_mtime(version), self.data.map_id,
        )
        # Recorded only on success, so a failed tick retries.
        await self.async_refresh_legacy_map()

    async def _async_legacy_map_keepalive(self, _now: Any = None) -> None:
        """Renew the device's live pose/trail publish window (DPS 121)."""
        if self.api_type != "legacy" or self._tuya_mqtt is None:
            return
        if self.data.activity != "cleaning":
            # Re-arm: the cap stops a storm, it is not an off switch.
            self._map_keepalive_failures = 0
            return
        if self._map_keepalive_failures >= _LEGACY_MAP_KEEPALIVE_MAX_FAILURES:
            return
        if getattr(self.eufy_login, "tuya_client", None) is None:
            return
        command = build_map_keepalive(self.device_id, self.tuya_schema)
        if not command:
            return
        try:
            await self.eufy_login.sendCloudCommand(self.device_id, command)
        except Exception:  # noqa: BLE001 - best-effort, never disturbs the clean
            self._map_keepalive_failures += 1
            _LOGGER.debug(
                "%s: map keepalive failed (%d/%d)",
                self.device_name,
                self._map_keepalive_failures,
                _LEGACY_MAP_KEEPALIVE_MAX_FAILURES,
                exc_info=True,
            )
            return
        self._map_keepalive_failures = 0

    def _on_legacy_pose_threadsafe(self, x: int, y: int, theta: int) -> None:
        """paho network-thread callback → marshal onto the event loop."""
        self.hass.loop.call_soon_threadsafe(self._on_legacy_pose, x, y, theta)

    def _legacy_pose_to_pixel(self, x: int, y: int) -> tuple[float, float] | None:
        """Convert a legacy live pose to a map pixel; ``None`` when off-grid.

        ``(x, y)`` is dock-relative 0.5 cm (one cell = 5 cm); the map frame is dock
        cell + ``_LEGACY_POSE_DOCK_OFFSET`` + scaled pose, row negated for the
        blob's bottom-up planes.
        """
        if self._map_data is None or self._map_data.dock_pixel is None:
            return None
        dock_col, dock_row = self._map_data.dock_pixel
        off_col, off_row = _LEGACY_POSE_DOCK_OFFSET
        px = dock_col + off_col + x / _TUYA_UNITS_PER_CELL
        py = dock_row + off_row - y / _TUYA_UNITS_PER_CELL
        if 0 <= px < self._map_data.width and 0 <= py < self._map_data.height:
            return px, py
        return None

    @callback
    def _on_legacy_pose(self, x: int, y: int, theta: int) -> None:
        """Place the decoded live pose as the robot dot (legacy/Tuya devices)."""
        if self._is_closing():
            return
        robot_px = self._legacy_pose_to_pixel(x, y)
        if robot_px is None:
            return
        if robot_px != self._robot_pixel:
            self._robot_pixel = robot_px
            self._notify_map_pose()
            now = time.monotonic()
            if now - self._last_robot_render >= 2.0 and self._map_data is not None:
                self._last_robot_render = now
                self._rerender_map()

    def _on_legacy_meta_threadsafe(self, channel: int, body: bytes) -> None:
        """paho network-thread callback -> marshal onto the event loop."""
        self.hass.loop.call_soon_threadsafe(self._on_legacy_meta, channel, body)

    @callback
    def _on_legacy_meta(self, channel: int, body: bytes) -> None:
        """Consume a map-metadata frame from the ``m/m/i`` stream."""
        if self._map_data is None or self._is_closing():
            return
        try:
            if channel == MMI_ROOM_NAME:
                names = decode_room_names(body)
                # Room id 0 is real: test the dict, not a key's truthiness.
                if names:
                    self._legacy_room_names = names
                    self._legacy_rooms_ts = time.time()
                    if names != self._map_data.room_names:
                        self._map_data.room_names = names
                        _LOGGER.debug("legacy meta: %d live room names for %s",
                                      len(names), self.device_name)
                        self._notify_map_geometry()
                    # The map layer is not the room LIST; renames reach both.
                    self._apply_legacy_rooms()
            elif channel == MMI_CUSTOM_ROOM:
                self._remember_legacy_room_custom(decode_room_custom(body))
            elif channel == MMI_GLOBAL_ROOM:
                # 0x73 carries only {roomId, cleanOrder}: never replace.
                self._remember_legacy_room_custom({
                    rid: {"id": rid, "clean_order": order}
                    for rid, order in decode_room_clean_order(body).items()
                })
            elif channel == MMI_CUSTOM_ROOMS_ENABLED:
                enabled = decode_custom_rooms_enabled(body)
                if enabled is not None:
                    self._legacy_rooms_ts = time.time()
                    if enabled != self.legacy_custom_clean_enabled:
                        self.legacy_custom_clean_enabled = enabled
                        _LOGGER.debug(
                            "legacy meta: per-room settings %s for %s",
                            "enabled" if enabled else "disabled", self.device_name,
                        )
            elif channel == MMI_ROOM:
                polys = decode_room_polygons(body)
                if polys and polys != self._legacy_room_polygons:
                    self._legacy_room_polygons = polys
                    self._apply_legacy_room_polygons()
                    _LOGGER.debug("legacy meta: %d room polygons (%d verts) for %s",
                                  len(polys), sum(len(p) for p in polys.values()),
                                  self.device_name)
            elif channel in (
                MMI_FORBIDDEN_ZONES, MMI_BAN_MOP_ZONES, MMI_VIRTUAL_WALL
            ):
                self._apply_live_restricted_geometry(channel, body)
            elif channel == MMI_DOCK_POSE:
                dock = decode_dock_pose(body)
                if dock is not None:
                    self._legacy_dock_pose = dock
                    self._apply_legacy_dock_pose()
            elif channel == MMI_PARAM:
                param = decode_map_param(body)
                if param is not None:
                    self._legacy_map_param = param
                    # _legacy_live_cell differences against this frame.
                    self._apply_legacy_dock_pose()
                    self._check_legacy_map_param()
        except Exception:  # noqa: BLE001
            _LOGGER.debug("legacy meta: channel 0x%02x failed for %s",
                          channel, self.device_name, exc_info=True)

    def _legacy_live_cell(self, x: int, y: int) -> tuple[int, int] | None:
        """A live map-relative 0.5 cm coordinate as a cell of the grid we HOLD.

        The device origin moves as SLAM grows the map while our grid lags, so the
        two frames are differenced via 0x64 (assumed equal until it arrives). Row
        is flipped into the bottom-up plane ``render_map_png`` flips back.
        """
        md = self._map_data
        if md is None or not md.height:
            return None
        param = self._legacy_map_param
        d_x = (md.origin_x - param["origin_x"]) if param else 0
        d_y = (md.origin_y - param["origin_y"]) if param else 0
        return (
            round((x + d_x) / _TUYA_UNITS_PER_CELL),
            md.height - 1 - round((y + d_y) / _TUYA_UNITS_PER_CELL),
        )

    def _apply_legacy_dock_pose(self) -> bool:
        """Place the dock from the LIVE 0x75 frame instead of the blob's stale copy.

        0x75 is map-relative 0.5 cm with no origin term, so it converts via
        ``_legacy_live_cell``. The pose transform hangs off ``dock_pixel``, so a
        stale dock misplaces the robot and every trail point; a dock off the grid
        means the grid is stale, so keep it and let the param check re-fetch.
        """
        md = self._map_data
        dock = self._legacy_dock_pose
        if md is None or dock is None or not md.height:
            return False
        cell = self._legacy_live_cell(dock["x"], dock["y"])
        if cell is None:
            return False
        if not (0 <= cell[0] < md.width and 0 <= cell[1] < md.height):
            return False
        # 0x64 carries the origin and 0x75 does not, so a growth between the two
        # is read in the wrong frame once.
        previous = self._legacy_dock_cell
        if (
            previous is not None
            and _px_dist(previous, cell) > _LEGACY_DOCK_MAX_SHIFT_CELLS
        ):
            _LOGGER.debug(
                "legacy meta: implausible live dock shift of %.0f cells for %s;"
                " ignoring as a map-frame mismatch",
                _px_dist(previous, cell), self.device_name,
            )
            return False
        self._legacy_dock_cell = cell
        if cell == md.dock_pixel and cell == self._dock_pixel:
            return False
        _LOGGER.debug("legacy meta: live dock placed for %s", self.device_name)
        md.dock_pixel = cell
        self._dock_pixel = cell
        if self._robot_trail_raw:
            # trail points are dock-relative
            self._rebuild_trail_from_raw()
            self._notify_map_trail_reset()
        self._notify_map_pose()
        self._rerender_map()
        return True

    def _check_legacy_map_param(self) -> bool:
        """Notice from the live 0x64 that the grid we hold is the wrong shape."""
        md = self._map_data
        param = self._legacy_map_param
        if md is None or param is None:
            return False
        live = (param["width"], param["height"], param["origin_x"], param["origin_y"])
        held = (md.width, md.height, md.origin_x, md.origin_y)
        if live == held:
            self._map_frame_divergence = None
            return False
        if live != self._map_frame_divergence:
            self._map_frame_divergence = live
            _LOGGER.debug(
                "%s: live map param %s != held %s (activity %s)",
                self.device_name, live, held, self.data.activity,
            )
        # Deliberately fetches DURING a clean: the map is rewritten at start.
        now = time.monotonic()
        if (
            self._map_refresh_in_progress
            or now - self._param_refetch_ts < _MAP_REFRESH_RETRY_COOLDOWN
        ):
            return False
        self._param_refetch_ts = now
        _LOGGER.debug(
            "%s: re-fetching the grid for live map param %s (held %s)",
            self.device_name, live, held,
        )
        self._spawn(self.async_refresh_legacy_map(), "map_refresh")
        return True

    def _apply_legacy_room_polygons(self) -> bool:
        """Re-project the cached 0x65 room outlines onto the current ``MapData``."""
        if self._map_data is None or not self._legacy_room_polygons:
            return False
        self._map_data.room_polygons = room_polygons_to_cells(
            self._legacy_room_polygons,
            origin_x=self._map_data.origin_x,
            origin_y=self._map_data.origin_y,
            height=self._map_data.height,
        )
        self._notify_map_geometry()
        return True

    def _remember_legacy_room_custom(self, table: dict[int, dict[str, int]]) -> bool:
        """Merge a live per-room settings table (0x70 / 0x73) and re-apply it."""
        if not table:
            return False
        for rid, entry in table.items():
            row = dict(self._legacy_room_custom.get(rid, {}))
            row.update(entry)
            self._legacy_room_custom[rid] = row
        self._legacy_rooms_ts = time.time()
        return self._apply_legacy_rooms()

    def _apply_legacy_rooms(self) -> bool:
        """Merge the live room tables (0x6a / 0x70 / 0x73) into ``data.rooms``."""
        names = {
            **(self._map_data.room_names if self._map_data else {}),
            **self._legacy_room_names,
        }
        custom = self._legacy_room_custom
        if not names and not custom:
            return False
        rooms = [dict(room) for room in self.data.rooms]
        known = {room.get("id") for room in rooms}
        rooms.extend(
            {"id": rid} for rid in sorted(set(names) | set(custom)) if rid not in known
        )
        for room in rooms:
            rid = room.get("id")
            if rid in names:
                room["name"] = names[rid]
            room.setdefault("name", f"Room {rid}")
            entry = (custom.get(rid) if rid is not None else None) or {}
            for key, default in (
                ("fan_speed", -1),
                ("water_level", -1),
                ("clean_times", 0),
                ("clean_order", 0),
            ):
                if key in entry:
                    room[key] = entry[key]
                else:
                    room.setdefault(key, default)
        if rooms == self.data.rooms:
            return False
        self.data = replace(self.data, rooms=rooms)
        self.async_update_listeners()
        async_dispatcher_send(self.hass, f"{DOMAIN}_{self.device_id}_rooms_updated")
        _LOGGER.debug("legacy meta: %d live rooms for %s",
                      len(rooms), self.device_name)
        return True

    def _live_rooms_are_newer_than_blob(self) -> bool:
        """Whether the stream's room tables postdate the blob we last fetched."""
        if not self._legacy_rooms_ts:
            return False
        written_at = _version_token_mtime(self._map_version)
        return written_at is None or self._legacy_rooms_ts > written_at

    def _carry_live_rooms_onto(self, md: MapData) -> None:
        """Re-apply the room tables a freshly fetched blob predates."""
        if not self._live_rooms_are_newer_than_blob():
            return
        if self._legacy_room_names:
            md.room_names = {**md.room_names, **self._legacy_room_names}
        if self._apply_legacy_rooms():
            _LOGGER.debug("%s: kept the live room table over the older blob copy",
                          self.device_name)

    def _apply_live_restricted_geometry(self, channel: int, body: bytes) -> None:
        """Install no-go zones / no-mop zones / virtual walls pushed on ``m/m/i``.

        A frame is the complete state of one category and replaces it wholesale.
        An empty body is IGNORED: on the wire a cleared category and a missing
        frame are identical, so a real clear is applied by ``async_set_nogo_zones``.
        """
        if self._map_data is None:
            return
        if channel == MMI_VIRTUAL_WALL:
            shapes = decode_virtual_walls(body)
        else:
            shapes = decode_forbidden_zones(body)
        if not shapes:
            return
        points_cm = self._blob_units_to_shapes_cm(shapes)
        self.remember_live_restricted_geometry(channel, points_cm)
        if not self._install_restricted_geometry(self._map_data, channel, points_cm):
            return
        _LOGGER.debug(
            "legacy meta: %d live %s for %s",
            len(points_cm), _RESTRICTED_LABELS[channel], self.device_name,
        )
        self._notify_map_geometry()
        self._rerender_map()

    @callback
    def remember_live_restricted_geometry(
        self, channel: int, points_cm: list[Any]
    ) -> None:
        """Record what this category holds NOW, and when we learned it."""
        self._legacy_live_geometry[channel] = (points_cm, time.time())

    @staticmethod
    def _install_restricted_geometry(
        md: MapData, channel: int, points_cm: list[Any]
    ) -> bool:
        """Write one restricted-geometry category onto ``md``. True if it changed."""
        if channel == MMI_VIRTUAL_WALL:
            walls = [
                (tuple(seg[0]), tuple(seg[1])) for seg in points_cm if len(seg) == 2
            ]
            if walls == md.virtual_walls:
                return False
            md.virtual_walls = walls
        elif channel == MMI_BAN_MOP_ZONES:
            if points_cm == md.ban_mop_zones:
                return False
            md.ban_mop_zones = [list(zone) for zone in points_cm]
        else:
            if points_cm == md.forbidden_zones:
                return False
            md.forbidden_zones = [list(zone) for zone in points_cm]
        return True

    def _carry_live_geometry_onto(self, md: MapData) -> None:
        """Re-apply live restricted geometry the freshly fetched blob predates."""
        written_at = _version_token_mtime(self._map_version)
        for channel, (points_cm, learned_at) in self._legacy_live_geometry.items():
            if written_at is not None and learned_at <= written_at:
                continue
            if self._install_restricted_geometry(md, channel, points_cm):
                _LOGGER.debug(
                    "%s: kept live %s over the older blob copy",
                    self.device_name, _RESTRICTED_LABELS[channel],
                )

    def _append_trail_point(self, cell: tuple[float, float], ptype: int = 0) -> None:
        """Append one trail point, keeping ``_robot_trail_types`` in lockstep."""
        self._robot_trail.append(cell)
        self._robot_trail_types.append(int(ptype))

    def _trail_types_for(self, start: int, end: int) -> list[int]:
        """Types for ``_robot_trail[start:end]``, padded to that exact length."""
        types = self._robot_trail_types
        return [types[i] if i < len(types) else 0 for i in range(start, end)]

    def _clear_trail(self) -> None:
        """Drop the live trail, its types and the raw points behind them."""
        self._robot_trail.clear()
        self._robot_trail_types.clear()
        self._robot_trail_raw.clear()
        self._trail_unplaced = 0

    def _trail_max_step(self) -> float:
        """The jump gate in CELLS of the map we currently hold."""
        res = (self._map_data.resolution or 5) if self._map_data else 5
        return _LEGACY_TRAIL_MAX_STEP_CM / res

    def _place_raw_trail_point(
        self, px: int, py: int, ptype: int, max_step: float
    ) -> str:
        """Place one raw 0x67 point on the current grid."""
        cell = self._legacy_pose_to_pixel(px, py)
        if cell is None:
            self._trail_unplaced += 1
            return "unplaced"
        # Against the last ACCEPTED point; after a rejection run, taken anyway.
        if (
            self._robot_trail
            and _px_dist(self._robot_trail[-1], cell) > max_step
            and self._trail_reject_streak < _LEGACY_TRAIL_MAX_REJECTS
        ):
            self._trail_reject_streak += 1
            return "rejected"
        self._trail_reject_streak = 0
        self._append_trail_point(cell, ptype)
        return "placed"

    def _rebuild_trail_from_raw(self) -> int:
        """Re-place the whole live trail from the points the device sent."""
        raw = list(self._robot_trail_raw)
        self._robot_trail.clear()
        self._robot_trail_types.clear()
        self._trail_reject_streak = 0
        self._trail_unplaced = 0
        max_step = self._trail_max_step()
        for px, py, ptype in raw:
            self._place_raw_trail_point(px, py, ptype, max_step)
        return self._trail_unplaced

    def _on_legacy_trail_threadsafe(
        self, counter: int, pts: list[tuple[int, int, int]]
    ) -> None:
        """paho network-thread callback → marshal onto the event loop."""
        self.hass.loop.call_soon_threadsafe(self._on_legacy_trail, counter, pts)

    @callback
    def _on_legacy_trail(self, counter: int, pts: list[tuple[int, int, int]]) -> None:
        """Accumulate the dense 0x67 cleaning trail (legacy/Tuya devices).

        Incremental live, but a dock/recharge re-streams the whole trail; those
        bursts are ignored (>=64 points, or ``counter`` going backwards). Points are
        dock-relative 0.5 cm in the 0x6c pose frame, so they need no anchoring.
        """
        if self._is_closing():
            return
        is_burst = len(pts) >= 64 and bool(self._robot_trail)
        is_reset = (
            self._trail_prev_counter is not None and counter < self._trail_prev_counter
        )
        self._trail_prev_counter = counter
        if is_burst or is_reset or self.data.activity not in _LEGACY_TRAIL_ACTIVITIES:
            _LOGGER.debug(
                "legacy trail: dropped %d-pt frame for %s (burst=%s reset=%s activity=%s)",
                len(pts), self.device_name, is_burst, is_reset, self.data.activity,
            )
            return
        max_step = self._trail_max_step()
        placed = unplaced = rejected = 0
        for px, py, ptype in pts:
            self._robot_trail_raw.append((int(px), int(py), int(ptype)))
            outcome = self._place_raw_trail_point(px, py, ptype, max_step)
            placed += outcome == "placed"
            unplaced += outcome == "unplaced"
            rejected += outcome == "rejected"
        changed = placed > 0
        if unplaced or rejected:
            _LOGGER.debug(
                "legacy trail: %d/%d pts unplaced (map=%s), %d jump-rejected; trail=%d"
                " of %d raw for %s",
                unplaced, len(pts), self._map_data is not None, rejected,
                len(self._robot_trail), len(self._robot_trail_raw), self.device_name,
            )
        if changed:
            self._notify_map_trail()
            now = time.monotonic()
            if now - self._last_robot_render >= 2.0 and self._map_data is not None:
                self._last_robot_render = now
                self._rerender_map()

    async def _tuya_timer_call(
        self, key: str, endpoints: tuple[str, ...], **fields: Any
    ) -> tuple[Any, Exception | None]:
        """Run one undocumented Tuya timer action, memoizing what worked."""

        async def attempt(candidate: tuple[str, str, str]) -> Any:
            client_attr, endpoint, shape = candidate
            client = getattr(self.eufy_login, client_attr, None)
            if client is None:
                return None
            return await client.request(
                endpoint, data=_timer_params(shape, self.device_id, **fields)
            )

        return await self._tuya_probe.run(
            key,
            [
                (client_attr, endpoint, shape)
                for client_attr in _TIMER_CLIENTS
                for endpoint in endpoints
                for shape in _TIMER_PARAM_SHAPES
            ],
            attempt,
        )

    async def async_refresh_legacy_schedules(self) -> bool:
        """Fetch legacy cleaning schedules from Tuya cloud."""
        if self.api_type != "legacy":
            return False

        if self._sched_refresh_in_progress:
            return False

        thing_client = getattr(self.eufy_login, "tuya_thing_client", None)
        tuya_client = getattr(self.eufy_login, "tuya_client", None)
        if thing_client is None and tuya_client is None:
            return False

        self._sched_refresh_in_progress = True
        try:
            raw, _ = await self._tuya_timer_call(
                "timer.list", ("tuya.m.timer.all.list",)
            )

            if raw is None:
                _LOGGER.debug(
                    "%s: legacy schedule fetch returned no response from Tuya cloud",
                    self.device_name,
                )
                return False

            schedules = parse_legacy_schedules(raw)

            if (
                schedules == self.data.schedules
                and "schedules" in self.data.received_fields
            ):
                return False

            self.data = replace(
                self.data,
                schedules=schedules,
                received_fields=self.data.received_fields | {"schedules"},
            )
            self.async_update_listeners()
            _LOGGER.debug(
                "%s: loaded %d cleaning schedule(s) from Tuya cloud",
                self.device_name,
                len(schedules),
            )
            return True
        finally:
            self._sched_refresh_in_progress = False

    def _resolve_schedule_id(self, schedule_id: int | str | None) -> int | str | None:
        """Resolve schedule_id from an explicit id, a label, or the selection."""
        if schedule_id is None or schedule_id == "" or schedule_id == "selected":
            return self.selected_schedule_id
        if isinstance(schedule_id, str):
            sched_str = schedule_id.strip()
            match = re.search(r"\[ID:\s*([^\]]+)\]", sched_str)
            if match:
                raw = match.group(1).strip()
                return int(raw) if raw.isdigit() else raw
            if sched_str.isdigit():
                return int(sched_str)
            return sched_str
        return schedule_id

    def _scalar_raw_entries(
        self, schedules: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """DPS 151 entries for ``schedules``.

        An entry unchanged but for ``enabled`` since the last DPS 151 report goes
        back as reported, so values the client has no name for survive; the rest
        are encoded. Raises ServiceValidationError on an entry that cannot be.
        """
        try:
            reported = {
                raw.get("id"): raw
                for raw in scalar_schedule_raw_entries(self.data.raw_dps.get("151") or {})
                if isinstance(raw, dict)
            }
        except (AttributeError, TypeError, ValueError):  # unreadable: encode all
            reported = {}
        entries = []
        for entry in schedules:
            enabled = bool(entry.get("enabled", True))
            raw = reported.get(entry.get("id"))
            if raw is not None and {
                **scalar_raw_to_schedule_entry(raw), "enabled": enabled
            } == {**entry, "enabled": enabled}:
                entries.append({**raw, "e": enabled})
                continue
            try:
                entries.append(schedule_entry_to_scalar_raw(entry))
            except ValueError as err:
                raise ServiceValidationError(
                    f"Schedule {entry.get('id')} on {self.device_name}: {err}"
                ) from err
        return entries

    async def _async_write_scalar_schedules(
        self, schedules: list[dict[str, Any]]
    ) -> None:
        """Send ``schedules`` as DPS 151 and keep them as the parser reads them back."""
        raw_entries = self._scalar_raw_entries(schedules)
        await self.async_send_command(
            {"151": build_scalar_schedule_payload(raw_entries)}
        )
        self.data = replace(
            self.data,
            schedules=[scalar_raw_to_schedule_entry(raw) for raw in raw_entries],
        )
        self.async_update_listeners()

    async def async_set_schedule_status(
        self, schedule_id: int | str | None, enabled: bool
    ) -> bool:
        """Enable or disable a cleaning schedule."""
        actual_id = self._resolve_schedule_id(schedule_id)
        if actual_id is None:
            raise HomeAssistantError(
                f"No schedule specified to update on {self.device_name}. "
                "Provide a schedule_id or select a schedule first."
            )

        if self.api_type == "legacy":
            thing_client = getattr(self.eufy_login, "tuya_thing_client", None)
            tuya_client = getattr(self.eufy_login, "tuya_client", None)
            if thing_client is None and tuya_client is None:
                raise HomeAssistantError(
                    f"Cannot update schedule on {self.device_name}: no Tuya cloud client available"
                )

            res, last_err = await self._tuya_timer_call(
                "timer.status",
                ("tuya.m.timer.set.status", "tuya.m.timer.status.set"),
                timerId=actual_id,
                status=1 if enabled else 0,
            )

            if res is None:
                err_msg = last_err or "No response from Tuya Cloud"
                raise HomeAssistantError(
                    f"Failed to update schedule status on {self.device_name}: {err_msg}"
                )
            await self.async_refresh_legacy_schedules()
            return True

        if self.api_type == "scalar":
            schedules = list(self.data.schedules or [])
            sid_int = int(actual_id) if str(actual_id).isdigit() else actual_id
            if not any(s.get("id") == sid_int for s in schedules):
                raise HomeAssistantError(
                    f"Schedule ID {actual_id} not found on {self.device_name}"
                )
            await self._async_write_scalar_schedules(
                [
                    {**s, "enabled": bool(enabled)} if s.get("id") == sid_int else s
                    for s in schedules
                ]
            )
            return True

        raise HomeAssistantError(
            f"Schedule editing is not supported on {self.device_name}"
        )

    async def async_delete_schedule(self, schedule_id: int | str | None = None) -> bool:
        """Delete a cleaning schedule."""
        actual_id = self._resolve_schedule_id(schedule_id)
        if actual_id is None:
            raise HomeAssistantError(
                f"No schedule specified to delete on {self.device_name}. "
                "Provide a schedule_id or select a schedule first."
            )

        if self.api_type == "legacy":
            thing_client = getattr(self.eufy_login, "tuya_thing_client", None)
            tuya_client = getattr(self.eufy_login, "tuya_client", None)
            if thing_client is None and tuya_client is None:
                raise HomeAssistantError(
                    f"Cannot delete schedule on {self.device_name}: no Tuya cloud client available"
                )

            res, last_err = await self._tuya_timer_call(
                "timer.delete", ("tuya.m.timer.delete",), timerId=actual_id
            )

            if res is None:
                err_msg = last_err or "No response from Tuya Cloud"
                raise HomeAssistantError(
                    f"Failed to delete schedule on {self.device_name}: {err_msg}"
                )
            if str(self.selected_schedule_id) == str(actual_id):
                self.selected_schedule_id = None
            await self.async_refresh_legacy_schedules()
            return True

        if self.api_type == "scalar":
            schedules = list(self.data.schedules or [])
            sid_int = int(actual_id) if str(actual_id).isdigit() else actual_id
            kept = [s for s in schedules if s.get("id") != sid_int]
            if len(kept) == len(schedules):
                raise HomeAssistantError(
                    f"Schedule ID {actual_id} not found on {self.device_name}"
                )
            await self._async_write_scalar_schedules(kept)
            if str(self.selected_schedule_id) == str(actual_id):
                self.selected_schedule_id = None
            return True

        raise HomeAssistantError(
            f"Schedule editing is not supported on {self.device_name}"
        )

    def _schedule_entry(self, schedule_id: int | str) -> dict[str, Any] | None:
        """The loaded schedule entry with this id, or None."""
        return next(
            (
                entry
                for entry in self.data.schedules or []
                if str(entry.get("id")) == str(schedule_id)
            ),
            None,
        )

    def _schedule_time(
        self,
        time: str | None,  # pylint: disable=redefined-outer-name  # service field name
        existing: dict[str, Any] | None,
    ) -> str:
        """``HH:MM`` for a set_schedule call: the given time, else the existing one."""
        if time is not None:
            return _normalize_schedule_time(time)
        if existing is None:
            raise ServiceValidationError(
                f"A new schedule on {self.device_name} needs a time"
            )
        return _normalize_schedule_time(existing.get("time") or "")

    async def async_set_schedule(
        self,
        *,
        time: str | None = None,  # pylint: disable=redefined-outer-name  # service field name
        schedule_id: int | str | None = None,
        days: list[str] | str | None = None,
        enabled: bool | None = None,
        suction: str | None = None,
        water: str | None = None,
        rooms: list[int] | None = None,
        clean_times: int | None = None,
        mode: str | None = None,
    ) -> bool:
        """Add a schedule, or change the given fields of an existing one.

        Modifying starts from the existing entry and overlays only the fields
        passed (None = keep). A new schedule needs ``time``; the rest default to
        every day, enabled, the middle levels, the whole home, one pass and the
        general mode.
        """
        actual_id = self._resolve_schedule_id(schedule_id)

        if self.api_type == "legacy":
            thing_client = getattr(self.eufy_login, "tuya_thing_client", None)
            tuya_client = getattr(self.eufy_login, "tuya_client", None)
            if thing_client is None and tuya_client is None:
                raise HomeAssistantError(
                    f"Cannot set schedule on {self.device_name}: no Tuya cloud client available"
                )

            existing = None
            if actual_id is not None:
                existing = self._schedule_entry(actual_id)
                if existing is None:  # not loaded yet, or made in the app since
                    await self.async_refresh_legacy_schedules()
                    existing = self._schedule_entry(actual_id)
                if existing is None:
                    raise HomeAssistantError(
                        f"Schedule ID {actual_id} not found on {self.device_name}"
                    )
            base = existing or {}
            time_clean = self._schedule_time(time, existing)
            if days is None:
                days = base.get("loops") if existing else _NEW_SCHEDULE_DAYS
            if enabled is None:
                enabled = base.get("enabled", True)
            # Room ids belong to the map the schedule was made on.
            map_id = base.get("map_id")
            if rooms is not None or map_id is None:
                map_id = self.resolve_map_id()
            try:
                loops = encode_legacy_loops(days)
                dps124 = build_legacy_schedule_dps(
                    map_id=map_id,
                    suction=base.get("suction") if suction is None else suction,
                    water=base.get("water") if water is None else water,
                    mode=base.get("mode") if mode is None else mode,
                    rooms=base.get("rooms") if rooms is None else rooms,
                    clean_times=(
                        base.get("clean_times") if clean_times is None else clean_times
                    ),
                    schema=self.tuya_schema,
                )
            except ValueError as err:
                raise ServiceValidationError(str(err)) from err

            # Modify and add share shapes but memoize separately.
            fields: dict[str, Any] = {
                "time": time_clean,
                "loops": loops,
                "status": 1 if enabled else 0,
                "dps": dps124,
            }
            if actual_id is not None:
                res, last_err = await self._tuya_timer_call(
                    "timer.modify",
                    ("tuya.m.timer.modify", "tuya.m.timer.group.modify"),
                    timerId=actual_id,
                    **fields,
                )
            else:
                res, last_err = await self._tuya_timer_call(
                    "timer.add",
                    ("tuya.m.timer.add", "tuya.m.timer.group.add"),
                    **fields,
                )

            if res is None:
                err_msg = last_err or "No response from Tuya Cloud"
                raise HomeAssistantError(
                    f"Failed to set schedule on {self.device_name}: {err_msg}"
                )
            await self.async_refresh_legacy_schedules()
            return True

        if self.api_type == "scalar":
            # DPS 151 holds id/e/t/r/s/f only; anything else would be dropped silently.
            unsupported = [
                name
                for name, given in (
                    ("rooms", bool(rooms)),
                    ("wash", water is not None),
                    ("clean_times", clean_times not in (None, 1)),
                    ("mode", mode is not None and scalar_pattern_to_int(mode) is None),
                )
                if given
            ]
            if unsupported:
                raise ServiceValidationError(
                    f"set_schedule on {self.device_name} supports time, days, enabled,"
                    f" suction and mode general/Arranged/Random only; not supported:"
                    f" {', '.join(unsupported)}"
                )
            if suction is not None and scalar_suction_to_int(suction) is None:
                raise ServiceValidationError(
                    f"Unknown suction {suction!r} for a schedule on {self.device_name}"
                )
            schedules = list(self.data.schedules or [])
            existing = None
            if actual_id is not None:
                existing = self._schedule_entry(actual_id)
                if existing is None:
                    raise HomeAssistantError(
                        f"Schedule ID {actual_id} not found on {self.device_name}"
                    )
                entry = dict(existing)
            else:
                existing_ids = [s["id"] for s in schedules if isinstance(s.get("id"), int)]
                entry = {
                    "id": max(existing_ids + [0]) + 1,
                    "days": _NEW_SCHEDULE_DAYS,
                    "enabled": True,
                }
            entry["time"] = self._schedule_time(time, existing)
            for key, value in (
                ("days", days),
                ("enabled", enabled),
                ("suction", suction),
                ("pattern", mode),
            ):
                if value is not None:
                    entry[key] = value
            updated = [entry if s is existing else s for s in schedules]
            if existing is None:
                updated.append(entry)
            await self._async_write_scalar_schedules(updated)
            return True

        raise HomeAssistantError(
            f"Schedule editing is not supported on {self.device_name}"
        )

    def selectable_rooms(self) -> list[dict[str, Any]]:
        """Return the rooms the Clean Room select lists, as ``{"id", "name"}``.

        The options-flow ``room_name_overrides`` (sorted by id) when set, else the
        map rooms. Per-room settings stay on ``data.rooms``; read them by id.
        """
        if self.room_name_overrides:
            return [
                {"id": rid, "name": name}
                for rid, name in sorted(self.room_name_overrides.items())
            ]
        return [
            {"id": room["id"], "name": room.get("name")}
            for room in self.data.rooms
            if room.get("id") is not None
        ]

    @property
    def legacy_room_config_supported(self) -> bool:
        """Whether per-room suction / wash / repeat config is available."""
        if self.api_type != "legacy" or not self.data.rooms:
            return False
        return (
            not self.tuya_schema
            or LEGACY_DPS_MAP["MAP_OPERATIONS"] in self.tuya_schema
        )

    async def async_set_room_config(
        self,
        room_id: int,
        *,
        fan_speed: str | None = None,
        water_level: str | None = None,
        clean_times: int | None = None,
    ) -> bool:
        """Set one room's suction / wash level / repeat count."""
        return await self.async_set_room_configs(
            {
                room_id: {
                    "fan_speed": fan_speed,
                    "water_level": water_level,
                    "clean_times": clean_times,
                }
            }
        )

    async def async_set_room_configs(
        self, targets: dict[int, dict[str, Any]]
    ) -> bool:
        """Set several rooms' suction / wash level / repeat count at once.

        ``customRooms`` is replace-all, so every room already carrying an override
        is resent alongside the named ones; rooms with none are left off, and an
        unset field falls back to the middle of its vocabulary.
        """
        rooms = self.data.rooms
        if not rooms or not targets:
            return False
        map_id = self.resolve_map_id()

        room_config: list[dict[str, Any]] = []
        new_rooms: list[dict[str, Any]] = []
        for room in rooms:
            rid = room.get("id")
            fan_idx = room.get("fan_speed", -1)
            water_idx = room.get("water_level", -1)
            times = room.get("clean_times", 0) or 0
            # Room id 0 is real; membership decides, never truthiness.
            target = targets.get(rid) if rid is not None else None
            is_target = target is not None
            has_override = fan_idx >= 0 or water_idx >= 0 or times >= 1

            if not is_target and not has_override:
                new_rooms.append(room)
                continue

            fan_speed = target.get("fan_speed") if target is not None else None
            water_level = target.get("water_level") if target is not None else None
            clean_times = target.get("clean_times") if target is not None else None
            fan_name = (
                fan_speed
                if fan_speed is not None
                else LEGACY_ROOM_FAN_LEVELS[fan_idx]
                if 0 <= fan_idx < len(LEGACY_ROOM_FAN_LEVELS)
                else LEGACY_ROOM_DEFAULT_FAN
            )
            water_name = (
                water_level
                if water_level is not None
                else LEGACY_ROOM_WATER_LEVELS[water_idx]
                if 0 <= water_idx < len(LEGACY_ROOM_WATER_LEVELS)
                else LEGACY_ROOM_DEFAULT_WATER
            )
            times_val = (
                int(clean_times)
                if clean_times is not None
                else times
                if times >= 1
                else 1
            )
            room_config.append(
                {
                    "room_id": rid,
                    "fan_speed": fan_name,
                    "water_level": water_name,
                    "clean_times": times_val,
                }
            )
            updated = dict(room)
            updated["fan_speed"] = (
                LEGACY_ROOM_FAN_LEVELS.index(fan_name)
                if fan_name in LEGACY_ROOM_FAN_LEVELS
                else fan_idx
            )
            updated["water_level"] = (
                LEGACY_ROOM_WATER_LEVELS.index(water_name)
                if water_name in LEGACY_ROOM_WATER_LEVELS
                else water_idx
            )
            updated["clean_times"] = times_val
            new_rooms.append(updated)

        # complete=True asserts every room with an override is named.
        command = self.build_device_command(
            "set_room_custom", map_id=map_id, room_config=room_config, complete=True
        )
        if not command:
            _LOGGER.warning(
                "%s: per-room config not supported on this device", self.device_name
            )
            return False

        await self.async_send_command(command)
        self.data = replace(self.data, rooms=new_rooms)
        self.async_update_listeners()
        _LOGGER.info(
            "%s: per-room config set for %s (document carried %d room(s))",
            self.device_name,
            sorted(targets),
            len(room_config),
        )
        return True

    async def async_check_firmware_updates(self) -> bool:
        """Query firmware versions, update availability and auto-update state."""
        thing_client = getattr(self.eufy_login, "tuya_thing_client", None)
        if thing_client is None:
            return False

        try:
            modules_raw = await thing_client.request(
                "m.thing.firmware.upgrade.info.get",
                data={"devId": self.device_id},
            )
            modules = modules_raw if isinstance(modules_raw, list) else []

            installed = self.firmware_version
            latest = self.firmware_version
            summary = ""
            in_progress = False

            main_mod = next((m for m in modules if m.get("type") == 0), modules[0] if modules else None)
            if main_mod:
                installed = main_mod.get("currentVersion") or installed
                latest = main_mod.get("version") or installed
                summary = main_mod.get("upgradeText") or main_mod.get("desc") or ""
                status = main_mod.get("upgradeStatus", 0)
                in_progress = status == 2
                if installed and installed != self.firmware_version:
                    self.firmware_version = installed

            auto_enabled = self.data.auto_update_enabled
            try:
                auto_sw = await thing_client.request(
                    "smartlife.m.device.upgrade.auto.switch.get",
                    data={"devId": self.device_id},
                )
                if isinstance(auto_sw, dict) and "value" in auto_sw:
                    auto_enabled = bool(auto_sw["value"])
            except Exception as err:
                _LOGGER.debug("%s: auto switch query failed: %s", self.device_name, err)

            self.data = replace(
                self.data,
                installed_version=installed or "",
                latest_version=latest or "",
                release_summary=summary,
                update_in_progress=in_progress,
                auto_update_enabled=auto_enabled,
                firmware_modules=modules,
            )
            self.async_update_listeners()
            _LOGGER.debug(
                "%s: firmware status checked: installed=%s, latest=%s, auto_update=%s",
                self.device_name,
                installed,
                latest,
                auto_enabled,
            )
            return latest != installed
        except Exception as err:
            _LOGGER.debug("%s: firmware update check failed: %s", self.device_name, err)
            return False

    async def async_set_auto_update(self, enabled: bool) -> bool:
        """Toggle automatic firmware updates overnight."""
        thing_client = getattr(self.eufy_login, "tuya_thing_client", None)
        if thing_client is None:
            return False

        try:
            await thing_client.request(
                "smartlife.m.device.upgrade.auto.switch.save",
                data={"devId": self.device_id, "value": 1 if enabled else 0},
            )
            self.data = replace(self.data, auto_update_enabled=enabled)
            self.async_update_listeners()
            _LOGGER.info("%s: auto firmware update set to %s", self.device_name, enabled)
            return True
        except Exception as err:
            _LOGGER.error("%s: failed to set auto firmware update: %s", self.device_name, err)
            return False

    async def async_install_firmware(self, version: str | None = None) -> bool:
        """Trigger an OTA firmware upgrade."""
        thing_client = getattr(self.eufy_login, "tuya_thing_client", None)
        if thing_client is None:
            return False

        async def attempt(action: str) -> str:
            await thing_client.request(action, data={"devId": self.device_id, "type": 0})
            return action  # any non-None result marks the winner

        try:
            action, _ = await self._tuya_probe.run(
                "firmware.install",
                (
                    "m.thing.firmware.upgrade.publish",
                    "smartlife.m.device.upgrade.start",
                    "tuya.m.device.upgrade.start",
                ),
                attempt,
            )
            if action is None:
                _LOGGER.warning(
                    "%s: no OTA upgrade trigger action accepted by gateway",
                    self.device_name,
                )
                return False
            self.data = replace(self.data, update_in_progress=True)
            self.async_update_listeners()
            _LOGGER.info("%s: firmware upgrade started via %s", self.device_name, action)
            return True
        except Exception as err:
            _LOGGER.error("%s: failed to trigger firmware upgrade: %s", self.device_name, err)
            return False

    @callback
    def _track_activity_change(
        self,
        prev_activity: str,
        new_state: VacuumState,
        changes: dict[str, Any],
    ) -> bool:
        """Apply session-boundary bookkeeping for a freshly parsed state.

        Returns whether to re-render, which must wait until ``self.data`` has been
        replaced: only when the activity really changed or the robot or dock cell
        moved, since a cloud poll repeats every DPS. EVERY path that parses DPS
        must call this, not only the push handler, or a cloud-polled device
        layers sessions on top of each other.
        """
        if "activity" not in changes:
            return False
        visible_change = new_state.activity != prev_activity

        if new_state.activity == "cleaning" and prev_activity != "cleaning":
            # A dock visit that INTERRUPTED a clean is a pause; keep the trail.
            resumed_pause = (
                self._dock_arrival_time is not None
                and time.monotonic() - self._dock_arrival_time
                < _DOCK_PAUSE_MAX_SECONDS
            )
            if not resumed_pause:
                # Keep the finished run so the map is not empty meanwhile.
                if len(self._robot_trail) > 1:
                    self._previous_trail = list(self._robot_trail)
                self._clear_trail()
                self._robot_pixel = None
                self._trail_reject_streak = 0
                self._notify_map_trail_reset()
                self._notify_map_pose()
                _LOGGER.debug(
                    "New cleaning session — trail cleared for %s", self.device_name
                )
            if self._dock_pixel is not None and not self._robot_trail:
                self._append_trail_point(self._dock_pixel)
                self._notify_map_trail()
            self._dock_arrival_time = None
        elif new_state.activity in ("docked", "idle"):
            # Stamp only a dock visit that interrupted a clean, or the next start
            # inherits the old trail.
            if self._dock_arrival_time is None and prev_activity in _ACTIVE_ACTIVITIES:
                self._dock_arrival_time = time.monotonic()
            if prev_activity in _ACTIVE_ACTIVITIES:
                # The clean just stopped: that is when the map is rewritten.
                self._schedule_legacy_map_freshness_checks()
            # A finished job ends the session; the next starts empty.
            if (new_state.task_status or "").lower().startswith("completed"):
                self._dock_arrival_time = None
            if self.api_type == "legacy" and self._dock_pixel is not None:
                # The legacy dock comes from the map; the pose snaps onto it.
                if self._robot_pixel != self._dock_pixel:
                    self._robot_pixel = self._dock_pixel
                    self._notify_map_pose()
                    visible_change = True
            elif self._robot_pixel is not None and self._robot_pixel != self._dock_pixel:
                # Re-captured at every dock: novel maps carry none, and a stop
                # mid-room, a map switch or a moved dock must not freeze it.
                self._dock_pixel = self._robot_pixel
                self._notify_map_pose()
                visible_change = True
                _LOGGER.debug("Dock position captured for %s", self.device_name)
        return visible_change and self._map_data is not None

    @callback
    def _handle_mqtt_message(self, payload: bytes) -> None:
        """Handle incoming MQTT message bytes."""
        try:
            parsed = json.loads(payload.decode("utf-8", errors="replace"))
            payload_data = parsed.get("payload", {})
            # Payload may be a nested JSON string or a dict.
            if isinstance(payload_data, str):
                payload_data = json.loads(payload_data)
        except Exception as e:  # noqa: BLE001 - one bad frame must not stop the stream
            _LOGGER.warning("Error handling MQTT message: %s", e)
            return
        if isinstance(payload_data, dict) and (dps := payload_data.get("data")):
            self._handle_dps(dps)

    @callback
    def _handle_dps(self, dps: dict[str, Any]) -> None:
        """Apply one pushed DPS dict (MQTT and local-Tuya entry point)."""
        if self._is_closing() or not dps:
            return
        try:
            prev_activity = self.data.activity
            new_state, changes = self._parse_dps(dps)
            _rerender_after_update = self._apply_parsed_state(
                prev_activity, new_state, changes
            )

            # dock_status stays pinned to the visible value.
            state_to_publish = replace(new_state, dock_status=self.data.dock_status)

            # The STARTUP map never arrives as a change.
            self._remember_map_id(new_state.map_id)

            # raw_dps rides every message; alone it changes no entity.
            if changes.keys() - {"raw_dps"}:
                self.async_set_updated_data(state_to_publish)
            else:
                self.data = state_to_publish
            self._maybe_refresh_legacy_map(state_to_publish)
            self._maybe_refresh_legacy_schedules()

            if _rerender_after_update:
                self._rerender_map()

            if "rooms" in changes:
                if self._segment_update_cancel:
                    self._segment_update_cancel()
                self._segment_update_cancel = async_call_later(
                    self.hass, 2.0, self._async_commit_segment_changes
                )

        except Exception as e:  # noqa: BLE001 - one bad frame must not stop the stream
            _LOGGER.warning("Error handling MQTT message: %s", e)

    def _apply_parsed_state(
        self,
        prev_activity: str,
        new_state: VacuumState,
        changes: dict[str, Any],
    ) -> bool:
        """Error notifications, session bookkeeping and the dock-status debounce.

        Shared by the push and the cloud-poll paths. Returns whether to re-render
        once ``self.data`` is replaced. A cloud poll carries every DPS, so each
        step compares against the previous state rather than reading ``changes``.
        """
        if "error_code" in changes:
            if new_state.error_code != 0:
                self._notify_error(new_state.error_code, new_state.error_message)
            elif self.data.error_code != 0:
                self._clear_error_notification()

        rerender = self._track_activity_change(prev_activity, new_state, changes)
        # dock_status is published only once debounced, so the badge reads the held one.
        dock = self.data.dock_status
        if self._map_data is not None and _robot_status_badge(
            dock, new_state.activity, new_state.battery_level
        ) != _robot_status_badge(dock, self.data.activity, self.data.battery_level):
            # e.g. battery reaching 100% clears the charging badge
            rerender = True

        # Only on messages carrying dock_status; others would reset the timer forever.
        if "dock_status" in changes:
            new_dock = changes["dock_status"]
            target_dock = self._pending_dock_status or self.data.dock_status
            if new_dock != target_dock:
                _LOGGER.debug(
                    "Dock status change: %s -> %s (committed: %s). Restarting debounce.",
                    target_dock,
                    new_dock,
                    self.data.dock_status,
                )
                if self._dock_idle_cancel:
                    self._dock_idle_cancel()
                self._pending_dock_status = new_dock
                self._dock_idle_cancel = async_call_later(
                    self.hass, 2.0, self._async_commit_dock_status
                )
        return rerender

    @callback
    def _handle_biz_message(self, payload: bytes) -> None:
        """Handle incoming biz/ MQTT message (map stream data)."""
        if self._is_closing():
            return
        _LOGGER.debug(
            "biz/ message received (%d bytes) for %s", len(payload), self.device_name
        )
        result = parse_biz_protocol41(payload)
        if result is None:
            _LOGGER.debug("biz/ message not a map stream, skipping")
            return

        channel_id, hex_data = result
        _LOGGER.debug("biz/ protocol-41 channel_id=%d, hex_len=%d", channel_id, len(hex_data))

        if len(hex_data) < _BIZ_INLINE_HEX_MAX:
            # Small frames: a MapDescription or a DynamicData pose; cheap inline.
            desc = try_extract_map_description(hex_data)
            if desc is not None:
                self._apply_map_description(desc)
                return
            self._apply_biz_pose(hex_data)
            return

        # The map channel differs between cleaning and editing.
        is_map_candidate = (
            self._map_data_chan_id is None
            or channel_id == self._map_data_chan_id
            or len(hex_data) > 15000
        )
        # MapBackup/Map decode runs LZ4 in pure Python: keep it off the loop.
        self._biz_decode_seq += 1
        seq = self._biz_decode_seq
        self._spawn(
            self._async_decode_biz_frame(seq, channel_id, hex_data, is_map_candidate),
            "biz_decode",
        )

    async def _async_decode_biz_frame(
        self, seq: int, channel_id: int, hex_data: str, map_candidate: bool
    ) -> None:
        """Decode a large biz/ frame in the executor and apply it if still current."""
        decoded = await self.hass.async_add_executor_job(
            _decode_biz_frame, hex_data, map_candidate
        )
        if self._is_closing() or decoded is None:
            return
        kind, value = decoded
        if kind == "desc":
            self._apply_map_description(value)
            return
        # A frame decoded after a newer one was applied would roll the map back.
        if seq <= self._biz_applied_seq:
            return
        self._biz_applied_seq = seq
        self._apply_biz_map(channel_id, value)

    @callback
    def _apply_map_description(self, desc: tuple[int, str]) -> None:
        """Record a MapDescription's ``(map_id, name)``."""
        map_id, name = desc
        if self.last_seen_maps.get(map_id) != name:
            self.last_seen_maps[map_id] = name
            _LOGGER.debug(
                "Discovered map %d (%d-char name) for %s",
                map_id, len(name), self.device_name,
            )
            self.async_update_listeners()
            self._spawn(self.async_save_maps(), "save_maps")

    @callback
    def _apply_biz_pose(self, hex_data: str) -> None:
        """Place a DynamicData pose from a small biz/ frame, if it is one."""
        pose = try_decode_as_dynamic_data(hex_data)
        if pose is None:
            return
        robot_px = self._pose_to_pixel(pose[0], pose[1])
        if robot_px is None:
            # off the map grid: no robot dot and no current room
            if self._robot_pixel is not None:
                self._robot_pixel = None
                self._notify_map_pose()
            self._update_current_room()
            return
        # Poses while returning or docked draw through walls.
        if self.data.activity == "cleaning":
            if not self._robot_trail:
                self._append_trail_point(robot_px)
                self._notify_map_trail()
            else:
                d = _px_dist(self._robot_trail[-1], robot_px)
                max_step = (
                    max(self._map_data.width, self._map_data.height) // 10
                    if self._map_data else 400
                )
                if 0 < d <= max_step:
                    self._append_trail_point(robot_px)
                    self._notify_map_trail()
        if robot_px != self._robot_pixel:
            self._robot_pixel = robot_px
            self._update_current_room()
            self._notify_map_pose()
            now = time.monotonic()
            if now - self._last_robot_render >= 2.0 and self._map_data is not None:
                self._last_robot_render = now
                self._rerender_map()

    @callback
    def _apply_biz_map(self, channel_id: int, map_data: MapData) -> None:
        """Install a decoded novel map frame."""
        if self._map_data_chan_id != channel_id:
            self._map_data_chan_id = channel_id
            _LOGGER.debug(
                "Discovered map channel %d for %s", channel_id, self.device_name
            )

        # A plain Map update has no outline/zone/name; keep MapBackup's.
        if self._map_data is not None and map_data.room_pixels is None:
            map_data.room_pixels = self._map_data.room_pixels
            map_data.room_outline_width = self._map_data.room_outline_width
            map_data.room_outline_height = self._map_data.room_outline_height
            map_data.room_outline_origin_x = self._map_data.room_outline_origin_x
            map_data.room_outline_origin_y = self._map_data.room_outline_origin_y
            map_data.room_names = self._map_data.room_names
            map_data.virtual_walls = self._map_data.virtual_walls
            map_data.forbidden_zones = self._map_data.forbidden_zones
            map_data.ban_mop_zones = self._map_data.ban_mop_zones

        self._set_map_data(map_data)
        self._rerender_map()

    @callback
    def _on_connection_change(self, connected: bool, auth_failed: bool) -> None:
        """Track the push transport; entities go unavailable after a sustained loss."""
        if self._is_closing():
            return
        if connected:
            self._auth_failures = 0
            self.eufy_login.mqtt_credentials_accepted(self._mqtt_credentials)
            if self._connection_loss_cancel is not None:
                self._connection_loss_cancel()
                self._connection_loss_cancel = None
            if not self._transport_available:
                self._transport_available = True
                _LOGGER.info("%s: connection restored", self.device_name)
                self.last_update_success = True
                self.async_update_listeners()
            return
        if auth_failed:
            self._auth_failures += 1
            if self._auth_failures == _AUTH_FAILURE_WARN_AFTER:
                _LOGGER.warning(
                    "%s: the MQTT broker rejected the client credentials on %d"
                    " connection attempts in a row",
                    self.device_name, self._auth_failures,
                )
            if (
                self._auth_failures % _AUTH_FAILURE_WARN_AFTER == 0
                and not self._mqtt_credentials_replacing
            ):
                self._mqtt_credentials_replacing = True
                self._spawn(
                    self._async_replace_rejected_credentials(), "mqtt_credentials"
                )
        if self._transport_available and self._connection_loss_cancel is None:
            self._connection_loss_cancel = async_call_later(
                self.hass, _CONNECTION_LOSS_GRACE, self._async_connection_lost
            )

    @callback
    def async_set_updated_data(self, data: VacuumState) -> None:
        """Publish ``data``; entities stay unavailable while the transport is down."""
        if self._transport_available:
            super().async_set_updated_data(data)
            return
        self.data = data
        self.async_update_listeners()

    @callback
    def _async_connection_lost(self, _now: Any) -> None:
        """The transport stayed down for the whole grace period."""
        self._connection_loss_cancel = None
        if self._is_closing() or not self._transport_available:
            return
        self._transport_available = False
        _LOGGER.warning(
            "%s: connection lost for %.0f s; marking entities unavailable",
            self.device_name, _CONNECTION_LOSS_GRACE,
        )
        self.last_update_success = False
        self.async_update_listeners()

    def _pose_to_pixel(self, x_cm: int, y_cm: int) -> tuple[int, int] | None:
        """Convert robot pose (cm) to map pixel coordinates."""
        if self._map_data is None:
            return None
        res = self._map_data.resolution or 5
        px = round((x_cm - self._map_data.origin_x) / res)
        py = round((y_cm - self._map_data.origin_y) / res)
        if 0 <= px < self._map_data.width and 0 <= py < self._map_data.height:
            return px, py
        return None

    async def async_set_nogo_zones(
        self,
        *,
        add_forbidden: list[Any] | None = None,
        add_ban_mop: list[Any] | None = None,
        add_walls: list[Any] | None = None,
        remove_forbidden: list[Any] | None = None,
        remove_ban_mop: list[Any] | None = None,
        remove_walls: list[Any] | None = None,
        move_forbidden: list[Any] | None = None,
        move_ban_mop: list[Any] | None = None,
        move_walls: list[Any] | None = None,
        expect_revision: int | None = None,
        replace: bool = False,  # pylint: disable=redefined-outer-name  # service field name
    ) -> bool:
        """Add restricted geometry drawn on the map, or replace it wholesale.

        ``add_*`` are normalized rects ``(x0, y0, x1, y1)`` on the rendered image;
        ``add_walls`` uses the same shape but means a LINE, not a bounding box.
        ``setNogoZones`` is REPLACE-ALL across all three categories, so shapes are
        merged with what the map carries unless ``replace=True`` (how a caller
        clears). Removals and moves address shapes BY INDEX into the current
        geometry, in world cm; a move is ``{"index", "dx" cm, "dy" cm, "rotate"
        radians}``. ``expect_revision`` refuses the write if geometry moved on.
        """
        if self.api_type != "legacy":
            raise HomeAssistantError(
                f"Editing no-go zones is not supported on {self.device_name}"
            )
        if self._map_data is None:
            raise HomeAssistantError(
                f"Cannot set no-go zones on {self.device_name}: no map decoded yet"
            )

        removing = bool(remove_forbidden or remove_ban_mop or remove_walls)
        moving = bool(move_forbidden or move_ban_mop or move_walls)
        if replace and (removing or moving):
            raise HomeAssistantError(
                "set_nogo_zones: 'replace' sends only the shapes supplied, so "
                "moving or removing by index at the same time is meaningless"
            )
        for label, moves, removals in (
            ("forbidden", move_forbidden, remove_forbidden),
            ("ban_mop", move_ban_mop, remove_ban_mop),
            ("walls", move_walls, remove_walls),
        ):
            clash = _index_set(moves) & _index_set(removals)
            if clash:
                raise HomeAssistantError(
                    f"set_nogo_zones: {label} index {sorted(clash)} is both moved and "
                    "removed — nothing was sent"
                )
        if (
            expect_revision is not None
            and int(expect_revision) != self.map_geometry_revision
        ):
            raise HomeAssistantError(
                "set_nogo_zones: the map changed since the client read it "
                f"(revision {expect_revision} != {self.map_geometry_revision}); "
                "nothing was sent"
            )

        md = self._map_data
        # Held in world cm; the DPS document wants blob units.
        existing_forbidden = [] if replace else [
            list(zone) for zone in md.forbidden_zones
        ]
        existing_mop = [] if replace else [list(zone) for zone in md.ban_mop_zones]
        existing_walls = [] if replace else [list(wall) for wall in md.virtual_walls]
        # Both index the ORIGINAL list: move before dropping.
        existing_forbidden = _move_shapes(
            existing_forbidden, move_forbidden, "forbidden"
        )
        existing_mop = _move_shapes(existing_mop, move_ban_mop, "ban_mop")
        existing_walls = _move_shapes(existing_walls, move_walls, "walls")
        existing_forbidden = _drop_indices(
            existing_forbidden, remove_forbidden, "forbidden"
        )
        existing_mop = _drop_indices(existing_mop, remove_ban_mop, "ban_mop")
        existing_walls = _drop_indices(existing_walls, remove_walls, "walls")

        new_forbidden = self.normalized_rects_to_quads_cm(add_forbidden or [])
        new_mop = self.normalized_rects_to_quads_cm(add_ban_mop or [])
        new_walls = self.normalized_lines_to_segments_cm(add_walls or [])
        if (add_forbidden or add_ban_mop or add_walls) and not (
            new_forbidden or new_mop or new_walls
        ):
            raise HomeAssistantError(
                "set_nogo_zones: every shape was invalid — nothing was sent"
            )

        command = self.build_device_command(
            "set_nogo_zones",
            forbidden_zones=self._zone_quads_to_blob_units(
                [*existing_forbidden, *new_forbidden]
            ),
            ban_mop_zones=self._zone_quads_to_blob_units([*existing_mop, *new_mop]),
            virtual_walls=self._zone_quads_to_blob_units([*existing_walls, *new_walls]),
        )
        if not command:
            raise HomeAssistantError(
                f"Cannot set no-go zones on {self.device_name}: "
                "the device does not expose map operations"
            )
        await self.async_send_command(command)
        # The device announces a cleared category by silence.
        md.forbidden_zones = [list(zone) for zone in existing_forbidden + new_forbidden]
        md.ban_mop_zones = [list(zone) for zone in existing_mop + new_mop]
        md.virtual_walls = [
            ((wall[0][0], wall[0][1]), (wall[1][0], wall[1][1]))
            for wall in existing_walls + new_walls
            if len(wall) == 2
        ]
        # Stamp all three, or an older blob resurrects the deletions.
        self.remember_live_restricted_geometry(
            MMI_FORBIDDEN_ZONES, list(md.forbidden_zones)
        )
        self.remember_live_restricted_geometry(
            MMI_BAN_MOP_ZONES, list(md.ban_mop_zones)
        )
        self.remember_live_restricted_geometry(
            MMI_VIRTUAL_WALL, [list(w) for w in md.virtual_walls]
        )
        self._notify_map_geometry()
        self._rerender_map()
        _LOGGER.debug(
            "set_nogo_zones for %s: %d no-go, %d no-mop, %d walls (replace=%s)",
            self.device_name,
            len(existing_forbidden) + len(new_forbidden),
            len(existing_mop) + len(new_mop),
            len(existing_walls) + len(new_walls), replace,
        )
        return True

    def _normalized_to_cm(self, nx: float, ny: float) -> tuple[int, int]:
        """One normalized map-image point -> world cm."""
        md = self._map_data
        res = (md.resolution or 5) if md else 5
        w, h = (md.width, md.height) if md else (0, 0)
        nx = min(max(_finite(nx, "map x"), 0.0), 1.0)
        ny = min(max(_finite(ny, "map y"), 0.0), 1.0)
        wx = (md.origin_x if md else 0) + nx * w * res
        wy = (md.origin_y if md else 0) + (h - 1 - ny * h) * res
        return round(wx), round(wy)

    def normalized_lines_to_segments_cm(
        self, lines: list[Any]
    ) -> list[list[tuple[int, int]]]:
        """Convert normalized lines on the rendered map image to world-cm segments.

        A line is ``(x0, y0, x1, y1)`` in 0-1 fractions, or ``[[x, y], [x, y]]``.
        Endpoints must NOT be sorted, or diagonal walls become axis-aligned.
        """
        if self._map_data is None:
            return []
        segments: list[list[tuple[int, int]]] = []
        for line in lines:
            points = _as_normalized_points(line)
            if points is not None:
                if len(points) != 2:
                    _LOGGER.warning(
                        "Ignoring virtual wall with %d points (need 2): %s",
                        len(points), line,
                    )
                    continue
                segments.append([self._normalized_to_cm(px, py) for px, py in points])
                continue
            try:
                x0, y0, x1, y1 = (float(v) for v in line)
            except (TypeError, ValueError):
                _LOGGER.warning("Ignoring malformed virtual wall: %s", line)
                continue
            segments.append(
                [self._normalized_to_cm(x0, y0), self._normalized_to_cm(x1, y1)]
            )
        return segments

    def normalized_rects_to_quads_cm(
        self, rects: list[Any]
    ) -> list[list[tuple[int, int]]]:
        """Convert normalized rectangles on the rendered map image to world-cm quads.

        A rect is ``(x0, y0, x1, y1)`` in 0-1 fractions, origin TOP-LEFT, or four
        explicit corners (a ROTATED zone), used in order. Inverse of
        ``render_map_png``: ``wx = origin_x + nx * width * res`` and
        ``wy = origin_y + (height - 1 - ny * height) * res``.
        """
        if self._map_data is None:
            return []
        _to_cm = self._normalized_to_cm

        quads: list[list[tuple[int, int]]] = []
        for rect in rects:
            points = _as_normalized_points(rect)
            if points is not None:
                # Order as drawn; sorting flattens a rotated zone.
                if len(points) != 4:
                    _LOGGER.warning(
                        "Ignoring zone with %d corner points (need 4): %s",
                        len(points), rect,
                    )
                    continue
                quads.append([_to_cm(px, py) for px, py in points])
                continue
            try:
                x0, y0, x1, y1 = (float(v) for v in rect)
            except (TypeError, ValueError):
                _LOGGER.warning("Ignoring malformed zone rect: %s", rect)
                continue
            lo_x, hi_x = sorted((x0, x1))
            lo_y, hi_y = sorted((y0, y1))
            quads.append(
                [
                    _to_cm(lo_x, lo_y),
                    _to_cm(hi_x, lo_y),
                    _to_cm(hi_x, hi_y),
                    _to_cm(lo_x, hi_y),
                ]
            )
        return quads

    def room_id_at_normalized(self, nx: float, ny: float) -> tuple[int | None, str | None]:
        """Resolve the (room id, name) under a normalized point on the map."""
        md = self._map_data
        if md is None:
            return None, None
        rid = md.room_id_at_normalized(_finite(nx, "x"), _finite(ny, "y"))
        if rid is None or rid < 0:
            return None, None
        return rid, md.room_names.get(rid)

    def current_room(self) -> tuple[int, str | None] | None:
        """The (room id, name) under the live map pose, or None outside any room.

        Resolved from the map, not DPS coordinates. Legacy robots number rooms
        from 0, so 0 is a room.
        """
        md = self._map_data
        if md is None or self._robot_pixel is None or md.width <= 0 or md.height <= 0:
            return None
        px, py = self._robot_pixel
        if not (0 <= px < md.width and 0 <= py < md.height):
            return None
        # cell centre, so the floor in room_id_at_normalized lands on this cell
        nx = (int(px) + 0.5) / md.width
        ny = 1.0 - (int(py) + 0.5) / md.height
        room_id, room_name = self.room_id_at_normalized(nx, ny)
        if room_id is None:
            return None
        if not room_name:
            room_name = next(
                (room.get("name") for room in self.data.rooms if room.get("id") == room_id),
                None,
            )
        return room_id, room_name

    @callback
    def _update_current_room(self) -> None:
        """Notify only room subscribers when the resolved ID or name changes."""
        room = self.current_room()
        if room != self._current_room:
            self._current_room = room
            async_dispatcher_send(
                self.hass, f"{DOMAIN}_{self.device_id}_current_room_updated"
            )

    def _get_robot_status(self) -> str | None:
        """Return a status badge string for the current dock/activity state."""
        return _robot_status_badge(
            self.data.dock_status, self.data.activity, self.data.battery_level
        )

    @callback
    def async_add_map_listener(
        self, map_callback: Callable[[dict[str, Any]], None]
    ) -> Callable[[], None]:
        """Subscribe to live map events; returns the unsubscribe callable."""
        if not self._map_listeners:
            # Nothing is tracked while unwatched; re-baseline so the snapshot
            # lines up with the first "from" sent.
            self._map_trail_sent = len(self._robot_trail)
            self._map_trail_reset = False
            self._map_pose_dirty = False
            self._map_sent_dock = self._dock_pixel
        self._map_listeners.append(map_callback)

        @callback
        def _remove_listener() -> None:
            if map_callback in self._map_listeners:
                self._map_listeners.remove(map_callback)
            if not self._map_listeners and self._map_flush_cancel is not None:
                self._map_flush_cancel()
                self._map_flush_cancel = None

        return _remove_listener

    @callback
    def _send_map_event(self, event: dict[str, Any]) -> None:
        """Fan one already-built event out to every subscriber."""
        for map_callback in list(self._map_listeners):
            try:
                map_callback(event)
            except Exception:  # a broken subscriber must not stall the others
                _LOGGER.debug("Map listener raised on %s", event.get("t"), exc_info=True)

    @callback
    def _notify_map_pose(self) -> None:
        """Robot and/or dock pixel changed."""
        if not self._map_listeners:
            return
        self._map_pose_dirty = True
        self._schedule_map_flush()

    @callback
    def _notify_map_trail(self) -> None:
        """Points were appended to _robot_trail."""
        if not self._map_listeners:
            return
        self._schedule_map_flush()

    @callback
    def _notify_map_trail_reset(self) -> None:
        """_robot_trail was cleared (new session / dock+recharge)."""
        if not self._map_listeners:
            return
        self._map_trail_reset = True
        self._schedule_map_flush()

    @callback
    def _notify_map_geometry(self) -> None:
        """Bump ``map_geometry_revision`` and notify, if geometry changed."""
        md = self._map_data
        if md is None:
            return
        sig = (
            md.width,
            md.height,
            md.origin_x,
            md.origin_y,
            md.resolution,
            md.room_id_offset,
            zlib.crc32(md.raw_pixels),
            zlib.crc32(md.room_pixels) if md.room_pixels else 0,
            md.room_outline_width,
            md.room_outline_height,
            md.room_outline_origin_x,
            md.room_outline_origin_y,
            tuple(sorted(md.room_names.items())),
            # Room polygons ride the static layer but arrive after it.
            tuple(
                (rid, _shapes_sig([poly])[0])
                for rid, poly in sorted(md.room_polygons.items())
            ),
            # By CONTENT: a moved or swapped zone keeps the same count.
            _shapes_sig(md.virtual_walls),
            _shapes_sig(md.forbidden_zones),
            _shapes_sig(md.ban_mop_zones),
        )
        if sig == self._map_geometry_sig:
            return
        self._map_geometry_sig = sig
        self.map_geometry_revision += 1
        if not self._map_listeners:
            return
        self._send_map_event(
            {"t": "geometry", "revision": self.map_geometry_revision}
        )

    async def async_map_static_geometry(self) -> tuple[int, dict[str, Any]] | None:
        """The revision-stable half of the map geometry payload, off the loop.

        ``build_map_static`` walks every cell twice, so it runs in an executor and
        its result is cached per revision. Returns ``(revision, payload)`` rather
        than reading the revision back afterwards: the two must describe the same
        map, or a client caches a grid under a revision it does not belong to. A
        map that changed mid-build is retried, and the last attempt is returned.
        """
        built: tuple[int, dict[str, Any]] | None = None
        for _ in range(3):
            md = self._map_data
            if md is None:
                return None
            revision = self.map_geometry_revision
            cached = self._map_static_geometry
            if cached is not None and cached[0] == revision:
                return cached
            payload = await self.hass.async_add_executor_job(
                partial(build_map_static, md, revision=revision)
            )
            built = (revision, payload)
            if self.map_geometry_revision == revision:
                self._map_static_geometry = built
                return built
        return built

    @callback
    def _set_map_data(self, map_data: MapData) -> None:
        """Install new map data and publish a geometry event if it really changed."""
        previous = self._map_data
        self._map_data = map_data
        self._reproject_legacy_live_cells(previous, map_data)
        # A parked robot publishes no 0x64, so a resolved divergence would
        # otherwise stay set.
        if self._legacy_map_param is not None and self.api_type == "legacy":
            param = self._legacy_map_param
            live = (
                param["width"], param["height"], param["origin_x"], param["origin_y"]
            )
            held = (
                map_data.width, map_data.height, map_data.origin_x, map_data.origin_y
            )
            self._map_frame_divergence = None if live == held else live
        self._notify_map_geometry()

    def _reproject_legacy_live_cells(
        self, old: MapData | None, new: MapData
    ) -> bool:
        """Carry the live trail, dot and dock across a legacy map that grew.

        A grown map re-indexes every cell; the frames differ only by origin and
        extent, so the correction is a translation (rows bottom-up, hence the
        height term). Points off the new grid are dropped. Legacy only: the novel
        origin is cm off a world pose with no row flip.
        """
        if self.api_type != "legacy" or old is None or not self._legacy_frame_moved(
            old, new
        ):
            return False
        # Whole cells: the grids share the 5 cm lattice.
        d_col = round((new.origin_x - old.origin_x) / _TUYA_UNITS_PER_CELL)
        d_row = (new.height - old.height) - round(
            (new.origin_y - old.origin_y) / _TUYA_UNITS_PER_CELL
        )

        def _shift(
            points: list[tuple[float, float]], types: list[int] | None = None
        ) -> tuple[list[tuple[float, float]], list[int]]:
            moved: list[tuple[float, float]] = []
            moved_types: list[int] = []
            for index, (col, row) in enumerate(points):
                col, row = col + d_col, row + d_row
                if 0 <= col < new.width and 0 <= row < new.height:
                    moved.append((col, row))
                    if types is not None:
                        moved_types.append(types[index] if index < len(types) else 0)
            return moved, moved_types

        # Re-placing from raw is exact; a raw-less trail is translated.
        unplaced = None
        if self._robot_trail_raw and new.dock_pixel is not None:
            unplaced = self._rebuild_trail_from_raw()
        else:
            self._robot_trail, self._robot_trail_types = _shift(
                self._robot_trail, self._robot_trail_types
            )
        self._previous_trail, _ = _shift(self._previous_trail)
        for attr in ("_robot_pixel", "_dock_pixel", "_legacy_dock_cell"):
            point = getattr(self, attr)
            if point is not None:
                shifted, _ = _shift([point])
                setattr(self, attr, shifted[0] if shifted else None)
        _LOGGER.debug(
            "legacy map frame moved (%+d, %+d) cells for %s; %s (%d points%s)",
            d_col, d_row, self.device_name,
            "re-placed the trail from raw" if unplaced is not None
            else "translated the trail",
            len(self._robot_trail),
            f", {unplaced} still off-grid" if unplaced else "",
        )
        # Subscribers hold the old frame; replace wholesale.
        self._notify_map_trail_reset()
        self._notify_map_pose()
        return True

    @staticmethod
    def _legacy_frame_moved(old: MapData, new: MapData) -> bool:
        """Do these two legacy grids index the same cell to a different place?"""
        return (old.origin_x, old.origin_y, old.height) != (
            new.origin_x, new.origin_y, new.height
        )

    @callback
    def _schedule_map_flush(self) -> None:
        """Emit now if the 2 Hz window has elapsed, else arm one timer for it."""
        if self._map_flush_cancel is not None:
            return  # an armed flush will pick up everything pending
        delay = _MAP_EVENT_MIN_INTERVAL - (time.monotonic() - self._last_map_event)
        if delay <= 0:
            self.flush_map_events()
            return
        self._map_flush_cancel = async_call_later(
            self.hass, delay, self._async_map_flush_due
        )

    @callback
    def _async_map_flush_due(self, _now: Any) -> None:
        """Throttle timer fired."""
        self._map_flush_cancel = None
        self.flush_map_events()

    @callback
    def flush_map_events(self) -> None:
        """Send any coalesced pose/trail events immediately."""
        if self._map_flush_cancel is not None:
            self._map_flush_cancel()
            self._map_flush_cancel = None
        if not self._map_listeners:
            return
        trail_len = len(self._robot_trail)
        # A shorter trail with no reset flag is a clear we missed.
        reset = self._map_trail_reset or trail_len < self._map_trail_sent
        if not self._map_pose_dirty and not reset and trail_len == self._map_trail_sent:
            return
        self._last_map_event = time.monotonic()

        if self._map_pose_dirty:
            self._map_pose_dirty = False
            event: dict[str, Any] = {
                "t": "pose",
                "robot": list(self._robot_pixel) if self._robot_pixel else None,
            }
            # Dock only when it changes; it is static most of a session.
            if self._dock_pixel != self._map_sent_dock:
                self._map_sent_dock = self._dock_pixel
                event["dock"] = list(self._dock_pixel) if self._dock_pixel else None
            self._send_map_event(event)

        if reset:
            self._map_trail_reset = False
            self._map_trail_sent = trail_len
            self._send_map_event(
                {
                    "t": "trail",
                    "from": 0,
                    "reset": True,
                    "p": [list(pt) for pt in self._robot_trail],
                    # One per point, same order as "p" (0 clean, 1 transit).
                    "types": self._trail_types_for(0, len(self._robot_trail)),
                }
            )
        elif trail_len > self._map_trail_sent:
            start = self._map_trail_sent
            self._map_trail_sent = trail_len
            self._send_map_event(
                {
                    "t": "trail",
                    "from": start,
                    "p": [list(pt) for pt in self._robot_trail[start:]],
                    "types": self._trail_types_for(start, trail_len),
                }
            )

    def _rerender_map(self) -> None:
        """Mark the rendered frame stale, bump the frame token, and tell the camera.

        Does NOT render (that is lazy, in ``async_get_map_image``), but the revision
        bump, the ``_map_updated`` signal and the debounced save must happen here.
        """
        self._update_current_room()
        if self._map_data is None or self._is_closing():
            # No placeholder map: it would ship someone's home.
            return
        self._map_frame_dirty = True
        self.map_revision += 1
        self._schedule_map_state_save()
        async_dispatcher_send(self.hass, f"{DOMAIN}_{self.device_id}_map_updated")

    async def async_get_map_image(self) -> bytes | None:
        """Return the current map PNG, rendering it on demand.

        Concurrent readers join the in-flight render. Never ``cancel()`` a render
        task to replace it: a job already in the thread pool cannot be reclaimed.
        """
        if self._map_data is None:
            return self.map_image
        task = self._render_task
        if task is not None and not task.done():
            if self._map_frame_dirty:
                self._render_pending = True
            await self._async_join_render(task)
            return self.map_image
        if self.map_image is not None and not self._map_frame_dirty:
            return self.map_image
        new_task = self.hass.async_create_task(self._async_render_loop())
        self._render_task = new_task
        await self._async_join_render(new_task)
        return self.map_image

    async def _async_join_render(self, task: asyncio.Task) -> None:
        """Wait for ``task`` without ever cancelling or re-raising into it."""
        await asyncio.wait({task})
        if task.cancelled():
            return
        if (exc := task.exception()) is not None:
            _LOGGER.debug(
                "Map render failed for %s: %s", self.device_name, exc, exc_info=exc
            )

    async def _async_render_loop(self) -> None:
        """Render, then render once more if anything asked while we were busy."""
        try:
            while True:
                self._render_pending = False
                await self._async_rerender_map()
                if not self._render_pending:
                    return
        finally:
            self._render_pending = False

    async def _async_rerender_map(self) -> None:
        """Re-render the PNG in an executor so PIL does not block the loop."""
        if self._map_data is None:
            return

        # Cleared BEFORE the render, so a change during it re-dirties.
        was_dirty = self._map_frame_dirty
        self._map_frame_dirty = False

        robot_px = (
            self._dock_pixel
            if self.data.activity in ("docked", "idle") and self._dock_pixel is not None
            else self._robot_pixel
        )
        entry = self.hass.config_entries.async_get_entry(self.entry_id)
        opts = entry.options if entry else {}
        max_px = int(opts.get(CONF_MAP_MAX_PX, DEFAULT_MAP_MAX_PX))
        robot_style = opts.get(CONF_ROBOT_STYLE, DEFAULT_ROBOT_STYLE)
        trail_color = self.trail_color
        map_data = self._map_data
        robot_trail = list(self._robot_trail) if self._robot_trail else None
        robot_trail_types = (
            self._trail_types_for(0, len(self._robot_trail)) if self._robot_trail else None
        )
        dock_pixel = self._dock_pixel
        robot_status = self._get_robot_status()

        # The legacy 0x67 trail can stray onto obstacle cells.
        clip_trail = self.api_type == "legacy"

        def _render() -> bytes:
            return render_map_png(
                map_data,
                robot_pixel=robot_px,
                robot_trail=robot_trail,
                robot_trail_types=robot_trail_types,
                dock_pixel=dock_pixel,
                robot_status=robot_status,
                max_px=max_px,
                robot_style=robot_style,
                clip_trail_to_floor=clip_trail,
                trail_color=trail_color,
            )

        try:
            png = await self.hass.async_add_executor_job(_render)
        except BaseException:
            # Nothing was drawn: stay stale or it never retries.
            self._map_frame_dirty = self._map_frame_dirty or was_dirty
            raise
        self.map_image = png
        _LOGGER.debug("Map image updated (%d bytes PNG) for %s", len(png), self.device_name)
        if not was_dirty:
            # A forced render: _rerender_map already bumped the token for a dirty
            # frame, and bumping twice costs a needless fetch.
            self.map_revision += 1
            async_dispatcher_send(self.hass, f"{DOMAIN}_{self.device_id}_map_updated")

    @callback
    def _async_commit_dock_status(self, _now: Any) -> None:
        """Commit the pending dock status."""
        _LOGGER.debug(
            "Debounce timer fired. Committing status: %s", self._pending_dock_status
        )
        self._dock_idle_cancel = None
        final_dock = self._pending_dock_status
        self._pending_dock_status = None

        if final_dock is None:
            _LOGGER.warning("Pending dock status was None when timer fired!")
            return

        committed_state = replace(self.data, dock_status=final_dock)
        self.async_set_updated_data(committed_state)
        if self._map_data is not None:
            self._rerender_map()

    @callback
    def _async_commit_segment_changes(self, _now: Any) -> None:
        """Commit segment changes."""
        self._segment_update_cancel = None
        async_dispatcher_send(self.hass, f"{DOMAIN}_{self.device_id}_rooms_updated")

    def _notify_error(self, code: int, message: str) -> None:
        """Fire error notifications through configured channels, once per code.

        A cloud poll repeats the code, and a dismissed notification stays dismissed.
        """
        if code == self._last_notified_error_code:
            return
        self._last_notified_error_code = code
        entry = self.hass.config_entries.async_get_entry(self.entry_id)
        opts = entry.options if entry else {}
        title = f"{self.device_name} Error"
        msg = f"Error {code}: {message.title()}"
        if opts.get(CONF_NOTIFY_DESKTOP, DEFAULT_NOTIFY_DESKTOP):
            pn_async_create(
                self.hass,
                message=msg,
                title=title,
                notification_id=f"{DOMAIN}_{self.device_id}_error",
            )
        mobile_svc = opts.get(CONF_NOTIFY_MOBILE_SERVICE, DEFAULT_NOTIFY_MOBILE_SERVICE).strip()
        if mobile_svc:
            self._spawn(
                self.hass.services.async_call(
                    "notify", mobile_svc,
                    {"title": title, "message": msg},
                    blocking=False,
                ),
                "error_notify",
            )

    def _clear_error_notification(self) -> None:
        """Dismiss the persistent error notification when error clears."""
        self._last_notified_error_code = 0
        pn_async_dismiss(self.hass, notification_id=f"{DOMAIN}_{self.device_id}_error")

    def async_shutdown_timers(self) -> None:
        """Cancel active debounce timers (call before teardown).

        Also ends every map subscription with a terminal ``{"t": "gone"}`` event.
        """
        # First: awaits already in flight check it before starting anything.
        self._closing = True
        if self._connection_loss_cancel:
            self._connection_loss_cancel()
            self._connection_loss_cancel = None
        if self._map_flush_cancel:
            self._map_flush_cancel()
            self._map_flush_cancel = None
        listeners, self._map_listeners = self._map_listeners, []
        for map_callback in listeners:
            try:
                map_callback({"t": "gone"})
            except Exception:  # noqa: BLE001 - a broken subscriber must not stop teardown
                _LOGGER.debug("Map listener raised on gone", exc_info=True)
        if self._dock_idle_cancel:
            self._dock_idle_cancel()
            self._dock_idle_cancel = None
        if self._segment_update_cancel:
            self._segment_update_cancel()
            self._segment_update_cancel = None
        if self._tuya_mqtt_refresh_cancel:
            self._tuya_mqtt_refresh_cancel()
            self._tuya_mqtt_refresh_cancel = None
        if self._tuya_session_unsub is not None:
            self._tuya_session_unsub()
            self._tuya_session_unsub = None
        if self._map_keepalive_cancel:
            self._map_keepalive_cancel()
            self._map_keepalive_cancel = None
        self._cancel_legacy_map_freshness_checks()
        # The in-flight executor job cannot be reclaimed, only disowned.
        self._render_pending = False
        if self._render_task and not self._render_task.done():
            self._render_task.cancel()
            self._render_task = None
        if self._tuya_mqtt is not None:
            # stop() JOINS paho's network thread, which ignores terminate during
            # a blocking connect; never on the loop.
            previous, self._tuya_mqtt = self._tuya_mqtt, None
            self.hass.async_add_executor_job(previous.stop)
        self._clear_error_notification()

    async def async_teardown(self) -> None:
        """Cancel timers and close the transport. Idempotent.

        HA does not unload entries on shutdown, so a STOP hook must call this or
        the local-Tuya listener keeps queueing blocking recv() jobs.
        """
        self.async_shutdown_timers()
        # Safe on a coordinator whose initialize() failed part-way.
        await self._async_drop_client()
        # The only point the PNG is cached; the first read is instant.
        await self._async_persist_map_image()

    async def _async_persist_map_image(self) -> None:
        """Write the PNG cache and the latest map state to .storage, from teardown.

        Map state only once storage was read and a map is held; otherwise the
        empty in-memory trail and map would overwrite the stored ones.
        """
        if self.map_image is None and not self._map_state_ready():
            return
        try:
            data = await self._async_store_doc()
            if self.map_image is not None:
                data["map_image_png"] = base64.b64encode(self.map_image).decode()
            if self._map_state_ready():
                self._map_state_doc()
            await self._store.async_save(data)
        except Exception as exc:  # noqa: BLE001 - teardown must never raise
            _LOGGER.debug(
                "Could not persist the map state for %s: %s", self.device_name, exc
            )

    @callback
    def set_active_cleaning_targets(
        self,
        room_ids: list[int] | None = None,
        zone_count: int = 0,
    ) -> None:
        """Set active cleaning targets on state (called when HA sends commands)."""
        rooms = self.data.rooms
        if room_ids:
            room_lookup = {r["id"]: r.get("name", f"Room {r['id']}") for r in rooms}
            names = [room_lookup.get(rid, f"Room {rid}") for rid in room_ids]
            new_state = replace(
                self.data,
                active_room_ids=room_ids,
                active_room_names=", ".join(names),
                active_zone_count=0,
                current_scene_id=0,
                current_scene_name=None,
                received_fields=self.data.received_fields | {"active_room_ids"},
            )
        else:
            new_state = replace(
                self.data,
                active_room_ids=[],
                active_room_names="",
                active_zone_count=zone_count,
                current_scene_id=0,
                current_scene_name=None,
                received_fields=self.data.received_fields | {"active_room_ids"},
            )
        self.async_set_updated_data(new_state)

    @callback
    def set_active_scene(self, scene_id: int, scene_name: str | None) -> None:
        """Set the active cleaning scene on state."""
        new_state = replace(
            self.data,
            current_scene_id=scene_id,
            current_scene_name=scene_name,
            active_room_ids=[],
            active_room_names="",
            active_zone_count=0,
        )
        self.async_set_updated_data(new_state)

    async def async_send_command(self, command_dict: dict[str, Any]) -> None:
        """Send command to device."""
        if not command_dict:
            _LOGGER.debug("Ignoring empty command for %s", self.device_name)
            return
        # Legacy map ops (DPS 124) MUST go over the Tuya cloud; the LAN socket
        # accepts and silently ignores them, so there is no local fallback.
        if (
            self.connection_type != "cloud"
            and self.api_type == "legacy"
            and LEGACY_DPS_MAP["MAP_OPERATIONS"] in command_dict
        ):
            if getattr(self.eufy_login, "tuya_client", None) is None:
                raise HomeAssistantError(
                    f"Cannot send map operation to {self.device_name}: "
                    "the Tuya cloud is not connected"
                )
            _LOGGER.debug(
                "Sending map operation to %s via cloud: DPS %s",
                self.device_name, sorted(command_dict),
            )
            try:
                await self.eufy_login.sendCloudCommand(self.device_id, command_dict)
            except Exception as e:
                raise HomeAssistantError(
                    f"Failed to send map operation to {self.device_name}: {e}"
                ) from e
            return

        _LOGGER.debug(
            "Sending command to %s via %s: DPS %s",
            self.device_name, self.connection_type, sorted(command_dict),
        )
        try:
            if self.connection_type == "cloud":
                await self.eufy_login.sendCloudCommand(self.device_id, command_dict)
            elif self.client:
                await self.client.send_command(command_dict)
            else:
                raise HomeAssistantError(
                    f"Cannot send command to {self.device_name}: no connection available"
                )
        except HomeAssistantError:
            raise
        except Exception as e:
            raise HomeAssistantError(
                f"Failed to send command to {self.device_name}: {e}"
            ) from e

    async def _async_update_data(self) -> VacuumState:
        """Fetch data from API endpoint."""
        if self.connection_type == "cloud":
            _LOGGER.debug("Cloud poll starting for %s", self.device_name)
            try:
                dps = await self.eufy_login.getCloudDevice(self.device_id)
                if dps:
                    prev_activity = self.data.activity
                    new_state, changes = self._parse_dps(dps)
                    self._on_cloud_success()
                    # A cloud-polled device changes activity ONLY here.
                    rerender = self._apply_parsed_state(prev_activity, new_state, changes)
                    new_state = replace(new_state, dock_status=self.data.dock_status)
                    if rerender:
                        self._rerender_map()
                    # Cloud-polled devices never traverse the MQTT path.
                    self._maybe_refresh_legacy_map(new_state)
                    self._maybe_refresh_legacy_schedules()
                    return new_state
            except Exception as e:
                _LOGGER.warning(
                    "Error polling cloud device %s: %s", self.device_name, e
                )

            self._on_cloud_failure()
            if self._consecutive_cloud_failures >= _FAILURE_THRESHOLD:
                raise UpdateFailed(
                    f"Cloud device {self.device_name} unreachable after "
                    f"{self._consecutive_cloud_failures} consecutive failures"
                )

        self._maybe_refresh_legacy_schedules()
        return self.data

    def _on_cloud_success(self) -> None:
        """Reset failure counter and restore base poll interval."""
        if self._consecutive_cloud_failures > 0:
            _LOGGER.debug(
                "Cloud device %s recovered after %d failure(s)",
                self.device_name,
                self._consecutive_cloud_failures,
            )
        self._consecutive_cloud_failures = 0
        if self._base_poll_interval:
            self.update_interval = self._base_poll_interval

    def _on_cloud_failure(self) -> None:
        """Increment failure counter and apply exponential backoff."""
        self._consecutive_cloud_failures += 1
        if self._base_poll_interval:
            backoff = self._base_poll_interval * (
                2 ** min(self._consecutive_cloud_failures, 4)
            )
            self.update_interval = min(backoff, _MAX_BACKOFF_INTERVAL)
            _LOGGER.debug(
                "Cloud device %s: failure %d, next poll in %s",
                self.device_name,
                self._consecutive_cloud_failures,
                self.update_interval,
            )

    async def _async_store_doc(self) -> dict[str, Any]:
        """The merged .storage document, read from disk at most once.

        Single-flight: concurrent first callers share one dict, or the last
        save would drop the keys the others wrote.
        """
        if self._store_data is None:
            async with self._store_load_lock:
                if self._store_data is None:
                    self._store_data = await self._store.async_load() or {}
        return self._store_data

    async def _async_store_save(self, **values: Any) -> None:
        """Merge ``values`` into the shared document and persist it."""
        data = await self._async_store_doc()
        data.update(values)
        # async_save cancels a pending delayed write; carry its map state along.
        if self._map_state_ready():
            self._map_state_doc()
        await self._store.async_save(data)

    def _map_state_ready(self) -> bool:
        """Whether the in-memory map state may overwrite the stored one."""
        return self._storage_loaded and self._map_data is not None

    async def async_load_storage(self) -> None:
        """Load data from storage."""
        try:
            await self._async_load_storage()
        finally:
            self._storage_loaded = True

    async def _async_load_storage(self) -> None:
        """Read and apply the persisted document. See ``async_load_storage``."""
        if data := await self._async_store_doc():
            self.last_seen_segments = data.get("last_seen_segments")
            _LOGGER.debug(
                "Loaded %s segments from storage for %s",
                len(self.last_seen_segments) if self.last_seen_segments else 0,
                self.device_name,
            )
            self.last_seen_maps = {
                int(k): v for k, v in (data.get("last_seen_maps") or {}).items()
            }
            if map_b64 := data.pop("map_image_png", None):
                # Popped, not read: left in the document it rejoins every save.
                self.map_image = base64.b64decode(map_b64)
                _LOGGER.debug(
                    "Loaded cached map image (%d bytes) for %s",
                    len(self.map_image),
                    self.device_name,
                )
            if prev := data.get("previous_trail"):
                self._previous_trail = [tuple(p) for p in prev]
            if trail := data.get("robot_trail"):
                # Only a clean STILL RUNNING gets its trail back.
                if self.data.activity == "cleaning":
                    self._robot_trail = [tuple(p) for p in trail]
                    # Stored cells carry no type; padded, then set from raw.
                    self._robot_trail_types = [0] * len(self._robot_trail)
                    self._robot_trail_raw = [
                        (int(x), int(y), int(t))
                        for x, y, t in data.get("robot_trail_raw") or []
                    ]
                    _LOGGER.debug(
                        "Loaded robot trail (%d points) for %s",
                        len(self._robot_trail),
                        self.device_name,
                    )
                else:
                    # A stored trail whose session ended IS the previous clean.
                    self._previous_trail = [tuple(p) for p in trail]
                    _LOGGER.debug(
                        "Stored trail (%d points) kept as the previous run for %s — "
                        "not cleaning (%s)",
                        len(trail),
                        self.device_name,
                        self.data.activity,
                    )
            if dp := data.get("dock_pixel"):
                self._dock_pixel = tuple(dp)
            if rooms := data.get("rooms"):
                if not self.data.rooms:
                    self.data = replace(self.data, rooms=[dict(r) for r in rooms])
            self._map_version = data.get("map_version")
            self._fetched_map_cid = data.get("fetched_map_cid")
            if polys := data.get("legacy_room_polygons"):
                self._legacy_room_polygons = {
                    int(rid): [(int(x), int(y)) for x, y in pts]
                    for rid, pts in polys.items()
                }
            if md_raw := data.get("map_data"):
                try:
                    restored = MapData(
                        raw_pixels=base64.b64decode(md_raw["raw_pixels"]),
                        width=md_raw["width"],
                        height=md_raw["height"],
                        origin_x=md_raw["origin_x"],
                        origin_y=md_raw["origin_y"],
                        resolution=md_raw["resolution"],
                        room_pixels=base64.b64decode(md_raw["room_pixels"]) if md_raw.get("room_pixels") else None,
                        room_outline_width=md_raw.get("room_outline_width", 0),
                        room_outline_height=md_raw.get("room_outline_height", 0),
                        room_outline_origin_x=md_raw.get("room_outline_origin_x", 0),
                        room_outline_origin_y=md_raw.get("room_outline_origin_y", 0),
                        room_names={int(k): v for k, v in md_raw.get("room_names", {}).items()},
                        room_id_offset=md_raw.get("room_id_offset", 0),
                        dock_pixel=(
                            tuple(md_raw["dock_pixel"])
                            if md_raw.get("dock_pixel") else None
                        ),
                        virtual_walls=[(tuple(w[0]), tuple(w[1])) for w in md_raw.get("virtual_walls", [])],
                        forbidden_zones=[[tuple(p) for p in zone] for zone in md_raw.get("forbidden_zones", [])],
                        ban_mop_zones=[[tuple(p) for p in zone] for zone in md_raw.get("ban_mop_zones", [])],
                    )
                    self._set_map_data(restored)
                    # The blob has no outlines; a parked robot sends no 0x65.
                    self._apply_legacy_room_polygons()
                    if restored.dock_pixel is None and self._dock_pixel:
                        # With no dock, the pose transform places nothing.
                        restored.dock_pixel = self._dock_pixel
                    if self._robot_trail_raw and restored.dock_pixel is not None:
                        # Raw points carry the real TYPES and place exactly.
                        left = self._rebuild_trail_from_raw()
                        _LOGGER.debug(
                            "Re-placed %d restored trail points for %s (%d raw, %d"
                            " off-grid)", len(self._robot_trail), self.device_name,
                            len(self._robot_trail_raw), left,
                        )
                    _LOGGER.debug("Loaded map data from storage for %s", self.device_name)
                except Exception as exc:
                    _LOGGER.warning("Failed to restore map data for %s: %s", self.device_name, exc)

    @callback
    def _schedule_map_state_save(self) -> None:
        """Write the map state at most ``_MAP_STATE_SAVE_DELAY`` after a change.

        ``Store.async_delay_save`` moves a pending write out to the latest call's
        delay, so a render every 2 s would hold it off for the whole clean: it is
        armed only when no write is pending, and the write reads the state then.
        Store flushes a pending write at HA stop.
        """
        if self._map_state_save_armed:
            return
        if self._store_data is None:
            if not self._storage_loaded:
                # async_load_storage restores over this state; nothing to keep yet.
                return
            # A failed read left no document in memory; read it first.
            self._map_state_save_armed = True
            self._spawn(self._async_schedule_map_state_save(), "map_state_save")
            return
        self._map_state_save_armed = True
        self._store.async_delay_save(self._map_state_doc, _MAP_STATE_SAVE_DELAY)

    async def _async_schedule_map_state_save(self) -> None:
        """Load the document, then queue the delayed map-state write."""
        try:
            await self._async_store_doc()
        except BaseException:
            self._map_state_save_armed = False
            raise
        self._store.async_delay_save(self._map_state_doc, _MAP_STATE_SAVE_DELAY)

    async def _async_save_map_state(self) -> None:
        """Persist the map state now. Teardown and tests; runtime uses the delayed save."""
        # Store drops its copy on save; async_load() would hit the disk.
        await self._async_store_doc()
        await self._store.async_save(self._map_state_doc())

    def _map_state_doc(self) -> dict[str, Any]:
        """The shared .storage document with the current trail, dock and map merged in.

        Deliberately NOT gated on ``map_image``: this is device state, so gating it
        would make a lazy render come back blank after a restart.
        """
        # Every write carrying the map state calls this; the next change re-arms.
        self._map_state_save_armed = False
        if self._store_data is None:
            self._store_data = {}
        data = self._store_data
        # Written even when empty or None: the document is shared and long-lived,
        # so a skipped key would restore the previous session's value.
        data["robot_trail"] = list(self._robot_trail)
        # Cells move with the map; raw points are dock-relative.
        data["robot_trail_raw"] = [list(p) for p in self._robot_trail_raw]
        data["previous_trail"] = list(self._previous_trail)
        data["dock_pixel"] = list(self._dock_pixel) if self._dock_pixel else None
        # Without this, startup cannot tell if the map is current.
        data["map_version"] = self._map_version
        if self._fetched_map_cid is not None:
            data["fetched_map_cid"] = self._fetched_map_cid
        if self.data.rooms:
            # Rebuilt only by a fetch; a skipped download must not lose it.
            data["rooms"] = [dict(room) for room in self.data.rooms]
        if self._legacy_room_polygons:
            # Kept in the stream's world frame; cells move with the map.
            data["legacy_room_polygons"] = {
                str(rid): [list(pt) for pt in pts]
                for rid, pts in self._legacy_room_polygons.items()
            }
        if self._map_data is not None:
            md = self._map_data
            data["map_data"] = {
                "raw_pixels": base64.b64encode(md.raw_pixels).decode(),
                "width": md.width,
                "height": md.height,
                "origin_x": md.origin_x,
                "origin_y": md.origin_y,
                "resolution": md.resolution,
                "room_pixels": base64.b64encode(md.room_pixels).decode() if md.room_pixels else None,
                "room_outline_width": md.room_outline_width,
                "room_outline_height": md.room_outline_height,
                "room_outline_origin_x": md.room_outline_origin_x,
                "room_outline_origin_y": md.room_outline_origin_y,
                "room_names": {str(k): v for k, v in md.room_names.items()},
                "room_id_offset": md.room_id_offset,
                # The pose transform reads THIS dock, not _dock_pixel.
                "dock_pixel": list(md.dock_pixel) if md.dock_pixel else None,
                "virtual_walls": [[list(p) for p in wall] for wall in md.virtual_walls],
                "forbidden_zones": [[list(p) for p in zone] for zone in md.forbidden_zones],
                "ban_mop_zones": [[list(p) for p in zone] for zone in md.ban_mop_zones],
            }
        return data

    async def async_save_segments(self, segments_payload: list[dict[str, Any]]) -> None:
        """Save segments to storage."""
        self.last_seen_segments = segments_payload
        await self._async_store_save(last_seen_segments=segments_payload)
        _LOGGER.debug(
            "Saved %s segments to storage for %s",
            len(segments_payload),
            self.device_name,
        )

    def _remember_map_id(self, map_id: int | None) -> None:
        """Record a visited map id into ``last_seen_maps`` and persist it.

        Id only; the friendly name is layered in later from the biz stream.
        """
        if map_id and map_id > 0 and map_id not in self.last_seen_maps:
            self.last_seen_maps[map_id] = ""
            self._spawn(self.async_save_maps(), "save_maps")

    async def async_save_maps(self) -> None:
        """Persist discovered saved-map id→name to storage."""
        await self._async_store_save(
            last_seen_maps={str(k): v for k, v in self.last_seen_maps.items()}
        )
        _LOGGER.debug(
            "Saved %s discovered maps to storage for %s",
            len(self.last_seen_maps),
            self.device_name,
        )

    async def async_forget_map(self, cloud_mapid: int) -> bool:
        """Drop a map id from ``last_seen_maps`` so the selector stops offering it.

        The list is learn-as-seen with nothing authoritative to reconcile against,
        so a deleted map lingers without this. Local only; the robot is not told.
        """
        if self.last_seen_maps.pop(cloud_mapid, None) is None:
            return False
        await self.async_save_maps()
        self.async_update_listeners()
        _LOGGER.debug("Forgot map %d for %s", cloud_mapid, self.device_name)
        return True
