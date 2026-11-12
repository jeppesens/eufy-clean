"""Parse the Tuya ``0pam`` map blob used by legacy Eufy vacuums (e.g. T2266).

Legacy devices publish no map on any datapoint; the app downloads the blob from
Tuya cloud storage and parses it locally, which is what makes a room list
available at all. The wire layout is documented inline below.

Grid cells are signed bytes: -1 unmapped, -7 obstacle, -12 wall, and >=0 a room
cell whose id is ``cell // 4`` (room 0 reads 0, room 1 reads 4, ...).
"""

from __future__ import annotations

import logging
import struct
from dataclasses import dataclass, field
from typing import Any

from ..utils import decode_varint, decode_zigzag, lz4_block_decompress

# Bounds on an attacker-influenceable map header; generous for any real map.
# ``_MAX_MAP_DIMENSION`` also bounds the biz/ stream maps in ``map_stream``.
_MAX_MAP_DIMENSION = 4000
# The trailer after the grid: a handful of sections whose uint8 counts cap each
# at 255 records (room names 255 x 255 bytes is the largest, ~64 KiB).
_MAX_TRAILER_BYTES = 1 << 17

_LOGGER = logging.getLogger(__name__)

MAGIC = b"0pam"
HEADER_LEN = 24

# Clean-record files carry this much NUL-padded ASCII before the magic.
RECORD_HEADER_LEN = 64

# Grid sentinels (as signed bytes).
CELL_UNMAPPED = -1
CELL_OBSTACLE = -7
CELL_WALL = -12

# Trailer section tags.
TAG_FORBIDDEN_ZONE = 3
TAG_VIRTUAL_WALL = 2
TAG_BAN_MOP_ZONE = 8
TAG_ROOM_NAME = 6
TAG_ROOM_CUSTOM = 9
TAG_DOCK_POSE = 11
TAG_MAP_INFO = 12

# Count is a record count, not a byte length; value = int16 fields per record.
_PACKED_SECTIONS = {
    TAG_FORBIDDEN_ZONE: 8,  # x0,y0 .. x3,y3 — a quadrilateral
    TAG_BAN_MOP_ZONE: 8,
    TAG_VIRTUAL_WALL: 4,  # x0,y0,x1,y1 — a segment
}


class TuyaMapError(ValueError):
    """The blob is not a parsable Tuya map."""


@dataclass(frozen=True)
class TuyaMapRoom:
    """One room discovered in a map blob."""

    id: int
    name: str = ""
    # Per-room overrides; "not set" is -1 for fan/water, 0 for the sint32 fields.
    water_level: int = -1
    fan_speed: int = -1
    clean_times: int = 0
    clean_order: int = 0
    # Cells this room occupies in the grid; not stored in the blob.
    cell_count: int = 0

    def as_entity_room(self) -> dict[str, Any]:
        """Return the shape used by ``VacuumState.rooms`` and the room entities.

        ``fan_speed``/``water_level`` are 0-based indices into
        ``LEGACY_ROOM_FAN_LEVELS``/``LEGACY_ROOM_WATER_LEVELS`` (-1 unset) and
        ``clean_order`` the room's 1-based place in the sequence (-1 unpinned).
        """
        return {
            "id": self.id,
            "name": self.name or f"Room {self.id}",
            "fan_speed": self.fan_speed,
            "water_level": self.water_level,
            "clean_times": self.clean_times,
            "clean_order": self.clean_order,
        }


@dataclass
class TuyaMap:
    """A parsed Tuya map blob."""

    map_id: int
    width: int
    height: int
    origin_x: int
    origin_y: int
    version: int = 1
    map_type: int = 0
    rooms: list[TuyaMapRoom] = field(default_factory=list)
    custom_clean_enabled: bool = False
    virtual_walls: list[tuple[int, ...]] = field(default_factory=list)
    forbidden_zones: list[tuple[int, ...]] = field(default_factory=list)
    ban_mop_zones: list[tuple[int, ...]] = field(default_factory=list)
    dock_pose: tuple[int, int, int] | None = None
    created_at: int = 0
    updated_at: int = 0
    grid: bytes = field(default=b"", repr=False)

    @property
    def room_names(self) -> dict[int, str]:
        """``{room_id: name}`` for rooms the device has a name for."""
        return {room.id: room.name for room in self.rooms if room.name}

    def as_entity_rooms(self) -> list[dict[str, Any]]:
        """Room list in the shape ``VacuumState.rooms`` holds."""
        return [room.as_entity_room() for room in self.rooms]


def _iter_protobuf(data: bytes):
    """Yield ``(field_number, wire_type, value)`` for a flat protobuf message.

    ``value`` is an int for varints, bytes for length-delimited fields; groups and
    32/64-bit fields are skipped. A malformed varint ends the iteration.
    """
    pos = 0
    while pos < len(data):
        length = 0
        value = 0
        try:
            key, pos = decode_varint(data, pos)
            field_no, wire = key >> 3, key & 0x07
            if wire == 0:
                value, pos = decode_varint(data, pos)
            elif wire == 2:
                length, pos = decode_varint(data, pos)
        except ValueError:
            # Stop at a malformed record, as ``_split_sections`` does.
            _LOGGER.debug("Malformed varint in a map trailer section; rest skipped")
            return
        if wire == 0:
            yield field_no, wire, value
        elif wire == 2:
            yield field_no, wire, data[pos : pos + length]
            pos += length
        elif wire == 5:
            pos += 4
        elif wire == 1:
            pos += 8
        else:  # pragma: no cover - not produced by these messages
            raise TuyaMapError(f"unsupported protobuf wire type {wire}")


