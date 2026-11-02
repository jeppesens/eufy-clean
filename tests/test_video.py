"""Tests for the robot camera stream: RTP/H.265 reader, control packets, stream manager."""

# pylint: disable=redefined-outer-name,protected-access

import asyncio
import base64
import shutil
import struct
import subprocess
import time
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.exceptions import HomeAssistantError

from custom_components.robovac_mqtt.api.commands import (
    build_command,
    build_video_manager_command,
)
from custom_components.robovac_mqtt.api.p2p import P2PError, P2PRefused, control, kcp
from custom_components.robovac_mqtt.api.p2p.framing import CMD_RTC, decode_frames
from custom_components.robovac_mqtt.api.p2p.video import (
    RtpHevcReader,
    VideoSession,
)
from custom_components.robovac_mqtt.api.parser import (
    _decode_raw_varints,
    _parse_video_manager_reply,
    update_state,
)
from custom_components.robovac_mqtt.camera import (
    EufyVideoCamera,
    _add_video_camera_when_supported,
)
from custom_components.robovac_mqtt.const import (
    VIDEO_MGR_STATE_SET,
    VIDEO_MGR_STREAM_OPEN,
    WORK_STATE_REMOTE_CTRL,
)
from custom_components.robovac_mqtt.models import VacuumState
from custom_components.robovac_mqtt.proto.cloud.common_pb2 import Switch
from custom_components.robovac_mqtt.utils import decode_varint
from custom_components.robovac_mqtt.video_stream import (
    FFMPEG_ARGS,
    RobotVideo,
    retry_delay,
)

START = b"\x00\x00\x00\x01"
SSRC = b"\x00\x00\x00\x0a"


_CLOUD = {
    "sessionId": "devid1700000000AbCdEfGh", "iceUfrag": "tEst", "icePassword": "FakeIcePassword0123456789",
    "aesKey": "00112233445566778899aabbccddeeff", "traceId": "0123456789abcdef0123456789abcdef",
    "uid": "eu0000000000000test",
}


def rtp(seq: int, payload: bytes, *, marker: bool = False, first_byte: int = 0x80) -> bytes:
    return bytes([first_byte, (0x80 if marker else 0) | 95]) + struct.pack(">HI", seq, 1000 + seq) + SSRC + payload


def frame(packet: bytes, header_len: int = 36) -> bytes:
    """A Tuya frame: a header of ``header_len`` bytes, the u32 packet length, the RTP packet."""
    head = bytes([3, 0, 1, 0, 0, 0, 0, 0]) + bytes(header_len - 8 - 4)
    return head + struct.pack("<I", len(packet)) + packet


def nal(kind: int, body: bytes) -> bytes:
    return bytes([kind << 1, 1]) + body  # H.265 NAL header: type in bits 1-6, layer 0, tid 1


def read_all(reader: RtpHevcReader, data: bytes, chunk: int | None = None) -> list[bytes]:
    pieces = [data] if chunk is None else [data[i : i + chunk] for i in range(0, len(data), chunk)]
    return [unit for piece in pieces for unit in reader.feed(piece)]


def test_single_nal_units_get_start_codes():
    vps, sps = nal(32, b"vps-data"), nal(33, b"sps-data")
    stream = frame(rtp(1, vps)) + frame(rtp(2, sps))
    assert read_all(RtpHevcReader(), stream) == [START + vps, START + sps]


def test_fragmentation_units_are_reassembled():
    original = nal(19, b"A" * 40 + b"B" * 40 + b"C" * 20)  # an IDR slice
    body = original[2:]
    header = bytes([49 << 1, 1])
    parts = [body[:40], body[40:80], body[80:]]
    fu_type = 19
    packets = [
        rtp(1, header + bytes([0x80 | fu_type]) + parts[0]),
        rtp(2, header + bytes([fu_type]) + parts[1]),
        rtp(3, header + bytes([0x40 | fu_type]) + parts[2], marker=True),
    ]
    out = read_all(RtpHevcReader(), b"".join(frame(p) for p in packets))
    assert out == [START + original]


def test_aggregation_packets_are_split():
    one, two = nal(39, b"sei"), nal(35, b"aud")
    payload = bytes([48 << 1, 1]) + struct.pack(">H", len(one)) + one + struct.pack(">H", len(two)) + two
    assert read_all(RtpHevcReader(), frame(rtp(1, payload))) == [START + one, START + two]


