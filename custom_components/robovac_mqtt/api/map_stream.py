"""Parse biz/ MQTT protocol-41 map stream messages and render PNG."""
from __future__ import annotations

import io
import json
import logging
import math
from dataclasses import dataclass, field
from typing import Any

from PIL import Image, ImageChops, ImageDraw, ImageFont

from ..const import DEFAULT_TRAIL_COLOR
from ..proto.cloud import stream_pb2
from ..utils import decode_varint, lz4_block_decompress
from .tuya_map import (
    _MAX_MAP_DIMENSION,
    CELL_OBSTACLE,
    CELL_WALL,
    TuyaMap,
)

_LOGGER = logging.getLogger(__name__)

# 2bpp pixel value → RGB (fallback when RoomOutline not available)
_PIXEL_COLORS: dict[int, tuple[int, int, int]] = {
    0: (30, 30, 30),    # UNKNOWN / unexplored
    1: (20, 20, 20),    # OBSTACLE / wall
    2: (200, 200, 200), # FREE floor
    3: (200, 200, 200), # CLEANED / carpet — same as free floor, so it blends in
}

# Room ID → RGB; index 0 = wall/outside, 1-N cycle.
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

# Translate tables unpacking a 2 bpp byte: table ``slot`` yields pixel ``slot``
# (lowest bits first).
_UNPACK_2BPP: tuple[bytes, ...] = tuple(
    bytes((b >> (2 * slot)) & 3 for b in range(256)) for slot in range(4)
)

# Render key per cell: ``room_key + pv`` with pv in 0-3. ``room_key`` is
# ``(colour_slot * 2 + fill) * 4``: colour_slot 0 = no room, 1-8 = the room's
# palette entry; fill = sub-type 0, which paints the room colour over any pv.
_ROOM_COLOUR_SLOTS = len(_ROOM_PALETTE) - 1
_RENDER_KEYS = (_ROOM_COLOUR_SLOTS + 1) * 2 * 4


def _room_key(stored: int) -> int:
    rid, sub_type = stored >> 2, stored & 3
    slot = 1 + (rid - 1) % _ROOM_COLOUR_SLOTS if rid > 0 else 0
    return (slot * 2 + (sub_type == 0)) * 4


def _render_key_colour(key: int) -> tuple[int, int, int]:
    pv, fill, slot = key & 3, (key >> 2) & 1, key >> 3
    if slot and (fill or pv in (2, 3)):
        return _ROOM_PALETTE[slot]
    return _PIXEL_COLORS[pv]


_ROOM_KEY_TABLE = bytes(_room_key(stored) for stored in range(256))
_RENDER_PALETTE: list[int] = [
    channel for key in range(_RENDER_KEYS) for channel in _render_key_colour(key)
]
# Stored room-mask byte → room id (the low 2 bits are the sub-type).
_ROOM_ID_TABLE = bytes(stored >> 2 for stored in range(256))
# pv → 255 for free floor (2), else 0.
_FLOOR_TABLE = bytes(255 if pv == 2 else 0 for pv in range(256))

# Room scene type → fallback label when room.name is empty
_ROOM_SCENE_NAMES: dict[int, str] = {
    1: "STUDY", 2: "BEDROOM", 3: "RESTROOM", 4: "KITCHEN",
    5: "LIVING RM", 6: "DINING RM", 7: "CORRIDOR",
}

