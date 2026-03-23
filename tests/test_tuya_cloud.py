"""Unit tests for api/tuya_cloud.py: Tuya Cloud API client."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.robovac_mqtt.api.tuya_cloud import (
    TuyaCloudClient,
    TuyaCloudError,
    _encrypt_password,
    _md5,
    _mobile_hash,
)


# ── Helper utilities ────────────────────────────────────────────────


def test_md5():
    """MD5 produces expected hex digest."""
    assert _md5("hello") == "5d41402abc4b2a76b9719d911017c592"


def test_mobile_hash():
    """Mobile hash shuffles MD5 correctly: [8:16]+[0:8]+[24:32]+[16:24]."""
    h = _md5("test_data")
    expected = h[8:16] + h[0:8] + h[24:32] + h[16:24]
    assert _mobile_hash("test_data") == expected


def test_mobile_hash_deterministic():
    """Same input always produces same hash."""
    assert _mobile_hash("abc") == _mobile_hash("abc")


def test_mobile_hash_length():
    """Hash output is always 32 characters (MD5 hex length)."""
    assert len(_mobile_hash("anything")) == 32


# ── Request signing ─────────────────────────────────────────────────


def test_sign_deterministic():
    """Signing the same params produces the same result."""
    client = TuyaCloudClient("EU", websession=MagicMock())
    params = {
        "a": "test.action",
        "clientId": "testkey",
        "time": 1234567890,
        "v": "1.0",
    }
    sig1 = client._sign(params)
    sig2 = client._sign(params)
    assert sig1 == sig2
    assert len(sig1) == 64  # HMAC-SHA256 hex is 64 chars


def test_sign_changes_with_params():
    """Different params produce different signatures."""
    client = TuyaCloudClient("EU", websession=MagicMock())
    params1 = {"a": "action1", "clientId": "key", "time": 100, "v": "1.0"}
    params2 = {"a": "action2", "clientId": "key", "time": 100, "v": "1.0"}
    assert client._sign(params1) != client._sign(params2)


def test_sign_ignores_non_sign_fields():
    """Fields not in _SIGN_FIELDS are excluded from signature."""
    client = TuyaCloudClient("EU", websession=MagicMock())
    params_base = {"a": "test", "clientId": "key", "time": 100, "v": "1.0"}
    params_extra = {**params_base, "customField": "ignored"}
    assert client._sign(params_base) == client._sign(params_extra)


def test_sign_includes_post_data_hashed():
    """postData is included in signature via mobile_hash."""
    client = TuyaCloudClient("EU", websession=MagicMock())
    params = {
        "a": "test",
        "clientId": "key",
        "time": 100,
        "v": "1.0",
        "postData": '{"foo":"bar"}',
    }
    sig_with = client._sign(params)

    params_no_pd = {k: v for k, v in params.items() if k != "postData"}
    sig_without = client._sign(params_no_pd)
    assert sig_with != sig_without


# ── Client initialization ──────────────────────────────────────────


def test_client_eu_region():
    client = TuyaCloudClient("EU", websession=MagicMock())
    assert "tuyaeu.com" in client.endpoint
    assert client.region == "EU"
    assert client.sid is None


def test_client_us_region():
    client = TuyaCloudClient("US", websession=MagicMock())
    assert "tuyaus.com" in client.endpoint
    assert client.region == "US"


def test_client_requires_region_and_websession():
    """TuyaCloudClient requires both region and websession."""
    import pytest as _pytest

    with _pytest.raises(TypeError):
        TuyaCloudClient()


# ── Password encryption ────────────────────────────────────────────


def test_encrypt_password_returns_hex():
    """Encrypted password is a hex string."""
    result = _encrypt_password(
        uid="eh-test123",
        public_key_n="00b3510a2e6c4fa1e339a0703e64444c0c4a0663385dbd0d2c2c0a8e2b4f1c63",
        exponent=65537,
    )
    assert isinstance(result, str)
    # Should be valid hex
    int(result, 16)


def test_encrypt_password_deterministic():
    """Same inputs produce same encrypted password."""
    kwargs = {
        "uid": "eh-user1",
        "public_key_n": "00b3510a2e6c4fa1e339a0703e64444c0c4a0663385dbd0d2c2c0a8e2b4f1c63",
        "exponent": 65537,
    }
    assert _encrypt_password(**kwargs) == _encrypt_password(**kwargs)


# ── API request errors ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_request_requires_sid():
    """Request with requires_sid=True should raise when no sid."""
    client = TuyaCloudClient("EU", websession=MagicMock())
    with pytest.raises(TuyaCloudError, match="Must call login"):
        await client.request("tuya.m.some.action")


@pytest.mark.asyncio
async def test_request_no_sid_required():
    """Request with requires_sid=False should work without sid."""
    mock_response = MagicMock()
    mock_response.json = AsyncMock(return_value={"success": True, "result": {"data": 1}})
    mock_response.__aenter__ = AsyncMock(return_value=mock_response)
    mock_response.__aexit__ = AsyncMock(return_value=False)

    mock_session = MagicMock()
    mock_session.get = MagicMock(return_value=mock_response)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    client = TuyaCloudClient("EU", websession=mock_session)

    result = await client.request("tuya.m.test", requires_sid=False)

    assert result == {"data": 1}


@pytest.mark.asyncio
async def test_request_api_error():
    """API error responses should raise TuyaCloudError."""
    mock_response = MagicMock()
    mock_response.json = AsyncMock(
        return_value={"success": False, "errorCode": "TOKEN_EXPIRED", "errorMsg": "Session expired"}
    )
    mock_response.__aenter__ = AsyncMock(return_value=mock_response)
    mock_response.__aexit__ = AsyncMock(return_value=False)

    mock_session = MagicMock()
    mock_session.get = MagicMock(return_value=mock_response)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    client = TuyaCloudClient("EU", websession=mock_session)
    client.sid = "test_sid"

    with pytest.raises(TuyaCloudError, match="TOKEN_EXPIRED"):
        await client.request("tuya.m.test")


# ── Send command ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_send_command_calls_request():
    """send_command should call request with correct action and data."""
    client = TuyaCloudClient("EU", websession=MagicMock())
    client.sid = "test_sid"

    with patch.object(client, "request", new_callable=AsyncMock) as mock_req:
        await client.send_command("device123", {"2": True})

    mock_req.assert_called_once_with(
        "tuya.m.device.dp.publish",
        data={"dps": {"2": True}, "devId": "device123", "gwId": "device123"},
    )


# ── Get device ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_device_found():
    """get_device should return DPS for matching device."""
    client = TuyaCloudClient("EU", websession=MagicMock())
    client.sid = "test_sid"

    devices = [
        {"devId": "dev1", "dps": {"15": "Running", "104": 85}},
        {"devId": "dev2", "dps": {"15": "Charging", "104": 100}},
    ]

    with patch.object(client, "get_device_list", new_callable=AsyncMock, return_value=devices):
        result = await client.get_device("dev2")

    assert result == {"15": "Charging", "104": 100}


@pytest.mark.asyncio
async def test_get_device_not_found():
    """get_device should return None for unknown device."""
    client = TuyaCloudClient("EU", websession=MagicMock())
    client.sid = "test_sid"

    with patch.object(client, "get_device_list", new_callable=AsyncMock, return_value=[]):
        result = await client.get_device("nonexistent")

    assert result is None


# ── Login flow ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_login_sets_sid():
    """Successful login should set the sid."""
    client = TuyaCloudClient("EU", websession=MagicMock())

    token_response = {
        "publicKey": "00b3510a2e6c4fa1e339a0703e64444c0c4a0663385dbd0d2c2c0a8e2b4f1c63",
        "exponent": "65537",
        "token": "test_token",
    }
    login_response = {
        "sid": "session_123",
        "domain": {},
    }

    call_count = 0

    async def mock_request(action, data=None, *, requires_sid=True, **kwargs):
        nonlocal call_count
        call_count += 1
        if "token.create" in action:
            return token_response
        if "password.login" in action:
            return login_response
        raise ValueError(f"Unexpected action: {action}")

    with patch.object(client, "request", side_effect=mock_request):
        sid = await client.login("user_id_123")

    assert sid == "session_123"
    assert client.sid == "session_123"
    assert call_count == 2


@pytest.mark.asyncio
async def test_login_handles_region_redirect():
    """Login should update endpoint when API returns a redirect."""
    client = TuyaCloudClient("EU", websession=MagicMock())

    token_response = {
        "publicKey": "00b3510a2e6c4fa1e339a0703e64444c0c4a0663385dbd0d2c2c0a8e2b4f1c63",
        "exponent": "65537",
        "token": "test_token",
    }
    login_response = {
        "sid": "session_456",
        "domain": {
            "mobileApiUrl": "https://a1.tuyacn.com",
            "regionCode": "AY",
        },
    }

    async def mock_request(action, data=None, *, requires_sid=True, **kwargs):
        if "token.create" in action:
            return token_response
        if "password.login" in action:
            return login_response
        raise ValueError(f"Unexpected action: {action}")

    with patch.object(client, "request", side_effect=mock_request):
        await client.login("user_id_123")

    assert client.endpoint == "https://a1.tuyacn.com/api.json"
    assert client.region == "AY"
