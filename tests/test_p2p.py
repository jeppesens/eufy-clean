"""Unit tests for the local P2P map channel (api/p2p).

Covers the wire layers (Tuya type-32 framing, STUN, tagged KCP), the stream
reassembly, the decoder that folds stream objects into a live map, and the
projection onto the shared map model. Fixtures are synthetic protobufs, never
captures from a real home.
"""

import asyncio
import hashlib
import hmac
import struct
import zlib

import pytest

from custom_components.robovac_mqtt.api.p2p import control, framing, kcp, stun
from custom_components.robovac_mqtt.api.p2p.mapdata import (
    CHANGED_MAP,
    CHANGED_OBSTACLES,
    CHANGED_PATH,
    CHANGED_POSE,
    CHANGED_ROOMS,
    CHANGED_TARGET,
    CHANGED_ZONES,
    P2PMapDecoder,
    Pose,
    decode_path,
)
from custom_components.robovac_mqtt.api.p2p.mapimage import (
    build_map_data,
    build_overlay,
)
from custom_components.robovac_mqtt.api.p2p.session import P2PError, P2PSession
from custom_components.robovac_mqtt.api.p2p.streams import StreamReassembler
from custom_components.robovac_mqtt.proto.cloud.p2pdata_pb2 import (
    CompletePath,
    MapChannelMsg,
    MapInfo,
)
from custom_components.robovac_mqtt.proto.cloud.stream_pb2 import DynamicData
from custom_components.robovac_mqtt.utils import encode_varint

_KEY = b"0123456789abcdef"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _delimited(message) -> bytes:
    body = message.SerializeToString()
    return encode_varint(len(body)) + body


def _lz4_literals(data: bytes) -> bytes:
    """A valid LZ4 block holding ``data`` as one literal run (no matches)."""
    n = len(data)
    if n < 15:
        return bytes([n << 4]) + data
    extra, rest = bytearray(), n - 15
    while rest >= 255:
        extra.append(255)
        rest -= 255
    extra.append(rest)
    return bytes([0xF0]) + bytes(extra) + data


def _chunk(name: bytes, payload: bytes, total: int | None = None, index: int = 0) -> bytes:
    header = bytearray(80)
    struct.pack_into("<IIHHI", header, 0, 1, 1000, 3, 1, index)
    header[20 : 20 + len(name)] = name
    total = len(payload) if total is None else total
    struct.pack_into("<III", header, 68, len(payload), total, 1)
    return bytes(header) + payload


def _map_msg(kind, width=4, height=3, origin=(-10, -5), map_id=1) -> MapChannelMsg:
    message = MapChannelMsg()
    message.type = MapChannelMsg.MAP_INFO
    info = message.map_info
    info.map_id, info.map_width, info.map_height = map_id, width, height
    info.origin.x, info.origin.y = origin
    dock = info.docks.add()
    dock.x, dock.y, dock.theta = 1, -29, 157
    info.msg_type = kind
    return message


def _outline_msg(pixels: bytes, compress: bool = True, **kw) -> MapChannelMsg:
    message = _map_msg(MapInfo.MAP_ROOMOUTLINE, **kw)
    message.map_info.pixels.pixels = _lz4_literals(pixels) if compress else pixels
    message.map_info.pixels.pixel_size = len(pixels)
    return message


def _rooms_msg(*rooms) -> MapChannelMsg:
    message = _map_msg(MapInfo.ROOM_PARAMS)
    for room_id, name in rooms:
        room = message.map_info.room_params.rooms.add()
        room.id, room.name = room_id, name
    return message


def _path_obj(points, compress=True) -> bytes:
    raw = b"".join(
        x.to_bytes(2, "big", signed=True) + y.to_bytes(2, "big", signed=True) + bytes([f])
        for x, y, f in points
    )
    message = CompletePath()
    message.path = _lz4_literals(raw) if compress else raw
    message.path_lz4len = len(raw)
    return _delimited(message)


def _pose_obj(x, y, theta) -> bytes:
    message = DynamicData()
    message.cur_pose.x, message.cur_pose.y, message.cur_pose.theta = x, y, theta
    return _delimited(message)


# ---------------------------------------------------------------------------
# control (conversation 0)
# ---------------------------------------------------------------------------


def test_auth_credential_formula():
    """The conversation-0 token is md5(password + '||' + localKey)."""
    assert control.auth_credential("pw", "lk") == hashlib.md5(b"pw||lk").hexdigest()


