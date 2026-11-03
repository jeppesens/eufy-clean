"""Reassemble the conversation-5 byte stream and pull the room list out of it.

The stream is a sequence of chunks: an 80-byte header (a constant ``1`` marker, a
constant ``1000``, a session counter, a chunk index, a 48-byte stream name, the
chunk payload length, the object's total length) followed by the payload. Objects
larger than one chunk span several chunks of the same stream name. Each assembled
``map.bin.stream`` object is a length-delimited ``MapChannelMsg``; the one whose
``msg_type`` is ``ROOM_PARAMS`` carries the rooms.
"""

from __future__ import annotations

import struct

from google.protobuf.internal.decoder import _DecodeVarint

from ...proto.cloud.p2pdata_pb2 import MapChannelMsg, MapInfo

_HEADER_LENGTH = 80
_SYNC = struct.pack("<II", 1, 1000)  # fields at offsets 0 and 4, used to find each header
_ROOM_PARAMS = MapInfo.ROOM_PARAMS
_MAP_INFO = MapChannelMsg.MAP_INFO
_MAP_STREAM = b"map.bin.stream"


def _iter_objects(stream: bytes):
    """Yield each ``(stream_name, object_bytes)`` reassembled from the chunk stream."""
    pos = stream.find(_SYNC)
    current_name: bytes | None = None
    buffer = b""
    total = 0
    while pos >= 0 and pos + _HEADER_LENGTH <= len(stream):
        name = stream[pos + 20 : pos + 68].split(b"\x00", 1)[0]
        payload_length, object_total = struct.unpack("<II", stream[pos + 68 : pos + 76])
        payload = stream[pos + _HEADER_LENGTH : pos + _HEADER_LENGTH + payload_length]
        if current_name != name or len(buffer) >= total:
            if current_name is not None and len(buffer) == total:
                yield current_name, buffer
            current_name, buffer, total = name, b"", object_total
        buffer += payload
        if len(buffer) == total:
            yield current_name, buffer
            current_name = None
        nxt = stream.find(_SYNC, pos + _HEADER_LENGTH + payload_length)
        pos = nxt
    if current_name is not None and len(buffer) == total:
        yield current_name, buffer


def _decode_delimited(buffer: bytes) -> MapChannelMsg:
    length, start = _DecodeVarint(buffer, 0)
    message = MapChannelMsg()
    message.ParseFromString(buffer[start : start + length])
    return message


def extract_rooms(stream: bytes) -> list[dict] | None:
    """Return ``[{"id", "name"}, ...]`` from the first ``ROOM_PARAMS`` object, or None."""
    for name, obj in _iter_objects(stream):
        if name != _MAP_STREAM:
            continue
        try:
            message = _decode_delimited(obj)
        except Exception:  # noqa: BLE001 - skip anything that is not a whole MapChannelMsg
            continue
        info = message.map_info
        if message.type != _MAP_INFO or info.msg_type != _ROOM_PARAMS:
            continue
        return [{"id": room.id, "name": room.name} for room in info.room_params.rooms]
    return None
