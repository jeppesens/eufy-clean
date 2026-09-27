"""Unit tests for the utils module (encode/decode/varint)."""

from base64 import b64encode

import pytest

from custom_components.robovac_mqtt.const import WEEKDAY_ABBREVIATIONS
from custom_components.robovac_mqtt.proto.cloud.error_code_pb2 import ErrorCode
from custom_components.robovac_mqtt.utils import (
    decode,
    deduplicate_names,
    encode,
    encode_message,
    encode_varint,
    parse_weekdays,
)


def test_decode_empty_data_raises():
    """decode() with has_length=True and empty base64 raises ValueError."""
    empty_b64 = b64encode(b"").decode()
    with pytest.raises(ValueError, match="Cannot decode empty data"):
        decode(ErrorCode, empty_b64, has_length=True)


def test_decode_truncated_varint_raises():
    """decode() with only continuation bytes raises ValueError."""
    truncated_b64 = b64encode(b"\x80\x80").decode()
    with pytest.raises(ValueError, match="Truncated varint"):
        decode(ErrorCode, truncated_b64, has_length=True)


def test_decode_without_length_prefix():
    """decode() with has_length=False passes raw bytes directly to protobuf."""
    msg = ErrorCode()
    msg.error.append(42)
    raw = msg.SerializeToString()
    b64_data = b64encode(raw).decode()

    result = decode(ErrorCode, b64_data, has_length=False)
    assert 42 in result.error


def test_decode_valid_with_length_prefix():
    """Round-trip: encode_message then decode returns correct fields."""
    msg = ErrorCode()
    msg.error.append(7)
    encoded = encode_message(msg, has_length=True)

    result = decode(ErrorCode, encoded, has_length=True)
    assert 7 in result.error


def test_encode_varint_negative_raises():
    """encode_varint with a negative number raises ValueError."""
    with pytest.raises(ValueError, match="Cannot encode negative varint"):
        encode_varint(-1)


def test_encode_varint_zero():
    """encode_varint(0) returns a single zero byte."""
    assert encode_varint(0) == b"\x00"


def test_encode_varint_large():
    """encode_varint(300) returns the correct two-byte varint encoding."""
    assert encode_varint(300) == b"\xac\x02"


def test_encode_decode_roundtrip():
    """Full roundtrip: encode() a dict, decode() it back, verify fields."""
    encoded = encode(ErrorCode, {"error": [99, 100]}, has_length=True)

    result = decode(ErrorCode, encoded, has_length=True)
    assert list(result.error) == [99, 100]


def test_deduplicate_names():
    assert deduplicate_names(["A", "B", "A", "C", "A"]) == [
        "A",
        "B",
        "A (2)",
        "C",
        "A (3)",
    ]
    assert deduplicate_names(["X", "Y"]) == ["X", "Y"]
    assert not deduplicate_names([])


@pytest.mark.parametrize(
    ("days", "expected"),
    [
        (None, set()),
        ([], set()),
        ("Once", set()),
        ("Every day", set(range(7))),
        (["daily"], set(range(7))),
        ("Weekdays", {0, 1, 2, 3, 4}),
        ("weekend", {5, 6}),
        ("Mon, Wed|fri", {0, 2, 4}),
        (["Tuesday", "THURSDAY", "sun"], {1, 3, 6}),
        (list(WEEKDAY_ABBREVIATIONS), set(range(7))),
    ],
)
def test_parse_weekdays_gives_monday_first_indices(days, expected):
    """Names, groups and lists all resolve to WEEKDAY_ABBREVIATIONS indices."""
    assert parse_weekdays(days) == expected


@pytest.mark.parametrize("days", ["Mondy", "Mon, xx", "day", "Tues"])
def test_parse_weekdays_rejects_unknown_words(days):
    """A typo is an error, not a silently dropped day."""
    with pytest.raises(ValueError, match="day"):
        parse_weekdays(days)