def test_auth_packet_layout():
    """Auth packet: magic, type, 'admin', then the credential at offset 40."""
    credential = "a" * 32
    packet = control._auth_packet(credential)
    assert len(packet) == 104
    assert packet[0:4] == b"\x78\x56\x34\x12"
    assert packet[8:13] == b"admin"
    assert packet[40:72] == credential.encode()


def test_start_burst_omits_the_download_control_packet():
    """auth + hello + subscribe only: the app's type-4 follow-up stops the stream."""
    packets = control.start_packets("pw", "lk")
    assert [control.parse(p).type for p in packets] == [0, 2, 0x00010003]
    assert b"cleanPath.bin.stream" in packets[2]


def test_control_parse():
    packet = struct.pack("<IIIII", 0x12345678, 0x10003, 1, 0xD0064, 8) + struct.pack("<II", 5, 1)
    parsed = control.parse(packet)
    assert (parsed.type, parsed.flag, parsed.sub_command) == (0x10003, 1, 0xD0064)
    assert parsed.payload == struct.pack("<II", 5, 1)
    assert control.parse(b"\x00" * 24) is None


# ---------------------------------------------------------------------------
# Tuya type-32 framing
# ---------------------------------------------------------------------------


def test_framing_roundtrip():
    """A type-32 frame encodes and decodes back to the same JSON."""
    payload = {"header": {"type": "offer"}, "msg": {"sdp": "v=0"}}
    frame = framing.encode_frame(_KEY, framing.CMD_RTC, payload, 3)
    frames, tail = framing.decode_frames(_KEY, frame)
    assert tail == b""
    assert frames == [(framing.CMD_RTC, payload)]


def test_framing_keeps_partial_tail():
    frame = framing.encode_frame(_KEY, framing.CMD_RTC, {"a": 1}, 1)
    frames, tail = framing.decode_frames(_KEY, frame[:-5])
    assert not frames and tail == frame[:-5]


def test_framing_strips_device_return_code():
    """Device frames carry a 4-byte return code before the ciphertext."""
    payload = {"msg": {"candidate": ""}}
    frame = bytearray(framing.encode_frame(_KEY, framing.CMD_RTC, payload, 1))
    length = int.from_bytes(frame[12:16], "big")
    frame[12:16] = (length + 4).to_bytes(4, "big")
    frame[16:16] = b"\x00\x00\x00\x00"
    frames, _ = framing.decode_frames(_KEY, bytes(frame))
    assert frames[0][1] == payload


# ---------------------------------------------------------------------------
# STUN
# ---------------------------------------------------------------------------


def _attributes(message: bytes) -> dict[int, bytes]:
    attrs, pos = {}, 20
    while pos + 4 <= len(message):
        kind, length = struct.unpack(">HH", message[pos : pos + 4])
        attrs[kind] = message[pos + 4 : pos + 4 + length]
        pos += 4 + length + (-length % 4)
    return attrs


def test_stun_fingerprint_is_valid():
    message = stun.binding_request("abcd", "wxyz", b"pwd", nominate=True)
    assert stun.is_stun(message)
    fingerprint = struct.unpack(">I", message[-4:])[0]
    assert fingerprint == (zlib.crc32(message[:-8]) & 0xFFFFFFFF) ^ 0x5354554E


def test_stun_ice_controlling_uses_the_rfc_attribute_code():
    """ICE-CONTROLLING is 0x802A; the robot rejects 0x002A with 420 Unknown Attribute."""
    attrs = _attributes(stun.binding_request("abcd", "wxyz", b"pwd", nominate=True))
    assert 0x802A in attrs and 0x002A not in attrs
    assert 0x0025 in attrs  # USE-CANDIDATE when nominating
    assert attrs[0x0006] == b"wxyz:abcd"  # USERNAME = remote:local


def test_stun_message_integrity_keyed_by_remote_password():
    message = stun.binding_request("abcd", "wxyz", b"pwd", nominate=False)
    attrs = _attributes(message)
    mi_pos = message.index(struct.pack(">HH", 0x0008, 20))
    signed = bytearray(message[:mi_pos])
    struct.pack_into(">H", signed, 2, mi_pos - 20 + 24)
    assert attrs[0x0008] == hmac.new(b"pwd", bytes(signed), hashlib.sha1).digest()


def test_stun_binding_success_echoes_transaction():
    request = stun.binding_request("abcd", "wxyz", b"pwd", nominate=False)
    response = stun.binding_success(request, "192.168.1.9", 40000, b"ours")
    assert stun.message_type(response) == stun.BIND_SUCCESS
    assert stun.transaction_id(response) == stun.transaction_id(request)


# ---------------------------------------------------------------------------
# KCP
# ---------------------------------------------------------------------------


