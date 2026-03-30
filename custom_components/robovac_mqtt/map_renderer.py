"""Map rendering for Eufy Clean vacuum floor plans.

Decodes LZ4-compressed map pixel data from cleaning records (CleanRecordData)
and renders colored floor plan PNGs with room partitions.

Two data formats are supported:
1. stream.Map + stream.RoomOutline (cloud record format)
   - Map: 2-bit pixels (4 pixels/byte, LZ4), pixel types only
   - RoomOutline: 1 byte/pixel = room ID (LZ4)
2. p2p.CompleteMap (P2P record format)
   - map: 2-bit pixels (4 pixels/byte, LZ4), pixel types only
   - room_outline: 1 byte/pixel, low 2 bits = pixel type, high 6 bits = room ID (LZ4)
"""
from __future__ import annotations

import io
import logging
import struct
import zlib
from dataclasses import dataclass
from typing import Any

_LOGGER = logging.getLogger(__name__)

# Pixel types (2-bit values from SLAM map)
PIXEL_UNKNOWN = 0
PIXEL_OBSTACLE = 1
PIXEL_FREE = 2
PIXEL_CARPET = 3

# Special room IDs (from p2p.proto comments)
ROOM_ID_NO_ROOM = 60
ROOM_ID_GAP = 61
ROOM_ID_OBSTACLE = 62
ROOM_ID_UNKNOWN = 63

# Room colors (RGBA) - distinct, pleasant colors for up to 32 rooms
ROOM_COLORS = [
    (120, 180, 240, 255),   # Blue
    (160, 220, 140, 255),   # Green
    (240, 180, 120, 255),   # Orange
    (200, 140, 220, 255),   # Purple
    (240, 220, 120, 255),   # Yellow
    (140, 220, 220, 255),   # Teal
    (240, 140, 160, 255),   # Pink
    (180, 200, 140, 255),   # Olive
    (140, 180, 200, 255),   # Steel blue
    (220, 180, 200, 255),   # Mauve
    (200, 220, 160, 255),   # Lime
    (180, 160, 220, 255),   # Lavender
    (220, 200, 140, 255),   # Khaki
    (140, 200, 180, 255),   # Mint
    (220, 160, 180, 255),   # Rose
    (160, 200, 220, 255),   # Sky
    (200, 180, 160, 255),   # Tan
    (180, 220, 200, 255),   # Seafoam
    (220, 180, 160, 255),   # Peach
    (160, 180, 200, 255),   # Slate
    (200, 200, 180, 255),   # Sage
    (180, 160, 200, 255),   # Iris
    (200, 220, 200, 255),   # Pale green
    (220, 200, 180, 255),   # Wheat
    (180, 200, 220, 255),   # Powder blue
    (200, 180, 200, 255),   # Thistle
    (220, 220, 180, 255),   # Cream
    (180, 220, 180, 255),   # Light green
    (200, 160, 200, 255),   # Orchid
    (160, 220, 200, 255),   # Aqua
    (220, 180, 200, 255),   # Pink 2
    (200, 220, 220, 255),   # Ice
]

# Non-room pixel colors
COLOR_UNKNOWN = (32, 32, 38, 255)      # Dark background
COLOR_OBSTACLE = (80, 80, 90, 255)     # Dark grey walls
COLOR_FREE = (200, 200, 210, 255)      # Light grey (free space without room)
COLOR_CARPET = (180, 170, 150, 255)    # Brownish (carpet without room)
COLOR_GAP = (50, 50, 58, 255)          # Slightly lighter than background
COLOR_DOCK = (255, 100, 80, 255)       # Red-orange dock marker
COLOR_ROBOT = (50, 220, 100, 255)      # Green robot marker
COLOR_TRAIL = (100, 180, 255, 180)     # Blue trail


@dataclass
class DecodedMap:
    """Decoded map pixel data ready for rendering."""

    width: int
    height: int
    pixel_types: bytes      # width*height bytes, each 0-3
    room_ids: bytes | None  # width*height bytes, each = room ID (or None if no room data)
    origin_x: int = 0       # Map origin in cm (m*100)
    origin_y: int = 0
    resolution: int = 5     # cm per pixel
    dock_x: int = 0         # Dock position in map pixel coords
    dock_y: int = 0
    room_names: dict[int, str] | None = None  # room_id -> name


