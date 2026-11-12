"""Tuya mobile-MQTT subscriber for the legacy live robot pose/trail.

Plaintext ``55 aa`` frames on ``m/m/i/<devId>``; the CONNECT is derived from the
Thing-SDK login session, whose ``sid`` expires after ~2h, so the caller must
re-derive and reconnect periodically. Best-effort: failures are debug no-ops.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from collections.abc import Callable
from dataclasses import dataclass

import paho.mqtt.client as mqtt
from homeassistant.util.ssl import client_context

from ..const import TUYA_THING_CHKEY, TUYA_THING_CLIENT_ID, TUYA_THING_SALT
from ..proto.cloud.common_pb2 import Pose
from ..utils import decode_varint, decode_zigzag

_LOGGER = logging.getLogger(__name__)

_PKG = "com.oceanwing.battery.cam"
_APP_ID = TUYA_THING_CLIENT_ID
_CLIENTID_SALT = "sdkfasodifca"
_DEFAULT_MQTT_HOST = "m1-us.iotbing.com"
_MQTT_PORT = 8883


def _md5hex(s: str | bytes) -> str:
    return hashlib.md5(s if isinstance(s, bytes) else s.encode()).hexdigest()


def build_username(partner_id: str, sid: str, ecode: str) -> str:
    """Build the signed mobile-MQTT username."""
    tail = _md5hex(_md5hex(_APP_ID) + ecode)[-16:]
    return f"{partner_id}_v1_{_APP_ID}_{TUYA_THING_CHKEY}_mb_{sid}{tail}"


def build_password(ecode: str) -> str:
    """Build the mobile-MQTT password: middle-16 of md5hex(md5hex(SALT)+ecode)."""
    return _md5hex(_md5hex(TUYA_THING_SALT) + ecode)[8:24]


def build_client_id(device_id44: str, uid: str) -> str:
    return f"{_PKG}_mb_{device_id44}_{_md5hex(uid + _CLIENTID_SALT)}_DEFAULT"


def _host_from_url(mqtt_url: str | None) -> str:
    """Extract the broker host from a ``ssl://host:port`` ``mobileMqttsUrl``."""
    if not mqtt_url:
        return _DEFAULT_MQTT_HOST
    host = mqtt_url.split("://", 1)[-1].split("/", 1)[0].split(":", 1)[0]
    return host or _DEFAULT_MQTT_HOST


# Channel ids of the ``m/m/i`` stream.
MMI_PARAM = 0x64
MMI_ROOM = 0x65
MMI_PATH = 0x67
MMI_FORBIDDEN_ZONES = 0x68
MMI_VIRTUAL_WALL = 0x69
MMI_BAN_MOP_ZONES = 0x6E
MMI_ROOM_NAME = 0x6A
MMI_POSE = 0x6C
MMI_CUSTOM_ROOM = 0x70
MMI_CUSTOM_ROOMS_ENABLED = 0x71
MMI_GLOBAL_ROOM = 0x73
MMI_DOCK_POSE = 0x75

_MMI_HEADER = 23  # 55aa .. channel@10, clear_type@11, offset@17, nbytes@21, body@23


def decode_mmi_frame(payload: bytes) -> tuple[str, int, int, int] | None:
    """Decode a 0x6c live-pose frame into ``("pose", x, y, theta)`` or ``None``.

    x/y in 0.5 cm, theta in mrad; the body is a bare length-prefixed
    :class:`Pose`, so offset 22 is ``pose_len + 1``, not a protobuf tag.
    """
    # 24 header/prefix bytes + a (possibly empty) Pose + 4-byte trailer.
    if len(payload) < 28 or payload[0] != 0x55 or payload[1] != 0xAA:
        return None
    if payload[10] != MMI_POSE:
        return None
    if ((payload[6] << 8) | payload[7]) != len(payload) - 12:
        return None
    if payload[17:22] != b"\x00\x00\x00\x00\x00":
        return None
    length, pose_len = payload[22], payload[23]
    # A Pose never reaches 128 bytes, so both prefixes are single-byte varints;
    # a continuation bit here means this is not a pose.
    if length >= 0x80 or pose_len >= 0x80 or length != pose_len + 1:
        return None
    if 24 + pose_len > len(payload) - 4:
        return None
    try:
        p = Pose.FromString(payload[24:24 + pose_len])
    except Exception:  # noqa: BLE001
        return None
    return ("pose", p.x, p.y, p.theta)


