"""Parse biz/ MQTT protocol-41 map stream messages and render PNG."""
from __future__ import annotations

import io
import json
import logging
from dataclasses import dataclass, field
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from ..proto.cloud import stream_pb2
from ..utils import decode_varint

_LOGGER = logging.getLogger(__name__)

# 2bpp pixel value → RGB (fallback when RoomOutline not available)
_PIXEL_COLORS: dict[int, tuple[int, int, int]] = {
    0: (30, 30, 30),    # UNKNOWN / unexplored
    1: (20, 20, 20),    # OBSTACLE / wall
    2: (200, 200, 200), # FREE floor
    3: (200, 200, 200), # CLEANED / carpet — same as free floor so it blends in
}

# Room ID → RGB.  Index 0 = wall/outside (unused in combined render); 1-N cycle.
_ROOM_PALETTE: list[tuple[int, int, int]] = [
    (45, 45, 45),
    (100, 150, 200),
    (150, 200, 130),
    (200, 160, 130),
    (180, 140, 200),
    (200, 190, 110),
    (140, 190, 200),
    (200, 130, 150),
    (160, 200, 180),
]

# Room scene type → fallback label when room.name is empty
_ROOM_SCENE_NAMES: dict[int, str] = {
    1: "STUDY", 2: "BEDROOM", 3: "RESTROOM", 4: "KITCHEN",
    5: "LIVING RM", 6: "DINING RM", 7: "CORRIDOR",
}

# Robot status badge: (circle_color, dark_symbol_pixel_offsets_from_badge_centre)
_STATUS_BADGE: dict[str, tuple[tuple[int, int, int], list[tuple[int, int]]]] = {
    "charging": (
        (255, 240, 0),  # bright yellow
        # Compact Z-bolt sized for r=5 badge
        [
            (0,-3),(1,-3),
            (-1,-2),(0,-2),
            (-2,-1),(-1,-1),(0,-1),(1,-1),
            (0,0),(1,0),
            (-1,1),(0,1),
            (-1,2),(-2,2),
        ],
    ),
    "emptying": (
        (160, 160, 160),  # grey
        [(-1, -1), (1, -1), (0, 0), (-1, 1), (1, 1)],
    ),
    "drying": (
        (135, 206, 235),  # sky blue
        [(-1, -1), (0, -1), (-1, 0), (0, 0), (-1, 1), (0, 1)],
    ),
    "washing": (
        (65, 105, 225),  # royal blue
        [(0, -1), (-1, 0), (1, 0), (-1, 1), (1, 1), (0, 2)],
    ),
    "station": (
        (180, 100, 210),  # purple
        [(0, -1), (-1, 0), (0, 0), (1, 0), (0, 1)],
    ),
}

# Dock icon — solid house pixel offsets (dx, dy) relative to dock centre.
_HOUSE_FILL: frozenset[tuple[int, int]] = frozenset([
    (0,-4),
    (-1,-3),(0,-3),(1,-3),
    (-2,-2),(-1,-2),(0,-2),(1,-2),(2,-2),
    (-3,-1),(-2,-1),(-1,-1),(0,-1),(1,-1),(2,-1),(3,-1),
    (-3,0),(-2,0),(-1,0),(0,0),(1,0),(2,0),(3,0),
    (-3,1),(-2,1),(-1,1),(0,1),(1,1),(2,1),(3,1),
    (-3,2),(-2,2),(2,2),(3,2),
    (-3,3),(-2,3),(2,3),(3,3),
])
_HOUSE_DOOR: tuple[tuple[int, int], ...] = (
    (-1,2),(0,2),(1,2),(-1,3),(0,3),(1,3),
)

_MAX_PNG_PX = 512


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


# ---------------------------------------------------------------------------
# Low-level helpers (LZ4)
# ---------------------------------------------------------------------------

def _hex_to_proto_bytes(hex_data: str) -> bytes:
    raw = bytes.fromhex(hex_data)
    _, pos = decode_varint(raw, 0)
    return raw[pos:]