def _conversation(conv_id=kcp.CONV_MAP, on_message=None):
    sent: list[bytes] = []
    return kcp.KcpConversation(conv_id, _KEY, sent.append, on_message), sent


def _deliver(datagrams, conversation):
    for datagram in datagrams:
        for segment in kcp.parse_datagram(datagram, _KEY):
            conversation.input(segment)


def test_kcp_push_is_tagged_and_roundtrips():
    """A PUSH ends with HMAC-SHA1(media_key, segment) and its record decrypts."""
    sender, sent = _conversation(kcp.CONV_CONTROL)
    sender.send(b"hello world payload")
    assert len(sent) == 1
    datagram = sent[0]
    length = struct.unpack_from("<I", datagram, 20)[0]
    segment, tag = datagram[: 24 + length], datagram[24 + length :]
    assert tag == hmac.new(_KEY, segment, hashlib.sha1).digest()

    received: list[bytes] = []
    receiver, _ = _conversation(kcp.CONV_CONTROL, received.append)
    _deliver(sent, receiver)
    assert received == [b"hello world payload"]


def test_kcp_ack_is_tagged_and_advances_una():
    """Our ACKs carry the tag too; without it the robot never retires its window."""
    sender, pushes = _conversation()
    sender.send(b"x" * 10)
    receiver, acks = _conversation(on_message=lambda _m: None)
    _deliver(pushes, receiver)
    assert len(acks) == 1
    ack = acks[0]
    assert len(ack) == kcp.HEADER_LENGTH + kcp.TAG_LENGTH
    assert ack[-20:] == hmac.new(_KEY, ack[:24], hashlib.sha1).digest()
    conv, cmd, _frg, _wnd, _ts, sn, una, length = struct.unpack("<IBBHIIII", ack[:24])
    assert (conv, cmd, sn, una, length) == (kcp.CONV_MAP, kcp.CMD_ACK, 0, 1, 0)


def test_kcp_reassembles_fragments_before_decrypting():
    big = bytes(range(256)) * 12  # spans several segments
    sender, sent = _conversation()
    sender.send(big)
    assert len(sent) > 1
    received: list[bytes] = []
    receiver, _ = _conversation(on_message=received.append)
    _deliver(reversed(sent), receiver)  # out of order on the wire
    assert received == [big]


def test_kcp_retransmits_until_acked_then_gives_up():
    conv, sent = _conversation(kcp.CONV_CONTROL)
    conv.send(b"hello")
    conv._pending[0].sent_at -= 10_000  # noqa: SLF001 - age the segment
    conv.tick()
    assert len(sent) == 2 and sent[0] == sent[1]
    conv._pending[0].transmits = 99  # noqa: SLF001
    conv._pending[0].sent_at -= 10_000  # noqa: SLF001
    with pytest.raises(kcp.KcpError):
        conv.tick()


def test_kcp_una_retires_pending():
    conv, _ = _conversation(kcp.CONV_CONTROL)
    conv.send(b"a")
    conv.send(b"b")
    conv.input(kcp.Segment(kcp.CONV_CONTROL, kcp.CMD_ACK, 0, 32, 0, 0, 1, b""))
    assert conv.pending == 1


def test_kcp_answers_window_probe():
    conv, sent = _conversation()
    conv.input(kcp.Segment(kcp.CONV_MAP, kcp.CMD_WINDOW_ASK, 0, 32, 0, 0, 0, b""))
    assert sent and sent[0][4] == kcp.CMD_WINDOW_TELL


# ---------------------------------------------------------------------------
# stream reassembly
# ---------------------------------------------------------------------------


def test_reassembler_joins_multi_chunk_objects_across_feeds():
    payload = bytes(range(250)) * 10
    data = _chunk(b"map.bin.stream", payload[:1200], total=len(payload)) + _chunk(
        b"map.bin.stream", payload[1200:], total=len(payload), index=1
    )
    reassembler = StreamReassembler()
    out = []
    for i in range(0, len(data), 333):  # records rarely align with chunks
        out += list(reassembler.feed(data[i : i + 333]))
    assert out == [("map.bin.stream", payload)]


def test_reassembler_separates_streams():
    reassembler = StreamReassembler()
    data = _chunk(b"map.bin.stream", b"m") + _chunk(b"navPath.bin", b"p", index=1)
    assert list(reassembler.feed(data)) == [("map.bin.stream", b"m"), ("navPath.bin", b"p")]


def test_reassembler_skips_absurd_lengths():
    header = bytearray(_chunk(b"map.bin.stream", b""))
    struct.pack_into("<II", header, 68, 1 << 30, 1 << 30)
    reassembler = StreamReassembler()
    assert list(reassembler.feed(bytes(header) + _chunk(b"x", b"ok"))) == [("x", b"ok")]


