"""Serialize decoded :class:`MapData` into the map websocket geometry payload.

Wire format: ``docs/MAP_WS_CONTRACT.md``. The renderer's arithmetic is reproduced
exactly where the two must agree; a disagreement is silent. :func:`build_map_static`
deflates two full grids, so it runs in an executor; :func:`build_map_dynamic` is
cheap and meant for the event loop.
"""
from __future__ import annotations

import base64
import logging
import zlib
from collections.abc import Iterable, Sequence

from .map_stream import MapData, _pixel_plane, _room_mask_plane

_LOGGER = logging.getLogger(__name__)

# Payload schema version. Bump only alongside docs/MAP_WS_CONTRACT.md.
GEOMETRY_VERSION = 3

# ``rooms_grid`` stores ``real_room_id + 1`` in one byte: 254 is the largest id.
_MAX_ROOM_GRID_VALUE = 255


def _deflate_b64(data: bytes) -> str:
    """Deflate ``data`` at max level and return it base64-encoded as ASCII."""
    return base64.b64encode(zlib.compress(data, 9)).decode("ascii")


def _point_list(points: Iterable[Sequence[float]]) -> list[list[int]]:
    """Return ``[[x, y], ...]`` — JSON has no tuples."""
    return [[int(p[0]), int(p[1])] for p in points]


def _point_list_f(points: Iterable[Sequence[float]]) -> list[list[float]]:
    """Like :func:`_point_list` but keeps sub-cell precision (2 dp = 0.5 mm)."""
    return [[round(float(p[0]), 2), round(float(p[1]), 2)] for p in points]


# Mask byte -> its sub-type moved to occupancy bits 2-3.
_SUB_TYPE_BITS = bytes((b & 3) << 2 for b in range(256))


def _build_occupancy(map_data: MapData) -> bytes:
    """Expand ``raw_pixels`` to one byte per cell, row-major, with the sub-type.

    Layout per byte: ``sub_type << 2 | pv`` — bits 0-1 the occupancy value
    (0 unknown, 1 wall/obstacle, 2 free floor, 3 cleaned), bits 2-3 the room mask's
    sub-type, which must be on the wire because the renderer paints the room colour
    when ``sub_type == 0 OR pv in (2, 3)``.
    """
    cells = map_data.width * map_data.height
    occupancy = _pixel_plane(map_data.raw_pixels, cells)
    mask = _room_mask_plane(map_data)
    if mask is None:
        return occupancy
    # Disjoint bits, so one big-int OR merges the two planes.
    merged = int.from_bytes(occupancy) | int.from_bytes(mask.translate(_SUB_TYPE_BITS))
    return merged.to_bytes(cells)


def _build_rooms_grid(map_data: MapData) -> bytes:
    """Re-register the room mask onto the occupancy frame as ``real_id + 1``.

    The mask has its own origin, so cells are translated by the renderer's
    ``_ro_dx``/``_ro_dy``. ``room_id_offset`` never reaches the wire; +1 leaves 0
    meaning "no room", because room id 0 is real on legacy — so the *stored* value,
    never the resulting id, is what is tested against zero.
    """
    cells = map_data.width * map_data.height
    mask = _room_mask_plane(map_data)
    if mask is None:
        return bytes(cells)
    offset = map_data.room_id_offset
    table = bytearray(256)
    overflow = bytearray()
    for byte in range(256):
        stored = byte >> 2  # low 2 bits are sub-type
        if stored == 0:  # 0 stored == no room (real id 0 is stored as 1 on legacy)
            continue
        value = stored - offset + 1
        if value > _MAX_ROOM_GRID_VALUE:
            overflow.append(byte)
        elif value >= 1:  # below the offset names no real room; unassigned beats wrapping
            table[byte] = value
    present = [pos for byte in overflow if (pos := mask.find(byte)) >= 0]
    if present:
        _LOGGER.warning(
            "Room id %d exceeds the %d-byte room grid limit; "
            "shipping an empty rooms_grid rather than a wrapped one",
            (mask[min(present)] >> 2) - offset,
            _MAX_ROOM_GRID_VALUE - 1,
        )
        return bytes(cells)
    return mask.translate(table)


