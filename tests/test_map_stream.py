"""Unit tests for api/map_stream.py: protocol parsing, LZ4 decompression, map render."""
import json

import pytest

from custom_components.robovac_mqtt.api.map_stream import (
    MapData,
    _dash,
    parse_biz_protocol41,
    render_map_png,
    room_polygons_to_cells,
    split_trail_runs,
    try_extract_map_data,
    try_extract_map_description,
)
from custom_components.robovac_mqtt.proto.cloud import stream_pb2
from custom_components.robovac_mqtt.utils import encode_varint, lz4_block_decompress

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_map_hex(width: int, height: int) -> str:
    """Return a hex string encoding a minimal plain Map proto with a varint prefix."""
    n_pixels = width * height
    n_bytes = (n_pixels + 3) // 4  # 2bpp
    raw_pixels = b"\xaa" * n_bytes  # all FREE (pixel value 2 in every 2-bit slot)
    map_proto = stream_pb2.Map(
        pixels=raw_pixels,
        pixel_size=len(raw_pixels),
        info=stream_pb2.MapInfo(width=width, height=height, resolution=5),
    )
    body = map_proto.SerializeToString()
    prefixed = encode_varint(len(body)) + body
    return prefixed.hex()


def _biz_payload(channel_id: int, hex_data: str) -> bytes:
    """Build a minimal biz/ MQTT JSON payload bytes."""
    return json.dumps(
        {"payload": {"data": {"channel_id": channel_id, "data": hex_data}}}
    ).encode()


# ---------------------------------------------------------------------------
# parse_biz_protocol41
# ---------------------------------------------------------------------------


def test_parse_biz_valid():
    """Valid biz payload returns (channel_id, hex_data) tuple."""
    result = parse_biz_protocol41(_biz_payload(7, "deadbeef"))
    assert result == (7, "deadbeef")


def test_parse_biz_nested_payload_string():
    """Payload value encoded as a JSON string (double-encoded) is also handled."""
    inner = json.dumps({"data": {"channel_id": 3, "data": "cafe1234"}})
    outer = json.dumps({"payload": inner}).encode()
    assert parse_biz_protocol41(outer) == (3, "cafe1234")


def test_parse_biz_missing_channel_id():
    """Missing channel_id returns None."""
    payload = json.dumps({"payload": {"data": {"data": "aabbcc"}}}).encode()
    assert parse_biz_protocol41(payload) is None


def test_parse_biz_empty_hex_data():
    """Empty hex data field returns None."""
    payload = json.dumps(
        {"payload": {"data": {"channel_id": 1, "data": ""}}}
    ).encode()
    assert parse_biz_protocol41(payload) is None


def test_parse_biz_invalid_json():
    """Non-JSON bytes return None without raising."""
    assert parse_biz_protocol41(b"not json at all") is None


# ---------------------------------------------------------------------------
# lz4_block_decompress
# ---------------------------------------------------------------------------


def test_lz4_literal_only():
    """Token with only literals (no back-reference) decompresses correctly."""
    # 0x50: lit_len=5, match_nibble=0; pos >= n after literals so loop exits.
    assert lz4_block_decompress(b"\x50ABCDE", 5) == b"ABCDE"


def test_lz4_with_backreference():
    """Back-reference copies bytes from earlier in the output buffer."""
    # 0x32: lit_len=3 ("ABC"), match_nibble=2 -> match_len=6, offset=3
    # Copies output[0..6] => "ABCABC", total output = "ABCABCABC"
    assert lz4_block_decompress(b"\x32ABC\x03\x00", 9) == b"ABCABCABC"


def test_lz4_overlapping_backreference():
    """Overlapping back-reference (offset < match_len) duplicates bytes correctly."""
    # 0x11: lit_len=1 ("Z"), match_nibble=1 -> match_len=5, offset=1
    # Copies from output[-1] 5 times: ZZZZZ, total = "ZZZZZZ"
    assert lz4_block_decompress(b"\x11Z\x01\x00", 6) == b"ZZZZZZ"


# ---------------------------------------------------------------------------
# try_extract_map_data
# ---------------------------------------------------------------------------


def test_try_extract_map_data_valid():
    """A well-formed Map hex string returns MapData with correct dimensions."""
    result = try_extract_map_data(_make_map_hex(8, 6))
    assert result is not None
    assert result.width == 8
    assert result.height == 6
    assert result.resolution == 5


def test_try_extract_map_data_invalid_hex():
    """Non-hex data returns None without raising."""
    assert try_extract_map_data("zzzz") is None


