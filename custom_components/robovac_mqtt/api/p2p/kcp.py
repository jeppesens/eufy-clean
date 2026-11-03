"""KCP segments and their per-segment integrity tag.

The media rides KCP over the UDP pair. Each data segment is followed by a 20-byte
``HMAC-SHA1(media_key, segment)`` tag covering the whole segment; the device
silently drops any data segment whose tag is missing or wrong. ACK segments carry
no tag. A segment's ``len`` field counts the record **including** its 16-byte IV,
so the ciphertext is ``len - 16`` bytes.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import struct
from dataclasses import dataclass

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

HEADER_LENGTH = 24
TAG_LENGTH = 20

CMD_PUSH = 0x51
CMD_ACK = 0x52

CONV_CONTROL = 0
CONV_MAP = 5


@dataclass(frozen=True, slots=True)
class Segment:
    conversation: int
    command: int
    timestamp: int
    sequence: int
    unacknowledged: int
    data: bytes


def _record(media_key: bytes, plaintext: bytes) -> bytes:
    iv = os.urandom(16)
    pad = 16 - (len(plaintext) % 16)
    plaintext += bytes([pad]) * pad
    enc = Cipher(algorithms.AES(media_key), modes.CBC(iv)).encryptor()
    return iv + enc.update(plaintext) + enc.finalize()


def decrypt_record(media_key: bytes, record: bytes) -> bytes:
    """Decrypt one ``IV | AES-CBC`` record and strip PKCS#7 padding."""
    iv, ciphertext = record[:16], record[16:]
    dec = Cipher(algorithms.AES(media_key), modes.CBC(iv)).decryptor()
    plain = dec.update(ciphertext) + dec.finalize()
    if plain and 1 <= plain[-1] <= 16:
        plain = plain[: -plain[-1]]
    return plain


def build_push(media_key: bytes, conversation: int, sequence: int, plaintext: bytes) -> bytes:
    data = _record(media_key, plaintext)
    header = struct.pack("<IBBHIIII", conversation, CMD_PUSH, 0, 512, 0, sequence, 0, len(data))
    segment = header + data
    return segment + hmac.new(media_key, segment, hashlib.sha1).digest()


def build_ack(conversation: int, sequence: int, receive_next: int) -> bytes:
    return struct.pack("<IBBHIIII", conversation, CMD_ACK, 0, 512, 0, sequence, receive_next, 0)


def parse_datagram(datagram: bytes) -> list[Segment]:
    """Split one UDP datagram into its stacked KCP segments."""
    segments: list[Segment] = []
    pos = 0
    while pos + HEADER_LENGTH <= len(datagram):
        conv, cmd, _frg, _wnd, ts, sn, una, length = struct.unpack("<IBBHIIII", datagram[pos : pos + HEADER_LENGTH])
        if cmd == CMD_PUSH:
            data = datagram[pos + HEADER_LENGTH : pos + HEADER_LENGTH + length]
            segments.append(Segment(conv, cmd, ts, sn, una, data))
            pos += HEADER_LENGTH + length + TAG_LENGTH
        else:
            segments.append(Segment(conv, cmd, ts, sn, una, b""))
            pos += HEADER_LENGTH
    return segments
