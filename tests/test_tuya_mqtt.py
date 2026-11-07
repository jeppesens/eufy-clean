"""Tests for the Tuya mobile-MQTT live-pose subscriber (api/tuya_mqtt.py).

The CONNECT builders are pinned against hand-derived values for a synthetic
session; the frame decoders against synthetic frames in the device's framing.
"""

import hashlib
import logging
import ssl
import struct
import time
import zlib
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from homeassistant.util.ssl import client_context

from custom_components.robovac_mqtt.api import tuya_mqtt as tm
from custom_components.robovac_mqtt.const import (
    TUYA_THING_CHKEY,
    TUYA_THING_CLIENT_ID,
    TUYA_THING_SALT,
)
from custom_components.robovac_mqtt.proto.cloud.common_pb2 import Pose
from custom_components.robovac_mqtt.proto.cloud.stream_pb2 import RoomParams

# Synthetic CONNECT parameters (same shape as a real session) and their derivations.
_ECODE = "a1b2c3d4e5f60718"
_PASSWORD = "0a0ff0a89e76c3b2"
_PARTNER = "p1000001"
_SID = "az100000n1000000EXAMPLE000123456789abcdef0123456789abcde"
_USERNAME = (
    "p1000001_v1_w8x4ppqkdxvqnd73ahj9_7cbfe6d8_mb_"
    "az100000n1000000EXAMPLE000123456789abcdef0123456789abcde2180cbdd6060f423"
)


def _md5hex(data: str | bytes) -> str:
    return hashlib.md5(data if isinstance(data, bytes) else data.encode()).hexdigest()


def test_build_password_is_the_middle_of_a_double_md5():
    """password = md5hex(md5hex(SALT) + ecode)[8:24]."""
    derived = _md5hex(_md5hex(TUYA_THING_SALT) + _ECODE)[8:24]
    assert derived == _PASSWORD
    assert tm.build_password(_ECODE) == _PASSWORD


def test_build_username_is_partner_app_chkey_sid_and_md5_tail():
    """username = partner_v1_<appId>_<chKey>_mb_<sid><md5hex(md5hex(appId)+ecode)[-16:]>."""
    tail = _md5hex(_md5hex(TUYA_THING_CLIENT_ID) + _ECODE)[-16:]
    derived = f"{_PARTNER}_v1_{TUYA_THING_CLIENT_ID}_{TUYA_THING_CHKEY}_mb_{_SID}{tail}"
    assert derived == _USERNAME
    assert tm.build_username(_PARTNER, _SID, _ECODE) == _USERNAME


def test_build_client_id_format():
    cid = tm.build_client_id("00112233445566778899aabbccddeeff00112233aabb", "eh-100000001")
    assert cid.startswith("com.oceanwing.battery.cam_mb_")
    assert cid.endswith("_DEFAULT")
    # pkg _mb_ <deviceID44> _ <md5:32> _ DEFAULT
    parts = cid.split("_")
    assert parts[-1] == "DEFAULT"
    assert len(parts[-2]) == 32  # md5hex(uid+salt)


def test_host_from_url():
    assert tm._host_from_url("ssl://m1-eu.iotbing.com:8883") == "m1-eu.iotbing.com"
    assert tm._host_from_url(None) == "m1-us.iotbing.com"
    assert tm._host_from_url("m1-in.iotbing.com") == "m1-in.iotbing.com"


def _mmi_frame(channel: int, body: bytes, *, offset: int = 0, clear_type: int = 0) -> bytes:
    """Build a plaintext m/m/i frame: 23-byte header, body, CRC32 trailer.

    ``len`` (bytes 6..7) counts from offset 12; ``nbytes`` (21..22) is the body size.
    """
    head = (
        b"\x55\xaa\x00\x00\x00\x02"
        + struct.pack(">H", len(body) + 15)
        + bytes([0x01, 0xC0, channel, clear_type, clear_type])
        + b"\x00\x00\x00\x01"
        + struct.pack(">IH", offset, len(body))
    )
    frame = head + body
    return frame + zlib.crc32(frame).to_bytes(4, "big")


