"""Unit tests for the Eufy Mega (v6) crypto and HTTP client."""

from __future__ import annotations

import base64
import json
import os
import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from custom_components.robovac_mqtt.api.mega_crypto import (
    EUFY_MEGA_LOCAL_KEY_HEX,
    _aes_cbc_decrypt,
    _aes_cbc_encrypt,
    decrypt_body,
    encrypt_body,
    encrypt_login_password,
    finish_key_exchange,
    gtoken,
    prepare_key_exchange,
    read_login_reply,
    sign_request,
)
from custom_components.robovac_mqtt.api.mega_http import (
    CODE_CAPTCHA_REQUIRED,
    CODE_IDENTITY_KEY_STALE,
    CODE_SIGNATURE_INVALID,
    MegaCaptchaRequiredError,
    MegaHTTPClient,
    MegaTwoFactorRequiredError,
)


class _FakeMegaServer:
    """In-memory Mega gateway that performs real algo_ecdh crypto."""

    def __init__(self) -> None:
        self.server_priv = ec.generate_private_key(ec.SECP256R1())
        self.server_pub_hex = self.server_priv.public_key().public_bytes(
            serialization.Encoding.X962,
            serialization.PublicFormat.UncompressedPoint,
        ).hex()
        self.share_key: str | None = None
        self.key_exchanges = 0
        self.calls: list[tuple[str, dict[str, str]]] = []
        self.fail_first_ct = False
        self.fail_first_identity = False

    def handle_post(
        self, url: str, data: bytes | str, headers: dict[str, str]
    ) -> tuple[int, dict[str, Any]]:
        self.calls.append((url, dict(headers)))
        raw_text = data.decode("utf-8") if isinstance(data, bytes) else data

        if url.endswith("/passport/estimate_domain"):
            return 200, {
                "code": 0,
                "data": {"domain": "app-openapi-eu-pr.eufy.com"},
            }

        if url.endswith("/openapi/oauth/key/exchange"):
            self.key_exchanges += 1
            body = json.loads(raw_text)
            local_key = bytes.fromhex(EUFY_MEGA_LOCAL_KEY_HEX)
            blob = base64.b64decode(body["client_public_key"])
            client_pub_hex = _aes_cbc_decrypt(blob[16:], local_key, blob[:16]).decode(
                "utf-8"
            )
            client_pub = ec.EllipticCurvePublicKey.from_encoded_point(
                ec.SECP256R1(), bytes.fromhex(client_pub_hex)
            )
            shared = self.server_priv.exchange(ec.ECDH(), client_pub)
            self.share_key = shared.hex().zfill(64)[:32]

            iv = os.urandom(16)
            enc_server = base64.b64encode(
                iv
                + _aes_cbc_encrypt(
                    self.server_pub_hex.encode("utf-8"), local_key, iv
                )
            ).decode("ascii")
            return 200, {"code": 0, "data": {"server_public_key": enc_server}}

        assert self.share_key is not None
        if self.fail_first_ct:
            self.fail_first_ct = False
            return 403, {"code": CODE_SIGNATURE_INVALID, "msg": "signature invalid"}

        if self.fail_first_identity:
            self.fail_first_identity = False
            return 463, {"code": CODE_IDENTITY_KEY_STALE, "msg": "get identity error"}

        req = json.loads(decrypt_body(raw_text, self.share_key).decode("utf-8"))
        payload: dict[str, Any]

        if url.endswith("/passport/generate/captcha"):
            payload = {"captcha_id": "cap_1", "item": "iVBORw0KGgo="}
            return 200, {
                "code": 0,
                "data": encrypt_body(json.dumps(payload), self.share_key),
            }

        if url.endswith("/passport/login"):
            if not req.get("captcha_id") and not req.get("verify_code"):
                return 200, {"code": CODE_CAPTCHA_REQUIRED, "msg": "captcha required"}
            if req.get("captcha_id") and not req.get("verify_code"):
                assert req["answer"] == "ABCD"
                payload = {
                    "user_id": "acc_1",
                    "ap_cloud_user_id": "ap_1",
                    "auth_token": "pre_2fa_token",
                    "fa_info": {"info": "email"},
                }
                return 200, {
                    "code": 0,
                    "data": encrypt_body(json.dumps(payload), self.share_key),
                }
            assert req["verify_code"] == "654321"
            assert headers.get("x-auth-token") == "pre_2fa_token"
            payload = {
                "user_id": "acc_1",
                "ap_cloud_user_id": "ap_1",
                "auth_token": "final_token",
                "token_expires_at": int(time.time()) + 86400,
                "fa_info": {},
            }
            return 200, {
                "code": 0,
                "data": encrypt_body(json.dumps(payload), self.share_key),
            }

        if url.endswith("/app/sendmsg/verify_code"):
            assert headers.get("x-auth-token") == "pre_2fa_token"
            return 200, {"code": 0, "data": ""}

        if url.endswith("/app/house/get_house_list"):
            payload = {"house_infos": [{"house_id": "h1"}]}
            return 200, {
                "code": 0,
                "data": encrypt_body(json.dumps(payload), self.share_key),
            }

        if url.endswith("/app/house/get_devs_list"):
            devices = (
                [
                    {
                        "device_sn": "VAC001",
                        "device_model": "T2351",
                        "alias_name": "Downstairs Vac",
                        "category": "eufy_home",
                        "main_sw_version": "2.1.0",
                    },
                    {
                        "device_sn": "CAM001",
                        "device_model": "T8160",
                        "device_name": "Front Cam",
                        "category": "eufy_security",
                    },
                ]
                if req.get("house_id") == "h1"
                else []
            )
            return 200, {
                "code": 0,
                "data": encrypt_body(json.dumps({"devices": devices}), self.share_key),
            }

        if url.endswith("/app/devicerelation/get_device_list"):
            payload = {
                "devices": [
                    {
                        "device": {
                            "device_sn": "VAC001",
                            "device_model": "T2351",
                            "dps": {"163": 95},
                        }
                    }
                ]
            }
            return 200, {
                "code": 0,
                "data": encrypt_body(json.dumps(payload), self.share_key),
            }

        if url.endswith("/app/devicemanage/get_user_mqtt_info"):
            payload = {
                "endpoint_addr": "aiot-mqtt-eu.anker.com",
                "certificate_pem": "CERT",
                "private_key": "KEY",
            }
            return 200, {
                "code": 0,
                "data": encrypt_body(json.dumps(payload), self.share_key),
            }

        raise AssertionError(f"Unhandled URL: {url}")


