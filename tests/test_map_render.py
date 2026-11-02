"""Unit tests for the floor map renderer (api/map_render)."""

import io

import pytest
from PIL import Image

from custom_components.robovac_mqtt.api.map_render import (
    MapOverlay,
    render_map,
    room_color,
)
from custom_components.robovac_mqtt.api.map_stream import MapData


def _png(data: bytes) -> Image.Image:
    assert data[:4] == b"\x89PNG"
    return Image.open(io.BytesIO(data)).convert("RGBA")


def _outline_map(width=20, height=10, room_names=None, rid_at=None) -> MapData:
    rid_at = rid_at or (lambda x, y: 0 if x < width // 2 else 60)
    pixels = bytes(
        (rid_at(x, y) << 2) | (2 if rid_at(x, y) != 60 else 0)
        for y in range(height)
        for x in range(width)
    )
    return MapData(
        raw_pixels=b"",
        width=width,
        height=height,
        resolution=5,
        room_pixels=pixels,
        room_outline_width=width,
        room_outline_height=height,
        room_names=room_names if room_names is not None else {0: "Kitchen"},
    )


def test_render_smoke_realtime_only():
    """A plain 2-bit real-time map (no room mask) renders."""
    md = MapData(raw_pixels=b"\xaa" * (16 * 12 // 4), width=16, height=12, resolution=5)
    image = _png(render_map(md, max_px=160))
    assert image.size == (160, 120)


def test_output_spans_the_grid_at_the_requested_size():
    """The image keeps the grid's aspect: tap/zone transforms depend on it."""
    image = _png(render_map(_outline_map(20, 10), max_px=400))
    assert image.size == (400, 200)


def test_downscales_large_maps():
    md = MapData(raw_pixels=b"\xaa" * (800 * 400 // 4), width=800, height=400, resolution=5)
    assert _png(render_map(md, max_px=256)).size == (256, 128)


def test_room_zero_is_coloured_and_background_transparent():
    """Room id 0 is a real room (S1 Pro); outline id 60 is background."""
    image = _png(render_map(_outline_map(), MapOverlay(show_labels=False), max_px=200))
    left = image.getpixel((20, 50))
    right = image.getpixel((180, 50))
    assert left[:3] == room_color(0) and left[3] == 255
    assert right[3] == 0


def test_rooms_outside_the_target_are_dimmed():
    md = _outline_map(rid_at=lambda x, y: 0 if x < 10 else 1, room_names={0: "A", 1: "B"})
    image = _png(
        render_map(md, MapOverlay(target_rooms=frozenset({0}), show_labels=False), max_px=200)
    )
    assert image.getpixel((20, 50))[3] == 255
    assert image.getpixel((180, 50))[3] < 255


def test_unlisted_room_ids_render_as_plain_floor():
    md = _outline_map(rid_at=lambda x, y: 5, room_names={0: "Kitchen"})
    image = _png(render_map(md, MapOverlay(show_labels=False), max_px=200))
    assert image.getpixel((100, 50))[:3] != room_color(5)


def test_overlays_draw_robot_dock_path_zones_and_labels():
    md = _outline_map(40, 30)
    md.forbidden_zones = [[(0, 0), (50, 0), (50, 50), (0, 50)]]
    overlay = MapOverlay(
        robot=(10, 15),
        robot_heading=0.0,
        robot_status="charging",
        dock=(5, 5),
        path=[(2, 2, 2), (12, 2, 2), (12, 12, 0x12), (20, 12, 4)],
        obstacles=[(15, 20, "Shoe")],
        target_zones=[[(1, 1), (5, 1), (5, 5), (1, 5)]],
    )
    plain = render_map(md, MapOverlay(show_labels=False), max_px=400)
    busy = render_map(md, overlay, max_px=400)
    assert plain != busy
    # The robot marker is opaque white-ish at its centre.
    cx, cy = round((10 + 0.5) * 10), round((30 - 0.5 - 15) * 10)
    assert _png(busy).getpixel((cx, cy))[3] == 255


def test_dot_robot_style():
    md = _outline_map()
    a = render_map(md, MapOverlay(robot=(5, 5), robot_style="dot"), max_px=200)
    b = render_map(md, MapOverlay(robot=(5, 5)), max_px=200)
    assert a != b


def test_rejects_oversized_maps():
    """Regression for H2: a crafted 65535x65535 map must not allocate ~17 GB."""
    with pytest.raises(ValueError, match="exceed safety limit"):
        render_map(MapData(raw_pixels=b"", width=5000, height=5000))


def test_rejects_empty_maps():
    with pytest.raises(ValueError):
        render_map(MapData(raw_pixels=b"", width=0, height=10))
