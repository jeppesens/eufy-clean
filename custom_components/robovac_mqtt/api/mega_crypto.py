"""Eufy Mega (Anker AIoT) cloud crypto — Python port of eufy-sdk algo_ecdh."""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import time
from dataclasses import dataclass
from typing import Any

from cryptography.hazmat.primitives import padding, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

# Bootstrap AES-128 key for the eufy_mega host stack (openapi + passport + app-*).
EUFY_MEGA_LOCAL_KEY_HEX = "2500a7d5617812f9d52515b2c8f20a3d"

# Hardcoded server P-256 uncompressed public key for one-shot login password encryption.
SERVER_STATIC_PUBLIC_KEY_HEX = (
    "04c5c00c4f8d1197cc7c3167c52bf7acb054d722f0ef08dcd7e0883236e0d72a"
    "3868d9750cb47fa4619248f3d83f0f662671dadc6e2d31c2f41db0161651c7c076"
)


def gen_id() -> str:
    """32-hex random ID for X-Key-Ident / X-Request-Once."""
    return os.urandom(16).hex()


def now_sec() -> str:
    """Current Unix timestamp in seconds as a string."""
    return str(int(time.time()))


def md5_hex(text: str) -> str:
    """Return lowercase MD5 hex digest of UTF-8 text."""
    return hashlib.md5(text.encode("utf-8")).hexdigest()


def gtoken(user_id: str) -> str:
    """Compute gtoken header = md5(user_id)."""
    return md5_hex(user_id)


def _aes_cbc_encrypt(plaintext: bytes, key: bytes, iv: bytes) -> bytes:
    """Encrypt bytes with AES-CBC and PKCS7 padding."""
    padder = padding.PKCS7(128).padder()
    padded = padder.update(plaintext) + padder.finalize()
    encryptor = Cipher(algorithms.AES(key), modes.CBC(iv)).encryptor()
    return encryptor.update(padded) + encryptor.finalize()


def _aes_cbc_decrypt(ciphertext: bytes, key: bytes, iv: bytes) -> bytes:
    """Decrypt bytes with AES-CBC and remove PKCS7 padding."""
    decryptor = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
    padded = decryptor.update(ciphertext) + decryptor.finalize()
    unpadder = padding.PKCS7(128).unpadder()
    return unpadder.update(padded) + unpadder.finalize()


def aes_key(share_key_hex: str) -> bytes:
    """First 16 bytes of the shared secret hex."""
    return bytes.fromhex(share_key_hex)[:16]


def sign_key(share_key_hex: str) -> bytes:
    """First 32 hex chars of shareKey encoded as UTF-8 bytes."""
    return share_key_hex[:32].encode("utf-8")


def encrypt_body(plaintext: str | bytes, share_key_hex: str) -> str:
    """Encrypt request body: base64(IV(16) || AES-128-CBC-PKCS7(plaintext))."""
    raw = plaintext.encode("utf-8") if isinstance(plaintext, str) else plaintext
    iv = os.urandom(16)
    ct = _aes_cbc_encrypt(raw, aes_key(share_key_hex), iv)
    return base64.b64encode(iv + ct).decode("ascii")


def decrypt_body(b64: str, share_key_hex: str) -> bytes:
    """Decrypt response data: base64(IV(16) || AES-128-CBC-PKCS7)."""
    raw = base64.b64decode(b64)
    return _aes_cbc_decrypt(raw[16:], aes_key(share_key_hex), raw[:16])


