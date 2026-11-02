"""Render a floor map PNG from decoded map data.

The output image always spans exactly the map grid (``width`` x ``height``
pixels at ``resolution`` cm each), Y-flipped so north is up, scaled uniformly.
Nothing is cropped or padded, so a normalized point on the image maps straight
back to the grid; ``MapData.room_id_at_normalized`` and
``EufyCleanCoordinator.normalized_rects_to_quads_cm`` rely on that.

Pipeline:

1. Classify every grid pixel into one palette index (room floor, carpet, wall,
   unassigned floor, unknown) and build a palette image. Room-outline maps map
   their bytes straight through a 256-entry palette, so there is no per-pixel
   Python loop on the common path.
2. Upscale with NEAREST to an integer multiple (crisp cells), at 2x the target
   size, and draw the vector layers there: restricted zones, the cleaning path,
   the dock and robot markers, obstacles.
3. Downsample the supersampled layer to the output size (anti-aliased lines and
   markers), then draw room labels at the final size so text stays sharp.

All overlay coordinates are *grid pixels* (floats, Y up, origin = map origin);
callers convert from world centimetres with ``(cm - origin) / resolution``.
"""

from __future__ import annotations

import io
import math
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from PIL import Image, ImageDraw, ImageFont

if TYPE_CHECKING:
    from .map_stream import MapData

MAX_MAP_PIXELS = 4000 * 4000
MAX_ROOM_ID = 31  # room outline ids 0-31 are rooms; 60-63 are special
_MAX_SUPERSAMPLED_PX = 4096
_SUPERSAMPLE = 2

# Path point flags (CompletePath): low nibble = type, bit 4 = new segment.
_PATH_GO_HOME = 4
_PATH_NAVIGATE = 3
_PATH_NEW = 0x10

# --- palette -----------------------------------------------------------------

_TRANSPARENT = (0, 0, 0, 0)
_WALL = (58, 63, 71, 255)
_FLOOR = (214, 218, 224, 255)  # explored floor not assigned to any room
_CARPET_SHADE = 0.86
_DIM_ALPHA = 120  # rooms outside the active target while a targeted clean runs

# Soft, distinguishable room fills (colour-blind-aware ordering).
ROOM_COLORS: tuple[tuple[int, int, int], ...] = (
    (126, 176, 222),
    (240, 178, 122),
    (139, 201, 160),
    (205, 160, 214),
    (240, 214, 120),
    (122, 200, 206),
    (232, 150, 160),
    (176, 196, 132),
    (160, 168, 230),
    (214, 184, 150),
)

_PATH_COLOR = (255, 255, 255, 210)
_PATH_HOME_COLOR = (255, 255, 255, 120)
_ZONE_FORBIDDEN = (224, 64, 64)
_ZONE_BAN_MOP = (240, 150, 40)
_TARGET_ZONE = (60, 140, 255)
_ROBOT_BODY = (255, 140, 0)
_ROBOT_RING = (160, 70, 0)
_DOCK_COLOR = (34, 160, 90)
_OBSTACLE_COLOR = (230, 90, 60)
_LABEL_TEXT = (33, 37, 41)
_LABEL_BG = (255, 255, 255, 215)

_STATUS_BADGE_COLORS: dict[str, tuple[int, int, int]] = {
    "charging": (250, 204, 21),
    "washing": (59, 130, 246),
    "drying": (125, 211, 252),
    "emptying": (156, 163, 175),
    "station": (168, 85, 247),
}


@dataclass
class MapOverlay:
    """Dynamic layers drawn on top of the static map, in grid pixels (Y up)."""

    robot: tuple[float, float] | None = None
    robot_heading: float | None = None  # radians, 0 = +x, counter-clockwise
    robot_status: str | None = None
    robot_style: str = "googly"
    dock: tuple[float, float] | None = None
    path: list[tuple[float, float, int]] = field(default_factory=list)  # x, y, flags
    obstacles: list[tuple[float, float, str]] = field(default_factory=list)
    target_rooms: frozenset[int] = frozenset()
    target_zones: list[list[tuple[float, float]]] = field(default_factory=list)
    show_labels: bool = True


def room_color(room_id: int) -> tuple[int, int, int]:
    return ROOM_COLORS[room_id % len(ROOM_COLORS)]


def _shade(rgb: tuple[int, int, int], factor: float) -> tuple[int, int, int]:
    return tuple(max(0, min(255, round(c * factor))) for c in rgb)  # type: ignore[return-value]


