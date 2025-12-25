import asyncio
from base64 import b64decode, b64encode
from typing import Any, Type, TypeVar

from google.protobuf.message import Message


async def sleep(ms: int):
    await asyncio.sleep(ms / 1000)

# This code comes from here: https://github.com/CodeFoodPixels/robovac/issues/68#issuecomment-2119573501

T = TypeVar("T", bound=Type[Message])


def decode(to_type: T, b64_data: str, has_length: bool = True) -> T:
    data = b64decode(b64_data)

    if has_length:
        # Skip varint length prefix
        pos = 0
        while data[pos] & 0x80:
            pos += 1
        pos += 1
        data = data[pos:]

    return to_type().FromString(data)


def encode(message: Type[Message], data: dict[str, Any], has_length: bool = True) -> str:
    m = message(**data)
    return encode_message(m, has_length)


def encode_varint(n: int) -> bytes:
    """Encode an integer as a protobuf varint."""
    out = bytearray()
    while n >= 0x80:
        out.append((n & 0x7f) | 0x80)
        n >>= 7
    out.append(n & 0x7f)
    return bytes(out)


def encode_message(message: Type[Message], has_length: bool = True) -> str:
    out = message.SerializeToString(deterministic=False)

    if has_length:
        out = encode_varint(len(out)) + out

    return b64encode(out).decode('utf-8')
