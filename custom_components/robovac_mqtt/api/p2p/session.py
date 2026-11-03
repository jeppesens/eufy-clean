"""Drive one P2P session on the LAN and return the room list.

Ties the pieces together: signaling over TCP 6668, ICE and the tagged KCP media
over a UDP pair, the conversation-0 control burst, then reassembly of the
conversation-5 map stream into the rooms. Everything is generated fresh (our own
AES media key); nothing from a prior capture is reused except the fixed,
secret-free control packets in :mod:`control`.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import secrets
import socket
import time

from . import control, kcp, stun
from .framing import CMD_DP_QUERY, CMD_RTC, decode_frames, encode_frame
from .mapdata import extract_rooms

_LOGGER = logging.getLogger(__name__)

ROBOT_PORT = 6668
_ALNUM = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"
_DEFAULT_LOG = {"api": "thing.m.rtc.log", "interval": 60, "size": 1024, "level": 2, "topic": "/av/moto/log"}


def _random(length: int) -> str:
    return "".join(secrets.choice(_ALNUM) for _ in range(length))


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


class _UdpProtocol(asyncio.DatagramProtocol):
    def __init__(self, queue: asyncio.Queue) -> None:
        self._queue = queue

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        self._queue.put_nowait(data)


async def fetch_snapshot(
    host: str,
    local_key: str,
    device_id: str,
    user_id: str,
    device_password: str,
    *,
    ice_config: dict | None = None,
    host_ip: str | None = None,
    timeout: float = 20.0,
    grace: float = 1.5,
) -> bytes:
    """Open a P2P session to ``host`` and return the conversation-5 byte stream.

    ``user_id`` is the account identity the offer is sent as. ``device_password``
    is the RTC-config password used to derive the conversation-0 credential.
    ``ice_config`` supplies the offer's ``token`` / ``tcp_token`` / ``log`` from
    the RTC config; without its ICE servers the device answers but never gathers
    its host candidate. The device pushes the whole map in one burst; we keep
    collecting for ``grace`` seconds after the first map segment, then return the
    reassembled stream. Raises :class:`TimeoutError` if no map arrives.
    """
    key = local_key.encode()
    media_key = os.urandom(16)
    media_key_hex = media_key.hex()
    ufrag, password = _random(4), _random(24)
    session_id = f"{device_id}{int(time.time())}{_random(8)}"
    trace_id = f"ipc_p2p_ios_{device_id}_{int(time.time())}000"
    cfg = ice_config or {}

    loop = asyncio.get_running_loop()
    udp_queue: asyncio.Queue = asyncio.Queue()
    if host_ip is None:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect((host, ROBOT_PORT))
            host_ip = probe.getsockname()[0]
    transport, _ = await loop.create_datagram_endpoint(lambda: _UdpProtocol(udp_queue), local_addr=(host_ip, 0))
    our_udp_port = transport.get_extra_info("sockname")[1]

    reader, writer = await asyncio.open_connection(host, ROBOT_PORT)
    state: dict = {"robot_ufrag": None, "robot_pwd": None, "robot_addr": None, "ice_up": False, "conv0_sent": False}
    conv5: dict[int, bytes] = {}
    receive_next = {kcp.CONV_CONTROL: 0, kcp.CONV_MAP: 0}

    def send_udp(datagram: bytes) -> None:
        if state["robot_addr"]:
            transport.sendto(datagram, state["robot_addr"])

    def send_conv0() -> None:
        if state["conv0_sent"]:
            return
        state["conv0_sent"] = True
        for sequence, packet in enumerate(control.start_packets(device_password, local_key)):
            send_udp(kcp.build_push(media_key, kcp.CONV_CONTROL, sequence, packet))

    async def signaling() -> None:
        sequence = 1
        writer.write(encode_frame(key, CMD_DP_QUERY, {"gwId": device_id, "devId": device_id}, sequence))
        sequence += 1
        offer = {
            "msg": {
                "sdp": _build_offer_sdp(session_id, ufrag, password, media_key_hex, user_id),
                "preconnect": True,
                "token": cfg.get("token", []),
                "tcp_token": cfg.get("tcp_token", {}),
                "log": cfg.get("log", _DEFAULT_LOG),
            },
            "header": {
                "from": user_id, "sessionid": session_id, "is_pre": 0, "p2p_skill": 67,
                "path": "lan", "security_level": 3, "type": "offer", "to": device_id,
                "moto_id": "", "trace_id": trace_id,
            },
        }
        writer.write(encode_frame(key, CMD_RTC, offer, sequence))
        sequence += 1
        candidate = {
            "msg": {"candidate": f"a=candidate:{secrets.randbelow(2_000_000_000)} 1 UDP 2130706431 {host_ip} {our_udp_port} typ host\r\n"},
            "header": {"from": user_id, "sessionid": session_id, "path": "lan", "sub_dev_id": "", "type": "candidate", "to": device_id, "trace_id": trace_id},
        }
        await writer.drain()
        await asyncio.sleep(0.4)
        writer.write(encode_frame(key, CMD_RTC, candidate, sequence))
        await writer.drain()
        _LOGGER.debug("p2p: offer and candidate sent to %s", host)

        buffer = b""
        while True:
            chunk = await reader.read(65536)
            if not chunk:
                return
            buffer += chunk
            frames, buffer = decode_frames(key, buffer)
            for command, payload in frames:
                if command != CMD_RTC or not isinstance(payload, dict):
                    continue
                header, msg = payload.get("header", {}), payload.get("msg", {})
                if header.get("type") == "answer":
                    sdp = msg.get("sdp", "")
                    state["robot_ufrag"] = (re.search(r"ice-ufrag:(\S+)", sdp) or [None, None])[1]
                    pwd = re.search(r"ice-pwd:(\S+)", sdp)
                    state["robot_pwd"] = pwd.group(1).encode() if pwd else None
                elif header.get("type") == "candidate":
                    match = re.search(r"(\d+\.\d+\.\d+\.\d+) (\d+) typ host", msg.get("candidate", ""))
                    if match and match.group(1) == host and state["robot_pwd"]:
                        state["robot_addr"] = (match.group(1), int(match.group(2)))
                        send_udp(stun.binding_request(ufrag, state["robot_ufrag"], state["robot_pwd"], False))

    def assembled() -> bytes:
        return b"".join(conv5[sn] for sn in sorted(conv5))

    async def media() -> bytes:
        deadline: float | None = None
        while True:
            wait = None if deadline is None else max(0.0, deadline - loop.time())
            try:
                datagram = await asyncio.wait_for(udp_queue.get(), wait)
            except asyncio.TimeoutError:
                return assembled()  # grace elapsed after the map burst
            if stun.is_stun(datagram):
                if stun.message_type(datagram) == stun.BIND_REQUEST and state["robot_addr"]:
                    send_udp(stun.binding_success(datagram, state["robot_addr"][0], state["robot_addr"][1], password.encode()))
                    if not state["ice_up"]:
                        state["ice_up"] = True
                        _LOGGER.debug("p2p: ICE connected, opening control channel")
                        send_udp(stun.binding_request(ufrag, state["robot_ufrag"], state["robot_pwd"], True))
                        loop.call_later(0.3, send_conv0)
                continue
            for segment in kcp.parse_datagram(datagram):
                if segment.command != kcp.CMD_PUSH:
                    continue
                send_udp(kcp.build_ack(segment.conversation, segment.sequence, receive_next[segment.conversation]))
                if segment.conversation != kcp.CONV_MAP:
                    continue
                conv5[segment.sequence] = kcp.decrypt_record(media_key, segment.data)
                while receive_next[kcp.CONV_MAP] in conv5:
                    receive_next[kcp.CONV_MAP] += 1
                if deadline is None:
                    deadline = loop.time() + grace

    async def signaling_guard() -> None:
        try:
            await signaling()
        except Exception:  # noqa: BLE001 - surface signaling failures without killing the media wait
            _LOGGER.exception("p2p: signaling failed")

    signaling_task = asyncio.ensure_future(signaling_guard())
    try:
        return await asyncio.wait_for(media(), timeout)
    finally:
        signaling_task.cancel()
        transport.close()
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:  # noqa: BLE001 - closing a half-open socket may raise
            pass


async def fetch_rooms(*args, **kwargs) -> list[dict]:
    """Open a P2P session and return ``[{"id", "name"}, ...]`` (empty if none)."""
    return extract_rooms(await fetch_snapshot(*args, **kwargs)) or []