def decode_trail_frame(payload: bytes) -> tuple[int, list[tuple[int, int, int]]] | None:
    """Decode a 0x67 dense trail frame into ``(offset, [(x, y, type), ...])``.

    Each point is ONE 32-bit BE bitfield (type, sy, Y, sx, X), sign-magnitude,
    0.5 cm dock-relative — the pose's own frame, so no anchoring. type: 0
    cleaning, 1 transit. offset is a cumulative BYTE offset.
    """
    if len(payload) < 27 or payload[0] != 0x55 or payload[1] != 0xAA:
        return None
    if payload[10] != MMI_PATH:
        return None
    offset = int.from_bytes(payload[17:21], "big")
    nbytes = (payload[21] << 8) | payload[22]
    data = payload[23:23 + nbytes]
    pts: list[tuple[int, int, int]] = []
    for i in range(0, len(data) - 3, 4):
        word = int.from_bytes(data[i:i + 4], "big")
        y_mag = (word >> 15) & 0x3FFF
        x_mag = word & 0x3FFF
        y = -y_mag if (word >> 29) & 1 else y_mag
        x = -x_mag if (word >> 14) & 1 else x_mag
        pts.append((x, y, (word >> 30) & 0x3))
    return offset, pts


def _read_varint(buf: bytes, i: int) -> tuple[int, int]:
    """:func:`decode_varint`, but a varint cut off by the buffer end raises.

    A record whose length prefix lies is dropped rather than read short.
    """
    value, end = decode_varint(buf, i)
    if end == i or buf[end - 1] & 0x80:
        raise ValueError("truncated varint")
    return value, end


def _parse_fields(buf: bytes) -> dict[int, list]:
    """Parse a flat protobuf message into ``{field_number: [values]}``.

    Varints stay raw; an unknown wire type aborts the record.
    """
    out: dict[int, list] = {}
    i = 0
    value: int | bytes
    while i < len(buf):
        key, i = _read_varint(buf, i)
        field, wire = key >> 3, key & 7
        if wire == 0:
            value, i = _read_varint(buf, i)
        elif wire == 2:
            length, i = _read_varint(buf, i)
            value, i = buf[i:i + length], i + length
        else:
            break
        out.setdefault(field, []).append(value)
    return out


def mmi_frame_body(payload: bytes) -> tuple[int, int, bytes] | None:
    """Split an ``m/m/i`` frame into ``(channel, offset, body)``, else ``None``.

    A body-less buffer-reset marker yields an empty body, not None.
    """
    if len(payload) < _MMI_HEADER or payload[0] != 0x55 or payload[1] != 0xAA:
        return None
    channel = payload[10]
    offset = int.from_bytes(payload[17:21], "big")
    nbytes = (payload[21] << 8) | payload[22]
    return channel, offset, payload[_MMI_HEADER:_MMI_HEADER + nbytes]


def _records(body: bytes) -> list[bytes]:
    """Split a body into its varint-length-prefixed protobuf records.

    A metadata body is a bare sequence of records, not one message.
    """
    out: list[bytes] = []
    i = 0
    while i < len(body):
        try:
            length, i = _read_varint(body, i)
        except ValueError:
            break
        if length == 0 or i + length > len(body):
            break
        out.append(body[i:i + length])
        i += length
    return out


def decode_room_names(body: bytes) -> dict[int, str]:
    """Decode 0x6A ``ROOM_NAME`` into ``{room_id: name}``.

    Plain varint id here (zigzagged on 0x70/0x73). Room id 0 carries no id
    field at all: id 0 is a real room id, not a missing field.
    """
    rooms: dict[int, str] = {}
    for rec in _records(body):
        fields = _parse_fields(rec)
        name = fields.get(2, [b""])[0]
        if not isinstance(name, bytes):
            continue
        room_id = fields.get(1, [0])[0]
        if not isinstance(room_id, int):
            continue
        try:
            rooms[room_id] = name.decode("utf-8")
        except UnicodeDecodeError:
            continue
    return rooms