def _lz4_block_decompress(data: bytes, uncompressed_size: int) -> bytes:
    output = bytearray()
    pos = 0
    n = len(data)
    while pos < n:
        token = data[pos]; pos += 1
        lit_len = (token >> 4) & 0xF
        if lit_len == 15:
            while pos < n:
                extra = data[pos]; pos += 1
                lit_len += extra
                if extra != 255:
                    break
        output.extend(data[pos: pos + lit_len]); pos += lit_len
        if pos >= n:
            break
        offset = data[pos] | (data[pos + 1] << 8); pos += 2
        match_len = (token & 0xF) + 4
        if (token & 0xF) == 15:
            while pos < n:
                extra = data[pos]; pos += 1
                match_len += extra
                if extra != 255:
                    break
        match_start = len(output) - offset
        for i in range(match_len):
            output.append(output[match_start + i])
    return bytes(output)


# ---------------------------------------------------------------------------
# Parse helpers
# ---------------------------------------------------------------------------

def _quad_points(q: Any) -> list[tuple[int, int]]:
    return [(q.p0.x, q.p0.y), (q.p1.x, q.p1.y), (q.p2.x, q.p2.y), (q.p3.x, q.p3.y)]


# ---------------------------------------------------------------------------
# Main render
# ---------------------------------------------------------------------------

