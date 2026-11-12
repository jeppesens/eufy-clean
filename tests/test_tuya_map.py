"""Unit tests for api/tuya_map.py: the Tuya ``0pam`` map blob parser.

Fixtures are built here rather than committed as binaries: the real blobs are
a snapshot of someone's home. The builders below emit the exact byte layout
observed from a T2266 on firmware 3.6.7, and the expected values in
``test_parses_a_full_blob`` are the ones the eufy app's own decoder produced
for the same input.
"""

import struct
from typing import Any

import pytest

from custom_components.robovac_mqtt.api.tuya_map import (
    _MAX_TRAILER_BYTES,
    RECORD_HEADER_LEN,
    TuyaMapError,
    parse_map_blob,
)

# ── Fixture builders ────────────────────────────────────────────────


def lz4_literals(payload: bytes) -> bytes:
    """Encode ``payload`` as a single all-literal LZ4 block.

    The block format allows a final sequence with literals and no match, which
    makes an uncompressed passthrough a legal block.
    """
    out = bytearray()
    length = len(payload)
    if length < 15:
        out.append(length << 4)
    else:
        out.append(0xF0)
        remaining = length - 15
        while remaining >= 255:
            out.append(255)
            remaining -= 255
        out.append(remaining)
    out.extend(payload)
    return bytes(out)


def varint(value: int) -> bytes:
    out = bytearray()
    while value >= 0x80:
        out.append((value & 0x7F) | 0x80)
        value >>= 7
    out.append(value)
    return bytes(out)


def zigzag(value: int) -> int:
    return (value << 1) ^ (value >> 31)


def room_name_section(names: dict[int, str]) -> bytes:
    """``room_id, record_len, name`` where record_len counts its own header."""
    out = bytearray()
    for room_id, name in names.items():
        encoded = name.encode()
        out += bytes([room_id, len(encoded) + 2]) + encoded
    return bytes([6, len(names)]) + bytes(out)


def room_custom_section(enabled: bool, rooms: list[dict]) -> bytes:
    """``MapCustomRoomConfig``: enable flag (field 1) + repeated room (field 2)."""
    body = bytearray()
    body += b"\x0a" + varint(2) + b"\x08" + varint(int(enabled))
    for room in rooms:
        entry = bytearray()
        entry += b"\x08" + varint(zigzag(room["id"]))
        entry += b"\x10" + varint(room["water"] + 1)
        entry += b"\x18" + varint(room["fan"] + 1)
        entry += b"\x20" + varint(zigzag(room["times"]))
        entry += b"\x28" + varint(zigzag(room["order"]))
        body += b"\x12" + varint(len(entry)) + bytes(entry)
    return bytes([9, len(body)]) + bytes(body)


def packed_section(tag: int, records: list[tuple[int, ...]]) -> bytes:
    body = b"".join(struct.pack(f">{len(r)}h", *r) for r in records)
    return bytes([tag, len(records)]) + body


def map_info_section(created: int, updated: int) -> bytes:
    body = b"\x08" + varint(zigzag(created)) + b"\x10" + varint(zigzag(updated))
    return bytes([12, len(body)]) + bytes(body)


def dock_pose_section(x: int, y: int, theta: int) -> bytes:
    """``MapDockPose`` (tag 11): sint32 x/y/theta on fields 1/2/3."""
    body = (
        b"\x08" + varint(zigzag(x))
        + b"\x10" + varint(zigzag(y))
        + b"\x18" + varint(zigzag(theta))
    )
    return bytes([11, len(body)]) + bytes(body)


def build_blob(
    *,
    grid: bytes,
    width: int,
    height: int,
    map_id: int = 3,
    origin: tuple[int, int] = (520, 1350),
    sections: bytes = b"",
    record_header: bool = False,
) -> bytes:
    """Assemble a complete blob from a grid and pre-encoded trailer sections."""
    # Six preamble bytes the device emits before the first tagged section.
    trailer = bytes([5, 0, 1, 0xB2, 0x80, 4]) + sections if sections else b""
    raw = grid + trailer
    block = lz4_literals(raw)
    header = (
        b"0pam"
        + struct.pack(
            ">HBBHHHH", map_id, 1, 6, width, height, origin[0], origin[1]
        )
        + struct.pack(">II", len(block), len(raw))
    )
    blob = header + block
    if record_header:
        prefix = b"1787326947_1787390972_10_12_5061_0_"
        blob = prefix.ljust(RECORD_HEADER_LEN, b"\0") + blob
    return blob


def simple_grid(width: int, height: int, rooms: dict[int, int]) -> bytes:
    """A grid with ``rooms`` mapping room id -> cell count, rest unmapped."""
    cells = bytearray([0xFF]) * (width * height)  # -1 everywhere
    index = 0
    for room_id, count in rooms.items():
        for _ in range(count):
            cells[index] = room_id * 4
            index += 1
    return bytes(cells)


