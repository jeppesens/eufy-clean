"""Parse biz/ MQTT protocol-41 map stream messages into ``MapData``.

Rendering lives in :mod:`.map_render`.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from ..proto.cloud import stream_pb2
from ..utils import decode_varint
from .map_render import MAX_MAP_PIXELS, MAX_ROOM_ID

_LOGGER = logging.getLogger(__name__)


# Room scene type → fallback label when room.name is empty
_ROOM_SCENE_NAMES: dict[int, str] = {
    1: "STUDY", 2: "BEDROOM", 3: "RESTROOM", 4: "KITCHEN",
    5: "LIVING RM", 6: "DINING RM", 7: "CORRIDOR",
}


@dataclass
class MapData:
    """Decoded map pixel data from a Map or MapBackup proto."""
    raw_pixels: bytes
    width: int
    height: int
    origin_x: int = 0
    origin_y: int = 0
    resolution: int = 5
    room_pixels: bytes | None = field(default=None, repr=False)
    room_outline_width: int = 0
    room_outline_height: int = 0
    room_outline_origin_x: int = 0
    room_outline_origin_y: int = 0
    room_names: dict[int, str] = field(default_factory=dict)
    virtual_walls: list[tuple[tuple[int, int], tuple[int, int]]] = field(default_factory=list)
    forbidden_zones: list[list[tuple[int, int]]] = field(default_factory=list)
    ban_mop_zones: list[list[tuple[int, int]]] = field(default_factory=list)

    def room_id_at_normalized(self, nx: float, ny: float) -> int | None:
        """Return the room id under a normalized point on the *rendered* map image.

        ``(nx, ny)`` are fractions (0-1) of the rendered PNG, top-left origin (the
        HA camera-image convention — the same space the zone card draws in). This
        is the exact inverse of the renderer's room-mask lookup: map the point
        back to a source grid pixel (undoing the baked-in Y-flip, exactly as
        ``normalized_rects_to_quads_cm`` does), then index ``room_pixels`` with the
        same outline origin offset the renderer uses. Returns ``None`` when there
        is no room mask or the point is outside any room. Room ids are 0-31 (0 is
        a real room on some robots); 60-63 mark background, gaps and obstacles.
        """
        if not self.room_pixels or not self.room_outline_width or not self.room_outline_height:
            return None
        nx = min(max(float(nx), 0.0), 1.0)
        ny = min(max(float(ny), 0.0), 1.0)
        res = self.resolution or 5
        w, h = self.width, self.height
        # normalized (rendered, top-left) -> source grid pixel; the render Y-flips,
        # so the displayed top edge is the source bottom row.
        px = min(max(round(nx * w), 0), max(w - 1, 0))
        py = min(max(round((h - 1) - ny * h), 0), max(h - 1, 0))
        # the room mask has its own origin; this offset matches render_map_png's _ro_dx/_ro_dy.
        ro_dx = round((self.origin_x - self.room_outline_origin_x) / res)
        ro_dy = round((self.origin_y - self.room_outline_origin_y) / res)
        rx, ry = px - ro_dx, py - ro_dy
        if 0 <= rx < self.room_outline_width and 0 <= ry < self.room_outline_height:
            idx = ry * self.room_outline_width + rx
            if 0 <= idx < len(self.room_pixels):
                rid = self.room_pixels[idx] >> 2  # low 2 bits are the pixel type
                if rid <= MAX_ROOM_ID and (not self.room_names or rid in self.room_names):
                    return rid
        return None


# ---------------------------------------------------------------------------
# Low-level helpers (LZ4)
# ---------------------------------------------------------------------------

def _hex_to_proto_bytes(hex_data: str) -> bytes:
    raw = bytes.fromhex(hex_data)
    _, pos = decode_varint(raw, 0)
    return raw[pos:]


def _lz4_block_decompress(data: bytes, uncompressed_size: int) -> bytes:
    """Decode one LZ4 block, enforcing its declared size and valid backreferences."""
    if not 0 <= uncompressed_size <= MAX_MAP_PIXELS:
        raise ValueError("decompressed map exceeds the pixel limit")
    output = bytearray()
    pos = 0

    def length(value: int) -> int:
        nonlocal pos
        if value == 15:
            while True:
                if pos >= len(data):
                    raise ValueError("truncated LZ4 length")
                extra = data[pos]
                pos += 1
                value += extra
                if extra != 255:
                    break
        return value

    while pos < len(data):
        token = data[pos]
        pos += 1
        literal = length(token >> 4)
        if pos + literal > len(data) or len(output) + literal > uncompressed_size:
            raise ValueError("invalid LZ4 literal length")
        output.extend(data[pos : pos + literal])
        pos += literal
        if pos == len(data):
            break
        if pos + 2 > len(data):
            raise ValueError("truncated LZ4 offset")
        offset = int.from_bytes(data[pos : pos + 2], "little")
        pos += 2
        match = length(token & 0xF) + 4
        if not 0 < offset <= len(output) or len(output) + match > uncompressed_size:
            raise ValueError("invalid LZ4 match")
        for _ in range(match):
            output.append(output[-offset])
    if len(output) != uncompressed_size:
        raise ValueError("LZ4 output does not match its declared size")
    return bytes(output)


# ---------------------------------------------------------------------------
# Parse helpers
# ---------------------------------------------------------------------------

def _quad_points(q: Any) -> list[tuple[int, int]]:
    return [(q.p0.x, q.p0.y), (q.p1.x, q.p1.y), (q.p2.x, q.p2.y), (q.p3.x, q.p3.y)]


# ---------------------------------------------------------------------------
# Protocol parsing
# ---------------------------------------------------------------------------

def try_extract_map_data(hex_data: str) -> MapData | None:
    """Try to extract MapData from biz/ channel hex data.

    Attempts MapBackup first (map-edit snapshot), then plain Map (cleaning stream).
    """
    try:
        proto_bytes = _hex_to_proto_bytes(hex_data)
    except Exception:
        return None

    map_msg = None
    room_pixels: bytes | None = None
    ro_width = ro_height = ro_origin_x = ro_origin_y = 0
    room_names: dict[int, str] = {}
    virtual_walls: list[tuple[tuple[int, int], tuple[int, int]]] = []
    forbidden_zones: list[list[tuple[int, int]]] = []
    ban_mop_zones: list[list[tuple[int, int]]] = []

    try:
        backup = stream_pb2.MapBackup().FromString(proto_bytes)
        if backup.map.pixels and backup.map.pixel_size:
            map_msg = backup.map

            ro = backup.rooms
            if ro.pixels and ro.pixel_size and ro.width and ro.height:
                rp = ro.pixels
                if len(rp) != ro.pixel_size:
                    rp = _lz4_block_decompress(rp, ro.pixel_size)
                room_pixels = rp
                ro_width, ro_height = ro.width, ro.height
                ro_origin_x, ro_origin_y = ro.origin.x, ro.origin.y
                _LOGGER.debug("RoomOutline decoded: %dx%d origin=(%d,%d)", ro_width, ro_height, ro_origin_x, ro_origin_y)

            for room in backup.room_params.rooms:
                name = room.name.strip()
                if not name:
                    name = _ROOM_SCENE_NAMES.get(room.scene.type, f"ROOM {room.id}")
                room_names[room.id] = name
            _LOGGER.debug("RoomParams room_names: %s", room_names)

            rz = backup.restricted_zone
            for wall in rz.virtual_walls:
                virtual_walls.append(((wall.p0.x, wall.p0.y), (wall.p1.x, wall.p1.y)))
            for zone in rz.forbidden_zones:
                forbidden_zones.append(_quad_points(zone))
            for zone in rz.ban_mop_zones:
                ban_mop_zones.append(_quad_points(zone))

            _LOGGER.debug(
                "RestrictedZone: %d walls, %d forbidden, %d ban-mop",
                len(virtual_walls), len(forbidden_zones), len(ban_mop_zones),
            )
    except Exception:
        pass

    if map_msg is None:
        try:
            m = stream_pb2.Map().FromString(proto_bytes)
            if m.pixels and m.pixel_size:
                map_msg = m
        except Exception:
            pass

    if map_msg is None or not map_msg.info.width or not map_msg.info.height:
        return None

    raw = map_msg.pixels
    if len(raw) != map_msg.pixel_size:
        try:
            raw = _lz4_block_decompress(raw, map_msg.pixel_size)
        except Exception as exc:
            _LOGGER.debug("LZ4 decompress failed: %s", exc)
            return None

    _LOGGER.debug(
        "Map decoded: %dx%d id=%d res=%d origin=(%d,%d)",
        map_msg.info.width, map_msg.info.height, map_msg.id,
        map_msg.info.resolution, map_msg.info.origin.x, map_msg.info.origin.y,
    )

    return MapData(
        raw_pixels=raw,
        width=map_msg.info.width,
        height=map_msg.info.height,
        origin_x=map_msg.info.origin.x,
        origin_y=map_msg.info.origin.y,
        resolution=map_msg.info.resolution or 5,
        room_pixels=room_pixels,
        room_outline_width=ro_width,
        room_outline_height=ro_height,
        room_outline_origin_x=ro_origin_x,
        room_outline_origin_y=ro_origin_y,
        room_names=room_names,
        virtual_walls=virtual_walls,
        forbidden_zones=forbidden_zones,
        ban_mop_zones=ban_mop_zones,
    )


def try_extract_map_description(hex_data: str) -> tuple[int, str] | None:
    """Extract ``(map_id, name)`` from a biz/ ``MapDescription`` frame, or None.

    Each saved map's id and friendly name arrive over the cloud map stream as a
    single-shot ``MapDescription`` when that map becomes active (e.g. after a map
    switch). Other small biz/ frames (robot pose ``DynamicData``, ``RoomParams``)
    can also decode without raising, so guard strictly: require a positive
    ``map_id`` and a short, printable name. Used for map discovery (the Active Map
    selector), which is why only id+name — not pixels — are returned.
    """
    try:
        proto_bytes = _hex_to_proto_bytes(hex_data)
        desc = stream_pb2.MapDescription().FromString(proto_bytes)
    except Exception:
        return None
    # Strip surrounding whitespace: renaming a map to a name Eufy considers
    # "unchanged" is rejected, so users seed a name by adding a trailing space —
    # keep the visible label clean.
    name = desc.name.strip()
    if desc.map_id > 0 and name and name.isprintable() and len(name) <= 48:
        return desc.map_id, name
    return None


def try_decode_as_dynamic_data(hex_data: str) -> tuple[int, int, int] | None:
    """Decode channel as DynamicData robot pose. Returns (x_cm, y_cm, theta_crad) or None."""
    try:
        proto_bytes = _hex_to_proto_bytes(hex_data)
        dyn = stream_pb2.DynamicData().FromString(proto_bytes)
        pose = dyn.cur_pose
        if pose.x != 0 or pose.y != 0:
            return pose.x, pose.y, pose.theta
    except Exception:
        pass
    return None


def parse_biz_protocol41(payload: bytes) -> tuple[int, str] | None:
    """Parse a biz/ MQTT message. Returns (channel_id, hex_data) or None."""
    try:
        msg = json.loads(payload)
        payload_data = msg.get("payload", {})
        if isinstance(payload_data, str):
            payload_data = json.loads(payload_data)
        data = payload_data.get("data", {})
        if not isinstance(data, dict):
            return None
        channel_id = data.get("channel_id")
        hex_data = data.get("data", "")
        if channel_id is None or not hex_data:
            _LOGGER.debug("biz/ missing channel_id or data — keys: %s", list(data.keys()))
            return None
        return channel_id, hex_data
    except Exception as exc:
        _LOGGER.debug("biz/ JSON parse failed: %s — first 200: %s", exc, payload[:200])
        return None
