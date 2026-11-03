"""The little STUN/ICE this client needs to satisfy the device's connectivity checks.

The device runs a normal ICE agent with short-term credentials and will not open
the data channel until connectivity is confirmed in both directions. We answer
its binding requests and send our own; MESSAGE-INTEGRITY is HMAC-SHA1 keyed by
the checked side's ICE password and FINGERPRINT is CRC32 xor ``0x5354554e``.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import struct
import zlib

MAGIC_COOKIE = 0x2112A442
_MAGIC = MAGIC_COOKIE.to_bytes(4, "big")

BIND_REQUEST = 0x0001
BIND_SUCCESS = 0x0101

_ATTR_USERNAME = 0x0006
_ATTR_MESSAGE_INTEGRITY = 0x0008
_ATTR_XOR_MAPPED_ADDRESS = 0x0020
_ATTR_PRIORITY = 0x0024
_ATTR_USE_CANDIDATE = 0x0025
_ATTR_ICE_CONTROLLING = 0x002A
_ATTR_FINGERPRINT = 0x8028
_ATTR_SOFTWARE = 0x8022

_SOFTWARE = b"tuya_p2p_sdk_v3.4.3\x00"


def _attribute(attr_type: int, value: bytes) -> bytes:
    pad = (4 - len(value) % 4) % 4
    return struct.pack(">HH", attr_type, len(value)) + value + b"\x00" * pad


def _xor_mapped_address(ip: str, port: int) -> bytes:
    body = bytearray(8)
    body[1] = 0x01
    struct.pack_into(">H", body, 2, port ^ 0x2112)
    for i, octet in enumerate(ip.split(".")):
        body[4 + i] = int(octet) ^ _MAGIC[i]
    return bytes(body)


def build_message(message_type: int, transaction_id: bytes, attributes: list[bytes], integrity_key: bytes | None) -> bytes:
    """Build a STUN message, appending MESSAGE-INTEGRITY then FINGERPRINT."""
    body = b"".join(attributes)
    if integrity_key is not None:
        header = struct.pack(">HH", message_type, len(body) + 24) + _MAGIC + transaction_id
        mac = hmac.new(integrity_key, header + body, hashlib.sha1).digest()
        body += _attribute(_ATTR_MESSAGE_INTEGRITY, mac)
    header = struct.pack(">HH", message_type, len(body) + 8) + _MAGIC + transaction_id
    fingerprint = (zlib.crc32(header + body) & 0xFFFFFFFF) ^ 0x5354554E
    body += _attribute(_ATTR_FINGERPRINT, struct.pack(">I", fingerprint))
    return struct.pack(">HH", message_type, len(body)) + _MAGIC + transaction_id + body


def is_stun(datagram: bytes) -> bool:
    return len(datagram) >= 20 and datagram[4:8] == _MAGIC


def message_type(datagram: bytes) -> int:
    return int.from_bytes(datagram[0:2], "big")


def transaction_id(datagram: bytes) -> bytes:
    return datagram[8:20]


def binding_success(request: bytes, source_ip: str, source_port: int, our_ice_password: bytes) -> bytes:
    """Answer a device binding request from ``source`` with a success response."""
    return build_message(
        BIND_SUCCESS,
        transaction_id(request),
        [_attribute(_ATTR_XOR_MAPPED_ADDRESS, _xor_mapped_address(source_ip, source_port)), _attribute(_ATTR_SOFTWARE, _SOFTWARE)],
        our_ice_password,
    )


def binding_request(local_ufrag: str, remote_ufrag: str, remote_ice_password: bytes, nominate: bool) -> bytes:
    """Build a binding request toward the device, optionally nominating."""
    tid = b"AYUT" + os.urandom(8)
    attributes = [
        _attribute(_ATTR_USERNAME, f"{remote_ufrag}:{local_ufrag}".encode()),
        _attribute(_ATTR_PRIORITY, b"\x6e\xff\xff\xff"),
        _attribute(_ATTR_ICE_CONTROLLING, b"\xff\xff\xff\xff" + os.urandom(4)),
    ]
    if nominate:
        attributes.append(_attribute(_ATTR_USE_CANDIDATE, b""))
    attributes.append(_attribute(_ATTR_SOFTWARE, _SOFTWARE))
    return build_message(BIND_REQUEST, tid, attributes, remote_ice_password)
