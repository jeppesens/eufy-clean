"""Tests for the Eufy HTTP client."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from unittest.mock import AsyncMock, MagicMock

import aiohttp
import pytest

from custom_components.robovac_mqtt.api.http import (
    _LOGIN_CONFIGS,
    _REQUEST_TIMEOUT,
    EufyHTTPClient,
    EufyLoginRateLimitedError,
    EufyLoginTransientError,
    _retry_after,
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


def test_login_configs_put_the_remembered_winner_first():
    client = _make_client()
    client.login_label = _LOGIN_CONFIGS[1]["label"]
    order = [c["label"] for c in client._ordered_login_configs()]
    assert order[0] == _LOGIN_CONFIGS[1]["label"]
    # Reordered, never filtered: the other entry is still a fallback.
    assert set(order) == {c["label"] for c in _LOGIN_CONFIGS}


def test_login_configs_ignore_an_unrecognised_memo():
    client = _make_client()
    client.login_label = "some endpoint that no longer exists"
    assert [c["label"] for c in client._ordered_login_configs()] == [
        c["label"] for c in _LOGIN_CONFIGS
    ]


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
    assert result["user"]["gtoken"]  # real gtoken computed by get_user_info
    assert result["mqtt"] == {"endpoint": "mqtt"}
    assert client.user_info["user_center_id"] == "uc1"
    # Only one login POST happened (v1 not attempted).
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


# --- transient vs rejected login ---


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [429, 500, 502, 503])
async def test_login_transient_status_raises_transient(status):
    """Rate limits and server errors are not a credential rejection."""
    mock_session = _mock_websession_sequence(
        _login_response(status), _login_response(status)
    )
    client = _make_client(websession=mock_session)

    with pytest.raises(EufyLoginTransientError):
        await client.login()


@pytest.mark.asyncio
async def test_login_transient_on_one_config_is_not_a_rejection():
    """One config failing on the server side and the other rejecting is undecided."""
    mock_session = _mock_websession_sequence(
        _login_response(503), _login_response(401)
    )
    client = _make_client(websession=mock_session)

    with pytest.raises(EufyLoginTransientError):
        await client.login(validate_only=True)


@pytest.mark.asyncio
async def test_login_network_error_raises_transient():
    """A transport failure on every config is transient."""
    mock_session = MagicMock()
    mock_session.post.side_effect = aiohttp.ClientConnectionError("reset")
    client = _make_client(websession=mock_session)

    with pytest.raises(EufyLoginTransientError):
        await client.login()


@pytest.mark.asyncio
async def test_login_unreadable_200_raises_transient():
    """A 200 whose body is not JSON cannot decide the credentials."""
    bad = AsyncMock()
    bad.status = 200
    bad.json = AsyncMock(side_effect=ValueError("not json"))
    mock_session = _mock_websession_sequence(bad, bad)
    client = _make_client(websession=mock_session)

    with pytest.raises(EufyLoginTransientError):
        await client.login()


@pytest.mark.asyncio
async def test_login_success_after_transient_config_is_kept():
    """A later config that yields a user_center wins over an undecided one."""
    mock_session = _mock_websession_sequence(
        _login_response(503), _login_response(200, "tok_v1")
    )
    client = _make_client(websession=mock_session)
    client.get_user_info = AsyncMock(
        return_value={"user_center_id": "x", "user_center_token": "t"}
    )
    client.get_mqtt_credentials = AsyncMock(return_value={"endpoint": "mqtt"})

    result = await client.login()

    assert result["session"]["access_token"] == "tok_v1"


@pytest.mark.asyncio
async def test_login_user_info_5xx_is_transient_not_fallback():
    """A 5xx on user info must not demote the account to a fallback session."""
    login_ok = _login_response(200, "tok")
    user_5xx = AsyncMock()
    user_5xx.status = 503
    user_5xx.json = AsyncMock(return_value=None)

    def _ctx(resp):
        c = MagicMock()
        c.__aenter__ = AsyncMock(return_value=resp)
        c.__aexit__ = AsyncMock(return_value=False)
        return c

    mock_session = MagicMock()
    mock_session.post.side_effect = [_ctx(login_ok), _ctx(login_ok)]
    mock_session.get.side_effect = [_ctx(user_5xx), _ctx(user_5xx)]
    client = _make_client(websession=mock_session)

    with pytest.raises(EufyLoginTransientError):
        await client.login()


@pytest.mark.asyncio
async def test_get_user_info_without_user_center_logs_debug_only(caplog):
    """A missing user_center is the expected fallback path, not an error."""
    resp = AsyncMock()
    resp.status = 200
    resp.json = AsyncMock(return_value={"email": "a@example.com"})
    client = _make_client(websession=_mock_websession(resp))
    client.session = {"access_token": "tok"}

    with caplog.at_level("DEBUG"):
        assert await client.get_user_info() is None

    assert not [r for r in caplog.records if r.levelname in ("ERROR", "WARNING")]


# --- HTTP 429 ---


def _rate_limited(retry_after: str | None = None) -> AsyncMock:
    r = _login_response(429)
    r.headers = {} if retry_after is None else {"Retry-After": retry_after}
    return r


@pytest.mark.asyncio
async def test_login_429_stops_at_the_first_config_with_its_retry_after():
    """A rate-limited login does not go on to the next config."""
    mock_session = _mock_websession_sequence(
        _rate_limited("120"), _login_response(200, "tok_v1")
    )
    client = _make_client(websession=mock_session)

    with pytest.raises(EufyLoginRateLimitedError) as err:
        await client.login()

    assert err.value.retry_after == 120
    assert mock_session.post.call_count == 1


@pytest.mark.asyncio
async def test_login_user_info_429_is_a_rate_limit_not_a_fallback():
    """A 429 on user info stops the login instead of trying the next config."""
    mock_session = _mock_websession_sequence(
        _login_response(200, "tok"), _login_response(200, "tok")
    )
    mock_session.get.side_effect = _mock_websession_sequence(_rate_limited()).get.side_effect
    client = _make_client(websession=mock_session)

    with pytest.raises(EufyLoginRateLimitedError) as err:
        await client.login()

    assert err.value.retry_after is None
    assert mock_session.post.call_count == 1


def _http_date(delta: timedelta) -> str:
    return format_datetime(datetime.now(timezone.utc) + delta, usegmt=True)


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        ("120", 120.0),
        ("0", 0.0),
        (None, None),
        ("", None),
        ("soon", None),
    ],
)
def test_retry_after_reads_seconds_or_nothing(header, expected):
    assert _retry_after(_rate_limited(header)) == expected


def test_retry_after_reads_an_http_date():
    got = _retry_after(_rate_limited(_http_date(timedelta(seconds=300))))
    assert got is not None and 290 <= got <= 300
    assert _retry_after(_rate_limited(_http_date(timedelta(seconds=-60)))) == 0.0


def test_retry_after_without_headers_is_none():
    response = AsyncMock()
    response.status = 429
    assert _retry_after(response) is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "auth_error", "transient_error"),
    [(401, True, False), (403, True, False), (408, False, True), (500, False, True),
     (503, False, True), (404, False, False)],
)
async def test_device_list_failures_are_classified(status, auth_error, transient_error):
    """A server-side failure is recorded apart from a rejected token."""
    resp = AsyncMock()
    resp.status = status
    client = _make_client(websession=_mock_websession(resp))
    client.session = {"access_token": "tok"}

    assert await client.get_cloud_device_list() == []
    assert (client.auth_error, client.transient_error) == (auth_error, transient_error)


@pytest.mark.asyncio
async def test_device_list_429_raises_a_rate_limit():
    mock_session = _mock_websession(_rate_limited("60"))
    client = _make_client(websession=mock_session)
    client.session = {"access_token": "tok"}

    with pytest.raises(EufyLoginRateLimitedError) as err:
        await client.get_cloud_device_list()

    assert err.value.retry_after == 60
    # the home-api fallback is not tried during a rate limit
    assert mock_session.get.call_count == 1


def test_restore_clears_the_recorded_failures():
    client = _make_client()
    client.auth_error = client.transient_error = True
    client.restore({"access_token": "t"}, None)
    assert (client.auth_error, client.transient_error) == (False, False)
