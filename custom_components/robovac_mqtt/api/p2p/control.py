"""The conversation-0 control burst that makes the robot start streaming the map.

The first packet authenticates: ``magic | type | username[32] | credential[32] |
reserved[32]``, where ``credential = md5(device_password + "||" + local_key)``.
The packets that follow it (a hello and the subscription to the map/path streams)
are fixed for this robot family and carry no secrets, so they are embedded
verbatim. The device answers each on conversation 0 and then opens conversation 5.

Every other conversation-0 message is ``magic | type | flag | sub | len |
payload``, all little-endian u32.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

_MAGIC = (0x12345678).to_bytes(4, "little")
_AUTH_TYPE = (0).to_bytes(4, "little")
_FIELD = 32
_USERNAME = "admin"

# Fixed conversation-0 packets captured from an S1 Pro (no secrets): a hello that
# queries the "ipc_sweeper_robot" album, then a subscription that streams
# map.bin.stream / cleanPath.bin.stream / navPath.bin.stream on conversation 5.
# The app follows these with a type-4 download-control packet; sending it makes
# the robot stop mid-file, so it is deliberately left out.
_HELLO = bytes.fromhex(
    "78563412020000000000000064000c0074000000ffffffff6970635f737765657065725f726f626f740000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
)
_SUBSCRIBE = bytes.fromhex(
    "78563412030001000000000064000d00d000000005000000000000006970635f737765657065725f726f626f740000000000000000000000000000000000000000000000000000000000000000000000030000006d61702e62696e2e73747265616d00000000000000000000000000000000000000000000000000000000000000000000636c65616e506174682e62696e2e73747265616d000000000000000000000000000000000000000000000000000000006e6176506174682e62696e2e73747265616d000000000000000000000000000000000000000000000000000000000000"
)


def auth_credential(device_password: str, local_key: str) -> str:
    """Return the conversation-0 auth token, ``md5(password + "||" + localKey)``."""
    return hashlib.md5(f"{device_password}||{local_key}".encode(), usedforsecurity=False).hexdigest()


def _auth_packet(credential: str) -> bytes:
    body = bytearray(_FIELD * 3)
    body[0 : len(_USERNAME)] = _USERNAME.encode()
    body[_FIELD : _FIELD + len(credential)] = credential.encode()
    return _MAGIC + _AUTH_TYPE + bytes(body)


def _command(kind: int, sub_command: int, payload: bytes = b"") -> bytes:
    """Build ``magic | type | flag=0 | sub | len | payload`` (all little-endian u32)."""
    return (
        _MAGIC
        + kind.to_bytes(4, "little")
        + (0).to_bytes(4, "little")
        + sub_command.to_bytes(4, "little")
        + len(payload).to_bytes(4, "little")
        + payload
    )


def _u32(*values: int) -> bytes:
    return b"".join(v.to_bytes(4, "little") for v in values)


# The capability exchange the app opens every IPC session with.
_CAPABILITIES = (
    b'{"cmd":"capability_exchange_req","protocol_version":1,'
    b'"data":{"capabilities":{"opus_encode":1,"opus_decode":1}}}\x00'
)


def _io_control(request_id: int, command: int, op: int, *args: int) -> bytes:
    """An IOCtrl request: type ``0x10000 | id``, sub ``(op << 16) | command``."""
    return _command(0x10000 | request_id, (op << 16) | command, _u32(*args))


def video_prelude_packets(device_password: str, local_key: str) -> list[bytes]:
    """Auth, hello and the capability exchange that open every IPC session."""
    return [
        _auth_packet(auth_credential(device_password, local_key)),
        _command(0, 0x0A, _u32(0x00010001)),
        _command(0, 0x15, _CAPABILITIES),
    ]


def video_start_packets() -> list[bytes]:
    """Select HD on channel 0 and start video after the prelude and DP 181 open.

    This is the sequence verified on the S1 Pro. SD clarity (2) can omit periodic
    keyframes; HD (4) sustained the 800x600 stream. Speculative alternatives are
    documented in the protocol notes rather than sent to the robot.
    """
    return [_io_control(2, 9, 0, 0, 4), _io_control(3, 6, 0, 0, 0), _io_control(4, 6, 4, 0, 4)]


def start_packets(device_password: str, local_key: str) -> list[bytes]:
    """Return the ordered conversation-0 packets, ready to wrap as KCP records."""
    return [_auth_packet(auth_credential(device_password, local_key)), _HELLO, _SUBSCRIBE]


@dataclass(frozen=True, slots=True)
class ControlPacket:
    """One decoded conversation-0 message."""

    type: int
    flag: int
    sub_command: int
    payload: bytes


def parse(plaintext: bytes) -> ControlPacket | None:
    """Decode ``magic | type | flag | sub | len | payload``; None without the magic."""
    if len(plaintext) < 20 or plaintext[:4] != _MAGIC:
        return None
    length = int.from_bytes(plaintext[16:20], "little")
    return ControlPacket(
        type=int.from_bytes(plaintext[4:8], "little"),
        flag=int.from_bytes(plaintext[8:12], "little"),
        sub_command=int.from_bytes(plaintext[12:16], "little"),
        payload=plaintext[20 : 20 + length],
    )
