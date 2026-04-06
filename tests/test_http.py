"""Tests for the Eufy HTTP client."""

from __future__ import annotations

from collections.abc import Callable
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.robovac_mqtt.api.http import _REQUEST_TIMEOUT, EufyHTTPClient


def _make_client() -> EufyHTTPClient:
    """Create an EufyHTTPClient with dummy credentials."""
    return EufyHTTPClient(
        username="test@example.com",
        password="secret",
        openudid="abc123",
    )


def _mock_aiohttp_session(mock_response: AsyncMock) -> MagicMock:
    """Build a mock aiohttp.ClientSession that yields *mock_response* for any request."""
    # The inner context manager (session.post(...)) must be a non-async MagicMock
    # so that `async with session.post(...)` works without awaiting post() first.
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=mock_response)
    ctx.__aexit__ = AsyncMock(return_value=False)

    mock_session = MagicMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_session.post.return_value = ctx
    mock_session.get.return_value = ctx

    return mock_session


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

    mock_session = _mock_aiohttp_session(mock_response)

    with patch("aiohttp.ClientSession", return_value=mock_session):
        client = _make_client()
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

    mock_session = _mock_aiohttp_session(mock_response)

    with patch("aiohttp.ClientSession", return_value=mock_session):
        client = _make_client()

        with patch.object(client, "get_user_info", new_callable=AsyncMock) as mock_gui:
            result = await client.login(validate_only=True)

        # Should contain session data
        assert "session" in result
        assert result["session"]["access_token"] == "tok_abc"

        # get_user_info must NOT have been called
        mock_gui.assert_not_called()


# --- eufy_login v2/v1 fallback tests ---


@pytest.mark.asyncio
async def test_eufy_login_succeeds_via_v2():
    """eufy_login() should succeed on v2 (first attempt) without trying v1."""
    login_data = {"access_token": "tok_v2", "user_id": "u1"}

    mock_response = AsyncMock()
    mock_response.status = 200
    mock_response.json = AsyncMock(return_value=login_data)

    mock_session = _mock_aiohttp_session(mock_response)

    with patch("aiohttp.ClientSession", return_value=mock_session):
        client = _make_client()
        result = await client.eufy_login()

    assert result is not None
    assert result["access_token"] == "tok_v2"
    # Only one POST call — v2 succeeded, v1 not attempted
    assert mock_session.post.call_count == 1
    call_url = mock_session.post.call_args[0][0]
    assert "v2/email/login" in call_url


def _mock_aiohttp_sessions(*responses: AsyncMock) -> Callable[..., MagicMock]:
    """Build a side_effect callable that returns a fresh mock session per call.

    Each invocation of ``aiohttp.ClientSession()`` yields the next response in
    *responses*.  This is needed because ``eufy_login`` creates a new session
    for each login attempt.
    """
    call_count = 0

    def _factory(*_args, **_kwargs):
        nonlocal call_count
        resp = responses[call_count]
        call_count += 1

        ctx = MagicMock()
        ctx.__aenter__ = AsyncMock(return_value=resp)
        ctx.__aexit__ = AsyncMock(return_value=False)

        session = MagicMock()
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)
        session.post.return_value = ctx
        return session

    return _factory


@pytest.mark.asyncio
async def test_eufy_login_falls_back_to_v1():
    """eufy_login() should fall back to v1 when v2 returns non-200."""
    v2_fail = AsyncMock()
    v2_fail.status = 401
    v2_fail.json = AsyncMock(return_value={"error": "invalid_client"})
    v2_fail.text = AsyncMock(return_value="Unauthorized")

    v1_ok = AsyncMock()
    v1_ok.status = 200
    v1_ok.json = AsyncMock(return_value={"access_token": "tok_v1", "user_id": "u1"})

    factory = _mock_aiohttp_sessions(v2_fail, v1_ok)

    with patch("aiohttp.ClientSession", side_effect=factory):
        client = _make_client()
        result = await client.eufy_login()

    assert result is not None
    assert result["access_token"] == "tok_v1"


@pytest.mark.asyncio
async def test_eufy_login_all_attempts_fail():
    """eufy_login() should return None when both v2 and v1 fail."""
    fail_response = AsyncMock()
    fail_response.status = 401
    fail_response.json = AsyncMock(return_value=None)
    fail_response.text = AsyncMock(return_value="Unauthorized")

    mock_session = _mock_aiohttp_session(fail_response)

    with patch("aiohttp.ClientSession", return_value=mock_session):
        client = _make_client()
        result = await client.eufy_login()

    assert result is None


@pytest.mark.asyncio
async def test_eufy_login_v2_no_token_falls_back_to_v1():
    """eufy_login() should try v1 if v2 returns 200 but no access_token."""
    v2_no_token = AsyncMock()
    v2_no_token.status = 200
    v2_no_token.json = AsyncMock(return_value={"some_other_field": "value"})
    v2_no_token.text = AsyncMock(return_value="")

    v1_ok = AsyncMock()
    v1_ok.status = 200
    v1_ok.json = AsyncMock(return_value={"access_token": "tok_v1"})

    factory = _mock_aiohttp_sessions(v2_no_token, v1_ok)

    with patch("aiohttp.ClientSession", side_effect=factory):
        client = _make_client()
        result = await client.eufy_login()

    assert result is not None
    assert result["access_token"] == "tok_v1"


# --- Configuration test ---


def test_request_timeout_is_configured():
    """_REQUEST_TIMEOUT should exist and have a 30-second total."""
    assert _REQUEST_TIMEOUT is not None
    assert _REQUEST_TIMEOUT.total == 30