def _pose_frame(x: int, y: int, theta: int) -> bytes:
    """Build a 0x6c pose frame.

    Body is a bare length-prefixed ``Pose``: ``L (= pose_len + 1) | pose_len |
    pose``; the header's ``nbytes`` high byte is 0, its low byte is ``L``.
    """
    pose = Pose(x=x, y=y, theta=theta).SerializeToString()
    return _mmi_frame(tm.MMI_POSE, bytes([len(pose)]) + pose)


def test_pose_frame_header_matches_the_device_layout():
    """The helper's framing is the wire layout: 0x55aa, len from 12, L | pose_len."""
    frame = _pose_frame(1, 2, 3)
    assert frame[:2] == b"\x55\xaa"
    assert struct.unpack(">H", frame[6:8])[0] == len(frame) - 12
    assert frame[10] == 0x6C
    assert frame[17:22] == b"\x00" * 5
    assert frame[22] == frame[23] + 1


def test_decode_mmi_frame_pose():
    frame = _pose_frame(-387, -128, 2772)
    assert tm.decode_mmi_frame(frame) == ("pose", -387, -128, 2772)


@pytest.mark.parametrize(
    ("pose", "frame_len"),
    [
        ((50, -40, -2500), 35),
        ((-60, -100, -1500), 36),
        ((-300, -500, 2800), 37),
    ],
)
def test_decode_mmi_frame_every_pose_length(pose, frame_len):
    """A Pose serialises to 7, 8 or 9 bytes by magnitude; each length decodes."""
    frame = _pose_frame(*pose)
    assert len(frame) == frame_len
    assert tm.decode_mmi_frame(frame) == ("pose", *pose)


def test_decode_mmi_frame_keepalive_has_no_pose():
    """The 27-byte 0x6c frames are keepalives (sub ``01 01``) carrying no pose."""
    keepalive = _mmi_frame(tm.MMI_POSE, b"", clear_type=1)
    assert len(keepalive) == 27
    assert tm.decode_mmi_frame(keepalive) is None


def test_decode_mmi_frame_rejects_inconsistent_length_prefixes():
    """``L`` must be ``pose_len + 1``; anything else is not a pose body."""
    frame = bytearray(_pose_frame(1, 2, 3))
    frame[22] += 1
    assert tm.decode_mmi_frame(bytes(frame)) is None


def test_decode_mmi_frame_rejects_bad_declared_length():
    frame = bytearray(_pose_frame(1, 2, 3))
    frame[7] += 1
    assert tm.decode_mmi_frame(bytes(frame)) is None


def test_decode_mmi_frame_rejects_non_tuya():
    assert tm.decode_mmi_frame(b"not a frame") is None
    assert tm.decode_mmi_frame(b"") is None


def test_decode_mmi_frame_ignores_other_channels():
    frame = bytearray(_pose_frame(1, 2, 3))
    frame[10] = 0x67  # trail channel, not pose
    assert tm.decode_mmi_frame(bytes(frame)) is None


def test_build_connect_params_full_session():
    thing = SimpleNamespace(
        partner_identity=_PARTNER, sid=_SID, uid="eh-100000001",
        ecode=_ECODE.encode(), mqtt_url="ssl://m1-us.iotbing.com:8883",
    )
    params = tm.build_connect_params(thing, "eb00112233445566778899", "a" * 44)
    assert params is not None
    assert params.host == "m1-us.iotbing.com"
    assert params.port == 8883
    assert params.username == tm.build_username(_PARTNER, _SID, _ECODE)
    assert params.password == _PASSWORD
    assert params.sub_topic == "m/m/i/eb00112233445566778899"
    assert params.will_topic == "tuya/smart/will"
    assert "ANDROID" in params.will_payload


def test_build_connect_params_incomplete_session_returns_none():
    thing = SimpleNamespace(partner_identity=None, sid=_SID, uid="eh-1", ecode=b"x")
    assert tm.build_connect_params(thing, "dev", "a" * 44) is None


def test_random_device_id44_length():
    did = tm.random_device_id44()
    assert len(did) == 44
    assert all(c in "0123456789abcdef" for c in did)