# ── Header handling ─────────────────────────────────────────────────


def test_rejects_non_map_input():
    with pytest.raises(TuyaMapError, match="no '0pam' magic"):
        parse_map_blob(b"definitely not a map")


def test_rejects_truncated_header():
    with pytest.raises(TuyaMapError, match="truncated"):
        parse_map_blob(b"0pam" + b"\x00" * 4)


def test_rejects_empty_dimensions():
    blob = build_blob(grid=b"", width=0, height=0)
    with pytest.raises(TuyaMapError, match="empty dimensions"):
        parse_map_blob(blob)


def test_rejects_grid_shorter_than_dimensions():
    # Header claims 10x10 but only 20 bytes of payload are declared.
    block = lz4_literals(b"\x00" * 20)
    blob = (
        b"0pam"
        + struct.pack(">HBBHHHH", 3, 1, 6, 10, 10, 0, 0)
        + struct.pack(">II", len(block), 20)
        + block
    )
    with pytest.raises(TuyaMapError, match="claims 20 bytes"):
        parse_map_blob(blob)


def test_reads_geometry_from_header():
    blob = build_blob(
        grid=simple_grid(10, 8, {}), width=10, height=8, map_id=7, origin=(64, 128)
    )
    parsed = parse_map_blob(blob)
    assert (parsed.map_id, parsed.width, parsed.height) == (7, 10, 8)
    assert (parsed.origin_x, parsed.origin_y) == (64, 128)


def test_accepts_the_clean_record_header():
    """``<ts>-map_<id>`` files pad an ASCII record header before the magic."""
    blob = build_blob(
        grid=simple_grid(10, 8, {1: 4}), width=10, height=8, record_header=True
    )
    assert parse_map_blob(blob).rooms[0].id == 1


# ── Rooms ───────────────────────────────────────────────────────────


def test_rooms_come_from_the_grid_without_a_name_section():
    """The layout file carries geometry only; ids still have to be usable."""
    blob = build_blob(
        grid=simple_grid(10, 10, {0: 5, 1: 9, 3: 2}), width=10, height=10
    )
    parsed = parse_map_blob(blob)
    assert [(r.id, r.cell_count) for r in parsed.rooms] == [(0, 5), (1, 9), (3, 2)]
    # Unnamed rooms still get a usable label for the select entity.
    assert parsed.as_entity_rooms()[0] == {
        "id": 0,
        "name": "Room 0",
        "fan_speed": -1,
        "water_level": -1,
        "clean_times": 0,
        "clean_order": 0,
    }


def test_room_zero_is_a_real_room_not_free_floor():
    """Cell value 0 is room 0; treating it as floor loses a whole room."""
    blob = build_blob(grid=simple_grid(10, 10, {0: 12}), width=10, height=10)
    parsed = parse_map_blob(blob)
    assert [r.id for r in parsed.rooms] == [0]
    assert parsed.rooms[0].cell_count == 12


def test_room_id_is_the_cell_value_divided_by_four():
    """Cell 20 is room 5, not room 20 — ids are stored shifted left by two."""
    blob = build_blob(grid=simple_grid(10, 10, {5: 3}), width=10, height=10)
    parsed = parse_map_blob(blob)
    assert [(r.id, r.cell_count) for r in parsed.rooms] == [(5, 3)]


def test_sentinel_cells_are_not_rooms():
    grid = bytearray([0xFF] * 100)  # -1 unmapped
    grid[0] = 0xF9  # -7 obstacle
    grid[1] = 0xF4  # -12 wall
    grid[2] = 8  # room 2
    parsed = parse_map_blob(build_blob(grid=bytes(grid), width=10, height=10))
    assert [r.id for r in parsed.rooms] == [2]


def test_cell_count_is_the_room_inventory():
    """The trailer names rooms; only the grid says which exist on this map."""
    grid = bytearray([0xFF] * 100)
    for index in (11, 12, 21, 22):
        grid[index] = 4
    parsed = parse_map_blob(build_blob(grid=bytes(grid), width=10, height=10))
    assert [(r.id, r.cell_count) for r in parsed.rooms] == [(1, 4)]


# ── Names and per-room settings ─────────────────────────────────────

# The values the eufy app's own decoder reported for this device.
REAL_ROOMS: list[dict[str, Any]] = [
    {"id": 0, "name": "Hallway", "fan": 1, "water": 0, "times": 2, "order": -1},
    {"id": 1, "name": "Living Room", "fan": 2, "water": 0, "times": 1, "order": -1},
    {"id": 2, "name": "Bedroom", "fan": 0, "water": 0, "times": 2, "order": 1},
    {"id": 3, "name": "SmallBedroom", "fan": 3, "water": 0, "times": 1, "order": -1},
    {"id": 4, "name": "Bathroom", "fan": 0, "water": 0, "times": 1, "order": -1},
    {"id": 5, "name": "Kitchen", "fan": 0, "water": 0, "times": 1, "order": -1},
]


