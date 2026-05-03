"""Camera entity for Eufy Clean vacuum map display.

Renders either:
1. A real floor plan from cleaning record data (colored rooms, walls, dock, robot)
2. A fallback position-tracking map if no floor plan is available yet
"""
from __future__ import annotations

import io
import logging
import math
import struct
import zlib
from collections import deque
from typing import Any

from homeassistant.components.camera import Camera
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import EufyCleanCoordinator

_LOGGER = logging.getLogger(__name__)

# Map rendering constants
MAP_SIZE = 800  # pixels
TRAIL_MAX_POINTS = 2000
BACKGROUND_COLOR = (32, 32, 38, 255)
TRAIL_COLOR = (100, 180, 255, 200)
ROBOT_COLOR = (50, 220, 100, 255)
DOCK_COLOR = (255, 100, 80, 255)
GRID_COLOR = (50, 50, 58, 255)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Eufy Clean camera entities."""
    data = hass.data[DOMAIN][entry.entry_id]
    coordinators: list[EufyCleanCoordinator] = data["coordinators"]

    entities = []
    for coordinator in coordinators:
        entities.append(EufyCleanMapCamera(coordinator))

    async_add_entities(entities)


class EufyCleanMapCamera(CoordinatorEntity[EufyCleanCoordinator], Camera):
    """Camera entity displaying the vacuum's map."""

    _attr_has_entity_name = True
    _attr_name = "Map"
    _attr_icon = "mdi:floor-plan"
    _attr_content_type = "image/png"

    def __init__(self, coordinator: EufyCleanCoordinator) -> None:
        """Initialize the map camera."""
        CoordinatorEntity.__init__(self, coordinator)
        Camera.__init__(self)
        self._attr_unique_id = f"{coordinator.device_id}_map"
        self._attr_device_info = coordinator.device_info
        self._trail: deque[tuple[int, int]] = deque(maxlen=TRAIL_MAX_POINTS)
        self._last_pos: tuple[int, int] | None = None
        self._cached_png: bytes | None = None
        self._last_map_png_id: int = 0  # Track when base map changes

    @property
    def available(self) -> bool:
        """Return True if we have any position data or a floor plan."""
        state = self.coordinator.data
        has_pos = state.robot_position_x != 0 or state.robot_position_y != 0
        has_map = state.map_image_png is not None
        return has_pos or has_map

    def _handle_coordinator_update(self) -> None:
        """Track position changes and invalidate cache."""
        state = self.coordinator.data
        pos = (state.robot_position_x, state.robot_position_y)

        if pos != self._last_pos and (pos[0] != 0 or pos[1] != 0):
            self._trail.append(pos)
            self._last_pos = pos
            self._cached_png = None  # Invalidate cache

        # Invalidate if the base floor plan changed
        new_map_id = id(state.map_image_png) if state.map_image_png else 0
        if new_map_id != self._last_map_png_id:
            self._last_map_png_id = new_map_id
            self._cached_png = None

        super()._handle_coordinator_update()

    async def async_camera_image(
        self, width: int | None = None, height: int | None = None
    ) -> bytes | None:
        """Return the current map image as PNG."""
        if self._cached_png is not None:
            return self._cached_png

        state = self.coordinator.data
        decoded_map = self.coordinator._decoded_map

        # If we have a decoded floor plan, render it with overlays
        if decoded_map is not None:
            from .map_renderer import render_map_png

            robot_pos = None
            if state.robot_position_x != 0 or state.robot_position_y != 0:
                robot_pos = (state.robot_position_x, state.robot_position_y)

            dock_pos = None
            if state.dock_ref_x is not None:
                dock_pos = (state.dock_ref_x, state.dock_ref_y)

            trail = list(self._trail) if self._trail else None

            png = await self.hass.async_add_executor_job(
                render_map_png,
                decoded_map,
                robot_pos,
                dock_pos,
                trail,
                MAP_SIZE,
            )
            self._cached_png = png
            return png

        # If we have a pre-rendered static floor plan but no decoded map
        # (shouldn't happen normally, but safety fallback)
        if state.map_image_png and not self._trail:
            self._cached_png = state.map_image_png
            return state.map_image_png

        # Fallback: tracking-only map
        if not self._trail:
            return None

        png = await self.hass.async_add_executor_job(
            _render_tracking_map,
            list(self._trail),
            (state.robot_position_x, state.robot_position_y),
            (state.dock_ref_x, state.dock_ref_y) if state.dock_ref_x is not None else None,
            state.activity,
            state.rooms,
        )
        self._cached_png = png
        return png

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return map metadata as attributes."""
        state = self.coordinator.data
        attrs: dict[str, Any] = {
            "trail_points": len(self._trail),
            "robot_x": state.robot_position_x,
            "robot_y": state.robot_position_y,
            "has_floor_plan": state.map_image_png is not None,
        }
        if state.map_width:
            attrs["map_width"] = state.map_width
            attrs["map_height"] = state.map_height
        if state.dock_ref_x is not None:
            attrs["dock_x"] = state.dock_ref_x
            attrs["dock_y"] = state.dock_ref_y
        if state.robot_rel_x is not None:
            attrs["rel_x_m"] = state.robot_rel_x
            attrs["rel_y_m"] = state.robot_rel_y
        decoded = self.coordinator._decoded_map
        if decoded and decoded.room_names:
            attrs["room_names"] = decoded.room_names
        return attrs


# ---- Fallback tracking-only renderer (used when no floor plan available) ----

def _render_tracking_map(
    trail: list[tuple[int, int]],
    robot_pos: tuple[int, int],
    dock_pos: tuple[int, int] | None,
    activity: str,
    rooms: list[dict[str, Any]],
) -> bytes:
    """Render the tracking map as a PNG image."""
    size = MAP_SIZE

    all_points = list(trail)
    if dock_pos:
        all_points.append(dock_pos)
    all_points.append(robot_pos)

    xs = [p[0] for p in all_points if p[0] != 0 or p[1] != 0]
    ys = [p[1] for p in all_points if p[0] != 0 or p[1] != 0]

    if not xs or not ys:
        return _empty_png(size)

    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)

    MIN_RANGE = 5000
    range_x = max(max_x - min_x, MIN_RANGE)
    range_y = max(max_y - min_y, MIN_RANGE)
    pad_x = int(range_x * 0.1) + 50
    pad_y = int(range_y * 0.1) + 50
    min_x -= pad_x
    max_x += pad_x
    min_y -= pad_y
    max_y += pad_y

    range_x = max_x - min_x
    range_y = max_y - min_y
    if range_x > range_y:
        diff = range_x - range_y
        min_y -= diff // 2
        max_y += diff // 2
    else:
        diff = range_y - range_x
        min_x -= diff // 2
        max_x += diff // 2

    range_x = max_x - min_x
    range_y = max_y - min_y

    def to_px(x: int, y: int) -> tuple[int, int]:
        px = int((x - min_x) / range_x * (size - 1))
        py = int((max_y - y) / range_y * (size - 1))
        return max(0, min(size - 1, px)), max(0, min(size - 1, py))

    img = bytearray(size * size * 4)
    for i in range(size * size):
        offset = i * 4
        img[offset] = BACKGROUND_COLOR[0]
        img[offset + 1] = BACKGROUND_COLOR[1]
        img[offset + 2] = BACKGROUND_COLOR[2]
        img[offset + 3] = BACKGROUND_COLOR[3]

    grid_step = 1000
    gx = (min_x // grid_step) * grid_step
    while gx <= max_x:
        px, _ = to_px(gx, 0)
        for py in range(size):
            _set_pixel(img, size, px, py, GRID_COLOR)
        gx += grid_step

    gy = (min_y // grid_step) * grid_step
    while gy <= max_y:
        _, py = to_px(0, gy)
        for px in range(size):
            _set_pixel(img, size, px, py, GRID_COLOR)
        gy += grid_step

    for i in range(len(trail)):
        px, py = to_px(trail[i][0], trail[i][1])
        age = (len(trail) - i) / max(len(trail), 1)
        alpha = int(200 * (1 - age * 0.7))
        color = (TRAIL_COLOR[0], TRAIL_COLOR[1], TRAIL_COLOR[2], alpha)
        _draw_circle(img, size, px, py, 3, color)
        if i + 1 < len(trail):
            npx, npy = to_px(trail[i + 1][0], trail[i + 1][1])
            _draw_line(img, size, px, py, npx, npy, color)

    if dock_pos:
        dx, dy = to_px(dock_pos[0], dock_pos[1])
        _draw_circle(img, size, dx, dy, 14, DOCK_COLOR)
        for d in range(-18, 19):
            _set_pixel(img, size, dx + d, dy, (255, 255, 255, 200))
            _set_pixel(img, size, dx, dy + d, (255, 255, 255, 200))

    rx, ry = to_px(robot_pos[0], robot_pos[1])
    _draw_circle(img, size, rx, ry, 10, ROBOT_COLOR)
    _draw_circle(img, size, rx, ry, 4, (255, 255, 255, 255))

    return _encode_png(img, size, size)


def _set_pixel(
    img: bytearray, size: int, x: int, y: int, color: tuple[int, int, int, int]
) -> None:
    """Set a single pixel with alpha blending."""
    if 0 <= x < size and 0 <= y < size:
        offset = (y * size + x) * 4
        a = color[3] / 255
        img[offset] = int(img[offset] * (1 - a) + color[0] * a)
        img[offset + 1] = int(img[offset + 1] * (1 - a) + color[1] * a)
        img[offset + 2] = int(img[offset + 2] * (1 - a) + color[2] * a)
        img[offset + 3] = 255


def _draw_circle(
    img: bytearray, size: int, cx: int, cy: int, r: int,
    color: tuple[int, int, int, int],
) -> None:
    """Draw a filled circle."""
    for dy in range(-r, r + 1):
        for dx in range(-r, r + 1):
            if dx * dx + dy * dy <= r * r:
                _set_pixel(img, size, cx + dx, cy + dy, color)


def _draw_line(
    img: bytearray, size: int, x0: int, y0: int, x1: int, y1: int,
    color: tuple[int, int, int, int],
) -> None:
    """Draw a line using Bresenham's algorithm."""
    dx = abs(x1 - x0)
    dy = abs(y1 - y0)
    sx = 1 if x0 < x1 else -1
    sy = 1 if y0 < y1 else -1
    err = dx - dy

    max_steps = dx + dy + 1
    steps = 0
    while steps < max_steps:
        _set_pixel(img, size, x0, y0, color)
        if x0 == x1 and y0 == y1:
            break
        e2 = 2 * err
        if e2 > -dy:
            err -= dy
            x0 += sx
        if e2 < dx:
            err += dx
            y0 += sy
        steps += 1


def _empty_png(size: int) -> bytes:
    """Return a blank dark PNG."""
    img = bytearray(size * size * 4)
    for i in range(size * size):
        offset = i * 4
        img[offset] = BACKGROUND_COLOR[0]
        img[offset + 1] = BACKGROUND_COLOR[1]
        img[offset + 2] = BACKGROUND_COLOR[2]
        img[offset + 3] = BACKGROUND_COLOR[3]
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
        raw_rows.append(0)
        row_start = y * width * 4
        raw_rows.extend(rgba_data[row_start:row_start + width * 4])

    compressed = zlib.compress(bytes(raw_rows), 6)
    write_chunk(buf, b"IDAT", compressed)
    write_chunk(buf, b"IEND", b"")

    return buf.getvalue()