def test_header_length_varies_and_rtp_first_byte_is_not_trusted():
    """Key frames carry a longer Tuya header; later frames set extra bits in RTP byte 0."""
    a, b = nal(32, b"a" * 10), nal(1, b"b" * 10)
    stream = frame(rtp(1, a), header_len=36) + frame(rtp(2, b, first_byte=0xA8), header_len=30)
    assert read_all(RtpHevcReader(), stream) == [START + a, START + b]


def test_byte_at_a_time_feeding_gives_the_same_result():
    units = [nal(32, b"x" * 30), nal(33, b"y" * 30), nal(1, b"z" * 200)]
    stream = b"".join(frame(rtp(i + 1, u)) for i, u in enumerate(units))
    reader = RtpHevcReader()
    assert read_all(reader, stream, chunk=1) == [START + u for u in units]
    assert reader.packets == 3 and reader.gaps == 0


def test_a_lost_packet_drops_the_open_fragment_and_is_counted():
    header = bytes([49 << 1, 1])
    start = rtp(1, header + bytes([0x80 | 1]) + b"first-half")
    end = rtp(3, header + bytes([0x40 | 1]) + b"second-half", marker=True)  # seq 2 never arrived
    good = nal(1, b"next-frame")
    reader = RtpHevcReader()
    out = read_all(reader, frame(start) + frame(end) + frame(rtp(4, good)))
    assert out == [START + good]
    assert reader.gaps == 1


def test_garbage_before_the_first_frame_is_skipped():
    unit = nal(32, b"vps")
    assert read_all(RtpHevcReader(), b"\xde\xad\xbe\xef" * 5 + frame(rtp(1, unit))) == [START + unit]


def test_video_start_packets_are_auth_hello_caps_and_three_iocontrols():
    packets = control.video_prelude_packets("pw", "k" * 16) + control.video_start_packets()
    assert len(packets) == 6
    assert packets[0] == control.start_packets("pw", "k" * 16)[0]  # same auth packet
    parsed = [control.parse(p) for p in packets[1:]]
    assert [(p.type, p.sub_command) for p in parsed] == [
        (0, 0x0A), (0, 0x15), (0x10002, 9), (0x10003, 6), (0x10004, 0x40006),
    ]
    assert parsed[1].payload.endswith(b"}\x00") and b"capability_exchange_req" in parsed[1].payload
    assert parsed[2].payload == struct.pack("<II", 0, 4)  # HD keeps periodic keyframes flowing


def test_video_session_hands_nal_units_out_and_counts_as_connected():
    seen: list[bytes] = []
    session = VideoSession(
        on_nal=seen.append, host="127.0.0.1", local_key="k" * 16,
        device_id="dev", device_password="pw", cloud_session=_CLOUD,
    )
    assert set(session._extra_conversations()) == {kcp.CONV_VIDEO}
    unit = nal(32, b"vps")
    session._on_video_record(frame(rtp(1, unit)))
    assert seen == [START + unit]
    assert session._first_object.is_set()
    assert session.bytes_received > 0


def test_stream_commands_match_the_bytes_sent_to_a_real_robot():
    assert build_command("video_pass_enable") == {"181": "DgoECAIQARIGCgQKAggB"}
    assert build_command("video_stream_open") == {"181": "BgoECAMQAQ=="}
    assert build_command("video_stream_close") == {"181": "BgoECAQQAQ=="}


@pytest.mark.parametrize("enabled", [True, False])
def test_pass_enable_decodes_as_a_switch_value(enabled):
    """Decode the iOS schema's setting -> mgrState -> passEn, using protobuf's Switch.

    The extra wrapper used by the old command was accepted by the robot but
    protobuf treated its value as an unknown field, leaving passEn false.
    """
    raw = base64.b64decode(build_video_manager_command(2, pass_enable=enabled)["181"])
    length, pos = decode_varint(raw, 0)
    assert length == len(raw) - pos
    request = _decode_raw_varints(raw[pos:])
    setting = _decode_raw_varints(request[2])
    manager = _decode_raw_varints(setting[1])
    switch = Switch.FromString(manager[1])
    assert switch.value is enabled
    assert set(manager) == {1}  # never change the separate locked switch