def _fake_websession(server: _FakeMegaServer) -> MagicMock:
    def _post(url: str, *, data: Any = None, headers: Any = None, timeout: Any = None):
        status, payload = server.handle_post(url, data or b"", headers or {})
        resp = AsyncMock()
        resp.status = status
        resp.text = AsyncMock(return_value=json.dumps(payload))
        ctx = MagicMock()
        ctx.__aenter__ = AsyncMock(return_value=resp)
        ctx.__aexit__ = AsyncMock(return_value=False)
        return ctx

    session = MagicMock()
    session.post.side_effect = _post
    return session


# --- Crypto tests ---


def test_ecdh_key_exchange_and_body_roundtrip():
    """prepare_key_exchange + finish_key_exchange derive matching shareKeys."""
    prep = prepare_key_exchange()
    local_key = bytes.fromhex(EUFY_MEGA_LOCAL_KEY_HEX)

    # Server decrypts client public key and replies with its own encrypted key.
    blob = base64.b64decode(prep.encrypted_client_public_key)
    client_pub_hex = _aes_cbc_decrypt(blob[16:], local_key, blob[:16]).decode("utf-8")
    assert client_pub_hex == prep.client_public_key_hex

    server_priv = ec.generate_private_key(ec.SECP256R1())
    server_pub_hex = server_priv.public_key().public_bytes(
        serialization.Encoding.X962,
        serialization.PublicFormat.UncompressedPoint,
    ).hex()
    client_pub = ec.EllipticCurvePublicKey.from_encoded_point(
        ec.SECP256R1(), bytes.fromhex(client_pub_hex)
    )
    expected_share = server_priv.exchange(ec.ECDH(), client_pub).hex().zfill(64)[:32]

    iv = os.urandom(16)
    enc_server = base64.b64encode(
        iv + _aes_cbc_encrypt(server_pub_hex.encode("utf-8"), local_key, iv)
    ).decode("ascii")

    entry = finish_key_exchange(prep, enc_server)
    assert entry.share_key == expected_share
    assert entry.key_ident == prep.key_ident

    enc = encrypt_body('{"hello":"world"}', entry.share_key)
    assert decrypt_body(enc, entry.share_key) == b'{"hello":"world"}'
    sig1 = sign_request(entry.share_key, "1700000000", "nonce", enc)
    sig2 = sign_request(entry.share_key, "1700000000", "nonce")
    assert len(sig1) == 64
    assert sig1 != sig2