# Robot status badge: (circle_color, dark symbol offsets from the badge centre)
_STATUS_BADGE: dict[str, tuple[tuple[int, int, int], list[tuple[int, int]]]] = {
    "charging": (
        (255, 240, 0),  # bright yellow
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

# Dock icon — house pixel offsets (dx, dy) from the dock centre.
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

_MAX_PNG_PX = 1024

# Overlay artwork drawn on the grid is scaled by ``out_px / _UI_REFERENCE_PX``.
_UI_REFERENCE_PX = 512

# Tuya ``0pam`` geometry is in 0.5 cm units; the grid is 5 cm per cell.
_TUYA_UNITS_PER_CELL = 10

# Squared cell distance beyond which trail points are cut into separate runs
# instead of joined.
_MAX_TRAIL_JUMP_SQ = 400 * 400
# Catmull-Rom subdivisions per source segment; the spline interpolates its points.
_TRAIL_SMOOTH_STEPS = 6
_TRAIL_WIDTH = 2.0
# Stroke supersampling for anti-aliasing, dropped to 1 above the pixel budget
# below (which sits above any output the 1024 px cap can produce).
_TRAIL_SUPERSAMPLE = 2
_TRAIL_SUPERSAMPLE_MAX_PX = 2048 * 1024


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
    # Added to a real room id before storing it in ``room_pixels``: a stored 0 means
    # "no room", so Tuya's 0-based rooms offset by one. ``room_names`` uses real ids.
    room_id_offset: int = 0
    virtual_walls: list[tuple[tuple[float, float], tuple[float, float]]] = field(default_factory=list)
    forbidden_zones: list[list[tuple[float, float]]] = field(default_factory=list)
    ban_mop_zones: list[list[tuple[float, float]]] = field(default_factory=list)
    # Dock position in *rendered* map-pixel space (``render_map_png``'s
    # ``dock_pixel`` frame). Only the Tuya ``0pam`` path fills this.
    dock_pixel: tuple[float, float] | None = None
    # Room outline polygons ``{real_room_id: [(col, row), ...]}`` in the stored grid
    # frame of ``raw_pixels``. Legacy only, from the live 0x65 ``ROOM`` channel.
    room_polygons: dict[int, list[tuple[float, float]]] = field(default_factory=dict)

    def room_id_at_normalized(self, nx: float, ny: float) -> int | None:
        """Return the room id at a normalized point on the rendered map, or None.

        ``(nx, ny)`` are 0-1 fractions of the rendered PNG with a top-left origin
        (the HA camera-image convention); this is the exact inverse of
        ``render_map_png``'s room-mask lookup.
        """
        if not self.room_pixels or not self.room_outline_width or not self.room_outline_height:
            return None
        nx = min(max(float(nx), 0.0), 1.0)
        ny = min(max(float(ny), 0.0), 1.0)
        res = self.resolution or 5
        w, h = self.width, self.height
        # normalized (rendered, top-left) -> source grid pixel; the render Y-flips.
        # FLOOR, not round: the card hit-tests the same grid with `Math.floor`.
        px = min(max(int(nx * w), 0), max(w - 1, 0))
        py = min(max(int((1.0 - ny) * h), 0), max(h - 1, 0))
        # the room mask has its own origin; matches render_map_png's _ro_dx/_ro_dy.
        ro_dx = round((self.origin_x - self.room_outline_origin_x) / res)
        ro_dy = round((self.origin_y - self.room_outline_origin_y) / res)
        rx, ry = px - ro_dx, py - ro_dy
        if 0 <= rx < self.room_outline_width and 0 <= ry < self.room_outline_height:
            idx = ry * self.room_outline_width + rx
            if 0 <= idx < len(self.room_pixels):
                stored = self.room_pixels[idx] >> 2  # low 2 bits are sub-type
                if stored > 0:
                    return stored - self.room_id_offset
        return None


def room_polygons_to_cells(
    polygons: dict[int, list[tuple[int, int]]],
    *,
    origin_x: int,
    origin_y: int,
    height: int,
) -> dict[int, list[tuple[float, float]]]:
    """Convert 0x65 ``ROOM`` outline polygons into stored-frame grid cells.

    Vertices arrive in the blob's 0.5 cm *world* frame, so a top-down cell is
    ``(v + origin) / 10``; the row is flipped to match ``MapData``'s bottom-up grid.
    """
    out: dict[int, list[tuple[float, float]]] = {}
    for room_id, points in polygons.items():
        cells = [
            (
                (x + origin_x) / _TUYA_UNITS_PER_CELL,
                (height - 1) - (y + origin_y) / _TUYA_UNITS_PER_CELL,
            )
            for x, y in points
        ]
        if len(cells) >= 3:  # a polygon needs three vertices to enclose anything
            out[room_id] = cells
    return out


def map_data_from_tuya_map(tuya_map: TuyaMap) -> MapData:
    """Convert a parsed Tuya ``0pam`` blob into renderable :class:`MapData`.

    One signed byte per cell becomes 2 bpp pixels (0 unknown, 1 obstacle, 2 floor)
    plus a one-byte room mask holding ``id << 2``; Tuya rooms are 0-based, so ids
    are offset by one. Both planes are row-flipped to cancel render_map_png's
    Y-flip.
    """
    width, height = tuya_map.width, tuya_map.height
    packed = bytearray((width * height + 3) // 4)
    rooms = bytearray(width * height)

    for index, cell in enumerate(tuya_map.grid):
        row, column = divmod(index, width)
        index = (height - 1 - row) * width + column
        signed = cell - 256 if cell > 127 else cell
        if signed in (CELL_OBSTACLE, CELL_WALL):
            value = 1
        elif signed >= 0:
            value = 2
            rooms[index] = (signed // 4 + 1) << 2
        else:  # CELL_UNMAPPED and anything unrecognised
            value = 0
        if value:
            packed[index >> 2] |= value << ((index & 3) * 2)

    # Dock pose is 0.5 cm units in the blob's top-down frame; flip the row like the
    # grid planes above.
    dock_pixel: tuple[int, int] | None = None
    if tuya_map.dock_pose is not None:
        dock_x, dock_y, _theta = tuya_map.dock_pose
        dock_pixel = (
            round(dock_x / _TUYA_UNITS_PER_CELL),
            height - 1 - round(dock_y / _TUYA_UNITS_PER_CELL),
        )

    # Walls and zones are 0.5 cm units in a *world* frame: a cell is
    # ``(coord + origin) / 10``, row pre-flipped to cancel render_map_png's Y-flip.
    # ``_RENDER_RES`` mirrors ``MapData.resolution``'s default (unset on this path).
    _RENDER_RES = 5

    def _geom(bx: int, by: int) -> tuple[float, float]:
        column = (bx + tuya_map.origin_x) / _TUYA_UNITS_PER_CELL
        row = height - 1 - (by + tuya_map.origin_y) / _TUYA_UNITS_PER_CELL
        return (
            tuya_map.origin_x + column * _RENDER_RES,
            tuya_map.origin_y + row * _RENDER_RES,
        )

    return MapData(
        raw_pixels=bytes(packed),
        width=width,
        height=height,
        origin_x=tuya_map.origin_x,
        origin_y=tuya_map.origin_y,
        room_pixels=bytes(rooms),
        room_outline_width=width,
        room_outline_height=height,
        room_outline_origin_x=tuya_map.origin_x,
        room_outline_origin_y=tuya_map.origin_y,
        room_names=tuya_map.room_names,
        room_id_offset=1,
        virtual_walls=[
            (_geom(wall[0], wall[1]), _geom(wall[2], wall[3]))
            for wall in tuya_map.virtual_walls
        ],
        forbidden_zones=[
            [_geom(zone[0], zone[1]), _geom(zone[2], zone[3]),
             _geom(zone[4], zone[5]), _geom(zone[6], zone[7])]
            for zone in tuya_map.forbidden_zones
        ],
        ban_mop_zones=[
            [_geom(zone[0], zone[1]), _geom(zone[2], zone[3]),
             _geom(zone[4], zone[5]), _geom(zone[6], zone[7])]
            for zone in tuya_map.ban_mop_zones
        ],
        dock_pixel=dock_pixel,
    )


def _hex_to_proto_bytes(hex_data: str) -> bytes:
    raw = bytes.fromhex(hex_data)
    _, pos = decode_varint(raw, 0)
    return raw[pos:]


def _check_map_dimensions(width: int, height: int) -> None:
    """Raise ValueError unless each side is within ``0..._MAX_MAP_DIMENSION``."""
    if not (0 <= width <= _MAX_MAP_DIMENSION and 0 <= height <= _MAX_MAP_DIMENSION):
        raise ValueError(
            f"Map dimensions {width}x{height} exceed safety limit "
            f"(max {_MAX_MAP_DIMENSION}x{_MAX_MAP_DIMENSION})"
        )


def _pixel_plane(raw: bytes, cells: int) -> bytes:
    """Unpack 2 bpp ``raw_pixels`` to one byte (0-3) per cell; missing cells read 0."""
    plane = bytearray(len(raw) * 4)
    for slot, table in enumerate(_UNPACK_2BPP):
        plane[slot::4] = raw.translate(table)
    if len(plane) >= cells:
        return bytes(plane[:cells])
    return bytes(plane) + bytes(cells - len(plane))


def _room_mask_plane(map_data: MapData) -> bytes | None:
    """Register the room mask onto the map grid: one stored mask byte per cell.

    Cells outside the mask, or past the end of a short mask, read 0 (no room).
    None when the map has no usable mask.
    """
    room_px = map_data.room_pixels
    ro_w = map_data.room_outline_width
    ro_h = map_data.room_outline_height
    if room_px is None or not ro_w or not ro_h:
        return None
    width, height = map_data.width, map_data.height
    res = map_data.resolution or 5
    ro_dx = round((map_data.origin_x - map_data.room_outline_origin_x) / res)
    ro_dy = round((map_data.origin_y - map_data.room_outline_origin_y) / res)
    x0 = max(0, ro_dx)
    x1 = min(width, ro_w + ro_dx)
    plane = bytearray(width * height)
    if x0 >= x1:
        return bytes(plane)
    span = x1 - x0
    for py in range(max(0, ro_dy), min(height, ro_h + ro_dy)):
        src = (py - ro_dy) * ro_w + (x0 - ro_dx)
        row = room_px[src : src + span]
        dst = py * width + x0
        plane[dst : dst + len(row)] = row
    return bytes(plane)


def _room_centroids(
    mask: bytes, width: int, height: int, map_data: MapData
) -> dict[int, list[int]]:
    """``{label_id: [sum_x, sum_y, count]}`` over named rooms, in source pixels.

    Keys are in row-major order of each room's first cell.
    """
    rid_plane = mask.translate(_ROOM_ID_TABLE)
    rid_image = Image.frombytes("L", (width, height), rid_plane)
    counts = rid_image.histogram()
    offset = map_data.room_id_offset
    rids = [
        rid for rid in range(1, 64)
        if counts[rid] and rid - offset in map_data.room_names
    ]
    if not rids:
        return {}
    rids.sort(key=rid_plane.find)
    # Column-major copy: column x is bytes [x * height, (x + 1) * height).
    columns = rid_image.transpose(Image.Transpose.TRANSPOSE).tobytes()
    centroids: dict[int, list[int]] = {}
    for rid in rids:
        sum_x = sum(
            x * columns.count(rid, x * height, (x + 1) * height) for x in range(width)
        )
        sum_y = sum(
            y * rid_plane.count(rid, y * width, (y + 1) * width) for y in range(height)
        )
        centroids[rid - offset] = [sum_x, sum_y, counts[rid]]
    return centroids


def _label_box(
    cx: float, cy: float, tw: float, th: float, margin: float
) -> tuple[float, float, float, float]:
    """Bounding box of a ``tw`` x ``th`` label centred on ``(cx, cy)``, plus margin."""
    return (cx - tw / 2 - margin, cy - th / 2 - margin,
            cx + tw / 2 + margin, cy + th / 2 + margin)


def _quad_points(q: Any) -> list[tuple[float, float]]:
    return [(q.p0.x, q.p0.y), (q.p1.x, q.p1.y), (q.p2.x, q.p2.y), (q.p3.x, q.p3.y)]


# Legacy 0x67 point types: 0 = cleaning, 1 = transit.
_TRAIL_TYPE_TRANSIT = 1
# Dash geometry for transit legs, in output pixels before supersampling.
_TRAIL_DASH_ON = 6.0
_TRAIL_DASH_OFF = 5.0


def _dash(
    points: list[tuple[float, float]], on: float, off: float
) -> list[list[tuple[float, float]]]:
    """Cut a polyline into dashes, returning the "on" segments.

    Walks by arc length, so the dash rhythm stays even regardless of how finely
    the curve was subdivided.
    """
    if len(points) < 2 or on <= 0 or off <= 0:
        return [points] if len(points) >= 2 else []
    segments: list[list[tuple[float, float]]] = []
    current: list[tuple[float, float]] = [points[0]]
    drawing = True
    remaining = on
    for start, end in zip(points, points[1:]):
        dx, dy = end[0] - start[0], end[1] - start[1]
        length = (dx * dx + dy * dy) ** 0.5
        if length == 0:
            continue
        travelled = 0.0
        while length - travelled > remaining:
            travelled += remaining
            t = travelled / length
            point = (start[0] + dx * t, start[1] + dy * t)
            if drawing:
                current.append(point)
                segments.append(current)
                current = []
            else:
                current = [point]
            drawing = not drawing
            remaining = on if drawing else off
        remaining -= length - travelled
        if drawing:
            current.append(end)
    if drawing and len(current) >= 2:
        segments.append(current)
    return segments


def split_trail_runs(
    points: list[tuple[float, float]],
    max_jump_sq: int = _MAX_TRAIL_JUMP_SQ,
    types: list[int] | None = None,
) -> list[tuple[list[tuple[float, float]], int]]:
    """Cut a trail into ``(run, type)`` pairs, breaking on jumps and type changes.

    A jump beyond ``max_jump_sq`` is a relocalisation and must never be joined by a
    line through walls. Splitting happens on the raw source cells, so no smoothing
    can interpolate across a gap. Each run carries its type (0 when unknown).
    """
    runs: list[tuple[list[tuple[float, float]], int]] = []
    current: list[tuple[float, float]] = []
    current_type = 0
    for index, point in enumerate(points):
        point_type = types[index] if types is not None and index < len(types) else 0
        if current:
            dx = point[0] - points[index - 1][0]
            dy = point[1] - points[index - 1][1]
            if dx * dx + dy * dy > max_jump_sq or point_type != current_type:
                runs.append((current, current_type))
                current = []
        if not current:
            current_type = point_type
        current.append(point)
    if current:
        runs.append((current, current_type))
    return runs


def catmull_rom(
    points: list[tuple[float, float]], steps: int = _TRAIL_SMOOTH_STEPS
) -> list[tuple[float, float]]:
    """Resample a polyline along a uniform Catmull-Rom spline through its points.

    The curve interpolates every input point, so smoothing only rounds corners.
    End points are duplicated to give the outer segments a control point.
    """
    if len(points) < 3 or steps < 2:
        return [(float(x), float(y)) for x, y in points]
    padded = [points[0], *points, points[-1]]
    out: list[tuple[float, float]] = [(float(points[0][0]), float(points[0][1]))]
    for i in range(len(padded) - 3):
        p0, p1, p2, p3 = padded[i], padded[i + 1], padded[i + 2], padded[i + 3]
        for step in range(1, steps + 1):
            t = step / steps
            t2 = t * t
            t3 = t2 * t
            out.append((
                0.5 * (2 * p1[0]
                       + (-p0[0] + p2[0]) * t
                       + (2 * p0[0] - 5 * p1[0] + 4 * p2[0] - p3[0]) * t2
                       + (-p0[0] + 3 * p1[0] - 3 * p2[0] + p3[0]) * t3),
                0.5 * (2 * p1[1]
                       + (-p0[1] + p2[1]) * t
                       + (2 * p0[1] - 5 * p1[1] + 4 * p2[1] - p3[1]) * t2
                       + (-p0[1] + 3 * p1[1] - 3 * p2[1] + p3[1]) * t3),
            ))
    return out


def _draw_outlined_text(
    draw: ImageDraw.ImageDraw,
    xy: tuple[float, float],
    text: str,
    font: Any,
    fill: tuple[int, int, int],
    outline: tuple[int, int, int],
    width: int,
) -> None:
    """Draw ``text`` in ``fill`` ringed by an ``outline`` halo, no backdrop box.

    Pillow's ``stroke_width``/``stroke_fill`` needs a FreeType font; the bitmap
    font old Pillow falls back to raises ``TypeError``, so stamp the halo by hand.
    """
    try:
        draw.text(xy, text, font=font, fill=fill, stroke_width=width, stroke_fill=outline)
        return
    except TypeError:
        pass
    for dx in range(-width, width + 1):
        for dy in range(-width, width + 1):
            if dx or dy:
                draw.text((xy[0] + dx, xy[1] + dy), text, font=font, fill=outline)
    draw.text(xy, text, font=font, fill=fill)


def render_map_png(
    map_data: MapData,
    robot_pixel: tuple[float, float] | None = None,
    robot_trail: list[tuple[float, float]] | None = None,
    robot_trail_types: list[int] | None = None,
    dock_pixel: tuple[float, float] | None = None,
    robot_status: str | None = None,
    max_px: int = _MAX_PNG_PX,
    robot_style: str = "googly",
    clip_trail_to_floor: bool = False,
    trail_color: tuple[int, int, int] | None = None,
) -> bytes:
    """Render a PNG from MapData using Pillow.

    ``max_px`` bounds the longer output edge in both directions, so a smaller map
    is upscaled. Resampling is NEAREST throughout: the room fill is paletted, so a
    smooth filter invents colours on every shared boundary.
    """
    width, height = map_data.width, map_data.height
    _check_map_dimensions(width, height)
    cells = width * height
    res = map_data.resolution or 5
    room_px = map_data.room_pixels
    raw = map_data.raw_pixels
    pv_plane = _pixel_plane(raw, cells)
    mask = _room_mask_plane(map_data) if room_px is not None else None

    # One palette index per cell (see ``_RENDER_KEYS``): room key OR pixel value.
    if mask is None:
        index_plane = pv_plane
    else:
        keys = mask.translate(_ROOM_KEY_TABLE)
        index_plane = (int.from_bytes(keys) | int.from_bytes(pv_plane)).to_bytes(cells)

    # label id → [sum_src_x, sum_src_y, count]  (source pixel space)
    src_centroids: dict[int, list[int]] = {}
    if mask is not None and map_data.room_names:
        src_centroids = _room_centroids(mask, width, height, map_data)

    img: Image.Image = Image.frombytes("P", (width, height), index_plane)
    img.putpalette(_RENDER_PALETTE)
    img = img.transpose(Image.Transpose.FLIP_TOP_BOTTOM)

    scale = max_px / max(width, height)
    out_w = max(1, round(width * scale))
    out_h = max(1, round(height * scale))
    if (out_w, out_h) != (width, height):
        img = img.resize((out_w, out_h), Image.Resampling.NEAREST)
    img = img.convert("RGB")

    # Overlay artwork scale: 1.0 at the 512 px reference size.
    ui = max(1.0, max(out_w, out_h) / _UI_REFERENCE_PX)
    pix = max(1, round(ui))  # side of one pixel-art unit (dock house, badge icon)

    draw = ImageDraw.Draw(img)

    # Map pixel → output pixel, Y-flip baked in; aim at the cell's centre.
    def _to_out(mx: float, my: float) -> tuple[int, int]:
        return (
            round((mx + 0.5) * scale - 0.5),
            round((height - 1 - my + 0.5) * scale - 0.5),
        )

    # World cm → output pixel
    def _world_to_out(wx: float, wy: float) -> tuple[int, int]:
        return _to_out(
            round((wx - map_data.origin_x) / res),
            round((wy - map_data.origin_y) / res),
        )

    def _circle(cx: float, cy: float, r: float, color: tuple[int, int, int]) -> None:
        if r < 1.0:
            draw.point((round(cx), round(cy)), fill=color)
        else:
            draw.ellipse([(cx - r, cy - r), (cx + r, cy + r)], fill=color)

    # Vector room outlines (legacy 0x65 ROOM channel) sharpen the blocky grid edges.
    # Same Y-flip as everything else, unrounded: these have sub-cell precision.
    if map_data.room_polygons:
        _OUTLINE = (255, 255, 255)
        _OUTLINE_ALPHA = 90
        _outline_w = max(1, round(ui))

        def _cell_to_out_f(cx: float, cy: float) -> tuple[float, float]:
            return (
                (cx + 0.5) * scale - 0.5,
                (height - 1 - cy + 0.5) * scale - 0.5,
            )

        outline_layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
        outline_draw = ImageDraw.Draw(outline_layer)
        for poly in map_data.room_polygons.values():
            if len(poly) < 3:
                continue
            pts = [_cell_to_out_f(cx, cy) for cx, cy in poly]
            outline_draw.line(
                [*pts, pts[0]],  # close the ring
                fill=(*_OUTLINE, _OUTLINE_ALPHA),
                width=_outline_w,
                joint="curve",
            )
        img = Image.alpha_composite(img.convert("RGBA"), outline_layer).convert("RGB")
        draw = ImageDraw.Draw(img)

    _BAN_MOP_COLOR = (255, 165, 0)
    _ZONE_COLOR = (220, 50, 50)
    # Wash the interior faintly as well; a hairline outline alone is easy to miss.
    _ZONE_FILL_ALPHA = 56
    _zone_width = max(1, round(1.5 * ui))

    if map_data.ban_mop_zones or map_data.forbidden_zones or map_data.virtual_walls:
        overlay = Image.new("RGBA", (out_w, out_h), (0, 0, 0, 0))
        odraw = ImageDraw.Draw(overlay)
        for zones, colour in (
            (map_data.ban_mop_zones, _BAN_MOP_COLOR),
            (map_data.forbidden_zones, _ZONE_COLOR),
        ):
            for zone in zones:
                pts = [_world_to_out(p[0], p[1]) for p in zone]
                if len(pts) >= 3:
                    odraw.polygon(
                        pts,
                        fill=(*colour, _ZONE_FILL_ALPHA),
                        outline=(*colour, 255),
                        width=_zone_width,
                    )
                elif len(pts) == 2:
                    odraw.line(pts, fill=(*colour, 255), width=_zone_width)
        for wall in map_data.virtual_walls:
            odraw.line(
                [_world_to_out(wall[0][0], wall[0][1]), _world_to_out(wall[1][0], wall[1][1])],
                fill=(*_ZONE_COLOR, 255),
                width=_zone_width,
            )
        img = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")
        draw = ImageDraw.Draw(img)

    # Pixel-art stamp: one art unit is a ``pix``-sided block, so artwork scales.
    def _stamp(cx: int, cy: int, offsets, color: tuple[int, int, int]) -> None:
        for ox, oy in offsets:
            bpx, bpy = cx + ox * pix, cy + oy * pix
            if -pix < bpx < out_w and -pix < bpy < out_h:
                if pix == 1:
                    draw.point((bpx, bpy), fill=color)
                else:
                    draw.rectangle([(bpx, bpy), (bpx + pix - 1, bpy + pix - 1)], fill=color)

    if dock_pixel is not None:
        dx, dy = _to_out(dock_pixel[0], dock_pixel[1])
        _house_border = {
            (nx, ny)
            for ox, oy in _HOUSE_FILL
            for nx, ny in ((ox + ddx, oy + ddy) for ddx in (-1, 0, 1) for ddy in (-1, 0, 1))
            if (nx, ny) not in _HOUSE_FILL
        }
        _stamp(dx, dy, _house_border, (100, 75, 0))
        _stamp(dx, dy, _HOUSE_FILL, (255, 215, 0))
        _stamp(dx, dy, _HOUSE_DOOR, (100, 75, 0))

    _trail_colour = tuple(trail_color) if trail_color else DEFAULT_TRAIL_COLOR
    if robot_trail:
        # Stroke into an oversized mask, downsample for AA, paste the colour through.
        ss = _TRAIL_SUPERSAMPLE if out_w * out_h <= _TRAIL_SUPERSAMPLE_MAX_PX else 1
        stroke = max(1, round(_TRAIL_WIDTH * ui)) * ss
        trail_layer = Image.new("L", (out_w * ss, out_h * ss), 0)
        tdraw = ImageDraw.Draw(trail_layer)
        for run, run_type in split_trail_runs(
            list(robot_trail), types=list(robot_trail_types) if robot_trail_types else None
        ):
            pts = [
                (x * ss, y * ss)
                for x, y in catmull_rom([_to_out(tx, ty) for tx, ty in run])
            ]
            if run_type == _TRAIL_TYPE_TRANSIT:
                # Transit legs are dashed: driven, not cleaned.
                dashes = _dash(pts, _TRAIL_DASH_ON * ss, _TRAIL_DASH_OFF * ss)
                for segment in dashes:
                    if len(segment) >= 2:
                        tdraw.line(segment, fill=255, width=stroke)
                continue
            if len(pts) >= 2:
                # No joint="curve": catmull_rom already subdivides ~6x, so its
                # per-vertex pieslices cost ~30% of render time and show nothing.
                tdraw.line(pts, fill=255, width=stroke)
            else:
                r = stroke / 2.0
                tdraw.ellipse(
                    [(pts[0][0] - r, pts[0][1] - r), (pts[0][0] + r, pts[0][1] + r)],
                    fill=255,
                )
        if ss > 1:
            # LANCZOS, not BILINEAR: averaging leaves a thin trail at ~50% coverage.
            trail_layer = trail_layer.resize((out_w, out_h), Image.Resampling.LANCZOS)

        if clip_trail_to_floor and raw:
            # The legacy 0x67 trail can cross an obstacle void; mask it to floor
            # cells (pv==2).
            floor_src = Image.frombytes(
                "L", (width, height), pv_plane.translate(_FLOOR_TABLE)
            )
            floor_src = floor_src.transpose(Image.Transpose.FLIP_TOP_BOTTOM)
            if (out_w, out_h) != (width, height):
                floor_src = floor_src.resize((out_w, out_h), Image.Resampling.NEAREST)
            trail_layer = ImageChops.multiply(trail_layer, floor_src)

        img.paste(Image.new("RGB", (out_w, out_h), _trail_colour), (0, 0), trail_layer)

    # Room labels come after the trail, so they render on top of it.
    if src_centroids:
        try:
            font: ImageFont.ImageFont | ImageFont.FreeTypeFont = ImageFont.load_default(
                size=max(9, round(9 * ui))
            )
        except TypeError:
            font = ImageFont.load_default()
        # White glyphs in a dark halo: readable on room fills and on the void alike.
        _LABEL_COLOR = (255, 255, 255)
        _LABEL_OUTLINE = (15, 15, 15)
        _label_stroke = max(1, round(1.5 * ui))
        _margin = _label_stroke + 1
        placed: list[tuple[float, float, float, float]] = []
        # Biggest room first, so large rooms keep their centroid and small ones move.
        for rid, vals in sorted(src_centroids.items(), key=lambda kv: -kv[1][2]):
            if vals[2] == 0:
                continue
            label = map_data.room_names[rid].upper()
            if not label:
                continue
            ox, oy = _to_out(vals[0] // vals[2], vals[1] // vals[2])
            bbox = draw.textbbox((0, 0), label, font=font)
            tw = bbox[2] - bbox[0]
            th = bbox[3] - bbox[1]

            # Nudge off the centroid only until it clears an already-placed label.
            step = th + 2 * _margin
            cx, cy = ox, oy
            for ddy in (0, -step, step, -2 * step, 2 * step):
                for ddx in (0, -tw / 2, tw / 2):
                    tx = min(max(ox + ddx, tw / 2 + _margin), out_w - tw / 2 - _margin)
                    ty = min(max(oy + ddy, th / 2 + _margin), out_h - th / 2 - _margin)
                    box = _label_box(tx, ty, tw, th, _margin)
                    if not any(box[0] < p[2] and p[0] < box[2]
                               and box[1] < p[3] and p[1] < box[3] for p in placed):
                        cx, cy = tx, ty
                        break
                else:
                    continue
                break
            else:
                # Nothing free — use the centroid, clamped so the name stays on-screen.
                cx = min(max(ox, tw / 2 + _margin), out_w - tw / 2 - _margin)
                cy = min(max(oy, th / 2 + _margin), out_h - th / 2 - _margin)
            placed.append(_label_box(cx, cy, tw, th, _margin))
            _draw_outlined_text(
                draw,
                (cx - tw / 2 - bbox[0], cy - th / 2 - bbox[1]),
                label,
                font,
                _LABEL_COLOR,
                _LABEL_OUTLINE,
                _label_stroke,
            )

    if robot_pixel is not None:
        orx, ory = _to_out(robot_pixel[0], robot_pixel[1])
        # The pose carries no type, so "in transit" is the newest trail point's type.
        in_transit = bool(
            robot_trail_types and robot_trail_types[-1] == _TRAIL_TYPE_TRANSIT
        )
        rot_angle = -math.pi / 2
        if robot_trail and len(robot_trail) > 0:
            last_p = robot_trail[-1]
            head_dx = robot_pixel[0] - last_p[0]
            head_dy = robot_pixel[1] - last_p[1]
            if head_dx == 0 and head_dy == 0 and len(robot_trail) >= 2:
                prev_p = robot_trail[-2]
                head_dx = last_p[0] - prev_p[0]
                head_dy = last_p[1] - prev_p[1]
            if head_dx != 0 or head_dy != 0:
                rot_angle = math.atan2(-head_dy, head_dx)

        theta = rot_angle + math.pi / 2
        cos_t = math.cos(theta)
        sin_t = math.sin(theta)

        if robot_style == "dot":
            _circle(orx, ory, 5.0 * ui, (20, 20, 20))
            _circle(orx, ory, 4.0 * ui, (70, 130, 180) if in_transit else (55, 55, 55))
            px = 0 * cos_t - (-2.5) * sin_t
            py = 0 * sin_t + (-2.5) * cos_t
            _circle(orx + px * ui, ory + py * ui, 1.2 * ui, (20, 20, 20))
            _circle(orx + px * ui, ory + py * ui, 0.7 * ui, (255, 255, 255))
        elif in_transit:
            _circle(orx, ory, 5.0 * ui, (20, 60, 100))
            _circle(orx, ory, 4.0 * ui, (70, 150, 230))
            for ex, ey in ((-1, -1), (2, -1)):
                rx = ex * cos_t - ey * sin_t
                ry = ex * sin_t + ey * cos_t
                _circle(orx + rx * ui, ory + ry * ui, 1.5 * ui, (255, 255, 255))
                _circle(orx + rx * ui, ory + ry * ui, 0.6 * ui, (20, 20, 20))
        else:  # "googly" (default)
            _circle(orx, ory, 5.0 * ui, (160, 70, 0))
            _circle(orx, ory, 4.0 * ui, (255, 140, 0))
            for ex, ey in ((-1, -1), (2, -1)):
                rx = ex * cos_t - ey * sin_t
                ry = ex * sin_t + ey * cos_t
                _circle(orx + rx * ui, ory + ry * ui, 1.5 * ui, (255, 255, 255))
                _circle(orx + rx * ui, ory + ry * ui, 0.6 * ui, (20, 20, 20))

        if robot_status and robot_status in _STATUS_BADGE:
            badge_color, icon_offsets = _STATUS_BADGE[robot_status]
            bx, by = round(orx + 6 * ui), round(ory - 6 * ui)
            _circle(bx, by, 6.0 * ui, (30, 30, 30))
            _circle(bx, by, 5.0 * ui, badge_color)
            _stamp(bx, by, icon_offsets, (20, 20, 20))

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=False, compress_level=3)
    return buf.getvalue()


def try_extract_map_data(hex_data: str) -> MapData | None:
    """Try to extract MapData from biz/ channel hex data.

    Attempts MapBackup first (map-edit snapshot), then plain Map (cleaning stream).
    Sizes are checked before anything is decompressed: each side at most
    ``_MAX_MAP_DIMENSION``, the 2 bpp map at most ``ceil(w * h / 4)`` bytes and the
    room mask exactly ``w * h``. A bad room mask drops only the mask. Pure and
    thread-safe, so a caller may run it in an executor.
    """
    try:
        proto_bytes = _hex_to_proto_bytes(hex_data)
    except Exception:
        return None

    map_msg = None
    room_pixels: bytes | None = None
    ro_width = ro_height = ro_origin_x = ro_origin_y = 0
    room_names: dict[int, str] = {}
    virtual_walls: list[tuple[tuple[float, float], tuple[float, float]]] = []
    forbidden_zones: list[list[tuple[float, float]]] = []
    ban_mop_zones: list[list[tuple[float, float]]] = []

    try:
        backup = stream_pb2.MapBackup().FromString(proto_bytes)
        if backup.map.pixels and backup.map.pixel_size:
            map_msg = backup.map

            ro = backup.rooms
            if ro.pixels and ro.pixel_size and ro.width and ro.height:
                room_pixels = _decode_room_outline(ro)
                if room_pixels is not None:
                    ro_width, ro_height = ro.width, ro.height
                    ro_origin_x, ro_origin_y = ro.origin.x, ro.origin.y
                    _LOGGER.debug("RoomOutline decoded: %dx%d", ro_width, ro_height)

            for room in backup.room_params.rooms:
                name = room.name.strip()
                if not name:
                    name = _ROOM_SCENE_NAMES.get(room.scene.type, f"ROOM {room.id}")
                room_names[room.id] = name
            _LOGGER.debug("RoomParams: %d rooms", len(room_names))

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

    width, height = map_msg.info.width, map_msg.info.height
    if width > _MAX_MAP_DIMENSION or height > _MAX_MAP_DIMENSION:
        _LOGGER.debug("Map %dx%d exceeds the size limit; dropped", width, height)
        return None
    if map_msg.pixel_size > (width * height + 3) // 4:
        _LOGGER.debug(
            "Map %dx%d declares %d pixel bytes; dropped",
            width, height, map_msg.pixel_size,
        )
        return None

    raw = map_msg.pixels
    if len(raw) != map_msg.pixel_size:
        try:
            raw = lz4_block_decompress(raw, map_msg.pixel_size)
        except Exception as exc:
            _LOGGER.debug("LZ4 decompress failed: %s", exc)
            return None

    _LOGGER.debug(
        "Map decoded: %dx%d id=%d res=%d",
        width, height, map_msg.id, map_msg.info.resolution,
    )

    return MapData(
        raw_pixels=raw,
        width=width,
        height=height,
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


def _decode_room_outline(ro: Any) -> bytes | None:
    """Return a ``RoomOutline``'s one-byte-per-cell mask, or None if it is unusable."""
    if ro.width > _MAX_MAP_DIMENSION or ro.height > _MAX_MAP_DIMENSION:
        _LOGGER.debug("RoomOutline %dx%d exceeds the size limit; dropped", ro.width, ro.height)
        return None
    if ro.pixel_size != ro.width * ro.height:
        _LOGGER.debug(
            "RoomOutline %dx%d declares %d bytes; dropped",
            ro.width, ro.height, ro.pixel_size,
        )
        return None
    if len(ro.pixels) == ro.pixel_size:
        return ro.pixels
    try:
        return lz4_block_decompress(ro.pixels, ro.pixel_size)
    except ValueError as exc:
        _LOGGER.debug("RoomOutline LZ4 decompress failed: %s", exc)
        return None


def try_extract_map_description(hex_data: str) -> tuple[int, str] | None:
    """Extract ``(map_id, name)`` from a biz/ ``MapDescription`` frame, or None.

    Other small biz/ frames also decode without raising, so guard strictly:
    require a positive ``map_id`` and a short, printable name.
    """
    try:
        proto_bytes = _hex_to_proto_bytes(hex_data)
        desc = stream_pb2.MapDescription().FromString(proto_bytes)
    except Exception:
        return None
    # Users seed a rename Eufy would reject as "unchanged" with a trailing space.
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
        _LOGGER.debug(
            "biz/ JSON parse failed (%s, %d bytes)", type(exc).__name__, len(payload)
        )
        return None