@pytest.mark.parametrize(
    ("reply", "expected"),
    [
        ("DAoCCAMSBgoECgASAA==", (3, 0)),  # StreamOpen accepted (result absent = 0)
        ("DgoECAMYARIGCgQKABIA", (3, 1)),  # StreamOpen refused
        ("DAoCCAQSBgoECgASAA==", (4, 0)),  # StreamClose accepted
        ("not base64!", None),
        ("", None),
    ],
)
def test_video_manager_replies_parse(reply, expected):
    assert _parse_video_manager_reply(reply) == expected


def test_update_state_records_the_video_reply_with_a_timestamp():
    before = time.monotonic()
    _, changes = update_state(VacuumState(api_type="novel"), {"181": "DAoCCAMSBgoECgASAA=="})
    method, result, at = changes["video_response"]
    assert (method, result) == (3, 0) and at >= before


# -- the stream manager -------------------------------------------------------


@pytest.fixture
def coordinator():
    coord = MagicMock()
    coord.device_name = "Test Vac"
    coord.data = VacuumState(api_type="novel", camera_enabled=True, status_code=WORK_STATE_REMOTE_CTRL)
    coord.build_device_command = MagicMock(side_effect=lambda name: {"181": name})
    coord.async_send_command = AsyncMock()
    return coord


@pytest.fixture
def video(coordinator):
    return RobotVideo(MagicMock(), coordinator)


@pytest.mark.asyncio
async def test_hold_refuses_when_the_camera_is_switched_off(video, coordinator):
    coordinator.data = VacuumState(api_type="novel", camera_enabled=False)
    with pytest.raises(HomeAssistantError, match="switched off"):
        async with video.hold():
            pytest.fail("must not stream with the camera off")


def _answer(coordinator, *, open_result: int, set_result: int = 0):
    """A robot that answers each DP 181 command with the matching reply."""

    async def reply(command_dict, **_kwargs):
        name = command_dict["181"]
        method, result = (VIDEO_MGR_STATE_SET, set_result) if name == "video_pass_enable" else (VIDEO_MGR_STREAM_OPEN, open_result)
        coordinator.data = VacuumState(video_response=(method, result, time.monotonic()))

    coordinator.async_send_command.side_effect = reply


@pytest.mark.asyncio
async def test_open_sets_pass_enable_then_opens_the_stream(video, coordinator):
    sent: list[str] = []
    _answer(coordinator, open_result=0)
    inner = coordinator.async_send_command.side_effect

    async def record(command_dict, **kwargs):
        sent.append(command_dict["181"])
        await inner(command_dict, **kwargs)

    coordinator.async_send_command.side_effect = record
    await video._open_robot_stream()
    assert sent == ["video_pass_enable", "video_stream_open"]
    # wait=False: the reply is a push, so the write must not swallow it.
    assert coordinator.async_send_command.await_args.kwargs == {"wait": False}


@pytest.mark.asyncio
async def test_open_reports_a_refusal(video, coordinator):
    _answer(coordinator, open_result=1)
    with pytest.raises(HomeAssistantError, match="refused"):
        await video._open_robot_stream()


@pytest.mark.asyncio
async def test_open_stops_if_the_pass_enable_is_refused(video, coordinator):
    _answer(coordinator, open_result=0, set_result=1)
    with pytest.raises(HomeAssistantError, match="refused"):
        await video._open_robot_stream()
    assert coordinator.async_send_command.await_count == 1  # never got as far as StreamOpen


@pytest.mark.asyncio
async def test_open_ignores_a_stale_reply_and_times_out(video, coordinator, monkeypatch):
    coordinator.data = VacuumState(video_response=(VIDEO_MGR_STATE_SET, 0, time.monotonic() - 60))
    monkeypatch.setattr("custom_components.robovac_mqtt.video_stream._OPEN_REPLY_TIMEOUT", 0.3)
    with pytest.raises(HomeAssistantError, match="did not answer"):
        await video._open_robot_stream()


@pytest.mark.asyncio
async def test_jpegs_are_split_out_of_the_decoder_stream(video):
    def jpeg(body: bytes) -> bytes:
        return b"\xff\xd8" + body + b"\xff\xd9"

    stream = asyncio.StreamReader()
    stream.feed_data(jpeg(b"one") + jpeg(b"two")[:4])  # second frame split across reads
    stream.feed_data(jpeg(b"two")[4:])
    stream.feed_eof()
    with pytest.raises(Exception, match="decoder stopped"):
        await video._read_frames(stream)
    assert video._frame == jpeg(b"two")
    assert video.frame_age is not None and video.frame_age < 5