def lz4_block_decompress(data: bytes, uncompressed_size: int) -> bytes:
    """Decompress LZ4 block format (no frame header).

    Pure Python implementation for environments without the lz4 C library.
    Handles the raw LZ4 block compression format used by Eufy map data.
    """
    src = memoryview(data)
    dst = bytearray(uncompressed_size)
    src_pos = 0
    dst_pos = 0
    src_len = len(data)

    while src_pos < src_len and dst_pos < uncompressed_size:
        # Read token
        token = src[src_pos]
        src_pos += 1

        # Literal length (high nibble)
        lit_len = (token >> 4) & 0x0F
        if lit_len == 15:
            while src_pos < src_len:
                extra = src[src_pos]
                src_pos += 1
                lit_len += extra
                if extra != 255:
                    break

        # Copy literals
        if lit_len > 0:
            end = min(dst_pos + lit_len, uncompressed_size)
            count = end - dst_pos
            dst[dst_pos:end] = src[src_pos:src_pos + count]
            src_pos += count
            dst_pos = end

        if dst_pos >= uncompressed_size:
            break

        # Match offset (2 bytes, little-endian)
        if src_pos + 1 >= src_len:
            break
        offset = src[src_pos] | (src[src_pos + 1] << 8)
        src_pos += 2

        if offset == 0:
            break

        # Match length (low nibble + 4 minimum)
        match_len = (token & 0x0F) + 4
        if (token & 0x0F) == 15:
            while src_pos < src_len:
                extra = src[src_pos]
                src_pos += 1
                match_len += extra
                if extra != 255:
                    break

        # Copy match (byte-by-byte for overlapping copies)
        match_start = dst_pos - offset
        for i in range(match_len):
            if dst_pos >= uncompressed_size:
                break
            dst[dst_pos] = dst[match_start + i]
            dst_pos += 1

    return bytes(dst[:dst_pos])


def _try_lz4_decompress(data: bytes, expected_size: int) -> bytes | None:
    """Try to decompress LZ4 data, with fallback to pure Python."""
    if not data or expected_size == 0:
        return None

    # Try C library first (faster)
    try:
        import lz4.block
        return lz4.block.decompress(data, uncompressed_size=expected_size)
    except (ImportError, Exception):
        pass

    # Pure Python fallback
    try:
        result = lz4_block_decompress(data, expected_size)
        if len(result) == expected_size:
            return result
        _LOGGER.warning(
            "LZ4 decompress size mismatch: got %d, expected %d",
            len(result), expected_size,
        )
        # Pad or truncate
        if len(result) < expected_size:
            return result + b'\x00' * (expected_size - len(result))
        return result[:expected_size]
    except Exception as exc:
        _LOGGER.error("LZ4 decompression failed: %s", exc)
        return None


def decode_slam_pixels(raw: bytes, width: int, height: int) -> bytes:
    """Decode 2-bit SLAM map pixels to 1 byte per pixel.

    Input: LZ4-decompressed bytes where each byte contains 4 pixels (2 bits each).
    Pixels start from the low bits of each byte.
    Output: width*height bytes, each 0-3 (UNKNOWN/OBSTACLE/FREE/CARPET).
    """
    total = width * height
    result = bytearray(total)
    idx = 0
    for byte_val in raw:
        for shift in range(0, 8, 2):
            if idx >= total:
                break
            result[idx] = (byte_val >> shift) & 0x03
            idx += 1
        if idx >= total:
            break
    return bytes(result)