def test_try_extract_map_data_empty_proto():
    """An empty proto (no pixels, no info) returns None."""
    body = stream_pb2.Map().SerializeToString()
    prefixed = encode_varint(len(body)) + body
    assert try_extract_map_data(prefixed.hex()) is None


def test_try_extract_map_data_raw_pixels_correct():
    """Returned raw_pixels match what was put into the Map proto."""
    hex_data = _make_map_hex(4, 4)
    result = try_extract_map_data(hex_data)
    assert result is not None
    assert result.raw_pixels == b"\xaa" * 4  # 16 pixels at 2bpp = 4 bytes


# ---------------------------------------------------------------------------
# render_map_png
# ---------------------------------------------------------------------------


def test_render_map_png_smoke():
    """render_map_png returns valid PNG bytes for a minimal map."""
    n_pixels = 16 * 12
    map_data = MapData(
        raw_pixels=b"\xaa" * ((n_pixels + 3) // 4),
        width=16,
        height=12,
        resolution=5,
    )
    result = render_map_png(map_data)
    assert isinstance(result, bytes)
    assert result[:4] == b"\x89PNG"


def test_render_map_png_with_robot_and_dock():
    """render_map_png does not crash with robot and dock positions supplied."""
    n_pixels = 16 * 16
    map_data = MapData(
        raw_pixels=b"\xaa" * ((n_pixels + 3) // 4),
        width=16,
        height=16,
        resolution=5,
    )
    result = render_map_png(map_data, robot_pixel=(8, 8), dock_pixel=(2, 2))
    assert result[:4] == b"\x89PNG"


def test_render_map_png_rejects_oversized():
    """render_map_png raises ValueError for dimensions exceeding 4000x4000.

    Regression for H2: without this guard, a crafted MQTT map message with
    width=65535 and height=65535 triggers a ~17 GB PIL allocation.
    """
    map_data = MapData(raw_pixels=b"", width=5000, height=5000)
    with pytest.raises(ValueError, match="exceed safety limit"):
        render_map_png(map_data)


# ---------------------------------------------------------------------------
# try_extract_map_description — map id + name discovery
# ---------------------------------------------------------------------------


def _make_map_desc_hex(map_id: int, name: str) -> str:
    """Return hex of a varint-prefixed MapDescription proto."""
    body = stream_pb2.MapDescription(map_id=map_id, name=name).SerializeToString()
    return (encode_varint(len(body)) + body).hex()


def test_map_description_extracts_id_and_name():
    """A well-formed MapDescription yields (map_id, name)."""
    assert try_extract_map_description(_make_map_desc_hex(6, "My home")) == (
        6,
        "My home",
    )


def test_map_description_rejects_zero_id():
    """map_id 0 is not a real saved map -> None (drops the RoomParams misparse)."""
    assert try_extract_map_description(_make_map_desc_hex(0, "My home")) is None


def test_map_description_rejects_empty_name():
    """An empty name is not usable as a label -> None."""
    assert try_extract_map_description(_make_map_desc_hex(7, "")) is None


def test_map_description_rejects_non_printable_name():
    """A non-printable name signals a misparsed frame -> None."""
    assert try_extract_map_description(_make_map_desc_hex(7, "bad\x00name")) is None


def test_map_description_rejects_garbage():
    """Non-hex / undecodable input -> None, never raises."""
    assert try_extract_map_description("zznothex") is None


def test_map_description_strips_whitespace():
    """A name seeded with a trailing space (Eufy same-name workaround) is trimmed."""
    assert try_extract_map_description(_make_map_desc_hex(6, "The main floor ")) == (
        6,
        "The main floor",
    )


# ---------------------------------------------------------------------------
# room_polygons_to_cells — the live 0x65 ROOM outline transform
# ---------------------------------------------------------------------------


def test_room_polygons_to_cells_applies_origin_and_row_flip():
    """A vertex is ``(v + origin) / 10`` in cells, with the row flipped.

    The flip matters: MapData's grid planes are stored bottom-up and
    render_map_png flips everything back, so geometry must be pre-flipped the
    same way the walls and zones are.
    """
    cells = room_polygons_to_cells(
        {0: [(0, 0), (100, 0), (100, 100)]},
        origin_x=520,
        origin_y=1350,
        height=215,
    )
    # col = (0 + 520)/10 = 52 ; row = 214 - (0 + 1350)/10 = 79
    assert cells[0][0] == (52.0, 79.0)
    assert cells[0][1] == (62.0, 79.0)
    assert cells[0][2] == (62.0, 69.0)


def test_room_polygons_to_cells_keeps_room_zero_and_drops_degenerate():
    """Room id 0 survives; a polygon with under three vertices cannot enclose
    anything and is dropped rather than shipped as a broken ring."""
    cells = room_polygons_to_cells(
        {0: [(0, 0), (10, 0), (10, 10)], 4: [(0, 0), (10, 0)]},
        origin_x=0,
        origin_y=0,
        height=100,
    )
    assert 0 in cells
    assert 4 not in cells


def test_room_polygons_to_cells_preserves_subcell_precision():
    """Vertices are vector data: 0.5 cm steps must not be rounded to whole cells."""
    cells = room_polygons_to_cells(
        {1: [(1, 2), (3, 4), (5, 6)]}, origin_x=0, origin_y=0, height=10
    )
    assert cells[1][0] == (0.1, 9.0 - 0.2)


def test_render_map_png_draws_room_outlines():
    """Polygons change the rendered image, and rendering without them still works."""
    map_data = MapData(
        raw_pixels=bytes([0b10101010] * 100),
        width=20,
        height=20,
        resolution=5,
    )
    before = render_map_png(map_data)
    map_data.room_polygons = {
        0: [(2.0, 2.0), (15.0, 2.0), (15.0, 15.0), (2.0, 15.0)]
    }
    after = render_map_png(map_data)
    assert before[:8] == b"\x89PNG\r\n\x1a\n"
    assert after[:8] == b"\x89PNG\r\n\x1a\n"
    assert after != before


# ---------------------------------------------------------------------------
# Typed trail runs — cleaning passes vs transit legs
# ---------------------------------------------------------------------------


def test_split_trail_runs_breaks_on_type_change():
    """A transit leg and a cleaning pass are not one continuous stroke.

    Joining them would draw a solid line along a route the robot only drove,
    implying coverage that does not exist.
    """
    points = [(0, 0), (1, 0), (2, 0), (3, 0)]
    runs = split_trail_runs(points, types=[0, 0, 1, 1])
    assert [t for _, t in runs] == [0, 1]
    assert [pts for pts, _ in runs] == [[(0, 0), (1, 0)], [(2, 0), (3, 0)]]


def test_split_trail_runs_still_breaks_on_jumps():
    """The relocalisation break survives alongside the type break."""
    points = [(0, 0), (1, 0), (900, 900)]
    runs = split_trail_runs(points, types=[0, 0, 0])
    assert len(runs) == 2
    assert all(t == 0 for _, t in runs)


def test_split_trail_runs_without_types_is_one_type():
    """Producers with no type (the novel pose path) yield plain type-0 runs."""
    runs = split_trail_runs([(0, 0), (1, 1), (2, 2)])
    assert len(runs) == 1
    assert runs[0][1] == 0
    assert runs[0][0] == [(0, 0), (1, 1), (2, 2)]


def test_split_trail_runs_pads_short_type_list():
    """A types array shorter than the points must not raise or misalign."""
    runs = split_trail_runs([(0, 0), (1, 0), (2, 0)], types=[1])
    assert [t for _, t in runs] == [1, 0]


def test_dash_splits_by_arc_length():
    """Dashes are cut by distance travelled, so the rhythm survives corners."""
    segments = _dash([(0.0, 0.0), (20.0, 0.0)], 5.0, 5.0)
    assert len(segments) == 2
    assert segments[0][0] == (0.0, 0.0)
    assert segments[0][-1] == (5.0, 0.0)
    assert segments[1][0] == (10.0, 0.0)


def test_dash_degenerate_input_is_safe():
    """A single point or a zero dash length must not hang or raise."""
    assert not _dash([(0.0, 0.0)], 5.0, 5.0)
    assert _dash([(0.0, 0.0), (5.0, 0.0)], 0.0, 5.0) == [[(0.0, 0.0), (5.0, 0.0)]]


def test_render_map_png_dashes_transit_differently():
    """A trail rendered as transit differs from the same trail rendered as cleaning."""
    map_data = MapData(
        raw_pixels=bytes([0b10101010] * 100), width=20, height=20, resolution=5
    )
    trail = [(x, 10) for x in range(2, 18)]
    solid = render_map_png(map_data, robot_trail=trail, robot_trail_types=[0] * len(trail))
    dashed = render_map_png(map_data, robot_trail=trail, robot_trail_types=[1] * len(trail))
    assert solid != dashed