@pytest.mark.asyncio
async def test_wait_for_frame_returns_the_fresh_frame_immediately(video):
    video._frame, video._frame_at = b"jpeg", time.monotonic()
    assert await video.wait_for_frame(timeout=1) == b"jpeg"


@pytest.mark.asyncio
async def test_wait_for_frame_gives_up_when_nothing_streams(video):
    assert await video.wait_for_frame(timeout=0.2) is None


def test_stream_close_is_sent_without_waiting(video, coordinator):
    asyncio.run(video._close_robot_stream())
    coordinator.async_send_command.assert_awaited_once_with({"181": "video_stream_close"}, wait=False)


# -- the camera entity --------------------------------------------------------


def make_camera(coordinator, video):
    coordinator.device_id = "dev"
    coordinator.last_update_success = True
    coordinator.device_info = {}
    return EufyVideoCamera(coordinator, video)


def test_camera_is_unavailable_until_the_robot_camera_is_switched_on(coordinator, video):
    camera = make_camera(coordinator, video)
    assert camera.available is True
    coordinator.data = VacuumState(api_type="novel", camera_enabled=False)
    assert camera.available is False
    assert camera.extra_state_attributes["camera_switch"] is False


def test_camera_reports_frame_age_and_the_last_error(coordinator, video):
    video._frame, video._frame_at = b"jpeg", time.monotonic() - 2
    video.last_error = "robot refused"
    attrs = make_camera(coordinator, video).extra_state_attributes
    assert attrs["last_error"] == "robot refused"
    assert 1.5 < attrs["frame_age_seconds"] < 5


@pytest.mark.asyncio
async def test_snapshot_holds_the_stream_while_it_waits_for_a_frame(coordinator, video):
    calls: list[str] = []

    @asynccontextmanager
    async def hold():
        calls.append("enter")
        yield video
        calls.append("exit")

    video.hold = hold
    video.wait_for_frame = AsyncMock(return_value=b"jpeg-bytes")
    assert await make_camera(coordinator, video).async_camera_image() == b"jpeg-bytes"
    assert calls == ["enter", "exit"]


def test_camera_is_added_only_once_the_robot_reports_a_camera_switch(coordinator):
    coordinator.api_type = "novel"
    coordinator.p2p = object()
    coordinator.video = None
    coordinator.hass = MagicMock()
    coordinator.device_id, coordinator.device_info = "dev", {}
    coordinator.last_update_success = True
    listeners = []
    removals: list[int] = []
    coordinator.async_add_listener = lambda cb: listeners.append(cb) or (lambda: removals.append(1))
    added: list = []
    entry = MagicMock()

    coordinator.data = VacuumState(api_type="novel")  # no camera switch reported yet
    _add_video_camera_when_supported(entry, coordinator, added.extend)
    assert not added

    coordinator.data = VacuumState(api_type="novel", camera_enabled=True, received_fields={"camera_enabled"})
    listeners[0]()
    assert len(added) == 1 and isinstance(added[0], EufyVideoCamera)
    listeners[0]()  # later updates must not add it again
    assert len(added) == 1
    # The listener is removed when the camera is added; the entry's unload then runs
    # the same callback again, which must not remove it a second time (KeyError in HA).
    assert removals == [1]
    entry.async_on_unload.call_args.args[0]()
    assert removals == [1]


def test_no_video_camera_for_robots_without_the_novel_protocol(coordinator):
    coordinator.api_type = "scalar"
    coordinator.async_add_listener = MagicMock()
    _add_video_camera_when_supported(MagicMock(), coordinator, lambda _e: pytest.fail("added"))
    coordinator.async_add_listener.assert_not_called()


# -- closing a session politely -----------------------------------------------


class _FakeWriter:
    def __init__(self, closing: bool = False) -> None:
        self.data = b""
        self._closing = closing

    def write(self, data: bytes) -> None:
        self.data += data

    async def drain(self) -> None:  # pylint: disable=no-self-use
        return None

    def is_closing(self) -> bool:
        return self._closing


def _session() -> VideoSession:
    return VideoSession(
        on_nal=lambda _nal: None, host="127.0.0.1", local_key="k" * 16,
        device_id="dev", device_password="pw", cloud_session=_CLOUD,
    )


