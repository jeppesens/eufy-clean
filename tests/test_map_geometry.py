"""Unit tests for api/map_geometry.py: the map websocket geometry payload.

The load-bearing test here is ``test_rooms_grid_agrees_with_room_id_at_normalized``:
the client hit-tests rooms by sampling ``rooms_grid``, so if this file's view of
which cell belongs to which room ever drifts from ``MapData.room_id_at_normalized``
(the server's own inverse of the renderer), taps silently target the wrong room.
"""
import base64
import json
import logging
import zlib

import pytest

from custom_components.robovac_mqtt.api.map_geometry import (
    GEOMETRY_VERSION,
    build_map_geometry,
)
from custom_components.robovac_mqtt.api.map_stream import MapData

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_W, _H = 8, 6
_RES = 5
# origin - room_outline_origin over resolution gives the renderer's _ro_dx/_ro_dy.
_ORIGIN_X, _ORIGIN_Y = 10, 5      # -> _ro_dx = 2, _ro_dy = 1
_RO_W, _RO_H = 4, 3


def _pack_2bpp(values: list[int]) -> bytes:
    """Pack per-cell 0-3 values into the renderer's 2 bits-per-cell plane."""
    raw = bytearray((len(values) + 3) // 4)
    for i, v in enumerate(values):
        raw[i >> 2] |= (v & 3) << ((i & 3) * 2)
    return bytes(raw)


def _unpack(field: str) -> bytes:
    """Reverse the wire encoding of one grid: base64 -> inflate -> bytes."""
    return zlib.decompress(base64.b64decode(field))


def _room_mask(stored_ids: list[int], sub_types: list[int] | None = None) -> bytes:
    """Build a room mask byte plane: ``stored_id << 2 | sub_type``."""
    subs = sub_types or [0] * len(stored_ids)
    return bytes((sid << 2) | (sub & 3) for sid, sub in zip(stored_ids, subs))


# A 4x3 room mask, stored ids (legacy: real id + 1). 0 = no room.
#   row 0:  1 1 2 2      -> real rooms 0 0 1 1
#   row 1:  1 0 2 2      -> real rooms 0 . 1 1
#   row 2:  3 3 3 0      -> real rooms 2 2 2 .
_STORED = [1, 1, 2, 2,
           1, 0, 2, 2,
           3, 3, 3, 0]
# Sub-types are the low 2 bits and must be stripped; set some non-zero ones so a
# missing ``>> 2`` cannot pass.
_SUBS = [0, 1, 0, 2,
         3, 0, 1, 0,
         0, 2, 0, 0]

# Occupancy: a mix of all four pixel values so the bit extraction is exercised.
_PIXELS = [(i * 7) % 4 for i in range(_W * _H)]


def _make_map(
    *,
    room_id_offset: int = 1,
    room_pixels: bytes | None = None,
    with_rooms: bool = True,
) -> MapData:
    return MapData(
        raw_pixels=_pack_2bpp(_PIXELS),
        width=_W,
        height=_H,
        origin_x=_ORIGIN_X,
        origin_y=_ORIGIN_Y,
        resolution=_RES,
        room_pixels=(room_pixels if room_pixels is not None else _room_mask(_STORED, _SUBS))
        if with_rooms
        else None,
        room_outline_width=_RO_W if with_rooms else 0,
        room_outline_height=_RO_H if with_rooms else 0,
        room_outline_origin_x=0,
        room_outline_origin_y=0,
        room_names={0: "Hallway", 1: "Kitchen", 2: "Bedroom"} if with_rooms else {},
        room_id_offset=room_id_offset,
    )


# ---------------------------------------------------------------------------
# Occupancy
# ---------------------------------------------------------------------------


def test_occupancy_round_trips_to_one_byte_per_cell():
    """Bits 0-1 are the occupancy value; bits 2-3 carry the room sub-type."""
    result = build_map_geometry(_make_map(), revision=7)
    occupancy = _unpack(result["occupancy"])

    assert len(occupancy) == _W * _H
    assert [cell & 3 for cell in occupancy] == _PIXELS


def test_occupancy_carries_the_room_sub_type_in_bits_2_3():
    """Without the sub-type the client cannot reproduce the server's fill.

    ``render_map_png`` paints the room colour when ``sub_type == 0 OR pv in
    (2, 3)`` (map_stream.py:486-492). A client seeing only ``pv`` cannot evaluate
    the first disjunct, so an in-room cell with sub-type 0 and pv 0/1 would render
    void/wall on the client and room-coloured on the server.
    """
    map_data = _make_map()
    occupancy = _unpack(build_map_geometry(map_data, revision=1)["occupancy"])

    res = map_data.resolution or 5
    ro_dx = round((map_data.origin_x - map_data.room_outline_origin_x) / res)
    ro_dy = round((map_data.origin_y - map_data.room_outline_origin_y) / res)
    seen = set()
    for row in range(_H):
        for col in range(_W):
            rx, ry = col - ro_dx, row - ro_dy
            expected = 0
            if 0 <= rx < map_data.room_outline_width and 0 <= ry < map_data.room_outline_height:
                idx = ry * map_data.room_outline_width + rx
                if idx < len(map_data.room_pixels):
                    expected = map_data.room_pixels[idx] & 3
            got = (occupancy[row * _W + col] >> 2) & 3
            assert got == expected, f"sub-type at ({col},{row})"
            seen.add(expected)
    # the fixture must actually exercise a non-zero sub-type, or this is vacuous
    assert seen != {0}


def test_occupancy_pads_short_raw_pixels_with_unknown():
    """A truncated 2bpp plane yields 0 (unknown), matching the renderer's guard."""
    map_data = _make_map()
    map_data.raw_pixels = map_data.raw_pixels[:3]  # covers only the first 12 cells

    occupancy = _unpack(build_map_geometry(map_data, revision=1)["occupancy"])

    assert len(occupancy) == _W * _H
    assert [cell & 3 for cell in occupancy[:12]] == _PIXELS[:12]
    assert {cell & 3 for cell in occupancy[12:]} == {0}


# ---------------------------------------------------------------------------
# rooms_grid
# ---------------------------------------------------------------------------


def test_rooms_grid_registers_mask_with_renderer_offsets():
    """The mask sits at _ro_dx=2, _ro_dy=1 in the occupancy frame."""
    rooms_grid = _unpack(build_map_geometry(_make_map(), revision=1)["rooms_grid"])

    assert len(rooms_grid) == _W * _H
    grid = [list(rooms_grid[r * _W:(r + 1) * _W]) for r in range(_H)]
    # stored id -> real id (offset 1) -> wire value (+1) == stored id here.
    assert grid == [
        [0, 0, 0, 0, 0, 0, 0, 0],
        [0, 0, 1, 1, 2, 2, 0, 0],
        [0, 0, 1, 0, 2, 2, 0, 0],
        [0, 0, 3, 3, 3, 0, 0, 0],
        [0, 0, 0, 0, 0, 0, 0, 0],
        [0, 0, 0, 0, 0, 0, 0, 0],
    ]


def _cell_from_normalized(nx: float, ny: float) -> tuple[int, int]:
    """The card's own normalized -> source-cell inverse, in Python.

    Mirrors ``eufy-map-renderer.js``: ``col = nx * width``, ``row = (1 - ny) *
    height``, both FLOORED (``roomIdAt`` / ``cellFromEvent``). A cell owns the
    half-open span of its own width, so floor is the inverse and round is not —
    rounding pushed every point in the outer half of a cell into the next one.
    """
    return (
        min(max(int(nx * _W), 0), _W - 1),
        min(max(int((1.0 - ny) * _H), 0), _H - 1),
    )


def test_rooms_grid_agrees_with_room_id_at_normalized():
    """The client's hit-test must resolve the same room the server does.

    ``room_id_at_normalized`` takes *rendered, top-left* normalized coords and
    maps them back into the unflipped source frame that ``rooms_grid`` is in, so
    the sample points are mapped with that same inverse (the Y-flip included)
    before the grid is indexed. The inverse used here is the CARD's, not a copy
    of the server's: agreeing with itself is not what this test is for.
    """
    map_data = _make_map()
    rooms_grid = _unpack(build_map_geometry(map_data, revision=1)["rooms_grid"])

    seen_a_room = False
    for i in range(21):
        for j in range(21):
            nx, ny = i / 20, j / 20
            px, py = _cell_from_normalized(nx, ny)

            stored = rooms_grid[py * _W + px]
            from_grid = None if stored == 0 else stored - 1
            expected = map_data.room_id_at_normalized(nx, ny)

            assert from_grid == expected, f"disagreement at ({nx}, {ny}) cell ({px}, {py})"
            if expected is not None:
                seen_a_room = True

    assert seen_a_room, "sample never landed on a room — the test proves nothing"


def test_legacy_room_id_zero_survives_as_grid_value_one():
    """Room id 0 is a real room on legacy; it must not read as 'no room'."""
    result = build_map_geometry(_make_map(room_id_offset=1), revision=1)
    rooms_grid = _unpack(result["rooms_grid"])

    # Mask cell (0, 0) holds stored id 1 -> real id 0 -> wire value 1.
    assert rooms_grid[1 * _W + 2] == 1
    assert {r["id"] for r in result["rooms"]} == {0, 1, 2}
    assert {"id": 0, "name": "Hallway"} in result["rooms"]


def test_novel_room_id_offset_zero_yields_real_ids():
    """With no offset the stored id *is* the real id, so the wire value is id + 1."""
    map_data = _make_map(room_id_offset=0)
    rooms_grid = _unpack(build_map_geometry(map_data, revision=1)["rooms_grid"])

    assert rooms_grid[1 * _W + 2] == 2   # stored 1 -> real 1 -> 2
    assert rooms_grid[3 * _W + 2] == 4   # stored 3 -> real 3 -> 4
    # Still the exact inverse of the server's own lookup: the CENTRE of source
    # cell (col 2, row 2) under the card's `nx = col / w`, `ny = 1 - row / h`.
    assert map_data.room_id_at_normalized(2.5 / _W, 1.0 - 2.5 / _H) == 1


def test_no_room_mask_yields_all_zero_grid():
    result = build_map_geometry(_make_map(with_rooms=False), revision=1)
    rooms_grid = _unpack(result["rooms_grid"])

    assert len(rooms_grid) == _W * _H
    assert set(rooms_grid) == {0}
    assert result["rooms"] == []


def test_room_id_above_byte_range_ships_empty_grid_and_warns(caplog):
    """A wrapped room id would clean the wrong room, so ship nothing instead.

    A ``bytes`` mask holds stored ids up to 63, so a negative ``room_id_offset``
    reaches the guard (63 + 337 = 400), which exists because the byte grid is the
    wire contract, not an artefact of today's source planes.
    """
    map_data = _make_map(room_pixels=bytes([0, 0, 0, 0,
                                            0, 0, 0, 0,
                                            0, 0, 0, 63 << 2]),
                         room_id_offset=-337)

    with caplog.at_level(logging.WARNING):
        rooms_grid = _unpack(build_map_geometry(map_data, revision=1)["rooms_grid"])

    assert set(rooms_grid) == {0}
    assert len(rooms_grid) == _W * _H
    assert "400" in caplog.text


def test_stored_id_below_offset_is_not_wrapped():
    """A stored id under the offset names no room; it must not wrap into one."""
    map_data = _make_map(room_pixels=_room_mask([1] * (_RO_W * _RO_H)), room_id_offset=2)

    rooms_grid = _unpack(build_map_geometry(map_data, revision=1)["rooms_grid"])

    assert set(rooms_grid) == {0}


# ---------------------------------------------------------------------------
# Envelope
# ---------------------------------------------------------------------------


def test_envelope_carries_geometry_and_live_positions():
    map_data = _make_map()
    map_data.virtual_walls = [((10, 20), (30, 40))]
    map_data.forbidden_zones = [[(0, 0), (10, 0), (10, 10), (0, 10)]]
    map_data.ban_mop_zones = [[(1, 1), (2, 1), (2, 2), (1, 2)]]

    result = build_map_geometry(
        map_data,
        revision=42,
        dock=(3, 4),
        robot=(5, 2),
        trail=[(1, 1), (2, 2)],
        trail_types=[1, 0],
        trail_seq=949,
    )

    assert result["v"] == GEOMETRY_VERSION == 3
    assert result["revision"] == 42
    assert (result["width"], result["height"]) == (_W, _H)
    assert (result["origin_x"], result["origin_y"]) == (_ORIGIN_X, _ORIGIN_Y)
    assert result["resolution"] == _RES
    assert result["virtual_walls"] == [[[10, 20], [30, 40]]]
    assert result["forbidden_zones"] == [[[0, 0], [10, 0], [10, 10], [0, 10]]]
    assert result["ban_mop_zones"] == [[[1, 1], [2, 1], [2, 2], [1, 2]]]
    assert result["dock"] == [3, 4]
    assert result["robot"] == [5, 2]
    assert result["trail"] == [[1, 1], [2, 2]]
    assert result["trail_types"] == [1, 0]
    assert result["trail_seq"] == 949


def test_absent_pose_and_trail_are_null_and_empty():
    result = build_map_geometry(_make_map(), revision=1)

    assert result["dock"] is None
    assert result["robot"] is None
    assert result["trail"] == []
    assert result["trail_types"] == []
    assert result["trail_seq"] == 0


def test_zero_resolution_falls_back_to_five():
    map_data = _make_map()
    map_data.resolution = 0

    assert build_map_geometry(map_data, revision=1)["resolution"] == 5


def test_payload_is_json_serializable():
    map_data = _make_map()
    map_data.virtual_walls = [((10, 20), (30, 40))]
    map_data.forbidden_zones = [[(0, 0), (10, 0), (10, 10), (0, 10)]]

    encoded = json.dumps(
        build_map_geometry(
            map_data, revision=1, dock=(3, 4), robot=(5, 2), trail=[(1, 1)], trail_seq=2
        )
    )

    assert json.loads(encoded)["rooms"][0] == {"id": 0, "name": "Hallway"}


@pytest.mark.parametrize("field", ["occupancy", "rooms_grid"])
def test_grids_are_deflated_base64_ascii(field):
    value = build_map_geometry(_make_map(), revision=1)[field]

    assert isinstance(value, str)
    assert value.isascii()
    assert len(_unpack(value)) == _W * _H


def test_prev_trail_is_carried_and_defaults_empty():
    """The previous run rides in the snapshot, never in an event.

    A new clean clears the live trail, so without this the map is blank for the
    first minutes of every session. It is snapshot-only because it never changes
    mid-session — only a session boundary replaces it.
    """
    payload = build_map_geometry(_make_map(), revision=1)
    assert payload["prev_trail"] == []

    payload = build_map_geometry(
        _make_map(), revision=1, prev_trail=[(1, 2), (3, 4)]
    )
    assert payload["prev_trail"] == [[1, 2], [3, 4]]
    json.dumps(payload)  # still serializable


def test_geometry_ships_room_polygons_with_real_ids():
    """Room outlines ride the geometry payload keyed by REAL room id.

    Room id 0 is a real room on legacy devices, so it must appear as the key
    ``"0"`` and never be filtered out by a truthiness test.
    """
    map_data = MapData(
        raw_pixels=b"\x00" * 25,
        width=10,
        height=10,
        resolution=5,
        room_polygons={
            0: [(1.5, 2.5), (3.5, 2.5), (3.5, 4.5)],
            2: [(5.0, 5.0), (7.0, 5.0), (7.0, 7.0)],
        },
    )
    payload = build_map_geometry(map_data, revision=1)
    assert set(payload["room_polygons"]) == {"0", "2"}
    assert payload["room_polygons"]["0"] == [[1.5, 2.5], [3.5, 2.5], [3.5, 4.5]]


def test_geometry_room_polygons_keep_subcell_precision():
    """Outline vertices are floats — truncating them would square off the shape."""
    map_data = MapData(
        raw_pixels=b"\x00" * 25,
        width=10,
        height=10,
        room_polygons={1: [(1.23, 4.56), (2.0, 3.0), (4.0, 4.0)]},
    )
    payload = build_map_geometry(map_data, revision=1)
    assert payload["room_polygons"]["1"][0] == [1.23, 4.56]


def test_geometry_room_polygons_default_empty():
    """Novel devices have no 0x65 channel, so the field is present but empty."""
    payload = build_map_geometry(
        MapData(raw_pixels=b"\x00" * 25, width=10, height=10), revision=1
    )
    assert payload["room_polygons"] == {}


def test_geometry_carries_the_trail_colour():
    """The trail colour rides the payload, not just the camera's attributes.

    A dashboard that draws the map in the browser need not have a camera entity
    configured at all — reading a documented option off one would silently ignore
    it. The camera keeps publishing it too, for the PNG path and old clients.
    """
    md = MapData(
        raw_pixels=b"", width=4, height=4, origin_x=0, origin_y=0, resolution=5
    )
    assert build_map_geometry(md, revision=1)["trail_color"] is None
    assert build_map_geometry(md, revision=1, trail_color=(1, 2, 3))["trail_color"] == [
        1, 2, 3
    ]