def test_on_frame_taps_every_payload_before_decode():
    """The optional on_frame hook receives every raw m/m/i payload (any channel),
    while on_pose still fires only for a decodable 0x6c pose. Lets capture tooling
    record other channels (e.g. 0x67 trail) without a production decoder."""
    params = SimpleNamespace()  # unused by _handle_message
    poses, frames = [], []
    sub = tm.TuyaMobileMQTT(
        params,
        on_pose=lambda x, y, t: poses.append((x, y, t)),
        on_frame=frames.append,
    )
    pose = _pose_frame(-387, -128, 2772)
    trail = bytearray(_pose_frame(1, 2, 3))
    trail[10] = 0x67  # a non-pose channel
    sub._handle_message(None, None, SimpleNamespace(payload=pose))
    sub._handle_message(None, None, SimpleNamespace(payload=bytes(trail)))
    # on_frame saw both raw payloads; on_pose only the decodable pose.
    assert frames == [pose, bytes(trail)]
    assert poses == [(-387, -128, 2772)]


def test_frame_debug_log_carries_no_payload_bytes(caplog):
    """The per-frame line names length, channel and offset, never body bytes."""
    sub = tm.TuyaMobileMQTT(SimpleNamespace(), on_pose=lambda *a: None)
    frame = _mmi_frame(tm.MMI_ROOM_NAME, b"\x0b\x12\x09Bedroom 2", offset=24)
    with caplog.at_level(logging.DEBUG, logger=tm.__name__):
        sub._handle_message(None, None, SimpleNamespace(payload=frame))
        sub._handle_message(None, None, SimpleNamespace(payload=b"junk"))
    assert f"{len(frame)} bytes, channel 0x6a, offset 24" in caplog.text
    assert frame[23:].hex() not in caplog.text
    assert frame[:20].hex() not in caplog.text
    assert b"junk".hex() not in caplog.text


@pytest.mark.parametrize(
    "record",
    [b"\x08" + b"\xff" * 11 + b"\x01", b"\x08\xff\xff"],
    ids=["past-the-10-byte-cap", "cut-off-by-the-record-end"],
)
def test_a_malformed_varint_rejects_the_record(record):
    with pytest.raises(ValueError):
        tm._parse_fields(record)


def test_on_frame_absent_is_safe():
    """No on_frame supplied → messages still decode to poses without error."""
    poses = []
    sub = tm.TuyaMobileMQTT(SimpleNamespace(), on_pose=lambda x, y, t: poses.append((x, y, t)))
    sub._handle_message(None, None, SimpleNamespace(payload=_pose_frame(5, 6, 7)))
    assert poses == [(5, 6, 7)]


def test_start_verifies_the_broker_certificate():
    """The MQTT username embeds the live Tuya `sid`, so the peer MUST be verified.

    HA's client_context() verifies the certificate and hostname and is
    lru_cached, so it does no blocking disk I/O after the first call, unlike
    ssl.create_default_context(). The broker serves a publicly trusted
    certificate for *.iotbing.com.
    """
    params = tm.ConnectParams(
        host="m1-us.iotbing.com", port=8883, client_id="c", username="u",
        password="p", will_topic="tuya/smart/will", will_payload="{}",
        sub_topic="m/m/i/dev",
    )
    sub = tm.TuyaMobileMQTT(params, on_pose=lambda *a: None)
    fake_client = MagicMock()
    with patch.object(tm.mqtt, "Client", return_value=fake_client), \
         patch.object(ssl, "create_default_context",
                      side_effect=AssertionError("create_default_context is blocking")):
        sub.start()
    ctx = fake_client.tls_set_context.call_args[0][0]
    assert ctx.verify_mode == ssl.CERT_REQUIRED, "broker cert must be verified"
    assert ctx.check_hostname is True, "hostname must be checked"
    fake_client.connect_async.assert_called_once()


def test_start_ssl_context_is_cached_so_it_never_blocks_the_loop():
    """client_context() is cached, so building the TLS context never blocks the loop."""
    assert client_context() is client_context()


