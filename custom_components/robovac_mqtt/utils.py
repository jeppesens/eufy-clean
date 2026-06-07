from __future__ import annotations

from base64 import b64decode, b64encode
from typing import Any, TypeVar

from google.protobuf.message import Message

# This code comes from here: https://github.com/CodeFoodPixels/robovac/issues/68#issuecomment-2119573501  # noqa: E501

T = TypeVar("T", bound=Message)


def is_protobuf_dps_value(value: Any) -> bool:
    """Heuristic: does a DPS value look like an Anker base64 protobuf blob?

    Anker "novel" DPS arrive as non-numeric base64 strings (e.g. "CgYI..."). The
    Tuya "scalar" protocol reuses the same DPS *numbers* with plain ints, numeric
    strings, or JSON objects. Used to tell the two protocols apart.
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
    """Ensure names are unique by appending a suffix to duplicates.

    e.g. ["Kitchen", "Kitchen", "Bedroom"] -> ["Kitchen", "Kitchen (2)", "Bedroom"].
    """
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
