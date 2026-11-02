"""A long-lived P2P session to the robot on the LAN.

Signaling rides the local Tuya socket (TCP 6668, command type 32): our SDP offer
names the AES media key, then host candidates are exchanged. The media is KCP
over a UDP pair once ICE connectivity checks pass both ways. Conversation 0
carries the auth + subscribe burst, conversation 5 the named file streams
(``map.bin.stream``, ``cleanPath.bin.stream``, ``navPath.bin.stream``).

:class:`P2PSession` keeps the channel alive (ICE consent refresh, Tuya
heartbeats, KCP acks and retransmits) and hands every reassembled stream object
to a callback until it is closed or the channel stalls. Supervision (reconnect,
backoff) is the caller's job: :meth:`P2PSession.run` returns or raises when the
session ends.
"""

from __future__ import annotations

import asyncio
import logging
import re
import secrets
import socket
import time
from collections.abc import Callable
from typing import Any

from . import control, kcp, stun
from .framing import CMD_DP_QUERY, CMD_HEARTBEAT, CMD_RTC, decode_frames, encode_frame
from .streams import StreamReassembler

_LOGGER = logging.getLogger(__name__)

ROBOT_PORT = 6668
_DEFAULT_LOG = {"api": "thing.m.rtc.log", "interval": 60, "size": 1024, "level": 2, "topic": "/av/moto/log"}

_CONNECT_TIMEOUT = 20.0  # offer -> first complete stream object
_TICK = 0.1  # KCP retransmit cadence
_CONSENT_INTERVAL = 2.5  # ICE consent refresh toward the device
_HEARTBEAT_INTERVAL = 10.0  # Tuya socket keep-alive
_STALL_TIMEOUT = 45.0  # nothing from the device for this long -> session is dead


class P2PError(Exception):
    """The P2P session could not be opened or has died."""


class P2PRefused(P2PError):
    """The robot closed the session before it connected (it is refusing sessions).

    Retrying quickly makes it refuse for longer, so callers should back off for a
    long time rather than reconnect.
    """


# close_reason values the robot sends when it refuses a session outright: 4 (torn down
# before reaching the connected state) and 12 (the session could not be created).
REFUSAL_REASONS = (4, 12)


def _build_offer_sdp(session_id: str, ufrag: str, password: str, aes_key_hex: str, cname: str) -> str:
    return "\r\n".join(
        (
            "v=0",
            f"o=- {int(time.time())} 1 IN IP4 127.0.0.1",
            "s=-",
            "t=0 0",
            "a=group:BUNDLE imm0",
            f"a=msid-semantic: WMS {session_id}",
            "m=application 9 imm 6001",
            "c=IN IP4 0.0.0.0",
            "a=rtcp:9 IN IP4 0.0.0.0",
            f"a=ice-ufrag:{ufrag}",
            f"a=ice-pwd:{password}",
            "a=ice-options:trickle",
            f"a=aes-key:{aes_key_hex}",
            "a=mid:imm0",
            "a=rtpmap:6001 AES/KCP 330",
            f"a=ssrc:0 cname:{cname}",
            "",
        )
    )