# ── Liveness counters (the diagnostics evidence path) ────────────────


def test_connack_and_subscribe_are_recorded():
    """CONNACK rc alone does not prove delivery — SUBACK does, so both are kept."""
    sub = tm.TuyaMobileMQTT(
        SimpleNamespace(sub_topic="m/m/i/dev"), on_pose=lambda *a: None
    )
    assert sub.connack_rc is None
    assert sub.subscribed is False

    sub._handle_connect(MagicMock(), None, None, 0)
    assert sub.connack_rc == 0
    assert sub.subscribed is False  # not until the broker SUBACKs

    sub._handle_subscribe(None, None, 1, [0])
    assert sub.subscribed is True


def test_failed_connack_clears_subscribed():
    """A rejected reconnect must not keep reporting the old subscription."""
    sub = tm.TuyaMobileMQTT(
        SimpleNamespace(sub_topic="m/m/i/dev"), on_pose=lambda *a: None
    )
    sub._handle_subscribe(None, None, 1, [0])
    sub._handle_connect(MagicMock(), None, None, 4)
    assert sub.connack_rc == 4
    assert sub.subscribed is False


def test_frame_counter_and_timestamp_track_every_payload():
    """Counts EVERY m/m/i frame, decodable or not: a device that stopped
    publishing and one whose frames fail to decode look identical otherwise."""
    sub = tm.TuyaMobileMQTT(SimpleNamespace(), on_pose=lambda *a: None)
    assert sub.frames == 0
    assert sub.last_frame_ts is None

    before = time.time()
    sub._handle_message(None, None, SimpleNamespace(payload=_pose_frame(1, 2, 3)))
    sub._handle_message(None, None, SimpleNamespace(payload=b"junk"))

    assert sub.frames == 2
    assert sub.last_frame_ts >= before


# ---------------------------------------------------------------------------
# decode_trail_frame — the 0x67 PATH channel
#
# Point words are hand-encoded bitfields (type<<30 | sy<<29 | |Y|<<15 | sx<<14 | |X|),
# independent of the decoder under test.
# ---------------------------------------------------------------------------

# 3 points, byte-offset 24: (-40, -120, transit), (-40, -110), (-30, -110).
_TRAIL_THREE = _mmi_frame(
    tm.MMI_PATH, bytes.fromhex("603c4028 20374028 2037401e"), offset=24
)
# 1 point, byte-offset 48: (75, -110).
_TRAIL_ONE = _mmi_frame(tm.MMI_PATH, bytes.fromhex("2037004b"), offset=48)
# A body-less clear_type=1 buffer-reset marker (byte 11 == 1, nbytes == 0).
_TRAIL_RESET = _mmi_frame(tm.MMI_PATH, b"", clear_type=1)


def test_decode_trail_frame_decodes_sign_magnitude_points():
    """Points are 32-bit BE bitfields: sign-magnitude Y then X, 0.5 cm units.

    Negative coordinates are the discriminator — a two's-complement or
    unsigned reading of these same bytes produces wildly different values.
    """
    offset, pts = tm.decode_trail_frame(_TRAIL_THREE)
    assert offset == 24
    assert pts == [(-40, -120, 1), (-40, -110, 0), (-30, -110, 0)]


def test_decode_trail_frame_positive_x_and_offset():
    """A positive X decodes without the sign bit, and offset is the u32 at 17..20."""
    offset, pts = tm.decode_trail_frame(_TRAIL_ONE)
    assert offset == 48
    assert pts == [(75, -110, 0)]


def test_decode_trail_frame_type_bits_mark_transit():
    """Bits 31..30 carry the point type; 1 marks a transit (undock/return) leg."""
    _, pts = tm.decode_trail_frame(_TRAIL_THREE)
    assert [t for _, _, t in pts] == [1, 0, 0]


def test_decode_trail_frame_reset_marker_has_no_points():
    """The body-less clear_type=1 marker decodes to an empty point list, not None."""
    assert tm.decode_trail_frame(_TRAIL_RESET) == (0, [])


