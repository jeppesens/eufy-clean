import asyncio
import base64
import hashlib
import hmac
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from cryptography.hazmat.primitives.asymmetric import padding as asym_padding
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from custom_components.robovac_mqtt.api.tuya_cloud import uid_password_md5
from custom_components.robovac_mqtt.api.tuya_thing import (
    TuyaThingClient,
    TuyaThingError,
    _build_canonical,
    _calc_sign,
    _decrypt_gcm,
    _encrypt_gcm,
    _encrypt_password_pkcs1,
    _get_prelogin_key,
    _get_session_key,
    _mobile_hash,
)
from custom_components.robovac_mqtt.const import TUYA_THING_SALT

SAMPLE_RID = "0fc238c7-d8c4-4898-8477-32297732ddf5"
SAMPLE_ECODE = b"z2z6z21241122714"


def test_get_session_key_derivation():
    """Verify session key derivation matches captured key."""
    key = _get_session_key(SAMPLE_RID, SAMPLE_ECODE)
    expected = hmac.new(
        SAMPLE_RID.encode(),
        TUYA_THING_SALT + b"_" + SAMPLE_ECODE,
        hashlib.sha256,
    ).hexdigest()[:16].encode()
    assert key == expected
    assert len(key) == 16


def test_get_prelogin_key_derivation():
    """Verify prelogin key derivation matches formula."""
    key = _get_prelogin_key(SAMPLE_RID)
    expected = hmac.new(SAMPLE_RID.encode(), TUYA_THING_SALT, hashlib.sha256).hexdigest()[:16].encode()
    assert key == expected
    assert len(key) == 16


