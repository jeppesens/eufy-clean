"""The conversation-0 control burst that makes the robot start streaming the map.

The first packet authenticates: ``magic | type | username[32] | credential[32] |
reserved[32]``, where ``credential = md5(device_password + "||" + local_key)``.
The packets that follow it (a hello and the subscription to the map/path streams)
are fixed for this robot family and carry no secrets, so they are embedded
verbatim. The device answers each on conversation 0 and then opens conversation 5.
"""

from __future__ import annotations

import hashlib

_MAGIC = (0x12345678).to_bytes(4, "little")
_AUTH_TYPE = (0).to_bytes(4, "little")
_FIELD = 32
_USERNAME = "admin"

# Fixed conversation-0 packets captured from an S1 Pro (no secrets: a hello naming
# the peer, then a subscription to map.bin.stream / cleanPath.bin.stream /
# navPath.bin.stream, then a short follow-up).
_HELLO = bytes.fromhex(
    "78563412020000000000000064000c0074000000ffffffff6970635f737765657065725f726f626f740000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
)
_SUBSCRIBE = bytes.fromhex(
    "78563412030001000000000064000d00d000000005000000000000006970635f737765657065725f726f626f740000000000000000000000000000000000000000000000000000000000000000000000030000006d61702e62696e2e73747265616d00000000000000000000000000000000000000000000000000000000000000000000636c65616e506174682e62696e2e73747265616d000000000000000000000000000000000000000000000000000000006e6176506174682e62696e2e73747265616d000000000000000000000000000000000000000000000000000000000000"
)
_FOLLOW_UP = bytes.fromhex(
    "78563412040000000000000064000d0048000000000000000400000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
)


def auth_credential(device_password: str, local_key: str) -> str:
    """Return the conversation-0 auth token, ``md5(password + "||" + localKey)``."""
    return hashlib.md5(f"{device_password}||{local_key}".encode(), usedforsecurity=False).hexdigest()


def _auth_packet(credential: str) -> bytes:
    body = bytearray(_FIELD * 3)
    body[0 : len(_USERNAME)] = _USERNAME.encode()
    body[_FIELD : _FIELD + len(credential)] = credential.encode()
    return _MAGIC + _AUTH_TYPE + bytes(body)


def start_packets(device_password: str, local_key: str) -> list[bytes]:
    """Return the ordered conversation-0 packets, ready to wrap as KCP records."""
    return [_auth_packet(auth_credential(device_password, local_key)), _HELLO, _SUBSCRIBE, _FOLLOW_UP]