def test_decode_trail_frame_rejects_other_channels():
    """Only channel 0x67 is a trail frame."""
    other = bytearray(_TRAIL_ONE)
    other[10] = 0x6C  # POSE
    assert tm.decode_trail_frame(bytes(other)) is None


def test_decode_trail_frame_rejects_short_and_unframed():
    """Truncated payloads and non-55aa frames are rejected, never raised on."""
    assert tm.decode_trail_frame(_TRAIL_ONE[:20]) is None
    bad = bytearray(_TRAIL_ONE)
    bad[0] = 0x00
    assert tm.decode_trail_frame(bytes(bad)) is None


def test_decode_trail_frame_places_with_the_pose_transform():
    """The decode's whole point: a trail point is in the POSE's frame and unit.

    ``(-40, -120)`` in 0.5 cm dock-relative units is 20 cm left of and 60 cm
    below the dock: 4 and 12 cells on a 5 cm grid. This is what lets the
    coordinator place trail points with ``_legacy_pose_to_pixel`` unchanged,
    with no anchoring and no anisotropic scale.
    """
    _, pts = tm.decode_trail_frame(_TRAIL_THREE)
    x, y, _ = pts[0]
    assert x / 10 == pytest.approx(-4.0)  # cells, at 10 units per 5 cm cell
    assert y / 10 == pytest.approx(-12.0)


# ---------------------------------------------------------------------------
# Map-metadata channels
#
# Fixtures are synthetic frames in the device's record layout: a body is a
# sequence of varint-length-prefixed protobuf records.
# ---------------------------------------------------------------------------


def _varint(value: int) -> bytes:
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        out.append(byte | (0x80 if value else 0))
        if not value:
            return bytes(out)


def _zigzag(value: int) -> int:
    return (value << 1) ^ (value >> 31)


def _record(*fields: tuple[int, int]) -> bytes:
    """One length-prefixed record of varint ``(field, value)`` pairs."""
    rec = b"".join(_varint(field << 3) + _varint(value) for field, value in fields)
    return _varint(len(rec)) + rec


def _sint_record(*values: int) -> bytes:
    """One record of zigzagged fields ``1..n``; a zero is omitted, as protobuf does."""
    return _record(*((i, _zigzag(v)) for i, v in enumerate(values, 1) if v))


_ROOM_NAMES = {0: "Room A", 1: "Room B", 2: "Room C", 3: "Room D", 4: "Room E", 5: "Room F"}


def _room_name_body() -> bytes:
    body = b""
    for room_id, name in _ROOM_NAMES.items():
        rec = RoomParams.Room(id=room_id, name=name).SerializeToString()
        body += _varint(len(rec)) + rec
    return body


_META_ROOM_NAME = _mmi_frame(tm.MMI_ROOM_NAME, _room_name_body())
# width, height, origin_x, origin_y, dock_x, dock_y as LE uint32.
_META_PARAM = _mmi_frame(tm.MMI_PARAM, struct.pack("<6I", 120, 180, 400, 1100, 380, 1120))
# x, y, theta zigzagged; type 2 plain.
_META_DOCK_POSE = _mmi_frame(
    tm.MMI_DOCK_POSE,
    _record((1, _zigzag(380)), (2, _zigzag(1120)), (3, _zigzag(1571)), (4, 2)),
)


def test_mmi_frame_body_splits_channel_offset_body():
    """The header split matches the vendor's own parser field-for-field."""
    channel, offset, body = tm.mmi_frame_body(_META_PARAM)
    assert channel == tm.MMI_PARAM
    assert offset == 0
    assert len(body) == 24


def test_mmi_frame_body_rejects_unframed():
    assert tm.mmi_frame_body(b"\x00\x01\x02") is None


def test_decode_room_names_includes_room_id_zero():
    """Room id 0 is REAL and must survive protobuf's default-omission.

    Room A is room 0, so its record carries no id field at all. A decoder
    that treats a missing/zero id as "no room" silently loses a whole room.
    """
    _, _, body = tm.mmi_frame_body(_META_ROOM_NAME)
    assert body[:2] == b"\x08\x12"  # room 0: length 8, then field 2 (name) first
    names = tm.decode_room_names(body)
    assert names == _ROOM_NAMES
    assert 0 in names  # explicitly: not dropped, not falsy-tested away


