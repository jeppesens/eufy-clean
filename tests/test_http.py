"""Tests for the Eufy HTTP client."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from unittest.mock import AsyncMock, MagicMock

import aiohttp
import pytest

from custom_components.robovac_mqtt.api.errors import (
    EufyLoginChallengeError,
    EufyLoginRateLimitedError,
    EufyLoginTransientError,
)
from custom_components.robovac_mqtt.api.http import (
    _LOGIN_CONFIGS,
    _REQUEST_TIMEOUT,
    EufyHTTPClient,
    _retry_after,
)
from custom_components.robovac_mqtt.api.throttle import REQUEST_HOLD_OFF


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
    client.get_user_info = AsyncMock(return_value=None)  # no user_center_id
    client.get_mqtt_credentials = AsyncMock(return_value={"endpoint": "mqtt"})

    result = await client.login()

    assert result["session"]["access_token"] == "tok_v2"  # first working token
    assert result["user"] is None
    assert result["mqtt"] is None
    client.get_mqtt_credentials.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "body"),
    [(401, None), (200, {"res_code": 26084}), (200, {"code": -401})],
    ids=["http-401", "26084", "body-401"],
)
async def test_login_rejected_user_info_is_not_a_fallback_session(status, body):
    """A token the user info call rejects is no fallback session; a later
    config's token without a user_center still is."""
    mock_session = _mock_websession_sequence(
        _login_response(200, "tok_v2"), _login_response(200, "tok_v1")
    )
    mock_session.get.side_effect = [
        _mock_websession(_body_response(status, body)).get.return_value,
        _mock_websession(_body_response(200, {"email": "e"})).get.return_value,
    ]
    client = _make_client(websession=mock_session)

    result = await client.login()

    assert result["session"]["access_token"] == "tok_v1"
    assert result["user"] is None


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
@pytest.mark.parametrize(
    ("status", "body"),
    [(503, None), (200, None), (200, ValueError("html")), (200, ["not", "an object"])],
    ids=["5xx", "200-null", "200-not-json", "200-list"],
)
async def test_login_unusable_user_info_is_transient_not_fallback(status, body):
    """A 5xx or a 200 that is not a JSON object on user info must not demote the
    account to a fallback session; only an object without user_center_id does."""
    login_ok = _login_response(200, "tok")
    user_5xx = AsyncMock()
    user_5xx.status = status
    if isinstance(body, Exception):
        user_5xx.json = AsyncMock(side_effect=body)
    else:
        user_5xx.json = AsyncMock(return_value=body)

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


# --- body codes, throttles and the login budget ---


def _body_response(status: int, body: dict | None, retry_after: str | None = None) -> AsyncMock:
    r = AsyncMock()
    r.status = status
    r.json = AsyncMock(return_value=body)
    r.headers = {"Retry-After": retry_after} if retry_after is not None else {}
    return r


def _rate_limited(retry_after: str | None = None) -> AsyncMock:
    return _body_response(429, None, retry_after)


@pytest.mark.asyncio
async def test_login_throttle_code_stops_every_config_and_holds_off():
    """A login throttle (100028) raises at once; the next login() sends nothing."""
    mock_session = _mock_websession_sequence(
        _body_response(200, {"res_code": 100028, "message": "too many"})
    )
    client = _make_client(websession=mock_session)

    with pytest.raises(EufyLoginRateLimitedError) as err:
        await client.login()
    assert err.value.code == 100028
    assert mock_session.post.call_count == 1

    with pytest.raises(EufyLoginRateLimitedError):
        await client.login()
    assert mock_session.post.call_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("retry_after", "held"),
    [(None, REQUEST_HOLD_OFF), ("120", REQUEST_HOLD_OFF), ("7200", 7200.0)],
    ids=["none", "short", "long"],
)
async def test_login_429_stops_at_the_first_config_and_holds_off(retry_after, held):
    """HTTP 429 on a login does not go on to the next config and holds off
    requests for at least an hour, longer when Retry-After says so."""
    mock_session = _mock_websession_sequence(
        _rate_limited(retry_after), _login_response(200, "tok_v1")
    )
    client = _make_client(websession=mock_session)

    with pytest.raises(EufyLoginRateLimitedError) as err:
        await client.login()

    assert err.value.retry_after == pytest.approx(held, abs=5)
    assert client.throttle.held_off("requests") == pytest.approx(held, abs=5)
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

    assert err.value.retry_after == pytest.approx(REQUEST_HOLD_OFF, abs=5)
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
@pytest.mark.parametrize("code", [401, -401, "-401"], ids=["401", "-401", "-401-text"])
async def test_a_token_invalid_body_code_is_a_rejected_token(code):
    """Body code 401 or -401 on an HTTP 200 answer rejects the token like HTTP 401."""
    client = _make_client(
        websession=_mock_websession(_body_response(200, {"code": code}))
    )
    client.session = {"access_token": "tok"}

    await client.get_cloud_device_list()

    assert (client.auth_error, client.transient_error) == (True, False)


