"""KCP over the direct-LAN P2P path, with the per-segment integrity tag.

Every KCP message is one encrypted record (``IV | AES-128-CBC``) keyed by the
session media key. A record larger than one segment is split across segments
whose ``frg`` counts down to zero, so records are rejoined *before* they are
decrypted. Every segment we send includes a 20-byte
``HMAC-SHA1(media_key, segment)`` tag, including ACKs. Device PUSHes carry the
tag; device ACKs and window segments do not.

Header, little-endian: ``conv u32 | cmd u8 | frg u8 | wnd u16 | ts u32 | sn u32 |
una u32 | len u32``. ``len`` counts the segment payload (the IV included).
"""

from __future__ import annotations

import hashlib
import hmac
import os
import struct
import time
from collections.abc import Callable
from dataclasses import dataclass

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

HEADER_LENGTH = 24
TAG_LENGTH = 20

CMD_PUSH = 0x51
CMD_ACK = 0x52
CMD_WINDOW_ASK = 0x53
CMD_WINDOW_TELL = 0x54

CONV_CONTROL = 0
CONV_VIDEO = 1  # camera stream (RTP/H.265), opened by the IOCtrl video start
CONV_MAP = 5

_HEADER = struct.Struct("<IBBHIIII")
_WINDOW = 512
# Leaves room for the header, the tag and the UDP/IP overhead within a 1500 MTU.
_MAX_SEGMENT_DATA = 1376
_RETRANSMIT_AFTER_MS = 300
_MAX_TRANSMITS = 10


class KcpError(Exception):
    """Raised when a conversation can no longer deliver."""


@dataclass(frozen=True, slots=True)
class Segment:
    conversation: int
    command: int
    fragment: int
    window: int
    timestamp: int
    sequence: int
    unacknowledged: int
    data: bytes


def _now_ms() -> int:
    return int(time.monotonic() * 1000) & 0xFFFFFFFF


def encrypt_record(media_key: bytes, plaintext: bytes) -> bytes:
    """Return ``IV | AES-CBC(PKCS#7(plaintext))`` under a fresh IV."""
    iv = os.urandom(16)
    pad = 16 - (len(plaintext) % 16)
    enc = Cipher(algorithms.AES(media_key), modes.CBC(iv)).encryptor()
    return iv + enc.update(plaintext + bytes([pad]) * pad) + enc.finalize()


def decrypt_record(media_key: bytes, record: bytes) -> bytes:
    """Decrypt one ``IV | AES-CBC`` record and strip PKCS#7 padding."""
    if len(record) < 32 or len(record) % 16:
        raise ValueError(f"record is not IV plus whole AES blocks ({len(record)} bytes)")
    iv, ciphertext = record[:16], record[16:]
    dec = Cipher(algorithms.AES(media_key), modes.CBC(iv)).decryptor()
    plain = dec.update(ciphertext) + dec.finalize()
    pad = plain[-1]
    if not 1 <= pad <= 16 or plain[-pad:] != bytes([pad]) * pad:
        raise ValueError("record has invalid PKCS#7 padding")
    return plain[:-pad]


def build_segment(
    media_key: bytes | None,
    conversation: int,
    command: int,
    fragment: int,
    timestamp: int,
    sequence: int,
    unacknowledged: int,
    data: bytes = b"",
) -> bytes:
    """Serialize one segment, tagging it when a media key is supplied."""
    segment = _HEADER.pack(
        conversation, command, fragment, _WINDOW, timestamp, sequence, unacknowledged, len(data)
    ) + data
    if media_key is not None:
        segment += hmac.new(media_key, segment, hashlib.sha1).digest()
    return segment


def parse_datagram(datagram: bytes, media_key: bytes) -> list[Segment]:
    """Split inbound segments, checking the device's PUSH integrity tags."""
    segments: list[Segment] = []
    pos = 0
    while pos + HEADER_LENGTH <= len(datagram):
        conv, cmd, frg, wnd, ts, sn, una, length = _HEADER.unpack_from(datagram, pos)
        if cmd not in (CMD_PUSH, CMD_ACK, CMD_WINDOW_ASK, CMD_WINDOW_TELL):
            break
        data = datagram[pos + HEADER_LENGTH : pos + HEADER_LENGTH + length]
        if len(data) < length:
            break
        end = pos + HEADER_LENGTH + length
        if cmd == CMD_PUSH:
            tag = datagram[end : end + TAG_LENGTH]
            expected = hmac.new(media_key, datagram[pos:end], hashlib.sha1).digest()
            if not hmac.compare_digest(tag, expected):
                break
        segments.append(Segment(conv, cmd, frg, wnd, ts, sn, una, data))
        pos += HEADER_LENGTH + length
        if cmd == CMD_PUSH:
            pos += TAG_LENGTH
    return segments


