"""Tuya local protocol 3.3 framing for the P2P signaling (command type 32).

The signaling that sets up a P2P session (SDP offer/answer, ICE candidates) rides
the same local TCP 6668 connection as normal DPS control, but on Tuya command
type ``32``. Unlike a DP write, a type-32 frame carries **no** "3.3" extended
header: its body is just the JSON, AES-ECB encrypted under the device local key.
Adding the header makes the device answer ``"parse data error"``.

Only the little that P2P needs is implemented here, so the module stays free of
any ``tinytuya`` version quirks around unknown command bytes.
"""

from __future__ import annotations

import json
import zlib
from typing import Any

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

PREFIX = 0x000055AA
SUFFIX = 0x0000AA55

CMD_DP_QUERY = 0x0A
CMD_RTC = 0x20  # command type 32: P2P / "thing.m.rtc" signaling


def _aes_ecb_encrypt(key: bytes, data: bytes) -> bytes:
    pad = 16 - (len(data) % 16)
    data += bytes([pad]) * pad
    enc = Cipher(algorithms.AES(key), modes.ECB()).encryptor()
    return enc.update(data) + enc.finalize()


def _aes_ecb_decrypt(key: bytes, data: bytes) -> bytes:
    dec = Cipher(algorithms.AES(key), modes.ECB()).decryptor()
    out = dec.update(data) + dec.finalize()
    if out and 1 <= out[-1] <= 16:
        out = out[: -out[-1]]
    return out


def encode_frame(local_key: bytes, command: int, payload: dict[str, Any] | bytes, sequence: int) -> bytes:
    """Encode one Tuya 3.3 local frame (no 3.3 header, as type-32 uses)."""
    body = payload if isinstance(payload, bytes) else json.dumps(payload, separators=(",", ":")).encode()
    body = _aes_ecb_encrypt(local_key, body)
    frame = bytearray()
    frame += PREFIX.to_bytes(4, "big")
    frame += sequence.to_bytes(4, "big")
    frame += command.to_bytes(4, "big")
    frame += (len(body) + 8).to_bytes(4, "big")
    frame += body
    frame += (zlib.crc32(bytes(frame)) & 0xFFFFFFFF).to_bytes(4, "big")
    frame += SUFFIX.to_bytes(4, "big")
    return bytes(frame)


def decode_frames(local_key: bytes, buffer: bytes) -> tuple[list[tuple[int, Any]], bytes]:
    """Decode every whole frame in ``buffer``.

    Returns the decoded ``(command, payload)`` pairs and the unconsumed tail.
    A type-32 payload comes back as a parsed JSON object; anything else as bytes.
    """
    out: list[tuple[int, Any]] = []
    pos = 0
    marker = PREFIX.to_bytes(4, "big")
    while True:
        start = buffer.find(marker, pos)
        if start < 0 or start + 16 > len(buffer):
            break
        length = int.from_bytes(buffer[start + 12 : start + 16], "big")
        end = start + 16 + length
        if end > len(buffer):
            break
        command = int.from_bytes(buffer[start + 8 : start + 12], "big")
        body = buffer[start + 16 : end - 8]  # drop crc(4) + suffix(4)
        # Device-originated frames carry a 4-byte return code before the encrypted
        # payload; the ciphertext is block-aligned, so a 4-byte remainder is it.
        if len(body) % 16 == 4:
            body = body[4:]
        payload: Any = body
        if body:
            try:
                plain = _aes_ecb_decrypt(local_key, body)
                if plain[:3] == b"3.3":
                    plain = plain[15:]
                payload = json.loads(plain)
            except Exception:  # noqa: BLE001 - non-JSON frames (status, heartbeat) are ignored
                payload = body
        out.append((command, payload))
        pos = end
    return out, buffer[pos:]
