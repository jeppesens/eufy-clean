"""Tests for the Eufy HTTP client."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.robovac_mqtt.api.http import _REQUEST_TIMEOUT, EufyHTTPClient
from custom_components.robovac_mqtt.api.mega_http import (
    MegaCaptchaRequiredError,
    MegaTwoFactorRequiredError,
)


def _mock_websession(mock_response: AsyncMock) -> MagicMock:
    """Build a mock aiohttp websession that yields *mock_response* for any request."""
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=mock_response)
    ctx.__aexit__ = AsyncMock(return_value=False)

    mock_session = MagicMock()
    mock_session.post.return_value = ctx
    mock_session.get.return_value = ctx

    return mock_session


def _make_client(websession: MagicMock | None = None) -> EufyHTTPClient:
    """Create an EufyHTTPClient with dummy credentials."""
    return EufyHTTPClient(
        username="test@example.com",
        password="secret",
        openudid="abc123",
        websession=websession or MagicMock(),
    )


# --- None-guard tests (no HTTP calls) ---


@pytest.mark.asyncio
async def test_get_user_info_returns_none_without_session():
    """get_user_info() should return None when session is not set."""
    client = _make_client()
    assert client.session is None
    result = await client.get_user_info()
    assert result is None


@pytest.mark.asyncio
async def test_get_device_list_returns_empty_without_user_info():
    """get_device_list() should return [] when user_info is not set."""
    client = _make_client()
    assert client.user_info is None
    result = await client.get_device_list()
    assert result == []


@pytest.mark.asyncio
async def test_get_cloud_device_list_returns_empty_without_session():
    """get_cloud_device_list() should return [] when session is not set."""
    client = _make_client()
    assert client.session is None
    result = await client.get_cloud_device_list()
    assert result == []


@pytest.mark.asyncio
async def test_get_mqtt_credentials_returns_none_without_user_info():
    """get_mqtt_credentials() should return None when user_info is not set."""
    client = _make_client()
    assert client.user_info is None
    result = await client.get_mqtt_credentials()
    assert result is None


# --- Mocked HTTP tests ---


@pytest.mark.asyncio
async def test_login_returns_empty_on_failed_login():
    """login() should return {} when legacy and Mega login all fail."""
    mock_response = AsyncMock()
    mock_response.status = 401
    mock_response.json = AsyncMock(return_value=None)
    mock_response.text = AsyncMock(return_value="Unauthorized")

    mock_session = _mock_websession(mock_response)
    client = _make_client(websession=mock_session)
    result = await client.login()

    assert result == {}


@pytest.mark.asyncio
async def test_login_validate_only():
    """login(validate_only=True) should return the session without calling get_user_info."""
    login_response_data = {
        "access_token": "tok_abc",
        "user_id": "u1",
    }

    mock_response = AsyncMock()
    mock_response.status = 200
    mock_response.json = AsyncMock(return_value=login_response_data)

    mock_session = _mock_websession(mock_response)
    client = _make_client(websession=mock_session)

    result = await client.login(validate_only=True)

    assert "session" in result
    assert result["session"]["access_token"] == "tok_abc"


# --- Configuration test ---


def test_request_timeout_is_configured():
    """_REQUEST_TIMEOUT should exist and have a 30-second total."""
    assert _REQUEST_TIMEOUT is not None
    assert _REQUEST_TIMEOUT.total == 30


# --- v2/v1 login fallback (PR #122) + Mega v6 fallback ---


def _mock_websession_sequence(*responses: AsyncMock) -> MagicMock:
    """websession whose successive post/get calls yield *responses* in order."""

    def _ctx(resp: AsyncMock) -> MagicMock:
        c = MagicMock()
        c.__aenter__ = AsyncMock(return_value=resp)
        c.__aexit__ = AsyncMock(return_value=False)
        return c

    mock_session = MagicMock()
    mock_session.post.side_effect = [_ctx(r) for r in responses]
    mock_session.get.side_effect = [_ctx(r) for r in responses]
    return mock_session


def _login_response(status: int, token: str | None = None) -> AsyncMock:
    r = AsyncMock()
    r.status = status
    r.json = AsyncMock(
        return_value={"access_token": token, "user_id": "u1"} if token else None
    )
    r.text = AsyncMock(return_value="error body")
    return r


@pytest.mark.asyncio
async def test_login_validate_prefers_v2():
    """v2 (unified Eufy app) login is tried first; success short-circuits v1."""
    mock_session = _mock_websession_sequence(_login_response(200, "tok_v2"))
    client = _make_client(websession=mock_session)

    result = await client.login(validate_only=True)

    assert result["session"]["access_token"] == "tok_v2"
    assert mock_session.post.call_count == 1
    first_url = mock_session.post.call_args_list[0][0][0]
    assert "v2/email/login" in first_url


@pytest.mark.asyncio
async def test_login_validate_falls_back_to_v1():
    """When v2 fails, v1 (legacy Eufy Clean app) is attempted and returned."""
    mock_session = _mock_websession_sequence(
        _login_response(401),            # v2 fails
        _login_response(200, "tok_v1"),  # v1 succeeds
    )
    client = _make_client(websession=mock_session)

    result = await client.login(validate_only=True)

    assert result["session"]["access_token"] == "tok_v1"
    assert mock_session.post.call_count == 2


@pytest.mark.asyncio
async def test_login_all_attempts_fail():
    """Returns {} when v2, v1, and Mega v6 fallback all fail."""
    mock_session = _mock_websession_sequence(
        _login_response(401), _login_response(403)
    )
    client = _make_client(websession=mock_session)
    client.login_mega = AsyncMock(side_effect=RuntimeError("mega failed"))

    result = await client.login(validate_only=True)

    assert result == {}
    assert mock_session.post.call_count == 2
    client.login_mega.assert_awaited_once_with(validate_only=True)


@pytest.mark.asyncio
async def test_login_falls_back_to_mega_when_legacy_fails():
    """When both legacy endpoints fail, login() falls back to Mega v6."""
    mock_session = _mock_websession_sequence(
        _login_response(401), _login_response(401)
    )
    client = _make_client(websession=mock_session)
    expected = {
        "session": {"access_token": "mega_tok", "user_id": "u_mega"},
        "user": {"user_center_id": "u_mega", "user_center_token": "mega_tok"},
        "mqtt": {"endpoint_addr": "aiot-mqtt-eu.anker.com"},
    }
    client.login_mega = AsyncMock(return_value=expected)

    result = await client.login()

    assert result == expected
    assert mock_session.post.call_count == 2
    client.login_mega.assert_awaited_once_with(validate_only=False)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "challenge",
    [
        MegaCaptchaRequiredError("cap1", "data:image/png;base64,AAA"),
        MegaTwoFactorRequiredError("email"),
    ],
)
async def test_login_propagates_mega_challenges(challenge):
    """Captcha and 2FA exceptions from Mega fallback propagate to config flow."""
    mock_session = _mock_websession_sequence(
        _login_response(401), _login_response(401)
    )
    client = _make_client(websession=mock_session)
    client.login_mega = AsyncMock(side_effect=challenge)

    with pytest.raises(type(challenge)):
        await client.login()


@pytest.mark.asyncio
async def test_login_reuses_persisted_mega_session():
    """When a valid Mega session is already restored, legacy endpoints are skipped."""
    mock_session = MagicMock()
    client = EufyHTTPClient(
        username="test@example.com",
        password="secret",
        openudid="0123456789abcdef",
        websession=mock_session,
        country_code="GB",
        mega_session={
            "user_id": "ap_1",
            "account_user_id": "acc_1",
            "auth_token": "saved_tok",
            "share_key": "00" * 16,
            "key_ident": "kid_1",
            "region": "eu-pr",
            "country_code": "GB",
            "token_expires_at": 0,
            "saved_at": 9_999_999_999.0,
        },
    )
    client.mega.get_user_mqtt_info = AsyncMock(
        return_value={"endpoint_addr": "aiot-mqtt-eu.anker.com"}
    )

    result = await client.login()

    assert client.use_mega is True
    assert result["session"]["access_token"] == "saved_tok"
    assert result["mqtt"]["endpoint_addr"] == "aiot-mqtt-eu.anker.com"
    mock_session.post.assert_not_called()


@pytest.mark.asyncio
async def test_login_prefers_credential_with_user_center():
    """When the first login authenticates but yields no user_center, login()
    keeps trying and prefers a later credential set that does (issues
    #121/#124/#131)."""
    mock_session = _mock_websession_sequence(
        _login_response(200, "tok_v2"),  # v2 authenticates...
        _login_response(200, "tok_v1"),  # ...so does v1
    )
    client = _make_client(websession=mock_session)
    client.get_user_info = AsyncMock(
        side_effect=[None, {"user_center_id": "x", "user_center_token": "t"}]
    )
    client.get_mqtt_credentials = AsyncMock(return_value={"endpoint": "mqtt"})

    result = await client.login()

    assert result["session"]["access_token"] == "tok_v1"
    assert result["user"]["user_center_id"] == "x"
    assert result["mqtt"] == {"endpoint": "mqtt"}
    assert client.get_user_info.await_count == 2
    client.get_mqtt_credentials.assert_awaited_once()


@pytest.mark.asyncio
async def test_login_falls_back_when_no_user_center_anywhere():
    """If no login yields a user_center, fall back to the first working token so
    the Tuya cloud/local path can still discover via the eufy user_id."""
    mock_session = _mock_websession_sequence(
        _login_response(200, "tok_v2"),
        _login_response(200, "tok_v1"),
    )
    client = _make_client(websession=mock_session)
    client.get_user_info = AsyncMock(return_value=None)
    client.get_mqtt_credentials = AsyncMock(return_value={"endpoint": "mqtt"})

    result = await client.login()

    assert result["session"]["access_token"] == "tok_v2"
    assert result["user"] is None
    assert result["mqtt"] is None
    client.get_mqtt_credentials.assert_not_awaited()


@pytest.mark.asyncio
async def test_login_real_sequence_v2_user_center_skips_v1():
    """End-to-end (real get_user_info/gtoken): when the v2 login yields a
    user_center, v1 is never attempted and MQTT creds are fetched."""

    def _ctx(resp: AsyncMock) -> MagicMock:
        c = MagicMock()
        c.__aenter__ = AsyncMock(return_value=resp)
        c.__aexit__ = AsyncMock(return_value=False)
        return c

    login_resp = _login_response(200, "tok_v2")
    userinfo_resp = AsyncMock()
    userinfo_resp.status = 200
    userinfo_resp.json = AsyncMock(
        return_value={"user_center_id": "uc1", "user_center_token": "uct"}
    )
    mqtt_resp = AsyncMock()
    mqtt_resp.status = 200
    mqtt_resp.json = AsyncMock(return_value={"data": {"endpoint": "mqtt"}})

    mock_session = MagicMock()
    mock_session.post.side_effect = [_ctx(login_resp), _ctx(mqtt_resp)]
    mock_session.get.side_effect = [_ctx(userinfo_resp)]
    client = _make_client(websession=mock_session)

    result = await client.login()

    assert result["session"]["access_token"] == "tok_v2"
    assert result["user"]["user_center_id"] == "uc1"
    assert result["user"]["gtoken"]
    assert result["mqtt"] == {"endpoint": "mqtt"}
    assert client.user_info["user_center_id"] == "uc1"
    login_posts = [
        c.args[0]
        for c in mock_session.post.call_args_list
        if "email/login" in c.args[0]
    ]
    assert len(login_posts) == 1
    assert "v2/email/login" in login_posts[0]


@pytest.mark.asyncio
async def test_get_cloud_device_list_falls_back_to_home_api():
    """When the legacy device endpoint is empty, the home-api fallback is used."""
    legacy = AsyncMock()
    legacy.status = 200
    legacy.json = AsyncMock(return_value={"devices": []})
    home = AsyncMock()
    home.status = 200
    home.json = AsyncMock(return_value={"devices": [{"id": "home_dev"}]})

    mock_session = _mock_websession_sequence(legacy, home)
    client = _make_client(websession=mock_session)
    client.session = {"access_token": "tok"}

    result = await client.get_cloud_device_list()

    assert result == [{"id": "home_dev"}]
    assert mock_session.get.call_count == 2


@pytest.mark.asyncio
async def test_get_cloud_device_list_legacy_short_circuits():
    """When the legacy endpoint returns devices, the home-api fallback is skipped."""
    legacy = AsyncMock()
    legacy.status = 200
    legacy.json = AsyncMock(return_value={"devices": [{"id": "legacy_dev"}]})

    mock_session = _mock_websession_sequence(legacy, AsyncMock())
    client = _make_client(websession=mock_session)
    client.session = {"access_token": "tok"}

    result = await client.get_cloud_device_list()

    assert result == [{"id": "legacy_dev"}]
    assert mock_session.get.call_count == 1