def _outline_palette(
    room_ids: set[int] | None, target_rooms: frozenset[int]
) -> list[tuple[int, int, int, int]]:
    """Palette for one room-outline byte: ``room_id << 2 | pixel_type``."""
    palette: list[tuple[int, int, int, int]] = []
    for value in range(256):
        rid, kind = value >> 2, value & 3
        is_room = rid <= MAX_ROOM_ID and (room_ids is None or rid in room_ids)
        if kind == 1 or rid == 62:
            palette.append(_WALL)
        elif is_room:
            rgb = room_color(rid)
            if kind == 3:
                rgb = _shade(rgb, _CARPET_SHADE)
            alpha = _DIM_ALPHA if target_rooms and rid not in target_rooms else 255
            palette.append((*rgb, alpha))
        elif kind in (2, 3) or rid == 61:
            palette.append(_FLOOR)
        else:
            palette.append(_TRANSPARENT)
    return palette


_REALTIME_PALETTE = [_TRANSPARENT, _WALL, _FLOOR, _FLOOR]


def _unpack_2bpp(raw: bytes, count: int) -> bytes:
    """Expand four 2-bit pixels per byte (LSB first) into one byte per pixel."""
    out = bytearray(len(raw) * 4)
    for shift in range(4):
        table = bytes(((b >> (shift * 2)) & 3) for b in range(256))
        out[shift::4] = raw.translate(table)
    return bytes(out[:count]).ljust(count, b"\x00")


def _base_image(md: MapData, overlay: MapOverlay) -> Image.Image:
    """Grid-sized RGBA image of the static map (not yet flipped or scaled)."""
    w, h = md.width, md.height
    room_ids = set(md.room_names) if md.room_names else None
    outline = md.room_pixels
    has_outline = bool(outline and md.room_outline_width and md.room_outline_height)
    res = md.resolution or 5
    outline_aligned = (
        has_outline
        and (md.room_outline_width, md.room_outline_height) == (w, h)
        and (md.room_outline_origin_x, md.room_outline_origin_y) == (md.origin_x, md.origin_y)
    )

    if outline_aligned and not _has_realtime(md):
        index = bytes(outline[: w * h]).ljust(w * h, bytes([60 << 2]))  # type: ignore[index]
        palette = _outline_palette(room_ids, overlay.target_rooms)
    else:
        pixels = _unpack_2bpp(md.raw_pixels, w * h)
        if not has_outline:
            index = pixels
            palette = list(_REALTIME_PALETTE)
        else:
            # Real-time walls/floor, coloured by the (possibly offset) room mask.
            ow, oh = md.room_outline_width, md.room_outline_height
            dx = round((md.origin_x - md.room_outline_origin_x) / res)
            dy = round((md.origin_y - md.room_outline_origin_y) / res)
            merged = bytearray(w * h)
            for y in range(h):
                ry = y - dy
                row = y * w
                for x in range(w):
                    pv = pixels[row + x]
                    rx = x - dx
                    value = (60 << 2) | pv
                    if 0 <= rx < ow and 0 <= ry < oh and pv != 1:
                        rbyte = outline[ry * ow + rx]  # type: ignore[index]
                        if (rbyte >> 2) <= MAX_ROOM_ID and pv in (0, 2, 3):
                            value = (rbyte & 0xFC) | (pv if pv else 2)
                    merged[row + x] = value
            index = bytes(merged)
            palette = _outline_palette(room_ids, overlay.target_rooms)

    image = Image.frombytes("P", (w, h), index)
    flat = [c for rgba in palette for c in rgba]
    image.putpalette(flat + [0] * (1024 - len(flat)), rawmode="RGBA")
    return image.convert("RGBA")


def _has_realtime(md: MapData) -> bool:
    return bool(md.raw_pixels) and any(md.raw_pixels)


def _room_label_anchors(md: MapData) -> dict[int, tuple[float, float]]:
    """Return a label anchor per room: the room pixel nearest its centroid.

    The centroid of an L-shaped room can fall outside it; snapping to the
    nearest member pixel keeps the label inside the room.
    """
    outline = md.room_pixels
    ow, oh = md.room_outline_width, md.room_outline_height
    if not outline or not ow or not oh:
        return {}
    res = md.resolution or 5
    dx = round((md.origin_x - md.room_outline_origin_x) / res)
    dy = round((md.origin_y - md.room_outline_origin_y) / res)
    sums: dict[int, list[int]] = {}
    # Sample every other pixel; plenty for a centroid and halves the work.
    for y in range(0, oh, 2):
        row = y * ow
        for x in range(0, ow, 2):
            rid = outline[row + x] >> 2
            if rid > MAX_ROOM_ID or (md.room_names and rid not in md.room_names):
                continue
            entry = sums.setdefault(rid, [0, 0, 0])
            entry[0] += x
            entry[1] += y
            entry[2] += 1
    anchors: dict[int, tuple[float, float]] = {}
    for rid, (sx, sy, n) in sums.items():
        cx, cy = sx / n, sy / n
        best, best_d = (cx, cy), math.inf
        for y in range(0, oh, 2):
            row = y * ow
            for x in range(0, ow, 2):
                if outline[row + x] >> 2 == rid:
                    d = (x - cx) ** 2 + (y - cy) ** 2
                    if d < best_d:
                        best, best_d = (x, y), d
        anchors[rid] = (best[0] + dx, best[1] + dy)
    return anchors


