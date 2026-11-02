"""Decode the P2P stream objects into one live map model.

Three streams arrive on the map conversation (see :mod:`.streams`):

``map.bin.stream``
    Length-delimited ``MapChannelMsg`` objects. Each carries the map geometry
    (id, size, origin, docks) plus one payload keyed by ``map_info.msg_type``:
    the room outline bitmap, the real-time SLAM bitmap, the room list, obstacles,
    restricted zones, cruise data or the current target. The S1 Pro re-sends the
    whole set every ~2 s while it is moving and once per session when it is not.

``cleanPath.bin.stream``
    Length-delimited ``CompletePath``: LZ4-compressed 5-byte points
    (``x i16 BE | y i16 BE | flags``, centimetres). The first object of a session
    is the whole path so far; later objects append. An empty object resets the
    path (a new clean started).

``navPath.bin`` / ``navPath.bin.stream``
    Length-delimited ``DynamicData``: the robot's current pose.

Coordinates are the device world frame: centimetres, ``theta`` in rad * 100.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from google.protobuf.message import DecodeError

from ...proto.cloud.p2pdata_pb2 import CompletePath, MapChannelMsg, MapInfo
from ...proto.cloud.stream_pb2 import DynamicData
from ...utils import decode_varint
from ..map_stream import _lz4_block_decompress
from .streams import CLEAN_PATH_STREAM, MAP_STREAM, NAV_PATH_STREAM

_LOGGER = logging.getLogger(__name__)

# A runaway path (a corrupt length) must not grow without bound.
_MAX_PATH_POINTS = 200_000

CHANGED_MAP = "map"
CHANGED_ROOMS = "rooms"
CHANGED_OBSTACLES = "obstacles"
CHANGED_ZONES = "zones"
CHANGED_TARGET = "target"
CHANGED_PATH = "path"
CHANGED_POSE = "pose"


@dataclass(frozen=True, slots=True)
class Pose:
    x: int
    y: int
    theta: int  # rad * 100


@dataclass(frozen=True, slots=True)
class Obstacle:
    object_type: str
    points: tuple[tuple[int, int], ...]


@dataclass(slots=True)
class P2PMap:
    """Everything the P2P channel has told us about the current map."""

    map_id: int = 0
    width: int = 0
    height: int = 0
    origin_x: int = 0
    origin_y: int = 0
    docks: list[Pose] = field(default_factory=list)
    # Room outline: one byte per pixel (room id << 2 | pixel type).
    outline: bytes | None = None
    # Real-time SLAM map: four pixels per byte, two bits each. Not every model
    # sends one; the S1 Pro relies on the outline alone.
    realtime: bytes | None = None
    realtime_width: int = 0
    realtime_height: int = 0
    realtime_origin_x: int = 0
    realtime_origin_y: int = 0
    rooms: list[dict] = field(default_factory=list)
    obstacles: list[Obstacle] = field(default_factory=list)
    virtual_walls: list[tuple[tuple[int, int], tuple[int, int]]] = field(default_factory=list)
    forbidden_zones: list[list[tuple[int, int]]] = field(default_factory=list)
    ban_mop_zones: list[list[tuple[int, int]]] = field(default_factory=list)
    target_room_ids: list[int] = field(default_factory=list)
    target_zones: list[list[tuple[int, int]]] = field(default_factory=list)
    path: list[tuple[int, int, int]] = field(default_factory=list)  # (x, y, flags)
    pose: Pose | None = None

    @property
    def has_map(self) -> bool:
        return bool(self.width and self.height and (self.outline or self.realtime))

    @property
    def dock(self) -> Pose | None:
        return self.docks[0] if self.docks else None


def _delimited(buffer: bytes) -> bytes:
    """Strip the varint length prefix of a length-delimited protobuf."""
    length, start = decode_varint(buffer, 0)
    return buffer[start : start + length]


def _decompress(pixels) -> bytes:
    if pixels.pixel_size and len(pixels.pixels) != pixels.pixel_size:
        return _lz4_block_decompress(pixels.pixels, pixels.pixel_size)
    return bytes(pixels.pixels)


def _quad(q) -> list[tuple[int, int]]:
    return [(q.p0.x, q.p0.y), (q.p1.x, q.p1.y), (q.p2.x, q.p2.y), (q.p3.x, q.p3.y)]


def decode_path(raw: bytes) -> list[tuple[int, int, int]]:
    """Decode packed 5-byte path points into ``(x, y, flags)`` tuples."""
    points = []
    for pos in range(0, len(raw) - 4, 5):
        x = int.from_bytes(raw[pos : pos + 2], "big", signed=True)
        y = int.from_bytes(raw[pos + 2 : pos + 4], "big", signed=True)
        points.append((x, y, raw[pos + 4]))
    return points


class P2PMapDecoder:
    """Fold stream objects into a :class:`P2PMap`.

    Call :meth:`start_session` whenever a new P2P session opens so the next path
    object is taken as a full snapshot rather than appended.
    """

    def __init__(self, state: P2PMap | None = None) -> None:
        self.state = state or P2PMap()
        self._path_snapshot_pending = True

    def start_session(self) -> None:
        self._path_snapshot_pending = True

    def apply(self, name: str, obj: bytes) -> set[str]:
        """Apply one stream object; return the aspects that changed."""
        try:
            if name == MAP_STREAM:
                return self._apply_map(obj)
            if name == CLEAN_PATH_STREAM:
                return self._apply_path(obj)
            if name.startswith(NAV_PATH_STREAM.removesuffix(".stream")):
                return self._apply_pose(obj)
        except (DecodeError, IndexError, ValueError) as err:
            _LOGGER.debug("p2p: undecodable %s object (%d bytes): %s", name, len(obj), err)
            return set()
        _LOGGER.debug("p2p: ignoring unknown stream %s (%d bytes)", name, len(obj))
        return set()

    def _apply_map(self, obj: bytes) -> set[str]:
        message = MapChannelMsg()
        message.ParseFromString(_delimited(obj))
        if message.type != MapChannelMsg.MAP_INFO or not message.HasField("map_info"):
            return set()
        info = message.map_info
        s = self.state
        changed: set[str] = set()
        if info.map_id != s.map_id:
            # Room ids, targets and geometry belong to one map. A room update
            # can precede its bitmap, so never combine it with the previous map.
            s = self.state = P2PMap()
            self._path_snapshot_pending = True
            changed.add(CHANGED_ROOMS)

        geometry = (info.map_id, info.map_width, info.map_height, info.origin.x, info.origin.y)
        if geometry != (s.map_id, s.width, s.height, s.origin_x, s.origin_y):
            s.outline = s.realtime = None
            s.map_id, s.width, s.height, s.origin_x, s.origin_y = geometry
            changed.add(CHANGED_MAP)
        docks = [Pose(d.x, d.y, d.theta) for d in info.docks]
        if docks and docks != s.docks:
            s.docks = docks
            changed.add(CHANGED_MAP)

        kind = info.msg_type
        if kind == MapInfo.MAP_ROOMOUTLINE and info.pixels.pixel_size:
            outline = _decompress(info.pixels)
            if len(outline) == info.map_width * info.map_height and outline != s.outline:
                s.outline = outline
                changed.add(CHANGED_MAP)
        elif kind == MapInfo.MAP_REALTIME and info.pixels.pixel_size:
            realtime = _decompress(info.pixels)
            if realtime != s.realtime:
                s.realtime = realtime
                s.realtime_width, s.realtime_height = info.map_width, info.map_height
                s.realtime_origin_x, s.realtime_origin_y = info.origin.x, info.origin.y
                changed.add(CHANGED_MAP)
        elif kind == MapInfo.ROOM_PARAMS:
            rooms = [
                {
                    "id": room.id,
                    "name": room.name.strip(),
                    "order": room.order.value,
                    "scene": room.scene.type,
                }
                for room in info.room_params.rooms
            ]
            if rooms != s.rooms:
                s.rooms = rooms
                changed.add(CHANGED_ROOMS)
        elif kind == MapInfo.OBSTACLE_INFO:
            obstacles = [
                Obstacle(
                    object_type=o.object_type,
                    points=tuple((p.x, p.y) for p in o.show_points),
                )
                for o in info.obstacles.obstacles
                if not o.HasField("valid") or o.valid.value
            ]
            if obstacles != s.obstacles:
                s.obstacles = obstacles
                changed.add(CHANGED_OBSTACLES)
        elif kind == MapInfo.RESTRICT_ZONES:
            zones = info.restricted_zones
            walls = [((w.p0.x, w.p0.y), (w.p1.x, w.p1.y)) for w in zones.virtual_walls]
            forbidden = [_quad(z) for z in zones.forbidden_zones]
            ban_mop = [_quad(z) for z in zones.ban_mop_zones]
            if (walls, forbidden, ban_mop) != (s.virtual_walls, s.forbidden_zones, s.ban_mop_zones):
                s.virtual_walls, s.forbidden_zones, s.ban_mop_zones = walls, forbidden, ban_mop
                changed.add(CHANGED_ZONES)
        elif kind == MapInfo.TEMPORARY_DATA:
            temp = info.temporary_data
            room_ids = [r.id for r in temp.select_rooms_clean.rooms]
            target_zones = [_quad(z.quadrangle) for z in temp.select_zones_clean.zones]
            if (room_ids, target_zones) != (s.target_room_ids, s.target_zones):
                s.target_room_ids, s.target_zones = room_ids, target_zones
                changed.add(CHANGED_TARGET)
        return changed

    def _apply_path(self, obj: bytes) -> set[str]:
        message = CompletePath()
        message.ParseFromString(_delimited(obj))
        raw = message.path
        if message.path_lz4len and message.path_lz4len != len(raw):
            raw = _lz4_block_decompress(raw, message.path_lz4len)
        points = decode_path(raw)[-_MAX_PATH_POINTS:]
        s = self.state
        if self._path_snapshot_pending or not points:
            # A session's first path object is the full path; an empty one resets it.
            self._path_snapshot_pending = False
            if points == s.path:
                return set()
            s.path = points
        else:
            s.path.extend(points)
            if len(s.path) > _MAX_PATH_POINTS:
                del s.path[: len(s.path) - _MAX_PATH_POINTS]
        return {CHANGED_PATH}

    def _apply_pose(self, obj: bytes) -> set[str]:
        message = DynamicData()
        message.ParseFromString(_delimited(obj))
        if not message.HasField("cur_pose"):
            return set()
        pose = Pose(message.cur_pose.x, message.cur_pose.y, message.cur_pose.theta)
        if pose == self.state.pose:
            return set()
        self.state.pose = pose
        return {CHANGED_POSE}
