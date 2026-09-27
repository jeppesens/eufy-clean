"""Generate the golden per-cell raster fixture shared by the Python and JS suites.

WHAT THIS PROVES, AND WHAT IT DOES NOT
--------------------------------------
``render_map_png`` (Pillow, server) and ``buildGridImageData`` (browser) rasterise
the *same* grid. Neither test suite can run the other's language, so a divergence
between them passes both suites green while the map visibly differs in a browser.
This fixture pins **RGB and class per cell over several realistic maps**, including
every ``(sub_type, pv, stored id)`` combination and the two registration details a
flat grid cannot reach (the room mask's ``_ro_dx``/``_ro_dy`` offset, and
``room_id_offset``).

**The comparison is at SOURCE-GRID RESOLUTION — one texel per grid cell.** That is
the whole of what is comparable without a canvas:

* ``render_map_png`` builds its colour list at cell resolution (``map_stream.py``
  step 1), and only then applies ``FLIP_TOP_BOTTOM`` and a NEAREST resize to
  ``max_px``. The client does the same two operations as a single
  ``ctx.setTransform`` with a negative vertical scale plus
  ``imageSmoothingEnabled=false``. Both post-processing steps are exact and
  parameter-free given the pre-flip raster, so proving the raster equal proves the
  grid layer equal.
* Everything drawn *on top* of the grid — dock, trail, robot, zones, room labels —
  is drawn at output resolution by both ends and is **not** covered here. jsdom
  ships no 2d context, so nothing in the JS suite can render those at all.

So: this is a golden-image check of the **grid layer**, pre-flip and pre-resize.
It is not a full-frame image diff and must not be described as one.

WHERE THE TWO PALETTES DELIBERATELY DIFFER
------------------------------------------
They are not the same palette and are not meant to be:

* ``_ROOM_PALETTE`` (server) is 9 entries with index 0 reserved, so rooms cycle
  through **8** hues. ``ROOM_PALETTE`` (client) is Paul Tol's colour-blind-safe
  "muted" scheme, **10** hues, none reserved. Room fills therefore never match by
  RGB, and this fixture does not ask them to — the JS side asserts the *structure*
  (identical set of room-filled cells, one client colour per room id).
* The unknown/void cell is ``(30, 30, 30)`` opaque on the server and fully
  transparent on the client, on purpose: the card's own background shows through
  the void, which a flat PNG could not do.
* Wall, free floor and cleaned floor **do** match exactly in the light theme, and
  the JS side asserts that as a hard RGB equality.

Fixture written to ``tests/frontend/fixtures/golden_render.json``;
``tests/test_golden_fixture.py`` regenerates it and fails if it is stale, and also
checks the expected colours below against a real ``render_map_png`` call — so the
derivation here can never quietly drift from the renderer it is speaking for.

Refresh with: ``PYTHONPATH=. python3 tests/generate_golden_fixture.py``
"""
from __future__ import annotations

import base64
import json
import zlib
from pathlib import Path

from custom_components.robovac_mqtt.api.map_geometry import build_map_geometry
from custom_components.robovac_mqtt.api.map_stream import (
    _PIXEL_COLORS,
    _ROOM_PALETTE,
    MapData,
)

FIXTURE = Path(__file__).parent / "frontend" / "fixtures" / "golden_render.json"

# Class byte written into ``expected_class``. 0-3 are the occupancy value of a cell
# the server colours from _PIXEL_COLORS; a room-filled cell is _ROOM_CLASS_BASE plus
# its REAL room id (real id 0 exists on legacy, hence the base rather than +1).
_ROOM_CLASS_BASE = 8


# ---------------------------------------------------------------------------
# map builders
# ---------------------------------------------------------------------------