def sign_request(
    share_key_hex: str,
    ts: str,
    once: str,
    enc_body_b64: str | None = None,
) -> str:
    """Compute x-signature = HMAC-SHA256(sign_key, ts+once[+encBody])."""
    parts = [ts, once]
    if enc_body_b64:
        parts.append(enc_body_b64)
    return hmac.new(
        sign_key(share_key_hex),
        "+".join(parts).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


@dataclass
class SessionEntry:
    """Negotiated ECDH session key + X-Key-Ident."""

    key_ident: str
    share_key: str
    created_at: float


@dataclass
class KeyExchangePrep:
    """In-flight ephemeral P-256 key exchange state."""

    private_key: ec.EllipticCurvePrivateKey
    local_key: bytes
    key_ident: str
    encrypted_client_public_key: str
    client_public_key_hex: str
    headers: dict[str, str]


def prepare_key_exchange(local_key_hex: str = EUFY_MEGA_LOCAL_KEY_HEX) -> KeyExchangePrep:
    """Build an ephemeral P-256 key exchange request."""
    local_key = bytes.fromhex(local_key_hex)
    private_key = ec.generate_private_key(ec.SECP256R1())
    client_public_key_hex = private_key.public_key().public_bytes(
        serialization.Encoding.X962,
        serialization.PublicFormat.UncompressedPoint,
    ).hex()

    iv = os.urandom(16)
    ct = _aes_cbc_encrypt(client_public_key_hex.encode("utf-8"), local_key, iv)
    encrypted_client_public_key = base64.b64encode(iv + ct).decode("ascii")

    ts = now_sec()
    once = gen_id()
    key_ident = gen_id()
    sig = hmac.new(
        local_key_hex.encode("utf-8"),
        f"{ts}+{once}+{encrypted_client_public_key}".encode(),
        hashlib.sha256,
    ).hexdigest()

    return KeyExchangePrep(
        private_key=private_key,
        local_key=local_key,
        key_ident=key_ident,
        encrypted_client_public_key=encrypted_client_public_key,
        client_public_key_hex=client_public_key_hex,
        headers={
            "x-encryption-info": "algo_ecdh",
            "x-replay-info": "replay",
            "x-key-ident": key_ident,
            "x-request-ts": ts,
            "x-request-once": once,
            "x-signature": sig,
        },
    )


def finish_key_exchange(
    prep: KeyExchangePrep, server_public_key_b64: str
) -> SessionEntry:
    """Decrypt server public key and derive the 32-hex-char shareKey."""
    blob = base64.b64decode(server_public_key_b64)
    server_pub_hex = _aes_cbc_decrypt(blob[16:], prep.local_key, blob[:16]).decode("utf-8")
    server_pub = ec.EllipticCurvePublicKey.from_encoded_point(
        ec.SECP256R1(), bytes.fromhex(server_pub_hex)
    )
    shared = prep.private_key.exchange(ec.ECDH(), server_pub)
    share_key = shared.hex().zfill(64)[:32]
    return SessionEntry(
        key_ident=prep.key_ident,
        share_key=share_key,
        created_at=time.time(),
    )


def encrypt_login_password(password: str) -> tuple[str, str]:
    """Encrypt login password via one-shot ECDH against the static server key."""
    private_key = ec.generate_private_key(ec.SECP256R1())
    client_public_key_hex = private_key.public_key().public_bytes(
        serialization.Encoding.X962,
        serialization.PublicFormat.UncompressedPoint,
    ).hex()
    server_pub = ec.EllipticCurvePublicKey.from_encoded_point(
        ec.SECP256R1(), bytes.fromhex(SERVER_STATIC_PUBLIC_KEY_HEX)
    )
    shared = private_key.exchange(ec.ECDH(), server_pub)
    ct = _aes_cbc_encrypt(password.encode("utf-8"), shared, shared[:16])
    return client_public_key_hex, base64.b64encode(ct).decode("ascii")


def login_credentials(email: str, password: str, country: str) -> dict[str, Any]:
    """Build the base /passport/login credential payload."""
    client_pub_hex, encrypted_password = encrypt_login_password(password)
    return {
        "email": email,
        "password": encrypted_password,
        "ab": country,
        "client_secret_info": {"public_key": client_pub_hex},
    }


def read_login_reply(data: dict[str, Any]) -> dict[str, Any] | None:
    """Parse a decrypted /passport/login reply."""
    user_id = data.get("ap_cloud_user_id") or data.get("user_id") or data.get("userId")
    auth_token = data.get("auth_token") or data.get("token")
    if not user_id or not auth_token:
        return None
    account_user_id = data.get("user_id") or data.get("userId") or user_id
    fa_info = data.get("fa_info")
    two_factor_pending = bool(isinstance(fa_info, dict) and fa_info.get("info"))
    raw_exp = data.get("token_expires_at") or 0
    try:
        token_expires_at = float(raw_exp)
        if token_expires_at > 1e12:
            token_expires_at /= 1000.0
    except (TypeError, ValueError):
        token_expires_at = 0.0
    return {
        "user_id": str(user_id),
        "account_user_id": str(account_user_id),
        "auth_token": str(auth_token),
        "geo_key": data.get("geo_key"),
        "token_expires_at": token_expires_at,
        "two_factor_pending": two_factor_pending,
    }


def signed_headers(entry: SessionEntry, enc_body: str) -> dict[str, str]:
    """Build algo_ecdh signing headers for an encrypted body."""
    ts = now_sec()
    once = gen_id()
    return {
        "x-encryption-info": "algo_ecdh",
        "x-key-ident": entry.key_ident,
        "x-request-ts": ts,
        "x-request-once": once,
        "x-signature": sign_request(entry.share_key, ts, once, enc_body),
    }