def _font(size: int) -> ImageFont.ImageFont | ImageFont.FreeTypeFont:
    try:
        return ImageFont.load_default(size=size)
    except (TypeError, OSError):  # Pillow < 10.1 or no FreeType
        return ImageFont.load_default()


def render_map(
    md: MapData,
    overlay: MapOverlay | None = None,
    *,
    max_px: int = 1024,
) -> bytes:
    """Render ``md`` (+ ``overlay``) to PNG bytes whose long side is ``max_px``."""
    overlay = overlay or MapOverlay()
    w, h = md.width, md.height
    if w <= 0 or h <= 0:
        raise ValueError("map has no size")
    if w * h > MAX_MAP_PIXELS:
        raise ValueError(f"Map dimensions {w}x{h} exceed safety limit (max 4000x4000)")

    out_scale = max_px / max(w, h)
    cell = max(1, math.floor(out_scale)) if out_scale >= 1 else 1
    ss = _SUPERSAMPLE
    while ss > 1 and max(w, h) * cell * ss > _MAX_SUPERSAMPLED_PX:
        ss -= 1
    k = cell * ss  # supersampled pixels per grid cell
    big_w, big_h = w * k, h * k
    out_w, out_h = max(1, round(w * out_scale)), max(1, round(h * out_scale))

    layer = _base_image(md, overlay).transpose(Image.Transpose.FLIP_TOP_BOTTOM)
    layer = layer.resize((big_w, big_h), Image.Resampling.NEAREST)
    vec = Image.new("RGBA", (big_w, big_h), _TRANSPARENT)
    draw = ImageDraw.Draw(vec)
    res = md.resolution or 5

    def g2s(gx: float, gy: float) -> tuple[float, float]:
        """Grid pixel (Y up) -> supersampled image pixel (Y down), cell centres."""
        return (gx + 0.5) * k, (h - 0.5 - gy) * k

    def w2s(wx: float, wy: float) -> tuple[float, float]:
        return g2s((wx - md.origin_x) / res, (wy - md.origin_y) / res)

    line = max(1, round(k * 0.45))

    # Restricted zones and the active target zones.
    for quad in md.ban_mop_zones:
        draw.polygon([w2s(*p) for p in quad], fill=(*_ZONE_BAN_MOP, 60), outline=(*_ZONE_BAN_MOP, 230), width=line)
    for quad in md.forbidden_zones:
        draw.polygon([w2s(*p) for p in quad], fill=(*_ZONE_FORBIDDEN, 60), outline=(*_ZONE_FORBIDDEN, 230), width=line)
    for start, end in md.virtual_walls:
        draw.line([w2s(*start), w2s(*end)], fill=(*_ZONE_FORBIDDEN, 255), width=line * 2)
    for target in overlay.target_zones:
        draw.polygon([g2s(*p) for p in target], fill=(*_TARGET_ZONE, 50), outline=(*_TARGET_ZONE, 230), width=line)

    # Cleaning path: one polyline per continuous run of the same kind.
    if len(overlay.path) > 1:
        path_w = max(1, round(k * 0.35))
        max_jump = (60 / res) ** 2  # >60 cm between samples is a gap, not a line
        run: list[tuple[float, float]] = []
        run_home = False
        prev_x = prev_y = math.inf

        def flush() -> None:
            if len(run) > 1:
                draw.line(run, fill=_PATH_HOME_COLOR if run_home else _PATH_COLOR, width=path_w, joint="curve")

        for x, y, flags in overlay.path:
            kind = flags & 0x0F
            home = kind in (_PATH_GO_HOME, _PATH_NAVIGATE)
            point = g2s(x, y)
            dist2 = (x - prev_x) ** 2 + (y - prev_y) ** 2
            gap = bool(flags & _PATH_NEW) or dist2 > max_jump
            if gap:
                flush()
                run = [point]
            elif home != run_home:
                flush()
                run = [run[-1], point]  # keep the line continuous across a kind change
            else:
                run.append(point)
            run_home = home
            prev_x, prev_y = x, y
        flush()

    # Markers track the robot's real footprint (~34 cm across) but never shrink
    # below a legible size on small renders.
    out_px_per_ss = out_w / big_w
    marker = max(17 / res * k, 8 / out_px_per_ss)

    marks = Image.new("RGBA", (big_w, big_h), _TRANSPARENT)
    draw = ImageDraw.Draw(marks)

    for ox, oy, _label in overlay.obstacles:
        cx, cy = g2s(ox, oy)
        r = marker * 0.5
        draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(*_OBSTACLE_COLOR, 235), outline=(255, 255, 255, 255), width=max(1, round(r * 0.25)))

    if overlay.dock is not None:
        cx, cy = g2s(*overlay.dock)
        r = marker * 0.9
        draw.rounded_rectangle((cx - r, cy - r, cx + r, cy + r), radius=r * 0.35, fill=(*_DOCK_COLOR, 255), outline=(255, 255, 255, 255), width=max(1, round(r * 0.18)))
        roof = [(cx, cy - r * 0.55), (cx - r * 0.55, cy), (cx + r * 0.55, cy)]
        draw.polygon(roof, fill=(255, 255, 255, 255))
        draw.rectangle((cx - r * 0.35, cy, cx + r * 0.35, cy + r * 0.45), fill=(255, 255, 255, 255))

    if overlay.robot is not None:
        cx, cy = g2s(*overlay.robot)
        r = marker
        if overlay.robot_style == "dot":
            draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(30, 30, 30, 255), outline=(255, 255, 255, 255), width=max(1, round(r * 0.2)))
        else:
            # Googly eyes: an orange robot whose pupils look where it is heading.
            draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(*_ROBOT_BODY, 255), outline=(*_ROBOT_RING, 255), width=max(2, round(r * 0.22)))
            heading = overlay.robot_heading
            look = (math.cos(heading), -math.sin(heading)) if heading is not None else (0.0, 0.0)
            eye_r, pupil_r = r * 0.34, r * 0.17
            for side in (-1, 1):
                ex, ey = cx + side * r * 0.36, cy - r * 0.18
                draw.ellipse((ex - eye_r, ey - eye_r, ex + eye_r, ey + eye_r), fill=(255, 255, 255, 255), outline=(40, 40, 40, 255), width=max(1, round(r * 0.06)))
                px, py = ex + look[0] * eye_r * 0.45, ey + look[1] * eye_r * 0.45
                draw.ellipse((px - pupil_r, py - pupil_r, px + pupil_r, py + pupil_r), fill=(20, 20, 20, 255))
        badge = _STATUS_BADGE_COLORS.get(overlay.robot_status or "")
        if badge:
            bx, by, br = cx + r * 0.85, cy - r * 0.85, r * 0.5
            draw.ellipse((bx - br, by - br, bx + br, by + br), fill=(*badge, 255), outline=(255, 255, 255, 255), width=max(1, round(br * 0.3)))

    layer.alpha_composite(vec)

    def to_out(img: Image.Image) -> Image.Image:
        if img.size == (out_w, out_h):
            return img
        return img.resize((out_w, out_h), Image.Resampling.LANCZOS)

    image = to_out(layer)

    if overlay.show_labels and md.room_names:
        scale = out_w / w
        text = ImageDraw.Draw(image, "RGBA")
        font = _font(max(11, min(26, round(scale * 4.2))))
        for rid, (gx, gy) in _room_label_anchors(md).items():
            name = (md.room_names.get(rid) or "").strip()
            if not name:
                continue
            x, y = (gx + 0.5) * scale, (h - 0.5 - gy) * scale
            bx0, by0, bx1, by1 = text.textbbox((0, 0), name, font=font)
            tw, th = bx1 - bx0, by1 - by0
            pad = max(2, round(th * 0.35))
            box = (x - tw / 2 - pad, y - th / 2 - pad, x + tw / 2 + pad, y + th / 2 + pad)
            text.rounded_rectangle(box, radius=pad + 1, fill=_LABEL_BG)
            text.text((x - tw / 2 - bx0, y - th / 2 - by0), name, fill=_LABEL_TEXT, font=font)

    # Markers last so a label never hides the robot or the dock.
    image.alpha_composite(to_out(marks))

    buf = io.BytesIO()
    image.save(buf, format="PNG", optimize=False, compress_level=6)
    return buf.getvalue()