@dataclass(slots=True)
class _Pending:
    sequence: int
    raw: bytes
    sent_at: int
    transmits: int


class KcpConversation:
    """One reliable conversation: acks, retransmits and fragment reassembly.

    ``transmit`` writes one raw segment to the wire. ``on_message`` receives each
    reassembled, decrypted record. The caller drives :meth:`tick` periodically
    for retransmission.
    """

    def __init__(
        self,
        conversation: int,
        media_key: bytes,
        transmit: Callable[[bytes], None],
        on_message: Callable[[bytes], None] | None = None,
    ) -> None:
        self.conversation = conversation
        self._key = media_key
        self._transmit = transmit
        self._on_message = on_message
        self._send_next = 0
        self._receive_next = 0
        self._received: dict[int, Segment] = {}
        self._fragments: list[bytes] = []
        self._pending: list[_Pending] = []

    @property
    def pending(self) -> int:
        return len(self._pending)

    def send(self, plaintext: bytes) -> None:
        """Encrypt one message into a record and queue it, fragmenting as needed."""
        record = encrypt_record(self._key, plaintext)
        count = max(1, -(-len(record) // _MAX_SEGMENT_DATA))
        now = _now_ms()
        for index in range(count):
            chunk = record[index * _MAX_SEGMENT_DATA : (index + 1) * _MAX_SEGMENT_DATA]
            raw = build_segment(
                self._key, self.conversation, CMD_PUSH, count - 1 - index, now,
                self._send_next, self._receive_next, chunk,
            )
            self._pending.append(_Pending(self._send_next, raw, now, 1))
            self._send_next += 1
            self._transmit(raw)

    def input(self, segment: Segment) -> None:
        """Feed one inbound segment addressed to this conversation."""
        self._retire(segment.unacknowledged)
        if segment.command == CMD_ACK:
            self._pending = [p for p in self._pending if p.sequence != segment.sequence]
        elif segment.command == CMD_PUSH:
            self._accept(segment)
            # Ack after delivery so ``una`` reflects what was just consumed.
            self._transmit(
                build_segment(
                    self._key, self.conversation, CMD_ACK, 0, segment.timestamp,
                    segment.sequence, self._receive_next,
                )
            )
        elif segment.command == CMD_WINDOW_ASK:
            self._transmit(
                build_segment(
                    self._key, self.conversation, CMD_WINDOW_TELL, 0, _now_ms(), 0, self._receive_next
                )
            )

    def tick(self) -> None:
        """Retransmit anything unacknowledged for too long."""
        now = _now_ms()
        for entry in self._pending:
            if (now - entry.sent_at) & 0xFFFFFFFF < _RETRANSMIT_AFTER_MS:
                continue
            if entry.transmits >= _MAX_TRANSMITS:
                raise KcpError(
                    f"conversation {self.conversation}: segment {entry.sequence} undelivered"
                )
            entry.sent_at = now
            entry.transmits += 1
            self._transmit(entry.raw)

    def _retire(self, unacknowledged: int) -> None:
        while self._pending and self._pending[0].sequence < unacknowledged:
            self._pending.pop(0)

    def _accept(self, segment: Segment) -> None:
        sn = segment.sequence
        if sn < self._receive_next or sn >= self._receive_next + _WINDOW or sn in self._received:
            return
        self._received[sn] = segment
        while (nxt := self._received.pop(self._receive_next, None)) is not None:
            self._receive_next += 1
            self._fragments.append(nxt.data)
            if nxt.fragment:
                continue
            record = b"".join(self._fragments)
            self._fragments = []
            if not record or self._on_message is None:
                continue
            try:
                plaintext = decrypt_record(self._key, record)
            except ValueError:
                continue
            self._on_message(plaintext)
