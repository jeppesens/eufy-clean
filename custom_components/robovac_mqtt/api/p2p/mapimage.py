"""Build a renderable ``MapData`` from the P2P map stream.

The renderer (``map_stream.render_map_png``) wants a real-time ``raw_pixels``
base (2 bits per pixel) plus an optional room-outline overlay (1 byte per pixel,
high 6 bits = room id). The device pushes both as ``MapChannelMsg`` objects, but
only streams the real-time map while it is moving; at rest it sends just the room
outline. When the real-time map is absent we synthesize the base from the
outline's low 2 bits (the same pixel-type nibble), so a floor plan renders either
way.
"""

from __future__ import annotations

from ...proto.cloud.p2pdata_pb2 import MapInfo
from ..map_stream import MapData, _lz4_block_decompress, _quad_points, _ROOM_SCENE_NAMES
from .mapdata import _decode_delimited, _iter_objects, _MAP_STREAM


def _decompress(pixels) -> bytes:
    if len(pixels.pixels) != pixels.pixel_size:
        return _lz4_block_decompress(pixels.pixels, pixels.pixel_size)
    return pixels.pixels


def _pack_2bit(outline: bytes) -> bytes:
    """Pack the outline's low-2-bit pixel type into the renderer's 4-px-per-byte base."""
    packed = bytearray((len(outline) + 3) // 4)
    for i, byte in enumerate(outline):
        packed[i >> 2] |= (byte & 3) << ((i & 3) * 2)
    return bytes(packed)


def build_map_data(stream: bytes) -> MapData | None:
    """Assemble a ``MapData`` from the conversation-5 byte stream, or None."""
    outline: bytes | None = None
    ow = oh = oox = ooy = 0
    realtime: bytes | None = None
    rw = rh = rox = roy = 0
    room_names: dict[int, str] = {}
    virtual_walls: list = []
    forbidden_zones: list = []
    ban_mop_zones: list = []

    for name, obj in _iter_objects(stream):
        if name != _MAP_STREAM:
            continue
        try:
            info = _decode_delimited(obj).map_info
        except Exception:  # noqa: BLE001 - skip anything that is not a whole MapChannelMsg
            continue
        kind = info.msg_type
        if kind == MapInfo.MAP_ROOMOUTLINE and info.pixels.pixel_size:
            outline = _decompress(info.pixels)
            ow, oh, oox, ooy = info.map_width, info.map_height, info.origin.x, info.origin.y
        elif kind == MapInfo.MAP_REALTIME and info.pixels.pixel_size:
            realtime = _decompress(info.pixels)
            rw, rh, rox, roy = info.map_width, info.map_height, info.origin.x, info.origin.y
        elif kind == MapInfo.ROOM_PARAMS:
            for room in info.room_params.rooms:
                room_names[room.id] = room.name.strip() or _ROOM_SCENE_NAMES.get(
                    room.scene.type, f"ROOM {room.id}"
                )
        elif kind == MapInfo.RESTRICT_ZONES:
            zones = info.restricted_zones
            virtual_walls += [((w.p0.x, w.p0.y), (w.p1.x, w.p1.y)) for w in zones.virtual_walls]
            forbidden_zones += [_quad_points(z) for z in zones.forbidden_zones]
            ban_mop_zones += [_quad_points(z) for z in zones.ban_mop_zones]

    if realtime is not None:
        base, width, height, ox, oy = realtime, rw, rh, rox, roy
    elif outline is not None:
        base, width, height, ox, oy = _pack_2bit(outline), ow, oh, oox, ooy
    else:
        return None

    return MapData(
        raw_pixels=base,
        width=width,
        height=height,
        origin_x=ox,
        origin_y=oy,
        resolution=5,
        room_pixels=outline,
        room_outline_width=ow,
        room_outline_height=oh,
        room_outline_origin_x=oox,
        room_outline_origin_y=ooy,
        room_names=room_names,
        virtual_walls=virtual_walls,
        forbidden_zones=forbidden_zones,
        ban_mop_zones=ban_mop_zones,
    )
