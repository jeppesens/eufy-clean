from __future__ import annotations

import re
from base64 import b64decode, b64encode
from typing import Any, TypeVar

from google.protobuf.message import Message

from .const import (
    MAX_CLEAN_TIMES,
    MIN_CLEAN_TIMES,
    WEEKDAY_ABBREVIATIONS,
    WEEKDAY_NAMES,
)

# Source: https://github.com/CodeFoodPixels/robovac/issues/68#issuecomment-2119573501  # noqa: E501

T = TypeVar("T", bound=Message)


def is_protobuf_dps_value(value: Any) -> bool:
    """Heuristic: does a DPS value look like an Anker base64 protobuf blob?

    Scalar devices reuse the same DPS numbers with ints, numeric strings or JSON,
    so value shape is what tells the two protocols apart.
    """
    return (
        isinstance(value, str)
        and not value.lstrip("-").isdigit()
        and not value.startswith("{")
    )


def decode(to_type: type[T], b64_data: str, has_length: bool = True) -> T:
    data = b64decode(b64_data)

    if has_length:
        # Skip varint length prefix
        if not data:
            raise ValueError("Cannot decode empty data")
        pos = 0
        while pos < len(data) and data[pos] & 0x80:
            pos += 1
        if pos >= len(data):
            raise ValueError("Truncated varint in data")
        pos += 1
        data = data[pos:]

    return to_type().FromString(data)


def encode(
    message: type[Message], data: dict[str, Any], has_length: bool = True
) -> str:
    m = message(**data)
    return encode_message(m, has_length)


# A protobuf varint encodes at most 64 bits, so it is never longer than 10 bytes.
_MAX_VARINT_BYTES = 10


def decode_varint(data: bytes, pos: int) -> tuple[int, int]:
    """Decode a protobuf varint starting at *pos*. Returns (value, new_pos).

    A truncated varint returns what was read. Raises ValueError when the
    continuation bits run past 10 bytes, so a hostile run of 0xFF bytes cannot
    build an unbounded integer.
    """
    value = 0
    shift = 0
    end = min(len(data), pos + _MAX_VARINT_BYTES)
    while pos < end:
        b = data[pos]
        value |= (b & 0x7F) << shift
        pos += 1
        if not b & 0x80:
            return value, pos
        shift += 7
    if pos < len(data):
        raise ValueError(f"varint longer than {_MAX_VARINT_BYTES} bytes")
    return value, pos


def decode_zigzag(value: int) -> int:
    """Decode a protobuf sint32/sint64 zigzag value."""
    return (value >> 1) ^ -(value & 1)


def encode_varint(n: int) -> bytes:
    """Encode an integer as a protobuf varint."""
    if n < 0:
        raise ValueError(f"Cannot encode negative varint: {n}")
    out = bytearray()
    while n >= 0x80:
        out.append((n & 0x7F) | 0x80)
        n >>= 7
    out.append(n & 0x7F)
    return bytes(out)


def deduplicate_names(names: list[str]) -> list[str]:
    """Ensure names are unique by appending a " (n)" suffix to duplicates."""
    counts: dict[str, int] = {}
    for name in names:
        counts[name] = counts.get(name, 0) + 1

    duplicated = {n for n, c in counts.items() if c > 1}
    if not duplicated:
        return names

    seen: dict[str, int] = {}
    result: list[str] = []
    for name in names:
        if name in duplicated:
            seen[name] = seen.get(name, 0) + 1
            result.append(f"{name} ({seen[name]})" if seen[name] > 1 else name)
        else:
            result.append(name)
    return result


def encode_message(message: Message, has_length: bool = True) -> str:
    out = message.SerializeToString(deterministic=False)

    if has_length:
        out = encode_varint(len(out)) + out

    return b64encode(out).decode("utf-8")


