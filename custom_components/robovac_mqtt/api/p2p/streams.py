"""Reassemble the named file streams carried on the map conversation.

The device pushes a sequence of chunks, each an 80-byte header followed by its
payload. Header fields, little-endian::

    @0   u32  1            sync
    @4   u32  1000         sync
    @8   u16  session      bumps per subscription
    @12  u32  chunk index  monotonic across every stream of the session
    @20  char[48] name     e.g. "map.bin.stream", "cleanPath.bin.stream"
    @68  u32  payload length of this chunk
    @72  u32  total length of the object the chunk belongs to
    @76  u32  last         1 on the final chunk of an object

Objects larger than one chunk span consecutive chunks of the same name.
"""

from __future__ import annotations

import struct
from collections.abc import Iterator

HEADER_LENGTH = 80
SYNC = struct.pack("<II", 1, 1000)
_NAME = slice(20, 68)

MAP_STREAM = "map.bin.stream"
CLEAN_PATH_STREAM = "cleanPath.bin.stream"
NAV_PATH_STREAM = "navPath.bin.stream"

# A guard against a corrupt length field pinning memory.
_MAX_OBJECT = 16 * 1024 * 1024


class StreamReassembler:
    """Feed raw decrypted bytes; iterate the completed ``(name, object)`` pairs."""

    def __init__(self) -> None:
        self._buffer = b""
        self._objects: dict[str, bytearray] = {}
        self._totals: dict[str, int] = {}

    def feed(self, data: bytes) -> Iterator[tuple[str, bytes]]:
        self._buffer += data
        while True:
            start = self._buffer.find(SYNC)
            if start < 0:
                # Keep a tail in case the sync marker straddles two records.
                self._buffer = self._buffer[-(len(SYNC) - 1) :]
                return
            if start:
                self._buffer = self._buffer[start:]
            if len(self._buffer) < HEADER_LENGTH:
                return
            header = self._buffer[:HEADER_LENGTH]
            length, total = struct.unpack_from("<II", header, 68)
            if length > _MAX_OBJECT or total > _MAX_OBJECT:
                self._buffer = self._buffer[len(SYNC) :]
                continue
            if len(self._buffer) < HEADER_LENGTH + length:
                return
            name = header[_NAME].split(b"\x00", 1)[0].decode("ascii", "replace")
            payload = self._buffer[HEADER_LENGTH : HEADER_LENGTH + length]
            self._buffer = self._buffer[HEADER_LENGTH + length :]

            buffer = self._objects.get(name)
            if buffer is None or self._totals.get(name) != total or len(buffer) >= total:
                buffer = self._objects[name] = bytearray()
                self._totals[name] = total
            buffer += payload
            if len(buffer) >= total:
                del self._objects[name]
                yield name, bytes(buffer[:total])