def decode_room_custom(body: bytes) -> dict[int, dict[str, int]]:
    """Decode 0x70 ``CUSTOM_ROOM`` into ``{room_id: {fan_speed, water_level, ...}}``.

    Zigzagged id here (plain on 0x6a/0x65); ``water``/``fan`` are stored one
    higher, so an absent field means -1 ("not set"), not 0; room id 0 is real
    and carries no id field.
    """
    rooms: dict[int, dict[str, int]] = {}
    for rec in _records(body):
        fields = _parse_fields(rec)
        if not fields or not all(
            isinstance(values[0], int) for values in fields.values()
        ):
            continue
        room_id = decode_zigzag(fields.get(1, [0])[0])
        rooms[room_id] = {
            "id": room_id,
            "water_level": fields.get(2, [0])[0] - 1,
            "fan_speed": fields.get(3, [0])[0] - 1,
            "clean_times": decode_zigzag(fields.get(4, [0])[0]),
            "clean_order": decode_zigzag(fields.get(5, [0])[0]),
        }
    return rooms


def decode_room_clean_order(body: bytes) -> dict[int, int]:
    """Decode 0x73 (global room order) into ``{room_id: clean_order}``.

    Zigzagged; -1 is "no explicit position", a real order is 1-based.
    """
    orders: dict[int, int] = {}
    for rec in _records(body):
        fields = _parse_fields(rec)
        if not fields or not all(
            isinstance(values[0], int) for values in fields.values()
        ):
            continue
        orders[decode_zigzag(fields.get(1, [0])[0])] = decode_zigzag(fields.get(2, [0])[0])
    return orders


def decode_custom_rooms_enabled(body: bytes) -> bool | None:
    """Decode 0x71 (custom rooms enabled), the master switch.

    Off, the robot ignores the overrides it stores. ``None`` is not ``False``.
    """
    for rec in _records(body):
        fields = _parse_fields(rec)
        value = fields.get(1, [None])[0]
        if isinstance(value, int):
            return bool(value)
    return None


def decode_room_polygons(body: bytes) -> dict[int, list[tuple[int, int]]]:
    """Decode 0x65 ``ROOM`` into ``{room_id: [(x, y), ...]}`` outline polygons.

    Vertices are zigzagged 0.5 cm, in the pose frame.
    """
    polys: dict[int, list[tuple[int, int]]] = {}
    for rec in _records(body):
        fields = _parse_fields(rec)
        room_id = fields.get(1, [0])[0]
        if not isinstance(room_id, int):
            continue
        points: list[tuple[int, int]] = []
        for raw in fields.get(2, []):
            if not isinstance(raw, bytes):
                continue
            pt = _parse_fields(raw)
            x = pt.get(1, [0])[0]
            y = pt.get(2, [0])[0]
            if isinstance(x, int) and isinstance(y, int):
                points.append((decode_zigzag(x), decode_zigzag(y)))
        if points:
            polys[room_id] = points
    return polys


def _decode_point_records(body: bytes, points: int) -> list[list[tuple[int, int]]]:
    """Decode records of ``{1..2n: sint32}`` into one ``(x, y)`` list each.

    Zigzagged, in the blob's 0.5 cm frame. A missing field means 0, not a bad
    record — else a zone cornered on the origin vanishes.
    """
    out: list[list[tuple[int, int]]] = []
    for rec in _records(body):
        fields = _parse_fields(rec)
        if not fields or max(fields) > points * 2:
            continue
        coords: list[int] = []
        for index in range(1, points * 2 + 1):
            value = fields.get(index, [0])[0]
            if not isinstance(value, int):
                coords = []
                break
            coords.append(decode_zigzag(value))
        if len(coords) == points * 2:
            out.append([(coords[i], coords[i + 1]) for i in range(0, len(coords), 2)])
    return out


def decode_forbidden_zones(body: bytes) -> list[list[tuple[int, int]]]:
    """Decode 0x68 ``FORBIDDEN_ZONES``: one 4-corner quad per zone, 0.5 cm units.

    A quad, not a bounding box: the corners are independent and may be rotated.
    """
    return _decode_point_records(body, 4)