def render_map_png(
    map_data: MapData,
    robot_pixel: tuple[int, int] | None = None,
    robot_trail: list[tuple[int, int]] | None = None,
    dock_pixel: tuple[int, int] | None = None,
    robot_status: str | None = None,
    max_px: int = _MAX_PNG_PX,
    robot_style: str = "googly",
) -> bytes:
    """Render a PNG from MapData using Pillow.

    Pipeline:
    1. Build flat color list from map pixels (room palette + lidar fallback).
    2. putdata() into PIL Image, Y-flip, LANCZOS scale.
    3. Draw restricted zones, room labels, dock icon, trail, robot marker.
    4. Encode to PNG bytes via img.save().
    """
    width, height = map_data.width, map_data.height
    res = map_data.resolution or 5
    room_px = map_data.room_pixels

    # ------------------------------------------------------------------
    # Step 1 — build pixel color list + accumulate room centroids
    # ------------------------------------------------------------------
    _ro_w = _ro_h = _ro_dx = _ro_dy = 0
    raw = map_data.raw_pixels
    colors: list[tuple[int, int, int]] = []
    # rid → [sum_src_x, sum_src_y, count]  (source pixel space)
    src_centroids: dict[int, list[int]] = {}
    _has_room_names = bool(room_px is not None and map_data.room_outline_width and map_data.room_names)

    if room_px is not None and map_data.room_outline_width and map_data.room_outline_height:
        _ro_w = map_data.room_outline_width
        _ro_h = map_data.room_outline_height
        _ro_dx = round((map_data.origin_x - map_data.room_outline_origin_x) / res)
        _ro_dy = round((map_data.origin_y - map_data.room_outline_origin_y) / res)
        palette_len = len(_ROOM_PALETTE)
        for py in range(height):
            for px_x in range(width):
                i = py * width + px_x
                byte_pos = i >> 2
                bit_pos = (i & 3) * 2
                pv = (raw[byte_pos] >> bit_pos) & 3 if byte_pos < len(raw) else 0
                rx, ry = px_x - _ro_dx, py - _ro_dy
                if 0 <= rx < _ro_w and 0 <= ry < _ro_h:
                    rpx = room_px[ry * _ro_w + rx]
                    rid = rpx >> 2
                    sub_type = rpx & 3
                else:
                    rid = sub_type = 0
                if rid > 0:
                    if sub_type == 0 or pv in (2, 3):
                        color = _ROOM_PALETTE[1 + (rid - 1) % (palette_len - 1)]
                    else:
                        color = _PIXEL_COLORS.get(pv, (30, 30, 30))
                else:
                    color = _PIXEL_COLORS.get(pv, (30, 30, 30))
                colors.append(color)
                if _has_room_names and rid > 0 and rid in map_data.room_names:
                    if rid not in src_centroids:
                        src_centroids[rid] = [0, 0, 0]
                    src_centroids[rid][0] += px_x
                    src_centroids[rid][1] += py
                    src_centroids[rid][2] += 1
    else:
        for i in range(width * height):
            byte_pos = i >> 2
            bit_pos = (i & 3) * 2
            pv = (raw[byte_pos] >> bit_pos) & 3 if byte_pos < len(raw) else 0
            colors.append(_PIXEL_COLORS.get(pv, (30, 30, 30)))

    # ------------------------------------------------------------------
    # Step 2 — create PIL image, Y-flip, scale
    # ------------------------------------------------------------------
    img: Image.Image = Image.new("RGB", (width, height))
    img.putdata(colors)
    img = img.transpose(Image.Transpose.FLIP_TOP_BOTTOM)

    scale = min(max_px / max(width, height), 1.0)
    out_w = max(1, round(width * scale))
    out_h = max(1, round(height * scale))
    if scale < 1.0:
        img = img.resize((out_w, out_h), Image.Resampling.LANCZOS)

    draw = ImageDraw.Draw(img)

    # Map pixel → output pixel (Y-flip baked in)
    def _to_out(mx: int, my: int) -> tuple[int, int]:
        return round(mx * scale), round((height - 1 - my) * scale)

    # World cm → output pixel
    def _world_to_out(wx: int, wy: int) -> tuple[int, int]:
        return _to_out(
            round((wx - map_data.origin_x) / res),
            round((wy - map_data.origin_y) / res),
        )

    # Filled circle helper
    def _circle(cx: float, cy: float, r: float, color: tuple[int, int, int]) -> None:
        if r < 1.0:
            draw.point((round(cx), round(cy)), fill=color)
        else:
            draw.ellipse([(cx - r, cy - r), (cx + r, cy + r)], fill=color)

    # ------------------------------------------------------------------
    # Step 3 — restricted zones
    # ------------------------------------------------------------------
    _BAN_MOP_COLOR = (255, 165, 0)
    _ZONE_COLOR = (220, 50, 50)

    for zone in map_data.ban_mop_zones:
        pts = [_world_to_out(p[0], p[1]) for p in zone]
        if len(pts) >= 2:
            draw.polygon(pts, outline=_BAN_MOP_COLOR)

    for zone in map_data.forbidden_zones:
        pts = [_world_to_out(p[0], p[1]) for p in zone]
        if len(pts) >= 2:
            draw.polygon(pts, outline=_ZONE_COLOR)

    for wall in map_data.virtual_walls:
        draw.line(
            [_world_to_out(wall[0][0], wall[0][1]), _world_to_out(wall[1][0], wall[1][1])],
            fill=_ZONE_COLOR,
        )

    # ------------------------------------------------------------------
    # Step 4 — dock icon (pixel-art house)
    # (labels drawn after trail in step 6 so they render on top)
    # ------------------------------------------------------------------
    if dock_pixel is not None:
        dx, dy = _to_out(dock_pixel[0], dock_pixel[1])
        _house_border = {
            (nx, ny)
            for ox, oy in _HOUSE_FILL
            for nx, ny in ((ox + ddx, oy + ddy) for ddx in (-1, 0, 1) for ddy in (-1, 0, 1))
            if (nx, ny) not in _HOUSE_FILL
        }
        for ox, oy in _house_border:
            bpx, bpy = dx + ox, dy + oy
            if 0 <= bpx < out_w and 0 <= bpy < out_h:
                draw.point((bpx, bpy), fill=(100, 75, 0))
        for ox, oy in _HOUSE_FILL:
            bpx, bpy = dx + ox, dy + oy
            if 0 <= bpx < out_w and 0 <= bpy < out_h:
                draw.point((bpx, bpy), fill=(255, 215, 0))
        for ox, oy in _HOUSE_DOOR:
            bpx, bpy = dx + ox, dy + oy
            if 0 <= bpx < out_w and 0 <= bpy < out_h:
                draw.point((bpx, bpy), fill=(100, 75, 0))

    # ------------------------------------------------------------------
    # Step 5 — cleaning trail
    # ------------------------------------------------------------------
    _TRAIL = (255, 140, 0)
    _MAX_TRAIL_JUMP_SQ = 400 * 400
    if robot_trail:
        raw_pts = list(robot_trail)
        out_pts = [_to_out(tx, ty) for tx, ty in raw_pts]
        for i in range(len(raw_pts) - 1):
            ddx = raw_pts[i + 1][0] - raw_pts[i][0]
            ddy = raw_pts[i + 1][1] - raw_pts[i][1]
            if ddx * ddx + ddy * ddy <= _MAX_TRAIL_JUMP_SQ:
                draw.line([out_pts[i], out_pts[i + 1]], fill=_TRAIL)
        ox, oy = out_pts[-1]
        if 0 <= ox < out_w and 0 <= oy < out_h:
            draw.point((ox, oy), fill=_TRAIL)

    # ------------------------------------------------------------------
    # Step 6 — room name labels (after trail so labels render on top)
    # ------------------------------------------------------------------
    if src_centroids:
        try:
            font: ImageFont.ImageFont | ImageFont.FreeTypeFont = ImageFont.load_default(size=9)
        except TypeError:
            font = ImageFont.load_default()
        _LABEL_COLOR = (30, 30, 30)
        _LABEL_BG = (255, 255, 255)
        for rid, vals in src_centroids.items():
            if vals[2] == 0:
                continue
            label = map_data.room_names[rid].upper()
            if not label:
                continue
            ox, oy = _to_out(vals[0] // vals[2], vals[1] // vals[2])
            bbox = draw.textbbox((0, 0), label, font=font)
            tw = bbox[2] - bbox[0]
            th = bbox[3] - bbox[1]
            draw.rectangle(
                [(ox - tw // 2 - 2, oy - th // 2 - 1), (ox + tw // 2 + 2, oy + th // 2 + 1)],
                fill=_LABEL_BG,
            )
            draw.text((ox - tw // 2 - bbox[0], oy - th // 2 - bbox[1]), label, fill=_LABEL_COLOR, font=font)

    # ------------------------------------------------------------------
    # Step 7 — robot marker + status badge
    # ------------------------------------------------------------------
    if robot_pixel is not None:
        orx, ory = _to_out(robot_pixel[0], robot_pixel[1])
        if robot_style == "dot":
            _circle(orx, ory, 5.0, (20, 20, 20))
            _circle(orx, ory, 4.0, (55, 55, 55))
        else:  # "googly" (default)
            _circle(orx, ory, 5.0, (160, 70, 0))
            _circle(orx, ory, 4.0, (255, 140, 0))
            for ex, ey in ((-1, -1), (2, -1)):
                _circle(orx + ex, ory + ey, 1.5, (255, 255, 255))
                _circle(orx + ex, ory + ey, 0.6, (20, 20, 20))

        if robot_status and robot_status in _STATUS_BADGE:
            badge_color, icon_offsets = _STATUS_BADGE[robot_status]
            bx, by = orx + 6, ory - 6
            _circle(bx, by, 6.0, (30, 30, 30))
            _circle(bx, by, 5.0, badge_color)
            for ox2, oy2 in icon_offsets:
                bpx, bpy = bx + ox2, by + oy2
                if 0 <= bpx < out_w and 0 <= bpy < out_h:
                    draw.point((bpx, bpy), fill=(20, 20, 20))

    # ------------------------------------------------------------------
    # Step 8 — encode PNG
    # ------------------------------------------------------------------
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=False, compress_level=3)
    return buf.getvalue()


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


def try_decode_as_metadata(hex_data: str) -> Any | None:
    """Decode channel as Metadata proto. Returns ChanIds if map_data channel present."""
    try:
        proto_bytes = _hex_to_proto_bytes(hex_data)
        meta = stream_pb2.Metadata().FromString(proto_bytes)
        if meta.chan_ids.map_data:
            return meta.chan_ids
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