@pytest.mark.asyncio
async def test_device_list_429_raises_a_rate_limit():
    mock_session = _mock_websession(_rate_limited("60"))
    client = _make_client(websession=mock_session)
    client.session = {"access_token": "tok"}

    with pytest.raises(EufyLoginRateLimitedError) as err:
        await client.get_cloud_device_list()

    assert err.value.retry_after == pytest.approx(REQUEST_HOLD_OFF, abs=5)
    # the home-api fallback is not tried during a rate limit
    assert mock_session.get.call_count == 1


def test_restore_clears_the_recorded_failures():
    client = _make_client()
    client.auth_error = client.transient_error = client.session_replaced = True
    client.restore({"access_token": "t"}, None)
    assert (client.auth_error, client.transient_error, client.session_replaced) == (
        False,
        False,
        False,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("code", [26052, 100032])
async def test_login_challenge_code_raises_challenge(code):
    """A verification code or captcha is not a credential rejection."""
    mock_session = _mock_websession_sequence(_body_response(200, {"res_code": code}))
    client = _make_client(websession=mock_session)

    with pytest.raises(EufyLoginChallengeError) as err:
        await client.login()
    assert err.value.code == code
    assert mock_session.post.call_count == 1


@pytest.mark.asyncio
async def test_login_credential_code_is_a_rejection():
    """A credential code on both configs is a plain rejection ({}), no hold-off."""
    rejected = {"res_code": 26006, "message": "wrong password"}
    mock_session = _mock_websession_sequence(
        _body_response(200, rejected), _body_response(200, rejected)
    )
    client = _make_client(websession=mock_session)

    assert await client.login() == {}
    assert client.throttle.held_off("login") is None


@pytest.mark.asyncio
async def test_login_budget_refuses_before_any_request():
    """Once the budget is spent, login() raises without contacting the cloud."""
    mock_session = MagicMock()
    client = _make_client(websession=mock_session)
    for _ in range(3):
        client.throttle.note_login()

    with pytest.raises(EufyLoginRateLimitedError):
        await client.login()
    mock_session.post.assert_not_called()


@pytest.mark.asyncio
async def test_login_counts_one_attempt_for_all_configs():
    """Trying v2 then v1 is one login against the budget."""
    mock_session = _mock_websession_sequence(
        _login_response(401), _login_response(401)
    )
    client = _make_client(websession=mock_session)

    await client.login()

    assert len(client.throttle.recent_logins()) == 1


@pytest.mark.asyncio
async def test_session_replaced_code_is_flagged():
    """Body code 26084 on an authenticated call marks the session as replaced."""
    resp = _body_response(401, {"res_code": 26084, "message": "kicked out"})
    client = _make_client(websession=_mock_websession(resp))
    client.session = {"access_token": "tok"}

    await client.get_cloud_device_list()

    assert client.session_replaced is True
    assert client.auth_error is True


@pytest.mark.asyncio
async def test_request_hold_off_blocks_authenticated_calls():
    """While requests are held off, no authenticated call reaches the cloud."""
    mock_session = MagicMock()
    client = _make_client(websession=mock_session)
    client.session = {"access_token": "tok"}
    client.throttle.hold_off("requests", 600)

    with pytest.raises(EufyLoginRateLimitedError):
        await client.get_cloud_device_list()
    mock_session.get.assert_not_called()
