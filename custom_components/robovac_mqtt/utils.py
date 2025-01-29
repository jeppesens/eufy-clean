import time
from base64 import b64decode, b64encode
from typing import Any, Type, TypeVar

from google.protobuf.message import Message


async def sleep(ms: int):
    time.sleep(ms / 1000)

T = TypeVar("T", bound=Type[Message])


async def decode(to_type: T, b64_data: str, has_length: bool = True) -> T:
    data = b64decode(b64_data)

    if has_length:
        data = data[1:]

    return to_type().FromString(data)


async def encode(message: Type[Message], data: dict[str, Any], has_length: bool = True) -> str:
    m = message(**data)
    out = m.SerializeToString(deterministic=False)

    if has_length:
        out = bytes([len(out)]) + out

    return b64encode(out).decode('utf-8')
