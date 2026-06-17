"""Unit tests for api/map_stream.py: protocol parsing, LZ4 decompression, map render."""
import json

import pytest

from custom_components.robovac_mqtt.api.map_stream import (
    MapData,
    _lz4_block_decompress,
    parse_biz_protocol41,
    render_map_png,
    try_extract_map_data,
)
from custom_components.robovac_mqtt.proto.cloud import stream_pb2
from custom_components.robovac_mqtt.utils import encode_varint


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
# _lz4_block_decompress
# ---------------------------------------------------------------------------


def test_lz4_literal_only():
    """Token with only literals (no back-reference) decompresses correctly."""
    # 0x50: lit_len=5, match_nibble=0; pos >= n after literals so loop exits.
    assert _lz4_block_decompress(b"\x50ABCDE", 5) == b"ABCDE"


def test_lz4_with_backreference():
    """Back-reference copies bytes from earlier in the output buffer."""
    # 0x32: lit_len=3 ("ABC"), match_nibble=2 -> match_len=6, offset=3
    # Copies output[0..6] => "ABCABC", total output = "ABCABCABC"
    assert _lz4_block_decompress(b"\x32ABC\x03\x00", 9) == b"ABCABCABC"


def test_lz4_overlapping_backreference():
    """Overlapping back-reference (offset < match_len) duplicates bytes correctly."""
    # 0x11: lit_len=1 ("Z"), match_nibble=1 -> match_len=5, offset=1
    # Copies from output[-1] 5 times: ZZZZZ, total = "ZZZZZZ"
    assert _lz4_block_decompress(b"\x11Z\x01\x00", 6) == b"ZZZZZZ"


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