# ---------------------------------------------------------------------------
# decoder
# ---------------------------------------------------------------------------


def test_decoder_builds_map_rooms_zones_target_obstacles():
    dec = P2PMapDecoder()
    outline = bytes([60 << 2] * 4 + [(0 << 2) | 2] * 4 + [(1 << 2) | 1] * 4)
    assert CHANGED_MAP in dec.apply("map.bin.stream", _delimited(_outline_msg(outline)))
    assert dec.state.outline == outline
    assert (dec.state.width, dec.state.height, dec.state.map_id) == (4, 3, 1)
    assert dec.state.dock == Pose(1, -29, 157)

    rooms = _delimited(_rooms_msg((0, "Kitchen "), (1, "")))
    assert dec.apply("map.bin.stream", rooms) == {CHANGED_ROOMS}
    assert [(r["id"], r["name"]) for r in dec.state.rooms] == [(0, "Kitchen"), (1, "")]

    zones = _map_msg(MapInfo.RESTRICT_ZONES)
    wall = zones.map_info.restricted_zones.virtual_walls.add()
    wall.p0.x, wall.p1.x = 1, 2
    assert dec.apply("map.bin.stream", _delimited(zones)) == {CHANGED_ZONES}
    assert dec.state.virtual_walls == [((1, 0), (2, 0))]

    target = _map_msg(MapInfo.TEMPORARY_DATA)
    target.map_info.temporary_data.select_rooms_clean.rooms.add().id = 0
    assert dec.apply("map.bin.stream", _delimited(target)) == {CHANGED_TARGET}
    assert dec.state.target_room_ids == [0]

    obstacles = _map_msg(MapInfo.OBSTACLE_INFO)
    obstacle = obstacles.map_info.obstacles.obstacles.add()
    obstacle.object_type = "Shoe"
    point = obstacle.show_points.add()
    point.x, point.y = 5, 6
    assert dec.apply("map.bin.stream", _delimited(obstacles)) == {CHANGED_OBSTACLES}
    assert dec.state.obstacles[0].object_type == "Shoe"
    assert dec.state.obstacles[0].points == ((5, 6),)


def test_decoder_accepts_uncompressed_outline():
    dec = P2PMapDecoder()
    outline = bytes([(2 << 2) | 2] * 12)
    dec.apply("map.bin.stream", _delimited(_outline_msg(outline, compress=False)))
    assert dec.state.outline == outline


def test_decoder_reports_no_change_for_repeats():
    dec = P2PMapDecoder()
    obj = _delimited(_rooms_msg((0, "Kitchen")))
    dec.apply("map.bin.stream", obj)
    assert dec.apply("map.bin.stream", obj) == set()


def test_decoder_path_snapshot_then_append_then_reset():
    dec = P2PMapDecoder()
    dec.apply("cleanPath.bin.stream", _path_obj([(1, 2, 2), (3, 4, 0x12)]))
    assert dec.state.path == [(1, 2, 2), (3, 4, 0x12)]
    assert dec.apply("cleanPath.bin.stream", _path_obj([(5, -6, 4)], compress=False)) == {
        CHANGED_PATH
    }
    assert dec.state.path[-1] == (5, -6, 4)
    dec.start_session()  # a new session re-sends the whole path
    dec.apply("cleanPath.bin.stream", _path_obj([(9, 9, 0)]))
    assert dec.state.path == [(9, 9, 0)]
    dec.apply("cleanPath.bin.stream", _delimited(CompletePath()))  # empty -> new clean
    assert dec.state.path == []


def test_decoder_pose():
    dec = P2PMapDecoder()
    assert dec.apply("navPath.bin", _pose_obj(3, 58, 152)) == {CHANGED_POSE}
    assert dec.state.pose == Pose(3, 58, 152)
    assert dec.apply("navPath.bin.stream", _pose_obj(3, 58, 152)) == set()


def test_decoder_ignores_garbage():
    dec = P2PMapDecoder()
    assert dec.apply("map.bin.stream", b"\x05\xff\xff\xff\xff\xff") == set()
    assert dec.apply("mystery.stream", b"") == set()


def test_decode_path_signed_coordinates():
    raw = (-277).to_bytes(2, "big", signed=True) + (1163).to_bytes(2, "big") + b"\x14"
    assert decode_path(raw) == [(-277, 1163, 0x14)]


# ---------------------------------------------------------------------------
# projection onto MapData / overlay
# ---------------------------------------------------------------------------


