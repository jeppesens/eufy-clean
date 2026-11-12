"""Regression tests: size validation before decompression, varint cap, mask registration."""

import logging

import pytest

from custom_components.robovac_mqtt.api import map_geometry, map_stream
from custom_components.robovac_mqtt.api.map_stream import (
    MapData,
    render_map_png,
    try_extract_map_data,
)
from custom_components.robovac_mqtt.api.tuya_map import _MAX_MAP_DIMENSION
from custom_components.robovac_mqtt.proto.cloud import stream_pb2
from custom_components.robovac_mqtt.utils import decode_varint, encode_varint

# An LZ4 block claiming a 16 MB output from a few bytes: one literal, then a
# single overlapping match whose length is a long 0xFF chain.
_BOMB_BLOCK = bytes([0x1F, 0x00, 0x01, 0x00]) + b"\xff" * 64 + b"\x00"


def _hex(message) -> str:
    body = message.SerializeToString()
    return (encode_varint(len(body)) + body).hex()


def _map(width: int, height: int, pixels: bytes, pixel_size: int) -> stream_pb2.Map:
    return stream_pb2.Map(
        pixels=pixels,
        pixel_size=pixel_size,
        info=stream_pb2.MapInfo(width=width, height=height, resolution=5),
    )


def test_oversized_dimensions_are_rejected_before_decompressing(monkeypatch):
    calls = []
    monkeypatch.setattr(map_stream, "lz4_block_decompress", lambda *a: calls.append(a))
    side = _MAX_MAP_DIMENSION + 1
    assert try_extract_map_data(_hex(_map(side, 1, _BOMB_BLOCK, 16))) is None
    assert not calls


def test_pixel_size_larger_than_the_grid_is_rejected(monkeypatch):
    """The declared 2 bpp size may not exceed ceil(w * h / 4)."""
    calls = []
    monkeypatch.setattr(map_stream, "lz4_block_decompress", lambda *a: calls.append(a))
    assert try_extract_map_data(_hex(_map(10, 10, _BOMB_BLOCK, 16_000_000))) is None
    assert not calls


def test_room_outline_with_mismatched_size_drops_only_the_mask():
    """A mask whose size is not width*height is dropped; the map still decodes."""
    backup = stream_pb2.MapBackup(map=_map(4, 4, b"\xaa" * 4, 4))
    backup.rooms.width = 4
    backup.rooms.height = 4
    backup.rooms.pixels = _BOMB_BLOCK
    backup.rooms.pixel_size = 16_000_000

    result = try_extract_map_data(_hex(backup))

    assert result is not None
    assert result.room_pixels is None
    assert result.raw_pixels == b"\xaa" * 4


def test_valid_room_outline_still_decodes():
    backup = stream_pb2.MapBackup(map=_map(2, 2, b"\xaa", 1))
    backup.rooms.width = 2
    backup.rooms.height = 2
    backup.rooms.pixels = bytes([4, 4, 8, 8])
    backup.rooms.pixel_size = 4

    result = try_extract_map_data(_hex(backup))

    assert result is not None
    assert result.room_pixels == bytes([4, 4, 8, 8])


def test_render_rejects_one_oversized_side():
    """Each side is bounded, not just the area."""
    md = MapData(raw_pixels=b"", width=_MAX_MAP_DIMENSION + 1, height=1)
    with pytest.raises(ValueError, match="safety limit"):
        render_map_png(md)


def test_short_room_mask_renders_instead_of_raising():
    """A mask shorter than its declared outline reads as 'no room' past its end."""
    md = MapData(
        raw_pixels=b"\xaa" * 4, width=4, height=4,
        room_pixels=bytes([4, 4]), room_outline_width=4, room_outline_height=4,
        room_names={1: "Room"},
    )
    assert render_map_png(md).startswith(b"\x89PNG")
    grid = map_geometry._build_rooms_grid(md)
    assert grid[:2] == bytes([2, 2]) and set(grid[2:]) == {0}


def test_decode_varint_caps_length():
    with pytest.raises(ValueError, match="longer than 10 bytes"):
        decode_varint(b"\xff" * 100_000 + b"\x01", 0)


def test_decode_varint_accepts_ten_bytes():
    assert decode_varint(encode_varint(2**64 - 1), 0) == (2**64 - 1, 10)


def test_biz_parse_failure_log_omits_payload(caplog):
    with caplog.at_level(logging.DEBUG, logger=map_stream.__name__):
        assert map_stream.parse_biz_protocol41(b'{"not json: ExampleSecret') is None
    assert "ExampleSecret" not in caplog.text


def test_room_names_are_not_logged(caplog):
    backup = stream_pb2.MapBackup(map=_map(2, 2, b"\xaa", 1))
    room = backup.room_params.rooms.add()
    room.id = 1
    room.name = "ExampleKitchen"
    with caplog.at_level(logging.DEBUG, logger=map_stream.__name__):
        result = try_extract_map_data(_hex(backup))
    assert result is not None and result.room_names == {1: "ExampleKitchen"}
    assert "ExampleKitchen" not in caplog.text
