"""Tests for the Eufy HTTP client."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.robovac_mqtt.api.http import _REQUEST_TIMEOUT, EufyHTTPClient


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
    """login() should return {} when eufy_login gets a non-200 / no access_token response."""
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

    # Should contain session data
    assert "session" in result
    assert result["session"]["access_token"] == "tok_abc"


# --- Configuration test ---


def test_request_timeout_is_configured():
    """_REQUEST_TIMEOUT should exist and have a 30-second total."""
    assert _REQUEST_TIMEOUT is not None
    assert _REQUEST_TIMEOUT.total == 30


# --- v2/v1 login fallback (PR #122) ---


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
    """Returns {} when both v2 and v1 fail."""
    mock_session = _mock_websession_sequence(
        _login_response(401), _login_response(403)
    )
    client = _make_client(websession=mock_session)

    result = await client.login(validate_only=True)

    assert result == {}
    assert mock_session.post.call_count == 2


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
    # v2's token has no user_center; v1's does.
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
    client.get_user_info = AsyncMock(return_value=None)  # 401 -> no user_center
    client.get_mqtt_credentials = AsyncMock(return_value={"endpoint": "mqtt"})

    result = await client.login()

    assert result["session"]["access_token"] == "tok_v2"  # first working token
    assert result["user"] is None
    assert result["mqtt"] is None
    client.get_mqtt_credentials.assert_not_awaited()


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