def _pack_pv(values: list[int]) -> bytes:
    """Pack a per-cell occupancy list into the 2 bits-per-pixel plane."""
    raw = bytearray((len(values) + 3) // 4)
    for i, v in enumerate(values):
        raw[i >> 2] |= (v & 3) << ((i & 3) * 2)
    return bytes(raw)


def _apartment(
    width: int = 150,
    height: int = 215,
    *,
    room_id_offset: int = 1,
    mask_origin_shift: tuple[int, int] = (0, 0),
) -> MapData:
    """A 150x215 apartment: 6 rectangular rooms, walls between them, void outside.

    Shaped like the real T2266 grid the contract was measured on (150 x 215 =
    32 250 cells, 6 rooms). Deterministic — no RNG anywhere, so the fixture is
    byte-reproducible.

    ``mask_origin_shift`` moves the room mask's own origin away from the map
    origin, which is what makes ``_ro_dx``/``_ro_dy`` non-zero: the mask is then a
    smaller plane that has to be re-registered onto the occupancy grid, and cells
    outside it must come out room-less on both ends. Rooms whose real ids start at
    ``1 - room_id_offset`` so that a legacy map (offset 1) really does contain room
    id **0**, which is a real room on a T2266 and must never be truthiness-tested.
    """
    res = 5
    # Six rooms as (col0, row0, col1, row1) half-open rectangles, laid out as a
    # flat: a long corridor down the middle with rooms either side.
    # Laid out against the reference 150x215 grid and scaled to whatever size is
    # asked for, so the same flat can be rendered at a second resolution without a
    # second hand-drawn layout drifting from this one.
    _REF_W, _REF_H = 150, 215
    _layout = [
        (10, 10, 70, 90),     # living room
        (74, 10, 140, 60),    # bedroom
        (74, 64, 140, 120),   # bedroom 2
        (10, 94, 70, 150),    # kitchen
        (10, 154, 140, 205),  # hallway (spans the width)
        (74, 124, 140, 150),  # bathroom
    ]
    rects = [
        (
            round(c0 * width / _REF_W),
            round(r0 * height / _REF_H),
            round(c1 * width / _REF_W),
            round(r1 * height / _REF_H),
        )
        for c0, r0, c1, r1 in _layout
    ]
    pv = [0] * (width * height)
    mask_w = width - abs(mask_origin_shift[0]) if mask_origin_shift[0] else width
    mask_h = height - abs(mask_origin_shift[1]) if mask_origin_shift[1] else height
    # _ro_dx = round((origin_x - room_outline_origin_x) / res)
    ro_dx = round((0 - mask_origin_shift[0]) / res)
    ro_dy = round((0 - mask_origin_shift[1]) / res)
    mask = bytearray(mask_w * mask_h)

    for index, (c0, r0, c1, r1) in enumerate(rects):
        real_id = index + (1 - room_id_offset)
        stored = real_id + room_id_offset
        for row in range(r0, r1):
            for col in range(c0, c1):
                i = row * width + col
                on_edge = row in (r0, r1 - 1) or col in (c0, c1 - 1)
                # Perimeter cells are wall (pv 1); a band of the interior is
                # "cleaned" (pv 3) so the free/cleaned split is exercised.
                pv[i] = 1 if on_edge else (3 if (row - r0) % 7 < 2 else 2)
                # sub_type: 0 over the interior, 1 on the room outline. That is the
                # combination that diverges without the sub-type on the wire — an
                # edge cell is pv 1 (wall) AND in a room, so the server paints it
                # room-coloured only via the `sub_type == 0` disjunct... which is
                # false here, so it stays wall; while the INTERIOR pv-0 pockets
                # below have sub_type 0 and MUST come out room-coloured.
                sub = 1 if on_edge else 0
                # Unmapped pockets inside a room: pv 0 with sub_type 0. The server
                # room-fills these; a client without the sub-type draws void.
                if not on_edge and (row * 31 + col * 17) % 97 == 0:
                    pv[i] = 0
                mx, my = col - ro_dx, row - ro_dy
                if 0 <= mx < mask_w and 0 <= my < mask_h:
                    mask[my * mask_w + mx] = (stored << 2) | sub

    return MapData(
        raw_pixels=_pack_pv(pv),
        width=width,
        height=height,
        origin_x=0,
        origin_y=0,
        resolution=res,
        room_pixels=bytes(mask),
        room_outline_width=mask_w,
        room_outline_height=mask_h,
        room_outline_origin_x=mask_origin_shift[0],
        room_outline_origin_y=mask_origin_shift[1],
        room_names={
            index + (1 - room_id_offset): name
            for index, name in enumerate(
                ["Living Rm", "Bedroom", "Bedroom 2", "Kitchen", "Hallway", "Bathroom"]
            )
        },
        room_id_offset=room_id_offset,
    )


def _all_combinations() -> MapData:
    """One cell per ``(sub_type, pv, stored room id)`` combination — exhaustive.

    4 sub-types x 4 occupancy values x 4 stored ids = **64 cells**, enumerated in
    order rather than drawn at random, so a failure names the exact combination
    rather than a seed. The two combinations that diverge when the sub-type is
    dropped from the wire (``sub_type == 0`` with ``pv`` 0 or 1, in a room) are
    cells 0-1 of each room block.

    Stored id 0 is included **with a non-zero sub-type**, which a "rooms only" grid
    would never produce: the sub-type rides in the mask byte, so the wire can carry
    one for a cell that belongs to no room. Both renderers must ignore it there —
    the server because it tests ``rid > 0`` first, the client because ``rooms_grid``
    is 0 — and that agreement is only tested if the combination exists.
    """
    width = 16
    height = 4
    pv = [0] * (width * height)
    mask = bytearray(width * height)
    i = 0
    for room in range(4):          # stored id; 0 = no room (sub-type still varies)
        for sub in range(4):
            for value in range(4):
                pv[i] = value
                mask[i] = (room << 2) | sub
                i += 1
    assert i == width * height
    return MapData(
        raw_pixels=_pack_pv(pv),
        width=width,
        height=height,
        origin_x=0,
        origin_y=0,
        resolution=5,
        room_pixels=bytes(mask),
        room_outline_width=width,
        room_outline_height=height,
        room_outline_origin_x=0,
        room_outline_origin_y=0,
        room_names={0: "R0", 1: "R1", 2: "R2"},
        room_id_offset=1,
    )


def _palette_cycle() -> MapData:
    """12 rooms in one row-block each — more rooms than either palette has hues.

    The server cycles 8 hues (``_ROOM_PALETTE`` reserves index 0), the client 10.
    So the two ends collide *different pairs* of rooms, and a naive "one colour per
    room, one room per colour" assertion is wrong on both. The JS side allows a
    collision only where the client's own index arithmetic says two rooms share a
    slot — which is the honest invariant, and it still catches a room being drawn
    with the wrong hue.
    """
    width = 12
    height = 12
    pv = [2] * (width * height)
    mask = bytearray(width * height)
    for row in range(height):
        stored = row + 1  # real ids 0..11 with offset 1
        for col in range(width):
            mask[row * width + col] = stored << 2
    return MapData(
        raw_pixels=_pack_pv(pv),
        width=width,
        height=height,
        origin_x=0,
        origin_y=0,
        resolution=5,
        room_pixels=bytes(mask),
        room_outline_width=width,
        room_outline_height=height,
        room_outline_origin_x=0,
        room_outline_origin_y=0,
        room_names={rid: f"Room {rid}" for rid in range(12)},
        room_id_offset=1,
    )


def _no_room_mask() -> MapData:
    """The renderer's else-branch: no room mask at all, colours from ``pv`` only."""
    width = 12
    height = 8
    pv = [(col + row) % 4 for row in range(height) for col in range(width)]
    return MapData(
        raw_pixels=_pack_pv(pv),
        width=width,
        height=height,
        origin_x=-1200,
        origin_y=-800,
        resolution=5,
    )


# ---------------------------------------------------------------------------
# the server's own colour rule
# ---------------------------------------------------------------------------


def server_cell_colors(map_data: MapData) -> list[tuple[int, int, int]]:
    """The pre-flip colour of every cell, by ``render_map_png``'s own rule.

    This mirrors ``map_stream.py`` step 1 (lines 460-506) and imports the colour
    tables rather than restating them, so a palette edit lands here automatically.
    ``tests/test_golden_fixture.py`` additionally asserts this equals the pixels a
    real ``render_map_png`` call produces at scale 1 with the overlays stripped —
    the derivation is never trusted on its own.

    Returned in the SOURCE-GRID frame: index ``row * width + col`` with row 0 =
    grid row 0. ``render_map_png`` flips this on the way out; the client flips at
    draw time. Neither flip is applied here, which is exactly why the two are
    comparable.
    """
    width, height = map_data.width, map_data.height
    raw = map_data.raw_pixels
    room_px = map_data.room_pixels
    res = map_data.resolution or 5
    colors: list[tuple[int, int, int]] = []

    if room_px is not None and map_data.room_outline_width and map_data.room_outline_height:
        ro_w = map_data.room_outline_width
        ro_h = map_data.room_outline_height
        ro_dx = round((map_data.origin_x - map_data.room_outline_origin_x) / res)
        ro_dy = round((map_data.origin_y - map_data.room_outline_origin_y) / res)
        palette_len = len(_ROOM_PALETTE)
        for py in range(height):
            for px_x in range(width):
                i = py * width + px_x
                byte_pos = i >> 2
                bit_pos = (i & 3) * 2
                pv = (raw[byte_pos] >> bit_pos) & 3 if byte_pos < len(raw) else 0
                rx, ry = px_x - ro_dx, py - ro_dy
                if 0 <= rx < ro_w and 0 <= ry < ro_h:
                    rpx = room_px[ry * ro_w + rx]
                    rid = rpx >> 2
                    sub_type = rpx & 3
                else:
                    rid = sub_type = 0
                if rid > 0:
                    if sub_type == 0 or pv in (2, 3):
                        colors.append(_ROOM_PALETTE[1 + (rid - 1) % (palette_len - 1)])
                    else:
                        colors.append(_PIXEL_COLORS.get(pv, (30, 30, 30)))
                else:
                    colors.append(_PIXEL_COLORS.get(pv, (30, 30, 30)))
    else:
        for i in range(width * height):
            byte_pos = i >> 2
            bit_pos = (i & 3) * 2
            pv = (raw[byte_pos] >> bit_pos) & 3 if byte_pos < len(raw) else 0
            colors.append(_PIXEL_COLORS.get(pv, (30, 30, 30)))
    return colors


def server_cell_classes(map_data: MapData) -> list[int]:
    """Per-cell class byte: the occupancy value, or ``8 + real room id`` if filled.

    The class is what the client must agree with *structurally*, since the two room
    palettes deliberately differ. It is derived from the same branch the colour is,
    so the two planes can never describe different cells.
    """
    width, height = map_data.width, map_data.height
    raw = map_data.raw_pixels
    res = map_data.resolution or 5
    out: list[int] = []
    # The room plane, or None when the map carries no usable mask.
    room_px = (
        map_data.room_pixels
        if map_data.room_outline_width and map_data.room_outline_height
        else None
    )
    ro_w = map_data.room_outline_width
    ro_h = map_data.room_outline_height
    ro_dx = round((map_data.origin_x - map_data.room_outline_origin_x) / res)
    ro_dy = round((map_data.origin_y - map_data.room_outline_origin_y) / res)

    for py in range(height):
        for px_x in range(width):
            i = py * width + px_x
            byte_pos = i >> 2
            bit_pos = (i & 3) * 2
            pv = (raw[byte_pos] >> bit_pos) & 3 if byte_pos < len(raw) else 0
            rid = sub_type = 0
            if room_px is not None:
                rx, ry = px_x - ro_dx, py - ro_dy
                if 0 <= rx < ro_w and 0 <= ry < ro_h:
                    rpx = room_px[ry * ro_w + rx]
                    rid = rpx >> 2
                    sub_type = rpx & 3
            if rid > 0 and (sub_type == 0 or pv in (2, 3)):
                real = rid - map_data.room_id_offset
                if not 0 <= real <= 255 - _ROOM_CLASS_BASE:
                    raise ValueError(f"room id {real} does not fit the class byte")
                out.append(_ROOM_CLASS_BASE + real)
            else:
                out.append(pv)
    return out


def _plane(data: bytes) -> str:
    return base64.b64encode(zlib.compress(bytes(data), 9)).decode("ascii")


def _cases() -> dict[str, tuple[str, MapData]]:
    return {
        "apartment": (
            "150x215 apartment, 6 rooms, room_id_offset=1 (legacy: real room id 0 "
            "exists). Room outlines carry sub_type 1, interiors sub_type 0, with "
            "unmapped pv-0 pockets inside rooms.",
            _apartment(),
        ),
        "mask_origin_offset": (
            "Same apartment with the room mask's origin moved off the map origin, "
            "so _ro_dx/_ro_dy are non-zero and the mask is smaller than the grid. "
            "Cells outside the mask must be room-less on both ends.",
            _apartment(mask_origin_shift=(-50, -30)),
        ),
        "novel_offset0": (
            "The novel/MQTT numbering: room_id_offset=0, real ids start at 1. The "
            "wire never carries the offset, so the client must land on the same "
            "cells without knowing it.",
            _apartment(width=90, height=120, room_id_offset=0),
        ),
        "all_combinations": (
            "Every (sub_type, pv, stored room id) combination exactly once — 64 cells, "
            "including a sub-type on a cell that belongs to no room.",
            _all_combinations(),
        ),
        "palette_cycle": (
            "12 rooms: more than the server's 8 cycling hues and more than the "
            "client's 10, so both ends collide rooms, and differently.",
            _palette_cycle(),
        ),
        "no_room_mask": (
            "No room mask at all: render_map_png's else-branch, colours from the "
            "occupancy value alone.",
            _no_room_mask(),
        ),
    }


def build() -> dict:
    """Build the whole fixture document."""
    cases = []
    for name, (description, map_data) in _cases().items():
        colors = server_cell_colors(map_data)
        rgb = bytearray()
        for r, g, b in colors:
            rgb += bytes((r, g, b))
        cases.append(
            {
                "name": name,
                "description": description,
                "cells": map_data.width * map_data.height,
                "room_id_offset": map_data.room_id_offset,
                "payload": build_map_geometry(map_data, revision=1),
                # Server RGB per cell, source-grid order, pre-flip, pre-resize.
                "expected_rgb": _plane(rgb),
                # Per-cell class: 0-3 = occupancy value, 8 + real room id = filled.
                "expected_class": _plane(bytes(server_cell_classes(map_data))),
            }
        )
    return {
        "v": 1,
        "room_class_base": _ROOM_CLASS_BASE,
        # Imported from map_stream, never retyped: the JS side asserts its own
        # wall/floor/cleaned colours equal these, and reports the room hues and the
        # void as the two places the palettes deliberately part company.
        "server_pixel_colors": {str(k): list(v) for k, v in sorted(_PIXEL_COLORS.items())},
        "server_room_palette": [list(c) for c in _ROOM_PALETTE],
        "cases": cases,
    }


if __name__ == "__main__":
    FIXTURE.parent.mkdir(parents=True, exist_ok=True)
    document = build()
    FIXTURE.write_text(json.dumps(document, indent=2) + "\n")
    total = sum(c["cells"] for c in document["cases"])
    print(f"wrote {FIXTURE} ({total} cells across {len(document['cases'])} cases)")
