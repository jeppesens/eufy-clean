"""Unit tests for the local P2P client (api/p2p): framing, KCP tag, rooms."""

import hashlib
import hmac
import struct

from google.protobuf.internal import encoder

from custom_components.robovac_mqtt.api.p2p import control, framing, kcp, mapdata, stun
from custom_components.robovac_mqtt.proto.cloud.p2pdata_pb2 import MapChannelMsg, MapInfo

_KEY = b"0123456789abcdef"


def test_auth_credential_formula():
    """The conversation-0 token is md5(password + '||' + localKey)."""
    assert control.auth_credential("pw", "lk") == hashlib.md5(b"pw||lk").hexdigest()


def test_auth_packet_layout():
    """Auth packet: magic, type 0, 'admin', then the credential at offset 40."""
    credential = "a" * 32
    packet = control._auth_packet(credential)
    assert len(packet) == 104
    assert packet[0:4] == b"\x78\x56\x34\x12"
    assert packet[4:8] == b"\x00\x00\x00\x00"
    assert packet[8:13] == b"admin"
    assert packet[40:72] == credential.encode()


def test_kcp_push_is_tagged_and_roundtrips():
    """A PUSH segment ends with HMAC-SHA1(media_key, segment) and decrypts back."""
    plaintext = b"hello world payload"
    datagram = kcp.build_push(_KEY, kcp.CONV_CONTROL, 7, plaintext)
    length = struct.unpack("<I", datagram[20:24])[0]
    segment, tag = datagram[: 24 + length], datagram[24 + length :]
    assert tag == hmac.new(_KEY, segment, hashlib.sha1).digest()
    assert len(tag) == kcp.TAG_LENGTH
    [parsed] = kcp.parse_datagram(datagram)
    assert parsed.command == kcp.CMD_PUSH
    assert parsed.sequence == 7
    assert kcp.decrypt_record(_KEY, parsed.data) == plaintext


def test_kcp_ack_has_no_tag():
    """An ACK is a bare 24-byte header with sn and una set."""
    ack = kcp.build_ack(kcp.CONV_MAP, 3, 4)
    assert len(ack) == kcp.HEADER_LENGTH
    conv, cmd, _frg, _wnd, _ts, sn, una, length = struct.unpack("<IBBHIIII", ack)
    assert (conv, cmd, sn, una, length) == (kcp.CONV_MAP, kcp.CMD_ACK, 3, 4, 0)


def test_framing_roundtrip():
    """A type-32 frame encodes and decodes back to the same JSON."""
    payload = {"header": {"type": "offer"}, "msg": {"sdp": "v=0"}}
    frame = framing.encode_frame(_KEY, framing.CMD_RTC, payload, 3)
    frames, tail = framing.decode_frames(_KEY, frame)
    assert tail == b""
    assert frames == [(framing.CMD_RTC, payload)]


def test_framing_strips_device_return_code():
    """Device frames carry a 4-byte return code before the ciphertext."""
    payload = {"msg": {"candidate": ""}}
    frame = bytearray(framing.encode_frame(_KEY, framing.CMD_RTC, payload, 1))
    # Splice a zero return code in front of the ciphertext and fix the length.
    length = int.from_bytes(frame[12:16], "big")
    frame[12:16] = (length + 4).to_bytes(4, "big")
    frame[16:16] = b"\x00\x00\x00\x00"
    frames, _ = framing.decode_frames(_KEY, bytes(frame))
    assert frames[0][1] == payload


def test_stun_fingerprint_is_valid():
    """binding_request ends with a correct FINGERPRINT attribute."""
    import zlib

    message = stun.binding_request("abcd", "wxyz", b"pwd", nominate=True)
    assert stun.is_stun(message)
    fingerprint = struct.unpack(">I", message[-4:])[0]
    assert fingerprint == (zlib.crc32(message[:-8]) & 0xFFFFFFFF) ^ 0x5354554E


def _delimited(message) -> bytes:
    body = message.SerializeToString()
    return encoder._VarintBytes(len(body)) + body


def _chunk(name: bytes, payload: bytes) -> bytes:
    header = bytearray(80)
    struct.pack_into("<II", header, 0, 1, 1000)
    struct.pack_into("<H", header, 8, 1)
    struct.pack_into("<H", header, 10, 1)
    header[20 : 20 + len(name)] = name
    struct.pack_into("<III", header, 68, len(payload), len(payload), 1)
    return bytes(header) + payload


def test_extract_rooms_keeps_room_zero():
    """extract_rooms decodes ROOM_PARAMS and preserves room id 0."""
    message = MapChannelMsg()
    message.type = MapChannelMsg.MAP_INFO
    message.map_info.msg_type = MapInfo.ROOM_PARAMS
    for room_id, name in ((0, "Kitchen"), (5, "")):
        room = message.map_info.room_params.rooms.add()
        room.id = room_id
        room.name = name
    stream = _chunk(b"map.bin.stream", _delimited(message))
    assert mapdata.extract_rooms(stream) == [
        {"id": 0, "name": "Kitchen"},
        {"id": 5, "name": ""},
    ]


def test_extract_rooms_none_without_room_params():
    """A stream with no ROOM_PARAMS object returns None."""
    message = MapChannelMsg()
    message.type = MapChannelMsg.MAP_INFO
    message.map_info.msg_type = MapInfo.OBSTACLE_INFO
    stream = _chunk(b"map.bin.stream", _delimited(message))
    assert mapdata.extract_rooms(stream) is None