@pytest.mark.asyncio
async def test_closing_an_established_session_sends_a_disconnect():
    session = _session()
    session._writer = _FakeWriter()
    session._robot_pwd = b"answered"  # the robot answered our offer, so a session exists
    await session._say_goodbye()
    frames, _ = decode_frames(b"k" * 16, session._writer.data)
    assert [(c, p["header"]["type"]) for c, p in frames] == [(CMD_RTC, "disconnect")]
    assert frames[0][1]["header"]["sessionid"] == session._session_id


@pytest.mark.asyncio
async def test_no_disconnect_before_the_robot_has_answered_or_after_the_socket_closed():
    session = _session()
    session._writer = _FakeWriter()
    await session._say_goodbye()  # never answered
    assert session._writer.data == b""
    session._robot_pwd = b"answered"
    session._writer = _FakeWriter(closing=True)
    await session._say_goodbye()
    assert session._writer.data == b""


# -- the ffmpeg command --------------------------------------------------------


def test_ffmpeg_args_avoid_the_two_flags_that_broke_the_pipeline():
    # `-fflags nobuffer` yields no output at all for a raw H.265 pipe.
    assert "nobuffer" not in " ".join(FFMPEG_ARGS)
    # The MJPEG encoder refuses limited-range YUV unless converted to full range.
    assert FFMPEG_ARGS[FFMPEG_ARGS.index("-pix_fmt") + 1] == "yuvj420p"
    assert FFMPEG_ARGS[-1] == "pipe:1" and "pipe:0" in FFMPEG_ARGS


def _can_encode_hevc() -> bool:
    if shutil.which("ffmpeg") is None:
        return False
    encoders = subprocess.run(["ffmpeg", "-hide_banner", "-encoders"], capture_output=True, text=True, check=False)
    return "libx265" in encoders.stdout


@pytest.mark.skipif(not _can_encode_hevc(), reason="needs ffmpeg with libx265")
def test_ffmpeg_turns_an_h265_stream_into_jpegs():
    """End to end with a generated stream (no real camera frames in the repo)."""
    make = subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=size=160x120:rate=10",
         "-t", "1", "-c:v", "libx265", "-x265-params", "log-level=none", "-f", "hevc", "pipe:1"],
        capture_output=True, check=True,
    )
    out = subprocess.run(["ffmpeg", *FFMPEG_ARGS], input=make.stdout, capture_output=True, check=True).stdout
    assert out.count(b"\xff\xd8") >= 5 and out.count(b"\xff\xd9") >= 5


# -- the cloud's pre-session ------------------------------------------------------


def test_a_session_adopts_the_session_the_cloud_reserved_on_the_robot():
    session = VideoSession(
        on_nal=lambda _n: None, host="127.0.0.1", local_key="k" * 16, device_id="dev",
        device_password="pw", cloud_session=_CLOUD,
    )
    assert session._session_id == _CLOUD["sessionId"]
    assert (session._ufrag, session._ice_pwd) == (_CLOUD["iceUfrag"], _CLOUD["icePassword"])
    assert session._media_key == bytes.fromhex(_CLOUD["aesKey"])
    assert session._trace_id == _CLOUD["traceId"] and session._user_id == _CLOUD["uid"]


@pytest.mark.parametrize("bad", [{}, {"aesKey": "zz"}, {**_CLOUD, "aesKey": "00"}, {**_CLOUD, "sessionId": None}])
def test_an_unusable_cloud_session_is_rejected_without_inventing_an_identity(bad):
    with pytest.raises(P2PError, match="cloud-issued session"):
        VideoSession(
            on_nal=lambda _n: None, host="127.0.0.1", local_key="k" * 16, device_id="dev",
            device_password="pw", cloud_session=bad,
        )


@pytest.mark.asyncio
async def test_a_busy_robot_gets_no_session_and_no_cloud_config(video, coordinator):
    """A refused session only makes the robot refuse longer; a fetched config reserves a slot."""
    feed = MagicMock()
    feed.get_rtc = AsyncMock()
    coordinator.p2p = feed
    coordinator.data = VacuumState(api_type="novel", camera_enabled=True, activity="cleaning")
    with pytest.raises(HomeAssistantError, match="busy"):
        await video._stream_once()
    feed.get_rtc.assert_not_awaited()


# -- starting the video within one session ----------------------------------------


