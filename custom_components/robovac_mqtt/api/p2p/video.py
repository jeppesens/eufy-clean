"""The robot's camera stream: RTP/H.265 carried on KCP conversation 1.

After ``StreamOpen`` on DP 181 and the IOCtrl start in :func:`control.video_start_packets`,
the robot opens conversation 1 and sends a byte stream of frames::

    <Tuya frame header> <u32 RTP packet length> <RTP packet>

The header is not fixed-length (key frames carry width/height/fps), so
:class:`RtpHevcReader` anchors on the RTP packet instead: payload type 95, RTP
version 2, and the length field just before it. The RTP payload is H.265 per
RFC 7798 (single NAL units, aggregation packets and fragmentation units), which
:class:`RtpHevcReader` turns into Annex-B NAL units for a decoder.
"""

from __future__ import annotations

import asyncio
import logging
import struct
from collections.abc import Awaitable, Callable, Iterator
from typing import Any

from . import control, kcp
from .session import P2PSession

_LOGGER = logging.getLogger(__name__)

RTP_PAYLOAD_TYPE = 95
_RTP_HEADER = 12
_MAX_PACKET = 1500
_START_CODE = b"\x00\x00\x00\x01"
_NAL_AGGREGATION = 48
_NAL_FRAGMENT = 49


class RtpHevcReader:
    """Incremental reader: feed decrypted stream bytes, iterate Annex-B NAL units."""

    def __init__(self) -> None:
        self._buffer = bytearray()
        self._ssrc: bytes | None = None
        self._fragment: bytearray | None = None
        self._last_seq: int | None = None
        self.packets = 0
        self.gaps = 0

    def feed(self, data: bytes) -> Iterator[bytes]:
        self._buffer += data
        while (packet := self._next_packet()) is not None:
            yield from self._depacketize(packet)

    def _next_packet(self) -> bytes | None:
        """Pop the next complete RTP packet, or None until more bytes arrive."""
        buf = self._buffer
        i = 4  # the u32 length sits right before the RTP header
        while i + _RTP_HEADER <= len(buf):
            if (
                buf[i] >> 6 == 2
                and buf[i + 1] & 0x7F == RTP_PAYLOAD_TYPE
                and (self._ssrc is None or buf[i + 8 : i + 12] == self._ssrc)
            ):
                size = struct.unpack_from("<I", buf, i - 4)[0]
                if _RTP_HEADER < size <= _MAX_PACKET:
                    if i + size > len(buf):
                        # Keep the unfinished packet's header and wait for the rest.
                        del buf[: i - 4]
                        return None
                    packet = bytes(buf[i : i + size])
                    self._ssrc = packet[8:12]
                    del buf[: i + size]
                    return packet
            i += 1
        # Nothing yet: keep only a tail that could hold a split header.
        del buf[: max(0, len(buf) - (_RTP_HEADER + 4))]
        return None

    def _depacketize(self, packet: bytes) -> Iterator[bytes]:
        seq = struct.unpack_from(">H", packet, 2)[0]
        if self._last_seq is not None and (seq - self._last_seq) & 0xFFFF != 1:
            self.gaps += 1
            self._fragment = None  # a lost packet makes any open fragment unusable
        self._last_seq = seq
        self.packets += 1
        payload = packet[_RTP_HEADER:]
        if len(payload) < 3:
            return
        nal_type = (payload[0] >> 1) & 0x3F
        if nal_type == _NAL_FRAGMENT:
            header = payload[2]
            if header & 0x80:  # start
                self._fragment = bytearray(
                    [(payload[0] & 0x81) | ((header & 0x3F) << 1), payload[1]]
                )
            if self._fragment is not None:
                self._fragment += payload[3:]
                if header & 0x40:  # end
                    yield _START_CODE + bytes(self._fragment)
                    self._fragment = None
        elif nal_type == _NAL_AGGREGATION:
            pos = 2
            while pos + 2 <= len(payload):
                size = struct.unpack_from(">H", payload, pos)[0]
                pos += 2
                yield _START_CODE + payload[pos : pos + size]
                pos += size
        else:
            yield _START_CODE + payload


# After the robot confirms its stream is open, give the camera pipeline this long to
# come up before the first start request: earlier sessions that streamed had the
# stream open for several seconds first.
STREAM_SETTLE = 2.5


class VideoSession(P2PSession):
    """A P2P session that asks for the camera stream and hands out H.265 NAL units.

    ``open_stream`` is awaited once the control channel is up and before any video
    start is sent, which is the app's order (connect, then ask the robot to open its
    stream). The verified HD startup sequence is sent once; the session timeout
    and the caller's backoff handle a robot that does not produce video.
    """

    _stream_label = "camera stream"

    def __init__(
        self,
        *,
        on_nal: Callable[[bytes], None],
        open_stream: Callable[[], Awaitable[None]] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(on_object=lambda _name, _obj: None, **kwargs)
        self._on_nal = on_nal
        # Budget for ICE, DP 181 replies, the settle delay and the first NAL.
        self.connect_timeout = 30.0
        self._open_stream = open_stream
        self._start_task: asyncio.Future | None = None
        self.reader = RtpHevcReader()

    def _extra_conversations(self) -> dict[int, kcp.KcpConversation]:
        return {
            kcp.CONV_VIDEO: kcp.KcpConversation(
                kcp.CONV_VIDEO, self._media_key, self._send_udp, self._on_video_record
            )
        }

    def _send_control_burst(self) -> None:
        if self._closed.is_set():
            return
        self._start_task = asyncio.ensure_future(self._start_video())

    async def _start_video(self) -> None:
        try:
            conversation = self._conversations[kcp.CONV_CONTROL]
            for packet in control.video_prelude_packets(self._device_password, self._local_key):
                conversation.send(packet)
            if self._open_stream is not None:
                try:
                    await self._open_stream()
                except Exception as err:  # noqa: BLE001 - the stream-open is advisory
                    # A video session that ignored a refused stream-open (and got
                    # no reply to it) still streamed on a real robot, so keep going
                    # and let the start requests decide.
                    _LOGGER.debug("p2p: stream-open not confirmed (%s); asking for video anyway", err)
            await asyncio.sleep(STREAM_SETTLE if self._open_stream is not None else 0.2)
            if not self._first_object.is_set():
                for packet in control.video_start_packets():
                    conversation.send(packet)
        except Exception as err:  # noqa: BLE001 - a failed start ends the session
            self._fail(err)

    def _shutdown(self) -> None:
        if self._start_task is not None:
            self._start_task.cancel()
        super()._shutdown()

    def _on_video_record(self, plaintext: bytes) -> None:
        self.bytes_received += len(plaintext)
        for nal in self.reader.feed(plaintext):
            self._first_object.set()
            try:
                self._on_nal(nal)
            except Exception:  # noqa: BLE001 - a consumer bug must not kill the channel
                _LOGGER.exception("p2p: video consumer failed")
