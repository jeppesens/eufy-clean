"""Tests for room discovery from the P2P/biz stream."""

from custom_components.robovac_mqtt.api.map_stream import (
    try_extract_room_params,
    try_extract_stream_metadata,
)
from custom_components.robovac_mqtt.proto.cloud import stream_pb2


def _varint(value: int) -> bytes:
    result = bytearray()
    while value > 0x7F:
        result.append((value & 0x7F) | 0x80)
        value >>= 7
    result.append(value)
    return bytes(result)


def _room_params_hex() -> str:
    message = stream_pb2.RoomParams(map_id=1)
    message.rooms.add(id=1, name="Living Room")
    message.rooms.add(id=2, name="Kitchen")
    message.rooms.add(id=3, name="Bedroom")
    payload = message.SerializeToString()
    return (_varint(len(payload)) + payload).hex()


def test_extract_room_params_from_delimited_stream_frame() -> None:
    result = try_extract_room_params(_room_params_hex())

    assert result == {
        "map_id": 1,
        "rooms": [
            {"id": 1, "name": "Living Room"},
            {"id": 2, "name": "Kitchen"},
            {"id": 3, "name": "Bedroom"},
        ],
    }


def _metadata_hex() -> str:
    message = stream_pb2.Metadata()
    message.chan_ids.map_info = 3
    message.chan_ids.room_outline = 7
    message.chan_ids.room_params = 11
    message.chan_ids.map_data = 2
    payload = message.SerializeToString()
    return (_varint(len(payload)) + payload).hex()


def test_extract_stream_metadata_channel_mapping() -> None:
    assert try_extract_stream_metadata(_metadata_hex()) == {
        "map_info": 3,
        "room_outline": 7,
        "room_params": 11,
        "map_data": 2,
    }


def test_extract_room_params_deduplicates_room_names() -> None:
    message = stream_pb2.RoomParams(map_id=1)
    message.rooms.add(id=1, name="Kitchen")
    message.rooms.add(id=2, name="Kitchen")
    payload = message.SerializeToString()
    result = try_extract_room_params((_varint(len(payload)) + payload).hex())

    assert result is not None
    assert [room["name"] for room in result["rooms"]] == ["Kitchen", "Kitchen (2)"]