def test_decode_map_param_is_little_endian():
    """0x64 is six LE uint32 — the one metadata channel that is not protobuf.

    """
    _, _, body = tm.mmi_frame_body(_META_PARAM)
    assert tm.decode_map_param(body) == {
        "width": 120,
        "height": 180,
        "origin_x": 400,
        "origin_y": 1100,
        "dock_x": 380,
        "dock_y": 1120,
    }


def test_decode_map_param_rejects_short_body():
    assert tm.decode_map_param(b"\x00" * 8) is None


def test_decode_dock_pose_is_zigzagged():
    """0x75 is zigzagged sint32; theta is milliradians and type is DockType."""
    _, _, body = tm.mmi_frame_body(_META_DOCK_POSE)
    assert tm.decode_dock_pose(body) == {
        "x": 380,
        "y": 1120,
        "theta": 1571,
        "type": 2,  # DUST_COLLECTOR
    }


def test_decode_dock_pose_empty_body_is_none():
    assert tm.decode_dock_pose(b"") is None


# --- 0x70 / 0x71 / 0x73 per-room settings ---------------------------------------------------
# 0x70 rows: {1: zigzag id, 2: water + 1, 3: fan + 1, 4: zigzag times, 5: zigzag order}.
# Room 0 omits field 1; room 1 has fan 2, room 2 order 1, the rest defaults.
_CUSTOM_ROWS = [
    (0, 1, 1, 2, -1),
    (1, 1, 3, 1, -1),
    (2, 1, 1, 1, 1),
    (3, 1, 1, 1, -1),
    (4, 1, 1, 1, -1),
    (5, 1, 1, 1, -1),
]
_META_CUSTOM_ROOM = _mmi_frame(
    tm.MMI_CUSTOM_ROOM,
    b"".join(
        _record(
            *(((1, _zigzag(rid)),) if rid else ()),
            (2, water),
            (3, fan),
            (4, _zigzag(times)),
            (5, _zigzag(order)),
        )
        for rid, water, fan, times, order in _CUSTOM_ROWS
    ),
)
# 0x73 rows: {1: zigzag id, 2: zigzag order}, room 0 again without field 1.
_META_GLOBAL_ROOM = _mmi_frame(
    tm.MMI_GLOBAL_ROOM,
    b"".join(
        _record(*(((1, _zigzag(rid)),) if rid else ()), (2, _zigzag(order)))
        for rid, *_, order in _CUSTOM_ROWS
    ),
)
_META_CUSTOM_ENABLED = _mmi_frame(tm.MMI_CUSTOM_ROOMS_ENABLED, _record((1, 1)))


def test_decode_room_custom_ids_are_zigzag_and_levels_offset():
    """0x70 is the blob's ``MapCustomRoom`` rows, live — and its ids are ZIGZAG.

    The wire ids read 0, 2, 4, 6, 8, 10 for rooms 0..5. Reading them plain (the
    rule that is correct on 0x6a and 0x65) produces the room set {0,1,2,3,4,5}
    shifted onto {0,2,4,6,8,10} and silently attaches every setting to the wrong
    room. Water and fan are stored one higher than they read, so an absent field
    means -1, "not set", not 0.
    """
    _, _, body = tm.mmi_frame_body(_META_CUSTOM_ROOM)
    rooms = tm.decode_room_custom(body)
    assert sorted(rooms) == [0, 1, 2, 3, 4, 5]
    assert rooms[0] == {
        "id": 0,
        "water_level": 0,
        "fan_speed": 0,
        "clean_times": 2,
        "clean_order": -1,
    }
    # Room 1 is the one room with a non-default fan, room 2 the one with a
    # pinned cleaning position.
    assert rooms[1]["fan_speed"] == 2
    assert rooms[2]["clean_order"] == 1
    assert [rooms[i]["clean_order"] for i in (0, 1, 3, 4, 5)] == [-1] * 5