def _decoded_state():
    dec = P2PMapDecoder()
    dec.apply("map.bin.stream", _delimited(_outline_msg(bytes([(0 << 2) | 2] * 12))))
    dec.apply("map.bin.stream", _delimited(_rooms_msg((0, "Kitchen"), (1, ""))))
    dec.apply("cleanPath.bin.stream", _path_obj([(-10, -5, 2), (0, 0, 2)]))
    dec.apply("navPath.bin", _pose_obj(0, 0, 314))
    return dec.state


def test_build_map_data_uses_outline_as_map_and_mask():
    md = build_map_data(_decoded_state())
    assert (md.width, md.height, md.origin_x, md.origin_y, md.resolution) == (4, 3, -10, -5, 5)
    assert md.room_pixels and md.room_outline_width == 4
    assert md.room_names == {0: "Kitchen", 1: "Room 2"}
    assert md.room_id_at_normalized(0.5, 0.5) == 0


def test_build_map_data_none_without_map():
    assert build_map_data(P2PMapDecoder().state) is None


def test_overlay_projects_world_to_grid_and_snaps_to_dock():
    state = _decoded_state()
    md = build_map_data(state)
    moving = build_overlay(md, state)
    assert moving.robot == (2.0, 1.0)
    assert moving.robot_heading == pytest.approx(3.14)
    assert moving.path[0][:2] == (0.0, 0.0)
    docked = build_overlay(md, state, docked=True)
    assert docked.robot == ((1 + 10) / 5, (-29 + 5) / 5)
    assert docked.robot_heading is None


# ---------------------------------------------------------------------------
# session (offline behaviour)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_session_fails_cleanly_when_the_robot_is_unreachable(monkeypatch):
    async def refuse(*_a, **_k):
        raise ConnectionRefusedError("nope")

    class _Udp:
        closed = False

        @staticmethod
        def get_extra_info(_name):
            return ("127.0.0.1", 40000)

        def close(self):
            self.closed = True

    udp = _Udp()

    async def fake_endpoint(*_a, **_k):
        return udp, None

    async def resolve(host, port, **_k):
        assert host == "robot.lan"
        return [(2, 1, 6, "", ("192.168.1.50", port))]

    monkeypatch.setattr(asyncio, "open_connection", refuse)
    loop = asyncio.get_running_loop()
    monkeypatch.setattr(loop, "create_datagram_endpoint", fake_endpoint)
    monkeypatch.setattr(loop, "getaddrinfo", resolve)
    session = P2PSession(
        host="robot.lan",
        local_key="0123456789abcdef",
        device_id="dev",
        device_password="pw",
        on_object=lambda *_: None,
        host_ip="127.0.0.1",
        cloud_session={"sessionId": "test", "iceUfrag": "test", "icePassword": "password",
                       "aesKey": "00" * 16, "traceId": "test", "uid": "test"},
    )
    with pytest.raises((P2PError, OSError)):
        await session.run()
    assert not session.connected
    assert udp.closed
    assert session._host == "192.168.1.50"  # noqa: SLF001 - resolved for ICE matching


@pytest.mark.parametrize("kind", ["header", "payload", "tag", "truncated"])
def test_corrupt_push_segments_are_rejected_before_delivery(kind):
    raw = bytearray(kcp.build_segment(_KEY, kcp.CONV_MAP, kcp.CMD_PUSH, 0, 0, 0, 0, b"payload"))
    if kind == "truncated":
        raw = raw[:-1]
    else:
        offset = {"header": 16, "payload": kcp.HEADER_LENGTH, "tag": -1}[kind]
        raw[offset] ^= 1
    assert not kcp.parse_datagram(bytes(raw), _KEY)


def test_a_new_map_discards_previous_geometry_rooms_and_motion():
    decoder = P2PMapDecoder()
    decoder.apply("map.bin.stream", _delimited(_outline_msg(bytes([2] * 12))))
    decoder.apply("map.bin.stream", _delimited(_rooms_msg((0, "Old room"))))
    decoder.apply("cleanPath.bin.stream", _path_obj([(1, 2, 0)]))
    decoder.apply("navPath.bin", _pose_obj(1, 2, 100))
    new_rooms = _rooms_msg((0, "New room"))
    new_rooms.map_info.map_id = 2
    changed = decoder.apply("map.bin.stream", _delimited(new_rooms))
    assert {CHANGED_MAP, CHANGED_ROOMS} <= changed
    assert decoder.state.map_id == 2 and not decoder.state.has_map
    assert decoder.state.rooms[0]["name"] == "New room"
    assert not decoder.state.path and decoder.state.pose is None