def test_login_reg_password_is_the_pkcs1_wrapped_uid_secret():
    """login.reg sends uid_password_md5 under RSA PKCS#1 v1.5 with the server key."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=1024)
    pb_key = base64.b64encode(
        key.public_key().public_bytes(Encoding.DER, PublicFormat.SubjectPublicKeyInfo)
    ).decode()
    sealed = bytes.fromhex(_encrypt_password_pkcs1("eh-testuser", pb_key))
    assert key.decrypt(sealed, asym_padding.PKCS1v15()).decode() == uid_password_md5(
        "eh-testuser"
    )


def test_gcm_encrypt_decrypt_roundtrip():
    """Verify AES-128-GCM encryption and decryption roundtrip."""
    key = b"1234567890abcdef"
    payload = {"devId": "test_device_123", "type": "Common", "count": 42}
    ct_b64 = _encrypt_gcm(key, payload)
    raw = base64.b64decode(ct_b64)
    assert len(raw) > 28

    decrypted = _decrypt_gcm(key, ct_b64)
    assert decrypted == payload


def test_build_canonical_and_sign():
    """Verify canonical sorting and signature exclusion."""
    params = {
        "v": "1.0",
        "a": "smartlife.p.time.get",
        "postData": "abc123encrypted",
        "sign": "ignore_me",
        "bizData": "ignore_me_too",
        "clientId": "test_client",
    }
    canon = _build_canonical(params)
    assert canon == f"a=smartlife.p.time.get||clientId=test_client||postData={_mobile_hash('abc123encrypted')}||v=1.0"

    sign = _calc_sign(canon)
    expected_sign = hmac.new(TUYA_THING_SALT, canon.encode(), hashlib.sha256).hexdigest()
    assert sign == expected_sign


def test_canonical_signs_sp_and_excludes_gid():
    """Lock in the two non-obvious signature rules recovered from captured app traffic.

    Across 51 captured app requests the signed canonical string INCLUDES ``sp``
    (e.g. ``file.list``/``timer.all.list`` send ``sp=1`` and hash it) but OMITS
    ``gid`` (``batch.invoke`` sends a group id that is not signed). Reconstructing
    the captured signatures only reproduced them under exactly this classification.
    """
    params = {
        "a": "tuya.m.dev.common.file.list",
        "clientId": "test_client",
        "sp": "1",
        "gid": "100000001",
        "nd": "1",
        "v": "1.0",
    }
    canon = _build_canonical(params)
    # sp is part of the signed canonical; gid (and the other wire-only fields) are not.
    assert "sp=1" in canon.split("||")
    assert not any(item.startswith("gid=") for item in canon.split("||"))
    assert not any(item.startswith("nd=") for item in canon.split("||"))
    assert canon == "a=tuya.m.dev.common.file.list||clientId=test_client||sp=1||v=1.0"


@pytest.mark.asyncio
async def test_thing_client_login_flow():
    """Test full 2-step login flow."""
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=1024)
    pb_key_b64 = base64.b64encode(private_key.public_key().public_bytes(Encoding.DER, PublicFormat.SubjectPublicKeyInfo)).decode()

    mock_session = MagicMock()
    mock_session.closed = False

    def dynamic_post(url, data=None, **kwargs):
        ctx = MagicMock()
        req_rid = data.get("requestId")
        action = data.get("a")
        k = _get_prelogin_key(req_rid)

        if action == "smartlife.m.user.username.token.get":
            enc = _encrypt_gcm(k, {"result": {"token": "sample_token_123", "pbKey": pb_key_b64, "exponent": "65537"}})
            resp = MagicMock()
            resp.json = AsyncMock(return_value={"t": 123456, "result": enc, "success": True})
        else:
            enc = _encrypt_gcm(k, {
                "result": {
                    "sid": "az_sample_sid_12345",
                    "ecode": "z2z6z21241122714",
                    "domain": {"mobileApiUrl": "https://a1.tuyaeu.com"},
                },
                "success": True,
            })
            resp = MagicMock()
            resp.json = AsyncMock(return_value={"t": 123456, "result": enc, "success": True})

        ctx.__aenter__ = AsyncMock(return_value=resp)
        ctx.__aexit__ = AsyncMock()
        return ctx

    mock_session.post.side_effect = dynamic_post
    client = TuyaThingClient("test_user_id", country_code="US", websession=mock_session)

    await client.login()

    assert client.sid == "az_sample_sid_12345"
    assert client.ecode == b"z2z6z21241122714"
    assert client.endpoint == "https://a1.tuyaeu.com/api.json"


@pytest.mark.asyncio
async def test_concurrent_logins_coalesce_into_one():
    """Concurrent callers must share ONE login, and force= must still re-auth.

    Several coordinator tasks (schedules, map storage, firmware check, the
    mobile-MQTT pose stream) start at once, each with ``sid is None``. Tuya
    invalidates superseded sessions, so separate logins would leave all but
    the last caller with a dead sid.
    """
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=1024)
    pb_key_b64 = base64.b64encode(
        private_key.public_key().public_bytes(Encoding.DER, PublicFormat.SubjectPublicKeyInfo)
    ).decode()

    logins = {"count": 0}
    mock_session = MagicMock()
    mock_session.closed = False

    def dynamic_post(url, data=None, **kwargs):
        ctx = MagicMock()
        k = _get_prelogin_key(data.get("requestId"))
        if data.get("a") == "smartlife.m.user.username.token.get":
            enc = _encrypt_gcm(k, {"result": {"token": "t", "pbKey": pb_key_b64}})
        else:
            logins["count"] += 1
            enc = _encrypt_gcm(k, {"result": {"sid": f"sid_{logins['count']}"}, "success": True})
        resp = MagicMock()
        resp.json = AsyncMock(return_value={"result": enc, "success": True})
        ctx.__aenter__ = AsyncMock(return_value=resp)
        ctx.__aexit__ = AsyncMock()
        return ctx

    mock_session.post.side_effect = dynamic_post
    client = TuyaThingClient("uid", country_code="US", websession=mock_session)

    # Four racing callers → exactly one login, one shared sid.
    await asyncio.gather(*(client.login() for _ in range(4)))
    assert logins["count"] == 1
    assert client.sid == "sid_1"

    # A plain login with a session present is a no-op...
    await client.login()
    assert logins["count"] == 1

    # ...but the periodic refresh must still get a genuinely fresh sid.
    await client.login(force=True)
    assert logins["count"] == 2
    assert client.sid == "sid_2"


@pytest.mark.asyncio
async def test_thing_client_authenticated_request():
    """Test sending an authenticated request and decrypting response."""
    mock_session = MagicMock()
    mock_session.closed = False

    client = TuyaThingClient("test_user_id", websession=mock_session)
    client.sid = "active_sid_123"
    client.ecode = b"z2z6z21241122714"

    def dynamic_req_post(url, data=None, **kwargs):
        ctx = MagicMock()
        req_rid = data.get("requestId")
        key = _get_session_key(req_rid, client.ecode)
        enc = _encrypt_gcm(key, {"result": {"files": ["file1.bin", "file2.bin"]}, "success": True})
        resp = MagicMock()
        resp.json = AsyncMock(return_value={"t": 123456, "result": enc, "success": True})
        ctx.__aenter__ = AsyncMock(return_value=resp)
        ctx.__aexit__ = AsyncMock()
        return ctx

    mock_session.post.side_effect = dynamic_req_post

    res = await client.request("tuya.m.dev.common.file.list", {"devId": "dev123"})
    assert res == {"files": ["file1.bin", "file2.bin"]}


@pytest.mark.asyncio
async def test_expired_session_re_logs_in_and_retries_once():
    """An EXPIRED sid must not be a permanent failure.

    ``sid`` stays set and truthy after it expires, so the "log in if we have no
    session" check never fired again and every later call raised — and every
    caller swallows TuyaThingError (the call probe and the coordinator's timer
    helpers both degrade to None), so map, room and schedule refresh went
    silently dead for the rest of the run.
    """
    mock_session = MagicMock()
    mock_session.closed = False

    client = TuyaThingClient("test_user_id", websession=mock_session)
    client.sid = "expired_sid"
    client.ecode = b"z2z6z21241122714"

    calls: list[str] = []

    def dynamic_post(url, data=None, **kwargs):
        ctx = MagicMock()
        resp = MagicMock()
        calls.append(data.get("a", ""))
        if len(calls) == 1:
            # First attempt: the gateway rejects the session outright.
            resp.json = AsyncMock(
                return_value={
                    "success": False,
                    "errorCode": "USER_SESSION_INVALID",
                    "errorMsg": "session invalid",
                }
            )
        else:
            key = _get_session_key(data.get("requestId"), client.ecode)
            resp.json = AsyncMock(
                return_value={
                    "result": _encrypt_gcm(key, {"result": {"ok": True}, "success": True}),
                    "success": True,
                }
            )
        ctx.__aenter__ = AsyncMock(return_value=resp)
        # return_value=False, or __aexit__'s truthy MagicMock SWALLOWS the
        # TuyaThingError raised inside the `async with` and the test proves nothing.
        ctx.__aexit__ = AsyncMock(return_value=False)
        return ctx

    mock_session.post.side_effect = dynamic_post

    with patch.object(
        TuyaThingClient, "_login_impl", new=AsyncMock()
    ) as login_impl:
        res = await client.request("tuya.m.dev.common.file.list", {"devId": "dev123"})

    assert res == {"ok": True}
    login_impl.assert_awaited_once()
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_a_business_error_is_not_retried():
    """Only a rejected SESSION earns a re-login; a real error must surface."""
    mock_session = MagicMock()
    mock_session.closed = False

    client = TuyaThingClient("test_user_id", websession=mock_session)
    client.sid = "good_sid"
    client.ecode = b"z2z6z21241122714"

    calls: list[str] = []

    def dynamic_post(url, data=None, **kwargs):
        ctx = MagicMock()
        resp = MagicMock()
        calls.append(data.get("a", ""))
        resp.json = AsyncMock(
            return_value={
                "success": False,
                "errorCode": "DEVICE_OFFLINE",
                "errorMsg": "device is offline",
            }
        )
        ctx.__aenter__ = AsyncMock(return_value=resp)
        ctx.__aexit__ = AsyncMock(return_value=False)
        return ctx

    mock_session.post.side_effect = dynamic_post

    with pytest.raises(TuyaThingError):
        await client.request("tuya.m.dev.common.file.list", {"devId": "dev123"})
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_concurrent_session_errors_share_one_forced_login():
    """Callers that failed on the same sid re-login once, not once each.

    Each extra login would invalidate the sid the earlier retries just got.
    """
    client = TuyaThingClient("test_user_id", websession=MagicMock())
    client.sid = "old_sid"
    logins = {"count": 0}

    async def request_once(action, data=None, version="1.0"):
        sid = client.sid
        await asyncio.sleep(0)
        if sid == "old_sid":
            raise TuyaThingError("USER_SESSION_INVALID", "session invalid")
        return {"sid": sid}

    async def login_impl():
        await asyncio.sleep(0)
        logins["count"] += 1
        client.sid = f"sid_{logins['count']}"

    with (
        patch.object(client, "_request_once", side_effect=request_once),
        patch.object(client, "_login_impl", side_effect=login_impl),
    ):
        results = await asyncio.gather(
            *(client.request("tuya.m.dev.common.file.list") for _ in range(4))
        )

    assert logins["count"] == 1
    assert results == [{"sid": "sid_1"}] * 4


@pytest.mark.asyncio
async def test_a_forced_refresh_reuses_a_session_younger_than_min_age():
    """Each robot's timer forces a refresh; a sibling's fresh one must serve it."""
    client = TuyaThingClient("test_user_id", websession=MagicMock())
    logins = {"count": 0}

    async def login_impl():
        logins["count"] += 1
        client.sid = f"sid_{logins['count']}"

    with patch.object(client, "_login_impl", side_effect=login_impl):
        await client.login(force=True, min_age=600)
        await client.login(force=True, min_age=600)
        assert logins["count"] == 1
        client._sid_since -= 601  # the session has aged past min_age
        await client.login(force=True, min_age=600)
    assert logins["count"] == 2


@pytest.mark.asyncio
async def test_every_sid_change_reaches_the_session_listeners():
    """A periodic refresh and a request's session-error retry both replace the sid."""
    client = TuyaThingClient("test_user_id", websession=MagicMock())
    client.sid = "old_sid"
    seen: list[str | None] = []
    remove = client.add_session_listener(lambda: seen.append(client.sid))
    logins = {"count": 0}

    async def login_impl():
        logins["count"] += 1
        client.sid = f"sid_{logins['count']}"

    async def request_once(action, data=None, version="1.0"):
        if client.sid == "sid_1":
            raise TuyaThingError("USER_SESSION_INVALID", "session invalid")
        return {}

    with (
        patch.object(client, "_login_impl", side_effect=login_impl),
        patch.object(client, "_request_once", side_effect=request_once),
    ):
        await client.login()  # a session exists: no login, no event
        await client.login(force=True)
        await client.request("tuya.m.dev.common.file.list")
        remove()
        await client.login(force=True)

    assert seen == ["sid_1", "sid_2"]
