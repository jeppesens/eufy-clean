"""Eufy local socket protocol client for map data retrieval.

The T2351 (and similar AIOT devices) expose a local TCP socket on port 9668
that uses protobuf-based challenge-response authentication. After auth,
map pixel data flows as MapChannelMsg messages - this is the "P2P" channel
referenced in the protobuf comments.

Protocol flow (from T2351.js getX10AIotProductInfo + socket.proto):
1. Client connects TCP to device_ip:9668
2. Client sends BtAppMsg{GetProductInfo} (client initiates!)
3. Device responds with BtRobotMsg{ProductInfo} + 12-char random challenge
4. Client sends SocketVerify{random, device_sn, user_id}
5. Device sends auth result (BtRobotMsg with ret=E_OK/E_FAIL)
6. Client sends DPS command (MAP_GET_ALL)
7. Device streams MapChannelMsg messages with map data
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from ..proto.cloud.ble_pb2 import BtAppMsg, BtRobotMsg
from ..proto.cloud.multi_maps_pb2 import (
    MultiMapsManageRequest,
    MultiMapsManageResponse,
)
from ..proto.cloud.p2pdata_pb2 import MapChannelMsg
from ..proto.cloud.socket_pb2 import SocketTransData, SocketVerify

_LOGGER = logging.getLogger(__name__)

# The local socket port used by Eufy AIOT devices
LOCAL_SOCKET_PORT = 9668


def _encode_varint(value: int) -> bytes:
    """Encode an integer as a protobuf varint."""
    result = bytearray()
    while value > 0x7F:
        result.append((value & 0x7F) | 0x80)
        value >>= 7
    result.append(value & 0x7F)
    return bytes(result)


def _decode_varint(data: bytes, offset: int = 0) -> tuple[int, int]:
    """Decode a varint from data at offset. Returns (value, bytes_consumed)."""
    value = 0
    shift = 0
    pos = offset
    while pos < len(data):
        byte = data[pos]
        value |= (byte & 0x7F) << shift
        pos += 1
        if not (byte & 0x80):
            break
        shift += 7
    return value, pos - offset


def _write_delimited(msg) -> bytes:
    """Serialize a protobuf message with varint length prefix."""
    serialized = msg.SerializeToString()
    return _encode_varint(len(serialized)) + serialized


class EufyLocalClient:
    """Connects to the vacuum's local socket for map data retrieval."""

    def __init__(
        self,
        device_ip: str,
        device_sn: str,
        user_id: str,
    ) -> None:
        self.device_ip = device_ip
        self.device_sn = device_sn
        self.user_id = user_id
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None

    async def connect(self) -> bool:
        """Connect and authenticate to the device's local socket."""
        try:
            _LOGGER.warning(
                "Connecting to %s:%d for local map data...",
                self.device_ip, LOCAL_SOCKET_PORT,
            )
            self._reader, self._writer = await asyncio.wait_for(
                asyncio.open_connection(self.device_ip, LOCAL_SOCKET_PORT),
                timeout=10,
            )

            # Step 1: Client sends BtAppMsg.GetProductInfo first (device waits for this)
            get_info = BtAppMsg.GetProductInfo(get=True)
            try:
                get_info.remedy_field.CopyFrom(
                    BtAppMsg.GetProductInfo.RemedyField(distribute_version2=1)
                )
                get_info.country.CopyFrom(
                    BtAppMsg.GetProductInfo.Country(code="SE")
                )
                get_info.support_ack = True
            except Exception:
                pass  # Optional fields

            app_msg = BtAppMsg(get_product_info=get_info)
            self._writer.write(_write_delimited(app_msg))
            await self._writer.drain()
            _LOGGER.warning("Sent BtAppMsg.GetProductInfo")

            # Step 2: Device responds with BtRobotMsg{ProductInfo} + 12-char random
            response_data = await self._read_response(timeout=10)
            if not response_data:
                _LOGGER.warning("No response after GetProductInfo")
                return False

            _LOGGER.warning(
                "Device response: %d bytes, hex=%s",
                len(response_data), response_data[:80].hex(),
            )

            # Parse response for product info and challenge
            random_str = self._extract_challenge(response_data)
            product_ok = self._check_auth_response(response_data)

            _LOGGER.warning(
                "ProductInfo OK=%s, challenge=%s",
                product_ok, random_str or "(none)",
            )

            # Step 3: Send SocketVerify
            verify = SocketVerify(
                random=random_str or "",
                device_sn=self.device_sn,
                user_id=self.user_id,
            )
            self._writer.write(_write_delimited(verify))
            await self._writer.drain()
            _LOGGER.warning("Sent SocketVerify")

            # Step 4: Receive auth result
            auth_data = await self._read_response(timeout=5)
            if auth_data:
                _LOGGER.warning(
                    "Auth result: %d bytes, hex=%s",
                    len(auth_data), auth_data[:50].hex(),
                )
                auth_ok = self._check_auth_response(auth_data)
            else:
                _LOGGER.warning("No explicit auth result (assuming OK if product_info was OK)")
                auth_ok = product_ok

            if auth_ok:
                _LOGGER.warning("Local socket authentication SUCCESS")
            else:
                _LOGGER.warning("Local socket authentication FAILED")
            return auth_ok

        except asyncio.TimeoutError:
            _LOGGER.warning("Timeout connecting to %s:%d", self.device_ip, LOCAL_SOCKET_PORT)
            return False
        except OSError as exc:
            _LOGGER.warning("Connection to %s:%d failed: %s", self.device_ip, LOCAL_SOCKET_PORT, exc)
            return False
        except Exception as exc:
            _LOGGER.warning("Local connect error: %s", exc, exc_info=True)
            return False

    async def _read_response(self, timeout: float = 5) -> bytes | None:
        """Read available data from the socket with timeout."""
        if not self._reader:
            return None
        data = bytearray()
        try:
            chunk = await asyncio.wait_for(self._reader.read(4096), timeout=timeout)
            if chunk:
                data.extend(chunk)
                # Try to read more with a short timeout
                try:
                    more = await asyncio.wait_for(self._reader.read(4096), timeout=0.5)
                    if more:
                        data.extend(more)
                except asyncio.TimeoutError:
                    pass
        except asyncio.TimeoutError:
            pass
        return bytes(data) if data else None

    def _extract_challenge(self, data: bytes) -> str | None:
        """Extract the 12-char random challenge from device response.

        The response may contain multiple varint-delimited messages.
        The challenge is a 12-char alphanumeric string, either as raw bytes
        after the protobuf message, or within a SocketVerify protobuf.
        """
        # Try as raw 12-char ASCII
        if len(data) == 12:
            try:
                return data.decode("ascii")
            except UnicodeDecodeError:
                pass

        # Try to skip past a varint-delimited protobuf message to find the challenge after it
        try:
            length, consumed = _decode_varint(data)
            after_msg = consumed + length
            if after_msg < len(data):
                remainder = data[after_msg:]
                # Check if remainder starts with a varint-delimited challenge
                try:
                    rlen, rconsumed = _decode_varint(remainder)
                    if rlen == 12 and rconsumed + rlen <= len(remainder):
                        candidate = remainder[rconsumed:rconsumed + rlen]
                        try:
                            return candidate.decode("ascii")
                        except UnicodeDecodeError:
                            pass
                except Exception:
                    pass
                # Or raw 12 bytes
                if len(remainder) >= 12:
                    candidate = remainder[:12]
                    try:
                        s = candidate.decode("ascii")
                        if s.isalnum():
                            return s
                    except UnicodeDecodeError:
                        pass
        except Exception:
            pass

        # Try parsing as SocketVerify
        for try_strip_varint in [True, False]:
            try:
                if try_strip_varint:
                    length, consumed = _decode_varint(data)
                    inner = data[consumed:consumed + length]
                else:
                    inner = data
                sv = SocketVerify()
                sv.ParseFromString(inner)
                if sv.random and len(sv.random) >= 8:
                    return sv.random
            except Exception:
                pass

        # Last resort: scan for 12-char alphanumeric sequences
        try:
            text = data.decode("ascii", errors="replace")
            for i in range(max(0, len(text) - 11)):
                candidate = text[i:i + 12]
                if len(candidate) == 12 and candidate.isalnum():
                    return candidate
        except Exception:
            pass

        return None

    def _check_auth_response(self, data: bytes) -> bool:
        """Check if the response contains BtRobotMsg{ProductInfo{ret=E_OK}}."""
        for try_strip_varint in [True, False]:
            try:
                if try_strip_varint:
                    length, consumed = _decode_varint(data)
                    inner = data[consumed:consumed + length]
                else:
                    inner = data
                msg = BtRobotMsg()
                msg.ParseFromString(inner)
                if msg.HasField("product_info"):
                    ret = msg.product_info.ret
                    _LOGGER.info(
                        "ProductInfo: ret=%s, brand=%s, model=%s, name=%s",
                        BtRobotMsg.ProductInfo.Result.Name(ret),
                        msg.product_info.brand,
                        msg.product_info.code_name,
                        msg.product_info.name,
                    )
                    return ret == BtRobotMsg.ProductInfo.Result.E_OK
            except Exception:
                pass
        return False

    async def request_map(self) -> list[Any] | None:
        """Request map data after authentication.

        Sends MAP_GET_ALL via DPS 170 and collects MapChannelMsg responses.
        Returns a list of CompleteMap objects, or None on failure.
        """
        if not self._reader or not self._writer:
            return None

        try:
            req = MultiMapsManageRequest(method=MultiMapsManageRequest.MAP_GET_ALL)

            # Send as SocketTransData{type=E_DP} + raw MAP_GET_ALL request
            trans = SocketTransData(type=SocketTransData.E_DP)
            self._writer.write(_write_delimited(trans))
            self._writer.write(_write_delimited(req))
            await self._writer.drain()
            _LOGGER.warning("Sent MAP_GET_ALL request")

            # Collect responses
            complete_maps: list[Any] = []
            map_infos: list[Any] = []
            buffer = bytearray()
            deadline = asyncio.get_event_loop().time() + 30

            while asyncio.get_event_loop().time() < deadline:
                try:
                    chunk = await asyncio.wait_for(self._reader.read(65536), timeout=5)
                    if not chunk:
                        break
                    buffer.extend(chunk)
                    _LOGGER.debug("Received %d bytes (buffer: %d)", len(chunk), len(buffer))

                    while len(buffer) > 1:
                        parsed = self._try_parse_message(buffer)
                        if parsed is None:
                            break
                        msg_type, msg_obj = parsed
                        if msg_type == "map_channel":
                            mcm = msg_obj
                            if mcm.type == MapChannelMsg.MULTI_MAP_RESPONSE:
                                resp = MultiMapsManageResponse()
                                resp.ParseFromString(mcm.multi_map_response)
                                _LOGGER.warning(
                                    "MULTI_MAP_RESPONSE: method=%s result=%s has_maps=%s",
                                    resp.method, resp.result, resp.HasField("complete_maps"),
                                )
                                if resp.HasField("complete_maps"):
                                    for cm in resp.complete_maps.complete_map:
                                        complete_maps.append(cm)
                                        _LOGGER.warning(
                                            "CompleteMap: %dx%d has_map=%s has_outline=%s",
                                            cm.map_width, cm.map_height,
                                            cm.HasField("map"), cm.HasField("room_outline"),
                                        )
                            elif mcm.type == MapChannelMsg.MAP_INFO:
                                map_infos.append(mcm.map_info)
                                _LOGGER.warning(
                                    "MAP_INFO: type=%s %dx%d id=%d",
                                    mcm.map_info.msg_type, mcm.map_info.map_width,
                                    mcm.map_info.map_height, mcm.map_info.map_id,
                                )
                except asyncio.TimeoutError:
                    if complete_maps or map_infos:
                        break
                    continue

            if complete_maps:
                _LOGGER.warning("Local map SUCCESS: %d CompleteMap(s)", len(complete_maps))
                return complete_maps
            if map_infos:
                _LOGGER.warning("Got %d MapInfo but no CompleteMaps", len(map_infos))
                return map_infos
            _LOGGER.warning("No map data received from local socket")
            return None

        except Exception as exc:
            _LOGGER.warning("Map request error: %s", exc, exc_info=True)
            return None

    def _try_parse_message(self, buffer: bytearray) -> tuple[str, Any] | None:
        """Parse next varint-delimited message from buffer. Returns None if incomplete."""
        if len(buffer) < 2:
            return None
        try:
            length, consumed = _decode_varint(bytes(buffer))
            total = consumed + length
            if total > len(buffer):
                return None
            inner = bytes(buffer[consumed:total])
            del buffer[:total]

            # Try MapChannelMsg
            try:
                mcm = MapChannelMsg()
                mcm.ParseFromString(inner)
                if mcm.type in (MapChannelMsg.MAP_INFO, MapChannelMsg.MULTI_MAP_RESPONSE):
                    return ("map_channel", mcm)
            except Exception:
                pass

            # Try MultiMapsManageResponse directly
            try:
                resp = MultiMapsManageResponse()
                resp.ParseFromString(inner)
                if resp.HasField("complete_maps") or resp.method:
                    mcm = MapChannelMsg()
                    mcm.type = MapChannelMsg.MULTI_MAP_RESPONSE
                    mcm.multi_map_response = inner
                    return ("map_channel", mcm)
            except Exception:
                pass

            return ("raw", inner)
        except Exception:
            del buffer[:1]
            return ("raw", b"")

    async def disconnect(self) -> None:
        """Close the local socket connection."""
        if self._writer:
            try:
                self._writer.close()
                await self._writer.wait_closed()
            except Exception:
                pass
            self._writer = None
            self._reader = None
            _LOGGER.debug("Local socket disconnected")