def decode_virtual_walls(body: bytes) -> list[list[tuple[int, int]]]:
    """Decode 0x69 ``VIRTUAL_WALL``: one 2-point segment per wall, 0.5 cm units.

    The endpoints are an arbitrary line and must never be sorted into a box.
    """
    return _decode_point_records(body, 2)


def decode_map_param(body: bytes) -> dict[str, int] | None:
    """Decode 0x64 ``PARAM``: map dims, origin and dock as six LE uint32.

    Not protobuf; origin/dock are 0.5 cm offsets from the top-left cell.
    """
    if len(body) < 24:
        return None
    values = [int.from_bytes(body[i:i + 4], "little") for i in range(0, 24, 4)]
    return {
        "width": values[0],
        "height": values[1],
        "origin_x": values[2],
        "origin_y": values[3],
        "dock_x": values[4],
        "dock_y": values[5],
    }


def decode_dock_pose(body: bytes) -> dict[str, int] | None:
    """Decode 0x75 ``DOCK_POSE`` into ``{x, y, theta, type}``.

    Zigzagged; x/y 0.5 cm in the pose frame, theta mrad, type is ``DockType``.
    """
    for rec in _records(body):
        fields = _parse_fields(rec)
        if 1 not in fields or 2 not in fields:
            continue
        return {
            "x": decode_zigzag(fields[1][0]),
            "y": decode_zigzag(fields[2][0]),
            "theta": decode_zigzag(fields.get(3, [0])[0]),
            "type": fields.get(4, [0])[0],
        }
    return None


@dataclass
class ConnectParams:
    host: str
    port: int
    client_id: str
    username: str
    password: str
    will_topic: str
    will_payload: str
    sub_topic: str


def build_connect_params(thing_client, device_id: str, device_id44: str) -> ConnectParams | None:
    """Assemble the CONNECT params from a logged-in Thing client, or ``None``
    if the session lacks partnerIdentity / sid / uid / ecode."""
    partner = getattr(thing_client, "partner_identity", None)
    sid = getattr(thing_client, "sid", None)
    uid = getattr(thing_client, "uid", None)
    ecode_raw = getattr(thing_client, "ecode", None)
    if not (partner and sid and uid and ecode_raw):
        return None
    ecode = ecode_raw.decode() if isinstance(ecode_raw, (bytes, bytearray)) else str(ecode_raw)
    client_id = build_client_id(device_id44, uid)
    will = json.dumps({
        "clientId": client_id, "deviceType": "ANDROID", "message": "",
        "userName": f"{device_id44}_{_md5hex(uid + _CLIENTID_SALT)}",
    })
    return ConnectParams(
        host=_host_from_url(getattr(thing_client, "mqtt_url", None)),
        port=_MQTT_PORT,
        client_id=client_id,
        username=build_username(partner, sid, ecode),
        password=build_password(ecode),
        will_topic="tuya/smart/will",
        will_payload=will,
        sub_topic=f"m/m/i/{device_id}",
    )


