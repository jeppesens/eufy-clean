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