def _parse_room_names(payload: bytes, count: int) -> dict[int, str]:
    """Decode the room-name section.

    Records are ``room_id (uint8), record_len (uint8), name``; ``record_len``
    counts the two header bytes, so the name is ``record_len - 2`` UTF-8 bytes.
    """
    names: dict[int, str] = {}
    pos = 0
    for _ in range(count):
        if pos + 2 > len(payload):
            break
        room_id = payload[pos]
        record_len = payload[pos + 1]
        if record_len < 2:
            break
        name = payload[pos + 2 : pos + record_len]
        names[room_id] = name.decode("utf-8", errors="replace")
        pos += record_len
    return names


def _parse_room_custom(payload: bytes) -> tuple[bool, dict[int, dict[str, int]]]:
    """Decode ``MapCustomRoomConfig``: an enable flag plus per-room overrides.

    ``water`` and ``fan`` are stored one higher than they read; ``id``,
    ``cleanTimes`` and ``cleanOrder`` are sint32.
    """
    enabled = False
    rooms: dict[int, dict[str, int]] = {}
    for field_no, wire, value in _iter_protobuf(payload):
        if field_no == 1 and wire == 2:
            for sub_no, sub_wire, sub_value in _iter_protobuf(value):
                if sub_no == 1 and sub_wire == 0:
                    enabled = bool(sub_value)
        elif field_no == 2 and wire == 2:
            entry = {
                "id": 0,
                "water_level": -1,
                "fan_speed": -1,
                "clean_times": 0,
                "clean_order": 0,
            }
            for sub_no, sub_wire, sub_value in _iter_protobuf(value):
                if sub_wire != 0:
                    continue
                if sub_no == 1:
                    entry["id"] = decode_zigzag(sub_value)
                elif sub_no == 2:
                    entry["water_level"] = sub_value - 1
                elif sub_no == 3:
                    entry["fan_speed"] = sub_value - 1
                elif sub_no == 4:
                    entry["clean_times"] = decode_zigzag(sub_value)
                elif sub_no == 5:
                    entry["clean_order"] = decode_zigzag(sub_value)
            rooms[entry["id"]] = entry
    return enabled, rooms


def _parse_pose(payload: bytes) -> tuple[int, int, int] | None:
    """Decode a ``MapDockPose``/``MapPose`` message into ``(x, y, theta)``."""
    coords = {1: 0, 2: 0, 3: 0}
    seen = False
    for field_no, wire, value in _iter_protobuf(payload):
        if wire == 0 and field_no in coords:
            coords[field_no] = decode_zigzag(value)
            seen = True
    return (coords[1], coords[2], coords[3]) if seen else None


def _parse_map_info(payload: bytes) -> tuple[int, int]:
    """Decode ``MapInfo`` into ``(created_at, updated_at)`` epoch seconds."""
    created = updated = 0
    for field_no, wire, value in _iter_protobuf(payload):
        if wire != 0:
            continue
        if field_no == 1:
            created = decode_zigzag(value)
        elif field_no == 2:
            updated = decode_zigzag(value)
    return created, updated


def _parse_packed_geometry(payload: bytes, fields: int) -> list[tuple[int, ...]]:
    """Split a packed big-endian int16 section into fixed-width records."""
    size = fields * 2
    return [
        struct.unpack(f">{fields}h", payload[off : off + size])
        for off in range(0, len(payload) - size + 1, size)
    ]


def _split_sections(tail: bytes) -> dict[int, tuple[int, bytes]]:
    """Split the tagged trailer into ``{tag: (count, payload)}``.

    Six-byte preamble, then ``tag (uint8), count (uint8), payload`` repeated;
    ``count`` is a record count for the packed geometry sections and a byte length
    elsewhere. Stops at the first malformed record rather than raising, so an
    unknown section still yields the rooms before it.
    """
    sections: dict[int, tuple[int, bytes]] = {}
    pos = 6
    while pos + 2 <= len(tail):
        tag = tail[pos]
        count = tail[pos + 1]
        pos += 2
        if tag in _PACKED_SECTIONS:
            size = count * _PACKED_SECTIONS[tag] * 2
        elif tag == TAG_ROOM_NAME:
            size = 0
            cursor = pos
            for _ in range(count):
                if cursor + 2 > len(tail):
                    break
                record_len = tail[cursor + 1]
                if record_len < 2:
                    break
                size += record_len
                cursor += record_len
        else:
            size = count
        if pos + size > len(tail):
            _LOGGER.debug(
                "Map trailer section %d claims %d bytes but only %d remain; "
                "stopping", tag, size, len(tail) - pos,
            )
            break
        sections[tag] = (count, tail[pos : pos + size])
        pos += size
    return sections