class _Conversation:
    def __init__(self) -> None:
        self.sent: list[bytes] = []

    def send(self, packet: bytes) -> None:
        self.sent.append(packet)


def _video_session(open_stream=None) -> tuple[VideoSession, _Conversation]:
    session = VideoSession(
        on_nal=lambda _n: None, open_stream=open_stream, host="127.0.0.1",
        local_key="k" * 16, device_id="dev", device_password="pw", cloud_session=_CLOUD,
    )
    conversation = _Conversation()
    session._conversations = {kcp.CONV_CONTROL: conversation}  # type: ignore[dict-item]
    return session, conversation


@pytest.mark.asyncio
async def test_the_stream_is_opened_after_the_prelude_and_before_any_video_start(monkeypatch):
    monkeypatch.setattr("custom_components.robovac_mqtt.api.p2p.video.STREAM_SETTLE", 0.01)
    order: list[str] = []
    session, conversation = _video_session()

    async def open_stream():
        order.append(f"open after {len(conversation.sent)} packets")

    session._open_stream = open_stream
    await session._start_video()
    assert order == ["open after 3 packets"]  # auth, hello and capabilities were sent first
    assert len(conversation.sent) > 3


@pytest.mark.asyncio
async def test_only_the_verified_start_sequence_is_sent_once(monkeypatch):
    monkeypatch.setattr("custom_components.robovac_mqtt.api.p2p.video.STREAM_SETTLE", 0.01)
    session, conversation = _video_session(open_stream=AsyncMock())
    await session._start_video()
    assert conversation.sent[3:] == control.video_start_packets()


@pytest.mark.asyncio
async def test_no_start_request_is_sent_when_video_already_flows():
    session, conversation = _video_session()
    session._first_object.set()
    await session._start_video()
    assert len(conversation.sent) == 3  # only the prelude


@pytest.mark.asyncio
async def test_a_refused_stream_open_does_not_stop_the_video_start(monkeypatch):
    """The stream-open is advisory: a session that ignored its refusal still got video from a real robot."""
    monkeypatch.setattr("custom_components.robovac_mqtt.api.p2p.video.STREAM_SETTLE", 0.01)

    async def refuse():
        raise HomeAssistantError("refused")

    session, conversation = _video_session(open_stream=refuse)
    await session._start_video()
    assert len(conversation.sent) > 3  # the verified start was sent regardless
    assert session._failure is None


# -- refusals ---------------------------------------------------------------------


def _disconnect(session, reason: int) -> None:
    session._on_signal({"header": {"type": "disconnect"}, "msg": {"close_reason": reason, "close_reason_local": 7}})


@pytest.mark.parametrize("reason", [4, 12])
def test_a_disconnect_before_the_session_connects_is_a_refusal(reason):
    session, _ = _video_session()
    _disconnect(session, reason)
    assert isinstance(session._failure, P2PRefused)


@pytest.mark.parametrize(("reason", "connected"), [(6, False), (4, True), (0, True)])
def test_other_disconnects_are_ordinary_failures(reason, connected):
    """Reason 6 is the normal idle close; anything after the stream is flowing is not a refusal."""
    session, _ = _video_session()
    if connected:
        session._first_object.set()
    _disconnect(session, reason)
    assert isinstance(session._failure, P2PError) and not isinstance(session._failure, P2PRefused)


def test_the_camera_waits_a_long_time_after_a_refusal_and_backs_off_otherwise():
    assert retry_delay(refused=True, attempt=0) == 30 * 60
    assert [retry_delay(refused=False, attempt=n) for n in range(6)] == [5.0, 30.0, 300.0, 600.0, 600.0, 600.0]


# -- one session at a time --------------------------------------------------------


@pytest.mark.asyncio
async def test_the_camera_waits_for_the_map_feed_to_release_the_session_slot(video, coordinator, monkeypatch):
    """The robot serves one P2P session at a time and refuses any other."""
    feed = MagicMock()
    feed.acquire_slot = AsyncMock(side_effect=TimeoutError)
    feed.get_rtc = AsyncMock()
    coordinator.p2p = feed
    with pytest.raises(HomeAssistantError, match="busy with the map"):
        await video._stream_once()
    feed.get_rtc.assert_not_awaited()  # no cloud config fetched, no slot burned on the robot