def lz4_block_decompress(data: bytes, uncompressed_size: int) -> bytes:
    """Decompress a raw LZ4 block, pure Python so no lz4 dependency is needed.

    ``uncompressed_size`` caps the output: a corrupt block can otherwise describe
    a match longer than the real payload and grow the buffer without bound. The
    caller must bound ``uncompressed_size`` itself when it comes off the wire.
    Pure and thread-safe; raises ValueError on a malformed block.
    """
    output = bytearray()
    pos = 0
    n = len(data)
    while pos < n and len(output) < uncompressed_size:
        token = data[pos]
        pos += 1
        lit_len = (token >> 4) & 0xF
        if lit_len == 15:
            while pos < n:
                extra = data[pos]
                pos += 1
                lit_len += extra
                if extra != 255:
                    break
        output += data[pos : pos + lit_len]
        pos += lit_len
        if pos >= n:
            break
        if pos + 2 > n:
            raise ValueError("LZ4 block truncated inside a match offset")
        offset = data[pos] | (data[pos + 1] << 8)
        pos += 2
        if offset == 0 or offset > len(output):
            raise ValueError(f"LZ4 match offset {offset} outside output")
        match_len = (token & 0xF) + 4
        if (token & 0xF) == 15:
            while pos < n:
                extra = data[pos]
                pos += 1
                match_len += extra
                if extra != 255:
                    break
        # Bound the copy by the DECLARED size: match_len accumulates from an
        # unbounded 0xFF chain, so one sequence can otherwise expand far past
        # uncompressed_size before the outer loop looks again.
        match_len = min(match_len, uncompressed_size - len(output))
        match_start = len(output) - offset
        if match_len <= offset:
            output += output[match_start : match_start + match_len]
        else:
            # An overlapping match repeats the last ``offset`` bytes.
            period = output[match_start:]
            output += (period * (match_len // offset + 1))[:match_len]
    # A sequence can overshoot the declared size; the declared size wins.
    return bytes(output[:uncompressed_size])


def clamp_clean_times(value: Any) -> int:
    """Coerce ``value`` to a pass count in ``MIN_CLEAN_TIMES..MAX_CLEAN_TIMES``.

    None, 0 and non-numbers mean one pass.
    """
    try:
        times = int(value or MIN_CLEAN_TIMES)
    except (TypeError, ValueError):
        return MIN_CLEAN_TIMES
    return min(max(times, MIN_CLEAN_TIMES), MAX_CLEAN_TIMES)


_ALL_DAYS = frozenset(range(len(WEEKDAY_ABBREVIATIONS)))
_WEEKDAY_GROUPS: dict[str, frozenset[int]] = {
    **dict.fromkeys(("every day", "everyday", "daily", "all", "*"), _ALL_DAYS),
    **dict.fromkeys(("once", "never", "none"), frozenset()),
    **dict.fromkeys(("weekdays", "weekday"), frozenset(range(5))),
    **dict.fromkeys(("weekends", "weekend"), frozenset((5, 6))),
}
_WEEKDAY_WORDS = {
    day.lower(): i
    for days in (WEEKDAY_ABBREVIATIONS, WEEKDAY_NAMES)
    for i, day in enumerate(days)
}


def parse_weekdays(days: list[str] | str | None) -> frozenset[int]:
    """Monday-first indices into ``WEEKDAY_ABBREVIATIONS`` named by ``days``.

    Takes a string or list of day names in any case (an abbreviation, or the
    full English name: "Mon", "thursday") separated by commas, ``|`` or spaces,
    and groups ("Every day", "daily", "Weekdays", "Weekends", "Once") between
    commas or ``|``. Empty input is no day. Raises ValueError on any other word.
    """
    items = [days] if isinstance(days, str) else list(days or [])
    selected: set[int] = set()
    for item in items:
        for part in re.split(r"[,|]", str(item).lower()):
            words = part.split()
            group = " ".join(words)
            if group in _WEEKDAY_GROUPS:
                selected |= _WEEKDAY_GROUPS[group]
                continue
            for word in words:
                if word in _WEEKDAY_GROUPS:
                    selected |= _WEEKDAY_GROUPS[word]
                elif word in _WEEKDAY_WORDS:
                    selected.add(_WEEKDAY_WORDS[word])
                else:
                    raise ValueError(f"unknown day {word!r} in {days!r}")
    return frozenset(selected)


def valid_time_window(
    begin_hour: int, begin_minute: int, end_hour: int, end_minute: int
) -> bool:
    """True when both times are real clock times (hour 0-23, minute 0-59)."""
    return all(0 <= h <= 23 for h in (begin_hour, end_hour)) and all(
        0 <= m <= 59 for m in (begin_minute, end_minute)
    )