def _room_cell_counts(grid: bytes) -> dict[int, int]:
    """Return ``{room_id: cell_count}`` — the trailer names rooms, but only the
    grid says which exist on this map.
    """
    counts: dict[int, int] = {}
    for cell in grid:
        signed = cell - 256 if cell > 127 else cell
        if signed < 0:
            continue
        room_id = signed // 4
        counts[room_id] = counts.get(room_id, 0) + 1
    return counts


def parse_map_blob(data: bytes) -> TuyaMap:
    """Parse a Tuya ``0pam`` map blob.

    Accepts the bare layout file and a clean-record file carrying the 64-byte ASCII
    record header. Raises :class:`TuyaMapError` on anything unparsable.
    """
    offset = data.find(MAGIC, 0, RECORD_HEADER_LEN + len(MAGIC))
    if offset < 0:
        raise TuyaMapError("not a Tuya map blob (no '0pam' magic)")
    body = data[offset:]
    if len(body) < HEADER_LEN:
        raise TuyaMapError("truncated Tuya map header")

    map_id, version, map_type, width, height, origin_x, origin_y = struct.unpack(
        ">HBBHHHH", body[4:16]
    )
    compressed_len, decompressed_len = struct.unpack(">II", body[16:HEADER_LEN])

    if not width or not height:
        raise TuyaMapError(f"map has empty dimensions {width}x{height}")
    # width/height are uint16, so a hostile header could claim 65535x65535 and make
    # the allocation below the attack rather than the LZ4 stream.
    if width > _MAX_MAP_DIMENSION or height > _MAX_MAP_DIMENSION:
        raise TuyaMapError(f"map dimensions {width}x{height} exceed the safety limit")
    cells = width * height
    if decompressed_len < cells:
        raise TuyaMapError(
            f"map claims {decompressed_len} bytes for a {width}x{height} grid"
        )
    # decompressed_len is an attacker-controlled uint32 handed to the decompressor
    # as its output budget; more than the grid plus a trailer is a bomb, not a map.
    if decompressed_len > cells + _MAX_TRAILER_BYTES:
        raise TuyaMapError(
            f"map claims {decompressed_len} bytes for {cells} cells; refusing"
        )

    payload = body[HEADER_LEN : HEADER_LEN + compressed_len]
    if len(payload) < compressed_len:
        raise TuyaMapError("truncated Tuya map payload")
    try:
        raw = lz4_block_decompress(payload, decompressed_len)
    except (ValueError, IndexError) as err:
        raise TuyaMapError(f"LZ4 decompression failed: {err}") from err
    if len(raw) < cells:
        raise TuyaMapError(
            f"map payload decompressed to {len(raw)} bytes, need {cells}"
        )

    grid = raw[:cells]
    sections = _split_sections(raw[cells:])

    names = {}
    if TAG_ROOM_NAME in sections:
        count, section = sections[TAG_ROOM_NAME]
        names = _parse_room_names(section, count)

    custom_enabled = False
    custom: dict[int, dict[str, int]] = {}
    if TAG_ROOM_CUSTOM in sections:
        custom_enabled, custom = _parse_room_custom(sections[TAG_ROOM_CUSTOM][1])

    cell_counts = _room_cell_counts(grid)

    rooms = [
        TuyaMapRoom(
            id=room_id,
            name=names.get(room_id, ""),
            water_level=custom.get(room_id, {}).get("water_level", -1),
            fan_speed=custom.get(room_id, {}).get("fan_speed", -1),
            clean_times=custom.get(room_id, {}).get("clean_times", 0),
            clean_order=custom.get(room_id, {}).get("clean_order", 0),
            cell_count=cell_count,
        )
        for room_id, cell_count in sorted(cell_counts.items())
    ]

    dock_pose = None
    if TAG_DOCK_POSE in sections:
        dock_pose = _parse_pose(sections[TAG_DOCK_POSE][1])

    created_at = updated_at = 0
    if TAG_MAP_INFO in sections:
        created_at, updated_at = _parse_map_info(sections[TAG_MAP_INFO][1])

    def geometry_of(tag: int) -> list[tuple[int, ...]]:
        if tag not in sections:
            return []
        return _parse_packed_geometry(sections[tag][1], _PACKED_SECTIONS[tag])

    parsed = TuyaMap(
        map_id=map_id,
        width=width,
        height=height,
        origin_x=origin_x,
        origin_y=origin_y,
        version=version,
        map_type=map_type,
        rooms=rooms,
        custom_clean_enabled=custom_enabled,
        virtual_walls=geometry_of(TAG_VIRTUAL_WALL),
        forbidden_zones=geometry_of(TAG_FORBIDDEN_ZONE),
        ban_mop_zones=geometry_of(TAG_BAN_MOP_ZONE),
        dock_pose=dock_pose,
        created_at=created_at,
        updated_at=updated_at,
        grid=grid,
    )
    _LOGGER.debug(
        "Parsed Tuya map %d (%dx%d): %d rooms, %d named",
        map_id, width, height, len(rooms), sum(1 for r in rooms if r.name),
    )
    return parsed