@pytest.mark.asyncio
async def test_the_slot_is_released_when_the_stream_ends(video, coordinator):
    feed = MagicMock()
    feed.acquire_slot = AsyncMock()
    coordinator.p2p = feed
    video._stream_in_slot = AsyncMock(side_effect=HomeAssistantError("ended"))
    with pytest.raises(HomeAssistantError, match="ended"):
        await video._stream_once()
    feed.release_slot.assert_called_once()


@pytest.mark.asyncio
async def test_a_new_viewer_wakes_a_stream_that_is_backing_off(video):
    video._kick.clear()
    waiter = asyncio.ensure_future(asyncio.wait_for(video._kick.wait(), 5))
    await asyncio.sleep(0)
    video._holders = 0
    video._ensure_running = lambda: None
    async with video.hold():
        pass
    await waiter  # returns at once because hold() set the kick


@pytest.mark.asyncio
async def test_a_new_viewer_does_not_wake_a_stream_the_robot_is_refusing(video):
    video._cooling_down = True
    video._ensure_running = lambda: None
    async with video.hold():
        pass
    assert not video._kick.is_set()


@pytest.mark.parametrize("status", [0, 2, 3, 5, 7, 9])
def test_camera_is_unavailable_outside_manual_control(coordinator, video, status):
    coordinator.data = VacuumState(camera_enabled=True, status_code=status)
    camera = make_camera(coordinator, video)
    assert camera.available is False
    assert camera.extra_state_attributes["manual_control"] is False


@pytest.mark.asyncio
async def test_no_session_or_viewer_is_started_outside_manual_control(video, coordinator):
    coordinator.data = VacuumState(camera_enabled=True, status_code=0)
    video._ensure_running = MagicMock()
    with pytest.raises(HomeAssistantError, match="manual control"):
        async with video.hold():
            pytest.fail("must not view the camera outside manual control")
    video._ensure_running.assert_not_called()
    assert video._holders == 0
    coordinator.p2p.acquire_slot = AsyncMock()
    with pytest.raises(HomeAssistantError, match="manual control"):
        await video._stream_once()
    coordinator.p2p.acquire_slot.assert_not_awaited()


@pytest.mark.asyncio
async def test_old_frame_is_not_returned_after_manual_control_ends(video, coordinator):
    video._frame, video._frame_at = b"jpeg", time.monotonic()
    coordinator.data = VacuumState(camera_enabled=True, status_code=0)
    assert await video.wait_for_frame(timeout=1) is None
    assert await video.latest() is None


@pytest.mark.asyncio
async def test_stream_exits_without_retrying_when_manual_control_ends(video, coordinator):
    async def leave_mode():
        coordinator.data = VacuumState(camera_enabled=True, status_code=0)
        raise P2PError("manual control ended")
    video._stream_once = AsyncMock(side_effect=leave_mode)
    video._close_robot_stream = AsyncMock()
    await asyncio.wait_for(video._run(), 0.5)
    video._stream_once.assert_awaited_once()
    video._close_robot_stream.assert_awaited_once()


@pytest.mark.asyncio
async def test_manual_mode_is_allowed_even_when_ha_calls_its_activity_cleaning(video, coordinator):
    coordinator.data = VacuumState(camera_enabled=True, status_code=WORK_STATE_REMOTE_CTRL, activity="cleaning")
    coordinator.p2p.acquire_slot = AsyncMock(side_effect=TimeoutError)
    with pytest.raises(HomeAssistantError, match="busy with the map"):
        await video._stream_once()
    coordinator.p2p.acquire_slot.assert_awaited_once()


@pytest.mark.asyncio
async def test_expired_frames_are_not_served_after_decoder_failure(video):
    video._frame, video._frame_at = b"old jpeg", time.monotonic() - 60
    assert await video.latest() is None
    assert await video.wait_for_frame(timeout=0) is None


@pytest.mark.asyncio
async def test_turning_the_physical_camera_off_blocks_cached_images_and_stops_watchdog(video, coordinator, monkeypatch):
    video._frame, video._frame_at = b"jpeg", time.monotonic()
    coordinator.data = VacuumState(camera_enabled=False, status_code=WORK_STATE_REMOTE_CTRL)
    assert await video.latest() is None
    assert await video.wait_for_frame(timeout=0) is None
    monkeypatch.setattr("custom_components.robovac_mqtt.video_stream.asyncio.sleep", AsyncMock())
    with pytest.raises(HomeAssistantError, match="switched off"):
        await video._watch_stall(20)
