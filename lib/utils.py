import time
from base64 import b64decode
from typing import Type, TypeVar

from google.protobuf.message import Message


async def sleep(ms: int):
    time.sleep(ms / 1000)

T = TypeVar("T", bound=Type[Message])


async def decode(to_type: T, b64_data: str, has_length: bool = True) -> T:
    data = b64decode(b64_data)

    if has_length:
        data = data[1:]

    return to_type().FromString(data)


async def encode(data: Message, has_length: bool = True) -> bytes:
    out = data.SerializeToString()

    if has_length:
        out = bytes([len(out)]) + out

    return out