def test_decode_room_clean_order_agrees_with_the_custom_rows():
    """0x73 carries the same order column as 0x70 field 5, from a separate write.

    They agree here because nothing has changed between the two frames; the point
    of consuming both is that a reorder in the app moves the ``globalRooms``
    table, and that is the one this channel reports.
    """
    _, _, custom_body = tm.mmi_frame_body(_META_CUSTOM_ROOM)
    _, _, order_body = tm.mmi_frame_body(_META_GLOBAL_ROOM)
    orders = tm.decode_room_clean_order(order_body)
    assert orders == {0: -1, 1: -1, 2: 1, 3: -1, 4: -1, 5: -1}
    assert orders == {
        rid: row["clean_order"] for rid, row in tm.decode_room_custom(custom_body).items()
    }


def test_decode_custom_rooms_enabled_is_the_master_switch():
    """0x71 is the enable bit 0x70 does not carry; a bodyless frame says nothing."""
    _, _, body = tm.mmi_frame_body(_META_CUSTOM_ENABLED)
    assert tm.decode_custom_rooms_enabled(body) is True
    # Not False: "the frame carried no record" and "the user turned it off" are
    # different answers, and only one of them should overwrite what we hold.
    assert tm.decode_custom_rooms_enabled(b"") is None


def test_room_setting_decoders_tolerate_garbage():
    """Metadata must never be able to break the pose/trail stream."""
    assert not tm.decode_room_custom(b"\xff\xff\xff")
    assert not tm.decode_room_clean_order(b"\xff\xff\xff")
    assert tm.decode_custom_rooms_enabled(b"\xff\xff\xff") is None


def test_decode_room_polygons_tolerates_garbage():
    """A malformed body yields nothing rather than raising — metadata must never
    be able to break the pose/trail stream."""
    assert not tm.decode_room_polygons(b"\xff\xff\xff")
    assert not tm.decode_room_names(b"\xff\xff\xff")


# --- 0x68 / 0x69 restricted geometry --------------------------------------------------------
# Records of zigzagged fields 1..8 (quad corners) and 1..4 (wall endpoints).
_META_FORBIDDEN_BODY = _sint_record(700, 500, 1000, 500, 1000, 800, 700, 800)
_META_WALL_BODY = (
    _sint_record(900, 120, 880, -300)
    + _sint_record(50, 100, 60, 850)
    + _sint_record(-450, -480, -440, 30)
)


def test_decode_forbidden_zones_is_a_quad_not_a_bbox():
    """0x68 carries four independent corners.

    The shape is a quadrilateral on the wire, which is what makes a ROTATED
    no-go zone expressible at all — the axis-aligned box is the card's
    limitation, not the device's.
    """
    assert _META_FORBIDDEN_BODY[:3] == bytes([0x18, 0x08, 0xF8])  # field 1 = zz(700)
    zones = tm.decode_forbidden_zones(_META_FORBIDDEN_BODY)
    assert zones == [[(700, 500), (1000, 500), (1000, 800), (700, 800)]]


def test_decode_virtual_walls_keeps_endpoints_unsorted():
    """0x69 is one 2-point segment per wall, sign and order as stored."""
    assert tm.decode_virtual_walls(_META_WALL_BODY) == [
        [(900, 120), (880, -300)],
        [(50, 100), (60, 850)],
        [(-450, -480), (-440, 30)],
    ]


def test_decode_point_records_keeps_a_zero_coordinate():
    """Protobuf omits a 0, so a corner on the origin has no field for it.

    Skipping the record instead of defaulting would silently drop the zone.
    """
    # {1: 0(omitted), 2: 2->1, 3: 4->2, 4: 6->3} as one 2-point record.
    body = bytes.fromhex("06 1002 1804 2006")
    assert tm.decode_virtual_walls(body) == [[(0, 1), (2, 3)]]


def test_decode_zone_channels_tolerate_garbage():
    assert not tm.decode_forbidden_zones(b"\xff\xff\xff")
    assert not tm.decode_virtual_walls(b"\xff\xff\xff")