def decode_stream_map(
    map_msg: Any,
    room_outline_msg: Any | None = None,
    room_params_msg: Any | None = None,
) -> DecodedMap | None:
    """Decode a stream.Map + optional stream.RoomOutline into DecodedMap.

    Args:
        map_msg: Parsed stream.Map protobuf message
        room_outline_msg: Optional stream.RoomOutline protobuf message
        room_params_msg: Optional stream.RoomParams protobuf message
    """
    if not map_msg.HasField("info"):
        _LOGGER.warning("stream.Map has no info field")
        return None

    info = map_msg.info
    width = info.width
    height = info.height
    if width == 0 or height == 0:
        _LOGGER.warning("Map dimensions are 0")
        return None

    resolution = info.resolution if info.resolution else 5
    origin_x = info.origin.x if info.HasField("origin") else 0
    origin_y = info.origin.y if info.HasField("origin") else 0

    # Dock position
    dock_x, dock_y = 0, 0
    if info.docks:
        dock_x = info.docks[0].x
        dock_y = info.docks[0].y

    _LOGGER.info(
        "Decoding stream.Map: %dx%d, resolution=%d, origin=(%d,%d), "
        "pixels=%d bytes, pixel_size=%d",
        width, height, resolution, origin_x, origin_y,
        len(map_msg.pixels), map_msg.pixel_size,
    )

    # Decompress SLAM map pixels
    slam_raw = _try_lz4_decompress(map_msg.pixels, map_msg.pixel_size)
    if not slam_raw:
        _LOGGER.error("Failed to decompress SLAM map pixels")
        return None

    pixel_types = decode_slam_pixels(slam_raw, width, height)

    # Decode room outline if available
    room_ids = None
    if room_outline_msg and room_outline_msg.pixels:
        _LOGGER.info(
            "Decoding stream.RoomOutline: %dx%d, pixels=%d bytes, pixel_size=%d",
            room_outline_msg.width, room_outline_msg.height,
            len(room_outline_msg.pixels), room_outline_msg.pixel_size,
        )
        room_raw = _try_lz4_decompress(
            room_outline_msg.pixels, room_outline_msg.pixel_size
        )
        if room_raw:
            # stream.RoomOutline: 1 byte per pixel = room ID directly
            room_ids = room_raw[:width * height]

    # Extract room names
    room_names = _extract_room_names(room_params_msg)

    return DecodedMap(
        width=width,
        height=height,
        pixel_types=pixel_types,
        room_ids=room_ids,
        origin_x=origin_x,
        origin_y=origin_y,
        resolution=resolution,
        dock_x=dock_x,
        dock_y=dock_y,
        room_names=room_names,
    )


def decode_p2p_complete_map(
    complete_map: Any,
    room_params_msg: Any | None = None,
) -> DecodedMap | None:
    """Decode a p2p.CompleteMap into DecodedMap.

    Args:
        complete_map: Parsed p2p.CompleteMap protobuf message
        room_params_msg: Optional stream.RoomParams protobuf message
    """
    width = complete_map.map_width
    height = complete_map.map_height
    if width == 0 or height == 0:
        _LOGGER.warning("CompleteMap dimensions are 0")
        return None

    origin_x = complete_map.origin.x if complete_map.HasField("origin") else 0
    origin_y = complete_map.origin.y if complete_map.HasField("origin") else 0

    dock_x, dock_y = 0, 0
    if complete_map.docks:
        dock_x = complete_map.docks[0].x
        dock_y = complete_map.docks[0].y

    _LOGGER.info(
        "Decoding p2p.CompleteMap: %dx%d, origin=(%d,%d)",
        width, height, origin_x, origin_y,
    )

    # Decode SLAM map (2-bit pixels)
    pixel_types = None
    if complete_map.HasField("map") and complete_map.map.pixels:
        slam_raw = _try_lz4_decompress(
            complete_map.map.pixels, complete_map.map.pixel_size
        )
        if slam_raw:
            pixel_types = decode_slam_pixels(slam_raw, width, height)

    # Decode room outline (combined format: low 2 bits = pixel type, high 6 bits = room ID)
    room_ids = None
    if complete_map.HasField("room_outline") and complete_map.room_outline.pixels:
        ro_raw = _try_lz4_decompress(
            complete_map.room_outline.pixels,
            complete_map.room_outline.pixel_size,
        )
        if ro_raw:
            total = width * height
            room_id_buf = bytearray(total)
            # If we don't have SLAM pixel_types, extract from room_outline
            if pixel_types is None:
                pt_buf = bytearray(total)
                for i in range(min(len(ro_raw), total)):
                    b = ro_raw[i]
                    pt_buf[i] = b & 0x03
                    room_id_buf[i] = (b >> 2) & 0x3F
                pixel_types = bytes(pt_buf)
            else:
                for i in range(min(len(ro_raw), total)):
                    room_id_buf[i] = (ro_raw[i] >> 2) & 0x3F
            room_ids = bytes(room_id_buf)

    if pixel_types is None:
        _LOGGER.error("No pixel data found in CompleteMap")
        return None

    # Room params from CompleteMap itself or passed in
    rp = room_params_msg
    if rp is None and complete_map.HasField("room_params"):
        rp = complete_map.room_params
    room_names = _extract_room_names(rp)

    return DecodedMap(
        width=width,
        height=height,
        pixel_types=pixel_types,
        room_ids=room_ids,
        origin_x=origin_x,
        origin_y=origin_y,
        resolution=5,  # p2p.CompleteMap doesn't have a resolution field
        dock_x=dock_x,
        dock_y=dock_y,
        room_names=room_names,
    )