class TuyaMobileMQTT:
    """Subscribe to the Tuya mobile broker and yield live robot poses.

    Callbacks fire on paho's network thread; the caller must marshal them.
    """

    def __init__(
        self,
        params: ConnectParams,
        on_pose: Callable[[int, int, int], None],
        on_connect_result: Callable[[int], None] | None = None,
        on_frame: Callable[[bytes], None] | None = None,
        on_trail: Callable[[int, list[tuple[int, int, int]]], None] | None = None,
        on_meta: Callable[[int, bytes], None] | None = None,
    ) -> None:
        self._params = params
        self._on_pose = on_pose
        self._on_connect_result = on_connect_result
        # Optional raw-payload hook, invoked before decoding.
        self._on_frame = on_frame
        self._on_trail = on_trail
        self._on_meta = on_meta
        self._client: mqtt.Client | None = None
        # Liveness evidence: never-connected vs not-subscribed vs silent.
        self.connack_rc: int | None = None
        self.subscribed: bool = False
        self.frames: int = 0
        self.last_frame_ts: float | None = None

    def start(self) -> None:
        """Create the paho client and begin connecting (non-blocking)."""
        p = self._params
        try:
            client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                                 client_id=p.client_id, protocol=mqtt.MQTTv311)
        except AttributeError:  # older paho
            client = mqtt.Client(client_id=p.client_id, protocol=mqtt.MQTTv311)
        client.username_pw_set(p.username, p.password)
        client.will_set(p.will_topic, p.will_payload, qos=1, retain=False)
        # The username embeds the live sid and the host is server-supplied, so
        # the peer MUST be verified — never CERT_NONE. This call is lru_cached.
        client.tls_set_context(client_context())
        client.on_connect = self._handle_connect
        client.on_subscribe = self._handle_subscribe
        client.on_message = self._handle_message
        client.reconnect_delay_set(min_delay=2, max_delay=60)
        self._client = client
        client.connect_async(p.host, p.port, keepalive=60)
        client.loop_start()
        _LOGGER.debug("Tuya mobile-MQTT connecting to %s:%d, topic %s",
                      p.host, p.port, p.sub_topic)

    def stop(self) -> None:
        """Disconnect and stop the network loop. **Blocking — never call this on
        the event loop.**

        ``loop_stop()`` joins paho's network thread, which ignores its
        terminate flag while parked in a blocking connect/TLS handshake.
        """
        if self._client is None:
            return
        try:
            # Disconnect before loop_stop so the DISCONNECT is flushed; the
            # other order drops the session and fires the LWT on every refresh.
            self._client.disconnect()
            self._client.loop_stop()
        except Exception:  # noqa: BLE001
            pass
        self._client = None

    def _handle_connect(self, client, userdata, flags, reason_code, properties=None):
        rc = int(getattr(reason_code, "value", reason_code))
        self.connack_rc = rc
        if rc != 0:
            self.subscribed = False
        if self._on_connect_result is not None:
            self._on_connect_result(rc)
        if rc == 0:
            client.subscribe(self._params.sub_topic, qos=1)
            _LOGGER.debug("Tuya mobile-MQTT connected; subscribed %s", self._params.sub_topic)
        else:
            _LOGGER.debug("Tuya mobile-MQTT CONNACK rc=%s (auth/session)", rc)

    def _handle_subscribe(self, client, userdata, mid, reason_codes=None, properties=None):
        """Record the SUBACK; CONNACK rc=0 alone only proves authentication."""
        self.subscribed = True
        _LOGGER.debug("Tuya mobile-MQTT SUBACK for %s", self._params.sub_topic)

    def _handle_message(self, client, userdata, msg):
        payload = msg.payload or b""
        self.frames += 1
        self.last_frame_ts = time.time()
        # The decode callbacks log only on success; this separates "nothing
        # delivered" from "delivered but undecodable". Header fields only: the
        # bodies carry the pose, map geometry and room names.
        if _LOGGER.isEnabledFor(logging.DEBUG):
            head = mmi_frame_body(payload)
            if head is None:
                _LOGGER.debug("Tuya mobile-MQTT frame: %d bytes, unframed", len(payload))
            else:
                _LOGGER.debug(
                    "Tuya mobile-MQTT frame: %d bytes, channel 0x%02x, offset %d",
                    len(payload), head[0], head[1],
                )
        if self._on_frame is not None:
            try:
                self._on_frame(msg.payload)
            except Exception:  # noqa: BLE001
                _LOGGER.debug("on_frame callback raised", exc_info=True)
        frame = decode_mmi_frame(msg.payload)
        if frame is not None:
            _kind, x, y, theta = frame
            try:
                self._on_pose(x, y, theta)
            except Exception:  # noqa: BLE001
                _LOGGER.debug("on_pose callback raised", exc_info=True)
            return
        if self._on_trail is not None:
            trail = decode_trail_frame(msg.payload)
            if trail is not None:
                try:
                    self._on_trail(trail[0], trail[1])
                except Exception:  # noqa: BLE001
                    _LOGGER.debug("on_trail callback raised", exc_info=True)
                return
        # Map metadata: a short burst after subscribe and on every map change.
        if self._on_meta is not None:
            meta = mmi_frame_body(msg.payload)
            if meta is not None and meta[2]:
                try:
                    self._on_meta(meta[0], meta[2])
                except Exception:  # noqa: BLE001
                    _LOGGER.debug("on_meta callback raised", exc_info=True)


def random_device_id44() -> str:
    """Generate a random 44-hex install id, unique per installation."""
    return os.urandom(22).hex()[:44]