def full_blob() -> bytes:
    sections = (
        packed_section(3, [(861, 593, 1161, 593, 1161, 893, 861, 893)])
        + packed_section(8, [])
        + packed_section(2, [(948, 131, 933, -307), (64, 109, 74, 890)])
        + room_name_section({r["id"]: r["name"] for r in REAL_ROOMS})
        + room_custom_section(True, REAL_ROOMS)
        + map_info_section(1771407009, 1787825136)
    )
    return build_blob(
        grid=simple_grid(40, 40, {r["id"]: 10 + r["id"] for r in REAL_ROOMS}),
        width=40,
        height=40,
        sections=sections,
    )


def test_parses_a_full_blob():
    parsed = parse_map_blob(full_blob())

    assert parsed.custom_clean_enabled is True
    assert [(r.id, r.name) for r in parsed.rooms] == [
        (r["id"], r["name"]) for r in REAL_ROOMS
    ]
    assert [(r.fan_speed, r.water_level) for r in parsed.rooms] == [
        (r["fan"], r["water"]) for r in REAL_ROOMS
    ]
    assert [(r.clean_times, r.clean_order) for r in parsed.rooms] == [
        (r["times"], r["order"]) for r in REAL_ROOMS
    ]
    assert parsed.created_at == 1771407009
    assert parsed.updated_at == 1787825136


def test_room_names_property_skips_unnamed_rooms():
    parsed = parse_map_blob(full_blob())
    assert parsed.room_names[3] == "SmallBedroom"

    bare = parse_map_blob(build_blob(grid=simple_grid(10, 10, {1: 4}), width=10, height=10))
    assert bare.room_names == {}


def test_parses_zone_geometry():
    parsed = parse_map_blob(full_blob())
    assert parsed.forbidden_zones == [(861, 593, 1161, 593, 1161, 893, 861, 893)]
    assert parsed.virtual_walls == [
        (948, 131, 933, -307),
        (64, 109, 74, 890),
    ]
    assert not parsed.ban_mop_zones


def test_names_survive_a_room_with_no_custom_entry():
    """A room named but absent from customRooms keeps its name and defaults."""
    sections = room_name_section({0: "Hallway", 1: "Kitchen"}) + room_custom_section(
        True, [{"id": 0, "name": "Hallway", "fan": 1, "water": 0, "times": 2, "order": -1}]
    )
    parsed = parse_map_blob(
        build_blob(grid=simple_grid(10, 10, {0: 4, 1: 4}), width=10, height=10,
                   sections=sections)
    )
    kitchen = parsed.rooms[1]
    assert (kitchen.name, kitchen.fan_speed, kitchen.clean_times) == ("Kitchen", -1, 0)


# ── Robustness ──────────────────────────────────────────────────────


def test_unknown_trailing_section_does_not_lose_earlier_rooms():
    """A firmware update adding a section must not cost us the room list."""
    sections = (
        room_name_section({0: "Hallway"})
        + bytes([99, 3, 1, 2, 3])  # unknown tag, byte-length payload
        + map_info_section(1, 2)
    )
    parsed = parse_map_blob(
        build_blob(grid=simple_grid(10, 10, {0: 4}), width=10, height=10,
                   sections=sections)
    )
    assert parsed.rooms[0].name == "Hallway"
    assert parsed.updated_at == 2


def test_section_claiming_more_bytes_than_remain_is_dropped():
    sections = room_name_section({0: "Hallway"}) + bytes([9, 200])
    parsed = parse_map_blob(
        build_blob(grid=simple_grid(10, 10, {0: 4}), width=10, height=10,
                   sections=sections)
    )
    assert parsed.rooms[0].name == "Hallway"
    assert parsed.custom_clean_enabled is False


def test_decompressed_size_is_bounded_by_grid_plus_trailer():
    """A header claiming far more output than the grid and a trailer need is refused."""
    blob = bytearray(build_blob(grid=simple_grid(10, 10, {0: 4}), width=10, height=10))
    struct.pack_into(">I", blob, 20, 100 + _MAX_TRAILER_BYTES + 1)  # decompressed_len
    with pytest.raises(TuyaMapError, match="refusing"):
        parse_map_blob(bytes(blob))


def test_malformed_varint_in_a_section_keeps_the_earlier_rooms():
    """An overlong varint ends that section's walk instead of failing the map."""
    bad = bytes([7, 12]) + b"\xff" * 12  # section tag 7, 12 bytes of continuation
    sections = room_name_section({0: "Hallway"}) + bad
    parsed = parse_map_blob(
        build_blob(grid=simple_grid(10, 10, {0: 4}), width=10, height=10,
                   sections=sections)
    )
    assert parsed.rooms[0].name == "Hallway"