def build_map_static(map_data: MapData, *, revision: int) -> dict:
    """Build the half of the geometry payload that only changes with ``revision``.

    Derived from ``map_data`` alone, so it is cacheable per geometry revision —
    and the expensive half: two full grids built and deflated.
    """
    return {
        "v": GEOMETRY_VERSION,
        "revision": int(revision),
        "width": int(map_data.width),
        "height": int(map_data.height),
        "origin_x": int(map_data.origin_x),
        "origin_y": int(map_data.origin_y),
        "resolution": int(map_data.resolution or 5),
        "occupancy": _deflate_b64(_build_occupancy(map_data)),
        "rooms_grid": _deflate_b64(_build_rooms_grid(map_data)),
        # Real ids: room id 0 is a real room on legacy, so never filter on truthiness.
        "rooms": [
            {"id": int(rid), "name": str(name)}
            for rid, name in sorted(map_data.room_names.items())
        ],
        # Room outlines in the source-grid frame, keyed by REAL room id (0 is real).
        # Legacy only, from the live 0x65 ROOM channel.
        "room_polygons": {
            str(int(rid)): _point_list_f(poly)
            for rid, poly in sorted(map_data.room_polygons.items())
        },
        "virtual_walls": [_point_list(wall) for wall in map_data.virtual_walls],
        "forbidden_zones": [_point_list(zone) for zone in map_data.forbidden_zones],
        "ban_mop_zones": [_point_list(zone) for zone in map_data.ban_mop_zones],
    }


def build_map_dynamic(
    *,
    dock: tuple[int, int] | None = None,
    robot: tuple[int, int] | None = None,
    trail: list[tuple[int, int]] | None = None,
    trail_seq: int = 0,
    trail_types: list[int] | None = None,
    prev_trail: list[tuple[int, int]] | None = None,
    trail_color: tuple[int, int, int] | list[int] | None = None,
) -> dict:
    """Build the live half: pose, trail and the trail's presentation.

    Cheap and independent of ``map_data``, so a caller can snapshot it on the event
    loop just before sending — after the static half's executor hop — and its
    ``trail_seq`` cannot then be stale.
    """
    return {
        "dock": None if dock is None else [int(dock[0]), int(dock[1])],
        "robot": None if robot is None else [int(robot[0]), int(robot[1])],
        "trail": _point_list(trail or []),
        # One type per trail point, same order and length as "trail": 0 = cleaning,
        # 1 = transit. Only the legacy 0x67 channel reports it; others send 0.
        "trail_types": [int(t) for t in (trail_types or [])],
        "trail_seq": int(trail_seq),
        # Trail colour, for a client that draws the map without a camera entity.
        "trail_color": None if trail_color is None else [int(c) for c in trail_color],
        # Previous completed run, drawn dimmed. Snapshot-only: no event carries it.
        "prev_trail": [[int(x), int(y)] for x, y in (prev_trail or [])],
    }


def build_map_geometry(
    map_data: MapData,
    *,
    revision: int,
    dock: tuple[int, int] | None = None,
    robot: tuple[int, int] | None = None,
    trail: list[tuple[int, int]] | None = None,
    trail_seq: int = 0,
    trail_types: list[int] | None = None,
    prev_trail: list[tuple[int, int]] | None = None,
    trail_color: tuple[int, int, int] | list[int] | None = None,
) -> dict:
    """Build both halves — the whole ``robovac_mqtt/map/geometry`` payload.

    Returns the dict specified by ``docs/MAP_WS_CONTRACT.md``. Every coordinate is
    in the source-grid frame (``row * width + col``, row 0 = grid row 0); the
    renderer's Y-flip is a display concern the client applies. The occupancy and
    room grids stay separate so the client's hit-test matches the server's.
    Contains ``build_map_static``, so the same "not on the event loop" rule applies.
    """
    return {
        **build_map_static(map_data, revision=revision),
        **build_map_dynamic(
            dock=dock,
            robot=robot,
            trail=trail,
            trail_seq=trail_seq,
            trail_types=trail_types,
            prev_trail=prev_trail,
            trail_color=trail_color,
        ),
    }