def _extract_room_names(room_params_msg: Any | None) -> dict[int, str] | None:
    """Extract room ID -> name mapping from RoomParams."""
    if room_params_msg is None:
        return None
    names: dict[int, str] = {}
    for room in room_params_msg.rooms:
        name = room.name if room.name else f"Room {room.id}"
        names[room.id] = name
    return names if names else None


def generate_schematic_map(
    rooms: list[dict[str, Any]],
    map_size: int = 100,
) -> DecodedMap:
    """Generate a schematic floor plan from room data (DPS 165).

    When real map pixel data is unavailable, this creates a grid-based
    room layout that can be rendered by render_map_png().

    Args:
        rooms: List of dicts with 'id' and 'name' keys (from DPS 165 parsing)
        map_size: Size of the generated map in pixels (square)

    Returns:
        DecodedMap with rooms laid out in a grid pattern
    """
    named_rooms = [r for r in rooms if r.get("name")]
    if not named_rooms:
        named_rooms = rooms[:9]  # Use first 9 rooms even if unnamed

    n = len(named_rooms)
    if n == 0:
        return DecodedMap(width=0, height=0, pixel_types=b"", room_ids=None)

    # Grid layout: arrange rooms in a roughly square grid
    import math
    cols = math.ceil(math.sqrt(n))
    rows = math.ceil(n / cols)

    # Each room cell size (with 1px gap between rooms)
    cell_w = map_size // cols
    cell_h = map_size // rows
    gap = max(1, min(cell_w, cell_h) // 15)

    w = cols * cell_w
    h = rows * cell_h

    pixel_types = bytearray(w * h)
    room_id_data = bytearray(w * h)

    # Fill rooms
    for i, room in enumerate(named_rooms):
        rid = room.get("id", i + 1)
        col = i % cols
        row = i // cols

        x0 = col * cell_w + gap
        y0 = row * cell_h + gap
        x1 = (col + 1) * cell_w - gap
        y1 = (row + 1) * cell_h - gap

        for y in range(y0, min(y1, h)):
            for x in range(x0, min(x1, w)):
                idx = y * w + x
                pixel_types[idx] = PIXEL_FREE
                room_id_data[idx] = rid & 0x1F  # Room IDs 0-31

    room_names = {r.get("id", i + 1): r.get("name", f"Room {r.get('id', i+1)}")
                  for i, r in enumerate(named_rooms)}

    return DecodedMap(
        width=w,
        height=h,
        pixel_types=bytes(pixel_types),
        room_ids=bytes(room_id_data),
        resolution=5,
        room_names=room_names,
    )


def render_map_png(
    decoded: DecodedMap,
    robot_pos: tuple[int, int] | None = None,
    dock_pos: tuple[int, int] | None = None,
    trail: list[tuple[int, int]] | None = None,
    output_size: int = 800,
) -> bytes:
    """Render a DecodedMap to a PNG image.

    Args:
        decoded: The decoded map data
        robot_pos: Robot position in raw DPS 179 coordinates (optional)
        dock_pos: Dock position in raw DPS 179 coordinates (optional)
        trail: List of trail points in raw DPS 179 coordinates (optional)
        output_size: Output image size in pixels (square)

    Returns:
        PNG image bytes
    """
    w, h = decoded.width, decoded.height
    if w == 0 or h == 0:
        return _empty_png(output_size)

    # Find the bounding box of non-unknown pixels to crop empty borders
    min_r, max_r, min_c, max_c = h, 0, w, 0
    pt = decoded.pixel_types
    for r in range(h):
        row_start = r * w
        for c in range(w):
            if pt[row_start + c] != PIXEL_UNKNOWN:
                if r < min_r:
                    min_r = r
                if r > max_r:
                    max_r = r
                if c < min_c:
                    min_c = c
                if c > max_c:
                    max_c = c

    if min_r > max_r:
        _LOGGER.warning("Map has no non-unknown pixels")
        return _empty_png(output_size)

    # Add padding
    pad = max(5, int((max_r - min_r + max_c - min_c) * 0.03))
    min_r = max(0, min_r - pad)
    max_r = min(h - 1, max_r + pad)
    min_c = max(0, min_c - pad)
    max_c = min(w - 1, max_c + pad)

    crop_w = max_c - min_c + 1
    crop_h = max_r - min_r + 1

    # Make square (keep aspect ratio, add padding to shorter side)
    if crop_w > crop_h:
        diff = crop_w - crop_h
        min_r = max(0, min_r - diff // 2)
        max_r = min(h - 1, min_r + crop_w - 1)
        crop_h = max_r - min_r + 1
    elif crop_h > crop_w:
        diff = crop_h - crop_w
        min_c = max(0, min_c - diff // 2)
        max_c = min(w - 1, min_c + crop_h - 1)
        crop_w = max_c - min_c + 1

    # Scale factor from map pixels to output pixels
    scale = output_size / max(crop_w, crop_h)

    # Build the output image
    img = bytearray(output_size * output_size * 4)
    # Fill with background
    bg = COLOR_UNKNOWN
    for i in range(output_size * output_size):
        off = i * 4
        img[off] = bg[0]
        img[off + 1] = bg[1]
        img[off + 2] = bg[2]
        img[off + 3] = bg[3]

    room_ids = decoded.room_ids

    # Render map pixels
    for r in range(min_r, max_r + 1):
        out_y = int((r - min_r) * scale)
        if out_y >= output_size:
            continue
        row_start = r * w
        for c in range(min_c, max_c + 1):
            out_x = int((c - min_c) * scale)
            if out_x >= output_size:
                continue

            idx = row_start + c
            ptype = pt[idx]

            if ptype == PIXEL_UNKNOWN:
                continue  # Already background

            # Determine color based on room ID (if available) and pixel type
            color = _pixel_color(ptype, room_ids[idx] if room_ids else None)

            # Fill the scaled pixel block
            end_y = min(int((r - min_r + 1) * scale), output_size)
            end_x = min(int((c - min_c + 1) * scale), output_size)
            for oy in range(out_y, end_y):
                for ox in range(out_x, end_x):
                    off = (oy * output_size + ox) * 4
                    img[off] = color[0]
                    img[off + 1] = color[1]
                    img[off + 2] = color[2]
                    img[off + 3] = color[3]

    # Draw walls/obstacles with a darker shade on top
    for r in range(min_r, max_r + 1):
        out_y = int((r - min_r) * scale)
        if out_y >= output_size:
            continue
        row_start = r * w
        for c in range(min_c, max_c + 1):
            idx = row_start + c
            ptype = pt[idx]
            if ptype != PIXEL_OBSTACLE:
                continue

            out_x = int((c - min_c) * scale)
            if out_x >= output_size:
                continue

            end_y = min(int((r - min_r + 1) * scale), output_size)
            end_x = min(int((c - min_c + 1) * scale), output_size)
            for oy in range(out_y, end_y):
                for ox in range(out_x, end_x):
                    off = (oy * output_size + ox) * 4
                    img[off] = COLOR_OBSTACLE[0]
                    img[off + 1] = COLOR_OBSTACLE[1]
                    img[off + 2] = COLOR_OBSTACLE[2]
                    img[off + 3] = COLOR_OBSTACLE[3]

    # Overlay dock position
    if dock_pos and decoded.resolution:
        dx, dy = _world_to_output(
            dock_pos[0], dock_pos[1],
            decoded, min_r, min_c, scale, output_size,
        )
        if dx is not None:
            _draw_circle_on(img, output_size, dx, dy, max(4, int(scale * 3)), COLOR_DOCK)
            # Cross
            arm = max(6, int(scale * 4))
            for d in range(-arm, arm + 1):
                _set_px(img, output_size, dx + d, dy, (255, 255, 255, 200))
                _set_px(img, output_size, dx, dy + d, (255, 255, 255, 200))

    # Overlay trail
    if trail:
        for i, (tx, ty) in enumerate(trail):
            px, py = _world_to_output(
                tx, ty, decoded, min_r, min_c, scale, output_size,
            )
            if px is not None:
                age = (len(trail) - i) / max(len(trail), 1)
                alpha = int(180 * (1 - age * 0.7))
                _draw_circle_on(
                    img, output_size, px, py, max(1, int(scale * 0.8)),
                    (COLOR_TRAIL[0], COLOR_TRAIL[1], COLOR_TRAIL[2], alpha),
                )

    # Overlay robot position
    if robot_pos:
        rx, ry = _world_to_output(
            robot_pos[0], robot_pos[1],
            decoded, min_r, min_c, scale, output_size,
        )
        if rx is not None:
            _draw_circle_on(img, output_size, rx, ry, max(4, int(scale * 2.5)), COLOR_ROBOT)
            _draw_circle_on(img, output_size, rx, ry, max(2, int(scale * 1)), (255, 255, 255, 255))

    # Draw room name labels
    if decoded.room_names and decoded.room_ids:
        _draw_room_labels(
            img, output_size, decoded, min_r, min_c, scale,
        )

    return _encode_png(img, output_size, output_size)


# Minimal 5x7 bitmap font for uppercase letters, digits, and space
_FONT: dict[str, list[int]] = {
    " ": [0, 0, 0, 0, 0, 0, 0],
    "A": [0x04, 0x0A, 0x11, 0x1F, 0x11, 0x11, 0x11],
    "B": [0x1E, 0x11, 0x11, 0x1E, 0x11, 0x11, 0x1E],
    "C": [0x0E, 0x11, 0x10, 0x10, 0x10, 0x11, 0x0E],
    "D": [0x1E, 0x11, 0x11, 0x11, 0x11, 0x11, 0x1E],
    "E": [0x1F, 0x10, 0x10, 0x1E, 0x10, 0x10, 0x1F],
    "F": [0x1F, 0x10, 0x10, 0x1E, 0x10, 0x10, 0x10],
    "G": [0x0E, 0x11, 0x10, 0x17, 0x11, 0x11, 0x0E],
    "H": [0x11, 0x11, 0x11, 0x1F, 0x11, 0x11, 0x11],
    "I": [0x0E, 0x04, 0x04, 0x04, 0x04, 0x04, 0x0E],
    "J": [0x07, 0x02, 0x02, 0x02, 0x02, 0x12, 0x0C],
    "K": [0x11, 0x12, 0x14, 0x18, 0x14, 0x12, 0x11],
    "L": [0x10, 0x10, 0x10, 0x10, 0x10, 0x10, 0x1F],
    "M": [0x11, 0x1B, 0x15, 0x11, 0x11, 0x11, 0x11],
    "N": [0x11, 0x19, 0x15, 0x13, 0x11, 0x11, 0x11],
    "O": [0x0E, 0x11, 0x11, 0x11, 0x11, 0x11, 0x0E],
    "P": [0x1E, 0x11, 0x11, 0x1E, 0x10, 0x10, 0x10],
    "Q": [0x0E, 0x11, 0x11, 0x11, 0x15, 0x12, 0x0D],
    "R": [0x1E, 0x11, 0x11, 0x1E, 0x14, 0x12, 0x11],
    "S": [0x0E, 0x11, 0x10, 0x0E, 0x01, 0x11, 0x0E],
    "T": [0x1F, 0x04, 0x04, 0x04, 0x04, 0x04, 0x04],
    "U": [0x11, 0x11, 0x11, 0x11, 0x11, 0x11, 0x0E],
    "V": [0x11, 0x11, 0x11, 0x11, 0x0A, 0x0A, 0x04],
    "W": [0x11, 0x11, 0x11, 0x15, 0x15, 0x1B, 0x11],
    "X": [0x11, 0x11, 0x0A, 0x04, 0x0A, 0x11, 0x11],
    "Y": [0x11, 0x11, 0x0A, 0x04, 0x04, 0x04, 0x04],
    "Z": [0x1F, 0x01, 0x02, 0x04, 0x08, 0x10, 0x1F],
    "0": [0x0E, 0x11, 0x13, 0x15, 0x19, 0x11, 0x0E],
    "1": [0x04, 0x0C, 0x04, 0x04, 0x04, 0x04, 0x0E],
    "2": [0x0E, 0x11, 0x01, 0x06, 0x08, 0x10, 0x1F],
    "3": [0x0E, 0x11, 0x01, 0x06, 0x01, 0x11, 0x0E],
    "4": [0x02, 0x06, 0x0A, 0x12, 0x1F, 0x02, 0x02],
    "5": [0x1F, 0x10, 0x1E, 0x01, 0x01, 0x11, 0x0E],
    "6": [0x06, 0x08, 0x10, 0x1E, 0x11, 0x11, 0x0E],
    "7": [0x1F, 0x01, 0x02, 0x04, 0x08, 0x08, 0x08],
    "8": [0x0E, 0x11, 0x11, 0x0E, 0x11, 0x11, 0x0E],
    "9": [0x0E, 0x11, 0x11, 0x0F, 0x01, 0x02, 0x0C],
}


def _draw_text(
    img: bytearray, img_w: int,
    x: int, y: int,
    text: str,
    color: tuple[int, int, int, int] = (255, 255, 255, 230),
    scale: int = 2,
) -> None:
    """Draw text on an RGBA image using the built-in bitmap font."""
    cx = x
    for ch in text.upper():
        glyph = _FONT.get(ch)
        if glyph is None:
            cx += 4 * scale  # skip unknown chars
            continue
        for row_idx, row_bits in enumerate(glyph):
            for col in range(5):
                if row_bits & (0x10 >> col):
                    for sy in range(scale):
                        for sx in range(scale):
                            _set_px(img, img_w,
                                    cx + col * scale + sx,
                                    y + row_idx * scale + sy,
                                    color)
        cx += 6 * scale  # 5 pixels + 1 gap per char


def _draw_room_labels(
    img: bytearray, img_w: int,
    decoded: DecodedMap,
    min_r: int, min_c: int, scale: float,
) -> None:
    """Draw room name labels centered on each room."""
    if not decoded.room_names or not decoded.room_ids:
        return

    w, h = decoded.width, decoded.height
    room_ids = decoded.room_ids

    # Find center of each room
    room_pixels: dict[int, list[int]] = {}
    for r in range(h):
        for c in range(w):
            rid = room_ids[r * w + c]
            if rid < ROOM_ID_NO_ROOM and decoded.pixel_types[r * w + c] == PIXEL_FREE:
                if rid not in room_pixels:
                    room_pixels[rid] = [0, 0, 0]  # sum_r, sum_c, count
                room_pixels[rid][0] += r
                room_pixels[rid][1] += c
                room_pixels[rid][2] += 1

    # Choose font scale based on output size
    font_scale = max(1, min(3, int(scale * 0.6)))

    for rid, (sum_r, sum_c, count) in room_pixels.items():
        name = decoded.room_names.get(rid, "")
        if not name:
            continue

        center_r = sum_r // count
        center_c = sum_c // count

        out_x = int((center_c - min_c) * scale)
        out_y = int((center_r - min_r) * scale)

        # Center the text
        text_w = len(name) * 6 * font_scale
        text_h = 7 * font_scale
        tx = out_x - text_w // 2
        ty = out_y - text_h // 2

        # Draw shadow then text
        _draw_text(img, img_w, tx + 1, ty + 1, name,
                   color=(0, 0, 0, 150), scale=font_scale)
        _draw_text(img, img_w, tx, ty, name,
                   color=(255, 255, 255, 230), scale=font_scale)


def _pixel_color(
    ptype: int, room_id: int | None
) -> tuple[int, int, int, int]:
    """Get the color for a map pixel based on type and room ID."""
    if ptype == PIXEL_UNKNOWN:
        return COLOR_UNKNOWN
    if ptype == PIXEL_OBSTACLE:
        return COLOR_OBSTACLE

    # For FREE or CARPET pixels, use room color if available
    if room_id is not None:
        if room_id >= ROOM_ID_NO_ROOM:
            # Special IDs
            if room_id == ROOM_ID_GAP:
                return COLOR_GAP
            if room_id == ROOM_ID_OBSTACLE:
                return COLOR_OBSTACLE
            return COLOR_UNKNOWN
        if 0 <= room_id < len(ROOM_COLORS):
            base = ROOM_COLORS[room_id]
            if ptype == PIXEL_CARPET:
                # Slightly darken carpet areas
                return (
                    max(0, base[0] - 20),
                    max(0, base[1] - 20),
                    max(0, base[2] - 10),
                    base[3],
                )
            return base

    # No room data
    if ptype == PIXEL_FREE:
        return COLOR_FREE
    if ptype == PIXEL_CARPET:
        return COLOR_CARPET
    return COLOR_UNKNOWN


def _world_to_output(
    world_x: int,
    world_y: int,
    decoded: DecodedMap,
    min_r: int,
    min_c: int,
    scale: float,
    output_size: int,
) -> tuple[int | None, int | None]:
    """Convert world coordinates (DPS 179 raw units) to output pixel coords.

    DPS 179 coordinates appear to be in the same coordinate system as the map
    pixel grid (origin + resolution based). We convert:
      map_col = (world_x - origin_x) / resolution
      map_row = (world_y - origin_y) / resolution
    Then to output:
      out_x = (map_col - min_c) * scale
      out_y = (map_row - min_r) * scale
    """
    res = decoded.resolution if decoded.resolution else 5
    map_c = (world_x - decoded.origin_x) / res
    map_r = (world_y - decoded.origin_y) / res

    out_x = int((map_c - min_c) * scale)
    out_y = int((map_r - min_r) * scale)

    if 0 <= out_x < output_size and 0 <= out_y < output_size:
        return out_x, out_y
    return None, None


def _set_px(
    img: bytearray, size: int, x: int, y: int,
    color: tuple[int, int, int, int],
) -> None:
    """Set pixel with alpha blending."""
    if 0 <= x < size and 0 <= y < size:
        off = (y * size + x) * 4
        a = color[3] / 255
        img[off] = int(img[off] * (1 - a) + color[0] * a)
        img[off + 1] = int(img[off + 1] * (1 - a) + color[1] * a)
        img[off + 2] = int(img[off + 2] * (1 - a) + color[2] * a)
        img[off + 3] = 255


def _draw_circle_on(
    img: bytearray, size: int, cx: int, cy: int, r: int,
    color: tuple[int, int, int, int],
) -> None:
    """Draw filled circle with alpha blending."""
    for dy in range(-r, r + 1):
        for dx in range(-r, r + 1):
            if dx * dx + dy * dy <= r * r:
                _set_px(img, size, cx + dx, cy + dy, color)


def _empty_png(size: int) -> bytes:
    """Return a blank dark PNG."""
    img = bytearray(size * size * 4)
    bg = COLOR_UNKNOWN
    for i in range(size * size):
        off = i * 4
        img[off] = bg[0]
        img[off + 1] = bg[1]
        img[off + 2] = bg[2]
        img[off + 3] = bg[3]
    return _encode_png(img, size, size)


def _encode_png(rgba_data: bytearray, width: int, height: int) -> bytes:
    """Encode RGBA pixel data as PNG."""
    def write_chunk(buf: io.BytesIO, chunk_type: bytes, data: bytes) -> None:
        buf.write(struct.pack(">I", len(data)))
        buf.write(chunk_type)
        buf.write(data)
        crc = zlib.crc32(chunk_type + data) & 0xFFFFFFFF
        buf.write(struct.pack(">I", crc))

    buf = io.BytesIO()
    buf.write(b"\x89PNG\r\n\x1a\n")
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    write_chunk(buf, b"IHDR", ihdr)

    raw_rows = bytearray()
    for y in range(height):
        raw_rows.append(0)  # Filter: None
        row_start = y * width * 4
        raw_rows.extend(rgba_data[row_start:row_start + width * 4])

    compressed = zlib.compress(bytes(raw_rows), 6)
    write_chunk(buf, b"IDAT", compressed)
    write_chunk(buf, b"IEND", b"")
    return buf.getvalue()