def local_ip_towards(host: str) -> str:
    """Return the local interface address that routes to ``host``."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        probe.connect((host, ROBOT_PORT))
        return probe.getsockname()[0]


class _UdpProtocol(asyncio.DatagramProtocol):
    def __init__(self, on_datagram: Callable[[bytes, tuple[str, int]], None]) -> None:
        self._on_datagram = on_datagram

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        self._on_datagram(data, addr)


class P2PSession:
    """One P2P session; :meth:`run` blocks until it ends."""

    def __init__(
        self,
        *,
        host: str,
        local_key: str,
        device_id: str,
        device_password: str,
        on_object: Callable[[str, bytes], None],
        cloud_session: dict[str, Any],
        ice_config: dict[str, Any] | None = None,
        host_ip: str | None = None,
    ) -> None:
        self._host = host
        self._local_key = local_key
        self._key = local_key.encode()
        self._device_id = device_id
        self._device_password = device_password
        self._ice = ice_config or {}
        self._on_object = on_object
        self._host_ip = host_ip

        # A locally invented identity leaves the cloud reservation unused.
        try:
            self._media_key = bytes.fromhex(cloud_session["aesKey"])
            self._session_id, self._ufrag, self._ice_pwd, self._trace_id, self._user_id = (
                cloud_session[key] for key in ("sessionId", "iceUfrag", "icePassword", "traceId", "uid")
            )
            if len(self._media_key) != 16 or not all(
                isinstance(v, str) and v
                for v in (self._session_id, self._ufrag, self._ice_pwd, self._trace_id, self._user_id)
            ):
                raise ValueError("invalid session identity")
        except (KeyError, TypeError, ValueError) as err:
            raise P2PError("RTC config has no usable cloud-issued session") from err

        self._robot_ufrag: str | None = None
        self._robot_pwd: bytes | None = None
        self._robot_addr: tuple[str, int] | None = None
        self._ice_up = False
        self._udp: asyncio.DatagramTransport | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._tcp_sequence = 1
        self._last_rx = time.monotonic()
        self._first_object = asyncio.Event()
        self._closed = asyncio.Event()
        self._failure: BaseException | None = None
        self._reassembler = StreamReassembler()
        self.connect_timeout = _CONNECT_TIMEOUT
        self._conversations: dict[int, kcp.KcpConversation] = {}
        self.bytes_received = 0

    # What this session is waiting for, for log and error messages.
    _stream_label = "map stream"

    def _extra_conversations(self) -> dict[int, kcp.KcpConversation]:  # pylint: disable=no-self-use
        """Additional KCP conversations a subclass wants opened (none for the map)."""
        return {}

    @property
    def connected(self) -> bool:
        return self._first_object.is_set() and not self._closed.is_set()

    async def run(self) -> None:
        """Open the channel and pump it until :meth:`close` or a failure."""
        loop = asyncio.get_running_loop()
        tasks: list[asyncio.Future] = []
        try:
            # The host may be a DNS name; ICE candidates carry IPv4 addresses.
            infos = await loop.getaddrinfo(self._host, ROBOT_PORT, family=socket.AF_INET)
            self._host = infos[0][4][0]
            if self._host_ip:
                host_ip = self._host_ip
            else:
                host_ip = await loop.run_in_executor(None, local_ip_towards, self._host)
            self._udp, _ = await loop.create_datagram_endpoint(
                lambda: _UdpProtocol(self._on_datagram), local_addr=(host_ip, 0)
            )
            udp_port = self._udp.get_extra_info("sockname")[1]
            self._conversations = {
                kcp.CONV_CONTROL: kcp.KcpConversation(
                    kcp.CONV_CONTROL, self._media_key, self._send_udp, self._on_control_record
                ),
                kcp.CONV_MAP: kcp.KcpConversation(
                    kcp.CONV_MAP, self._media_key, self._send_udp, self._on_map_record
                ),
                **self._extra_conversations(),
            }
            reader, self._writer = await asyncio.wait_for(
                asyncio.open_connection(self._host, ROBOT_PORT), 10
            )
            tasks = [
                asyncio.ensure_future(self._signaling(reader, host_ip, udp_port)),
                asyncio.ensure_future(self._housekeeping()),
            ]
            opened = asyncio.ensure_future(self._first_object.wait())
            ended = asyncio.ensure_future(self._closed.wait())
            tasks.extend((opened, ended))
            done, _ = await asyncio.wait(
                {opened, ended}, timeout=self.connect_timeout, return_when=asyncio.FIRST_COMPLETED
            )
            opened.cancel()
            ended.cancel()
            if not done:
                raise P2PError(
                    f"no {self._stream_label} from the robot"
                    + ("" if self._ice_up else " (ICE never connected)")
                )
            if self._first_object.is_set():
                _LOGGER.debug("p2p: %s flowing from %s", self._stream_label, self._host)
                await self._closed.wait()
            if self._failure is not None:
                if isinstance(self._failure, P2PError):
                    raise self._failure
                raise P2PError(str(self._failure)) from self._failure
        finally:
            self._closed.set()
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            await self._say_goodbye()
            self._shutdown()

    async def close(self) -> None:
        self._closed.set()

    async def _say_goodbye(self) -> None:
        """Tell the robot the session is over, so it frees the slot now.

        The robot only allows a few concurrent sessions and, if we just drop the
        socket, may hold the slot until its own timeout; the signalling it sends us
        when it ends a session (``type: disconnect``) is the polite way out.
        """
        if self._writer is None or self._writer.is_closing() or self._robot_pwd is None:
            return
        try:
            self._send_tcp(
                CMD_RTC,
                {
                    "header": self._header("disconnect"),
                    "msg": {"close_reason": 0, "close_reason_local": 0},
                },
            )
            await asyncio.wait_for(self._writer.drain(), 1.0)
        except (OSError, TimeoutError):
            pass  # the socket closes right after this either way

    def _fail(self, err: BaseException) -> None:
        if not self._closed.is_set():
            self._failure = err
            self._closed.set()

    def _shutdown(self) -> None:
        if self._udp is not None:
            self._udp.close()
            self._udp = None
        if self._writer is not None:
            self._writer.close()
            self._writer = None

    def _send_udp(self, datagram: bytes) -> None:
        if self._udp is not None and self._robot_addr is not None:
            self._udp.sendto(datagram, self._robot_addr)

    def _send_tcp(self, command: int, payload: dict[str, Any]) -> None:
        if self._writer is None:
            return
        self._writer.write(encode_frame(self._key, command, payload, self._tcp_sequence))
        self._tcp_sequence += 1

    def _header(self, kind: str, **extra: Any) -> dict[str, Any]:
        return {
            "from": self._user_id, "to": self._device_id, "sessionid": self._session_id,
            "path": "lan", "type": kind, "trace_id": self._trace_id, **extra,
        }

    async def _signaling(self, reader: asyncio.StreamReader, host_ip: str, udp_port: int) -> None:
        try:
            assert self._writer is not None
            self._send_tcp(CMD_DP_QUERY, {"gwId": self._device_id, "devId": self._device_id})
            sdp = _build_offer_sdp(
                self._session_id, self._ufrag, self._ice_pwd, self._media_key.hex(), self._user_id
            )
            self._send_tcp(CMD_RTC, {
                "msg": {
                    "sdp": sdp, "preconnect": True,
                    "token": self._ice.get("token", []),
                    "tcp_token": self._ice.get("tcp_token", {}),
                    "log": self._ice.get("log") or _DEFAULT_LOG,
                },
                "header": self._header("offer", is_pre=0, p2p_skill=67, security_level=3, moto_id=""),
            })
            await self._writer.drain()
            await asyncio.sleep(0.4)
            foundation = secrets.randbelow(2_000_000_000)
            self._send_tcp(CMD_RTC, {
                "msg": {"candidate": f"a=candidate:{foundation} 1 UDP 2130706431 {host_ip} {udp_port} typ host\r\n"},
                "header": self._header("candidate", sub_dev_id=""),
            })
            await self._writer.drain()

            buffer = b""
            while not self._closed.is_set():
                chunk = await reader.read(65536)
                if not chunk:
                    raise P2PError("robot closed the signaling socket")
                buffer += chunk
                frames, buffer = decode_frames(self._key, buffer)
                for command, payload in frames:
                    if command == CMD_RTC and isinstance(payload, dict):
                        self._on_signal(payload)
        except Exception as err:  # noqa: BLE001 - any signaling failure ends the session
            self._fail(err)

    def _on_signal(self, payload: dict[str, Any]) -> None:
        header, msg = payload.get("header", {}), payload.get("msg", {})
        kind = header.get("type")
        if kind == "answer":
            sdp = msg.get("sdp", "")
            if ufrag := re.search(r"ice-ufrag:(\S+)", sdp):
                self._robot_ufrag = ufrag.group(1)
            if pwd := re.search(r"ice-pwd:(\S+)", sdp):
                self._robot_pwd = pwd.group(1).encode()
        elif kind == "candidate":
            match = re.search(r"(\d+\.\d+\.\d+\.\d+) (\d+) typ host", msg.get("candidate", ""))
            if match and match.group(1) == self._host and self._robot_pwd and self._robot_ufrag:
                self._robot_addr = (match.group(1), int(match.group(2)))
                self._send_consent(nominate=False)
        elif kind == "disconnect":
            _LOGGER.debug("p2p: robot disconnect: %s", msg)
            error = P2PRefused if (
                not self._first_object.is_set() and msg.get("close_reason") in REFUSAL_REASONS
            ) else P2PError
            self._fail(error(f"robot sent disconnect: {msg}"))

    def _on_datagram(self, datagram: bytes, addr: tuple[str, int]) -> None:
        if self._robot_addr is None or addr != self._robot_addr:
            return
        self._last_rx = time.monotonic()
        if stun.is_stun(datagram):
            _LOGGER.debug("p2p: stun %#06x from robot: %s", stun.message_type(datagram), datagram[20:].hex())
            if stun.message_type(datagram) == stun.BIND_REQUEST:
                self._send_udp(stun.binding_success(datagram, addr[0], addr[1], self._ice_pwd.encode()))
                if not self._ice_up:
                    self._ice_up = True
                    _LOGGER.debug("p2p: ICE connected to %s:%s", *addr)
                    self._send_consent(nominate=True)
                    asyncio.get_running_loop().call_later(0.3, self._send_control_burst)
            return
        segments = kcp.parse_datagram(datagram, self._media_key)
        if not segments:
            _LOGGER.debug("p2p: unrecognised datagram (%d bytes) %s", len(datagram), datagram[:48].hex())
        for segment in segments:
            conversation = self._conversations.get(segment.conversation)
            if conversation is not None:
                conversation.input(segment)

    def _send_consent(self, nominate: bool) -> None:
        if self._robot_ufrag and self._robot_pwd:
            self._send_udp(stun.binding_request(self._ufrag, self._robot_ufrag, self._robot_pwd, nominate))

    def _send_control_burst(self) -> None:
        if self._closed.is_set():
            return
        control_conv = self._conversations[kcp.CONV_CONTROL]
        for packet in control.start_packets(self._device_password, self._local_key):
            control_conv.send(packet)

    @staticmethod
    def _on_control_record(plaintext: bytes) -> None:
        packet = control.parse(plaintext)
        if packet is None:
            _LOGGER.debug("p2p: control record (%d bytes) %s", len(plaintext), plaintext[:64].hex())
            return
        _LOGGER.debug(
            "p2p: control type=%#x flag=%s sub=%#x payload=%s",
            packet.type, packet.flag, packet.sub_command, packet.payload.hex(),
        )

    def _on_map_record(self, plaintext: bytes) -> None:
        self.bytes_received += len(plaintext)
        for name, obj in self._reassembler.feed(plaintext):
            self._first_object.set()
            try:
                self._on_object(name, obj)
            except Exception:  # noqa: BLE001 - a consumer bug must not kill the channel
                _LOGGER.exception("p2p: stream consumer failed on %s", name)

    async def _housekeeping(self) -> None:
        next_consent = next_heartbeat = time.monotonic()
        try:
            while not self._closed.is_set():
                await asyncio.sleep(_TICK)
                now = time.monotonic()
                for conversation in self._conversations.values():
                    conversation.tick()
                if self._ice_up and now >= next_consent:
                    self._send_consent(nominate=True)
                    next_consent = now + _CONSENT_INTERVAL
                if now >= next_heartbeat:
                    self._send_tcp(CMD_HEARTBEAT, {"gwId": "", "devId": ""})
                    next_heartbeat = now + _HEARTBEAT_INTERVAL
                if self._first_object.is_set() and now - self._last_rx > _STALL_TIMEOUT:
                    raise P2PError(f"no traffic from the robot for {_STALL_TIMEOUT:.0f}s")
        except Exception as err:  # noqa: BLE001 - housekeeping failure ends the session
            self._fail(err)
