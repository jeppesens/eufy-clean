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
        data = data[1:]

    return to_type().FromString(data)


def encode(message: Type[Message], data: dict[str, Any], has_length: bool = True) -> str:
    m = message(**data)
    return encode_message(m, has_length)


def encode_message(message: Type[Message], has_length: bool = True) -> str:
    out = message.SerializeToString(deterministic=False)

    if has_length:
        out = bytes([len(out)]) + out

    return b64encode(out).decode('utf-8')