def test_encrypt_login_password_and_read_login_reply():
    """Login password produces uncompressed P-256 key + base64 ciphertext."""
    pub_hex, enc_pw = encrypt_login_password("my-secret")
    assert pub_hex.startswith("04")
    assert len(pub_hex) == 130
    assert len(base64.b64decode(enc_pw)) >= 16

    reply = read_login_reply(
        {
            "user_id": "u_acc",
            "ap_cloud_user_id": "u_ap",
            "auth_token": "tok",
            "token_expires_at": 1_800_000_000_000,
            "fa_info": {"info": "email"},
        }
    )
    assert reply is not None
    assert reply["user_id"] == "u_ap"
    assert reply["account_user_id"] == "u_acc"
    assert reply["two_factor_pending"] is True
    assert reply["token_expires_at"] == 1_800_000_000.0
    assert len(gtoken("u_acc")) == 32


# --- MegaHTTPClient tests ---


@pytest.mark.asyncio
async def test_mega_login_captcha_2fa_persist_and_restore():
    """Full login handshake: estimate_domain -> captcha -> 2FA -> session persist."""
    server = _FakeMegaServer()
    saved_snapshots: list[dict[str, Any]] = []
    client = MegaHTTPClient(
        email="user@example.com",
        password="secret",
        websession=_fake_websession(server),
        country_code="GB",
        openudid="0123456789abcdef",
        on_session_updated=saved_snapshots.append,
    )

    with pytest.raises(MegaCaptchaRequiredError) as cap_err:
        await client.login()
    assert cap_err.value.captcha_id == "cap_1"
    assert cap_err.value.image.startswith("data:image/png;base64,")

    with pytest.raises(MegaTwoFactorRequiredError) as tfa_err:
        await client.solve_captcha("ABCD")
    assert tfa_err.value.method == "email"

    result = await client.submit_verify_code("654321")
    assert result["access_token"] == "final_token"
    assert result["user_id"] == "acc_1"
    assert server.key_exchanges == 2  # initial anon + post-login authed re-exchange
    assert len(saved_snapshots) == 1

    # Restoring the saved session skips all network calls.
    restored_session_mock = MagicMock()
    restored = MegaHTTPClient(
        email="user@example.com",
        password="secret",
        websession=restored_session_mock,
        country_code="GB",
        openudid="0123456789abcdef",
        session_data=saved_snapshots[-1],
    )
    assert restored.has_valid_session is True
    res2 = await restored.login()
    assert res2["restored"] is True
    restored_session_mock.post.assert_not_called()


@pytest.mark.asyncio
async def test_mega_content_type_probe_and_4404_reexchange():
    """post_signed recovers from 4416 content-type probe and 4404 stale key_ident."""
    server = _FakeMegaServer()
    client = MegaHTTPClient(
        email="user@example.com",
        password="secret",
        websession=_fake_websession(server),
        country_code="GB",
        openudid="0123456789abcdef",
    )
    client.user_id = "ap_1"
    client.account_user_id = "acc_1"
    client.auth_token = "final_token"
    client._domain_estimated = True

    await client.ensure_session_key()
    assert server.key_exchanges == 1

    # 4416 forces content-type fallback; next call uses the cached content-type.
    server.fail_first_ct = True
    creds = await client.get_user_mqtt_info()
    assert creds["endpoint_addr"] == "aiot-mqtt-eu.anker.com"
    assert creds["thing_name"] == "ap_1-eufy_mega"

    # 4404 triggers a one-shot ECDH re-exchange and retries transparently.
    server.fail_first_identity = True
    devices = await client.discover_vacuum_devices()
    assert server.key_exchanges == 2
    assert len(devices) == 1
    assert devices[0]["device_sn"] == "VAC001"
    assert devices[0]["alias_name"] == "Downstairs Vac"
    assert devices[0]["dps"] == {"163": 95}
