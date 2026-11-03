"""Unit tests for auth_store.py and the cached-login fast path in api/cloud.py."""

import json
import time
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from custom_components.robovac_mqtt.api.cloud import (
    EufyLogin,
    EufyLoginRateLimitedError,
    EufyLoginTransientError,
)
from custom_components.robovac_mqtt.auth_store import (
    LOGIN_HOLD_OFF_DEFAULT,
    LOGIN_HOLD_OFF_MAX,
    AuthCache,
    AuthStore,
    certificate_not_after,
    mqtt_credentials_fresh,
    new_openudid,
    session_expiry,
    trim_session,
    trim_user_info,
)

# ---------------------------------------------------------------------------
# Certificate expiry
# ---------------------------------------------------------------------------


def _self_signed(not_after_delta: timedelta) -> str:
    """A throwaway self-signed cert expiring at now+delta, as PEM."""
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "test")])
    now = datetime.now(timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + not_after_delta)
        .sign(key, hashes.SHA256())
    )
    return cert.public_bytes(serialization.Encoding.PEM).decode()


def _creds(pem: str) -> dict:
    """A complete credential — every field coordinator._initialize_mqtt reads."""
    return {
        "user_id": "u",
        "app_name": "eufy_home",
        "thing_name": "t",
        "certificate_pem": pem,
        "private_key": "k",
        "endpoint_addr": "e",
    }


def test_certificate_not_after_reads_a_real_cert():
    pem = _self_signed(timedelta(days=30))
    parsed = certificate_not_after(pem)
    assert parsed is not None
    assert parsed > datetime.now(timezone.utc)


def test_certificate_not_after_is_none_for_garbage():
    """An unparsable cert must read as 'cannot vouch for it', not as valid."""
    assert certificate_not_after("not a certificate") is None
    assert certificate_not_after("") is None


def test_mqtt_credentials_fresh_accepts_a_live_cert():
    assert mqtt_credentials_fresh(_creds(_self_signed(timedelta(days=30)))) is True


def test_mqtt_credentials_stale_when_the_cert_has_expired():
    assert mqtt_credentials_fresh(_creds(_self_signed(timedelta(days=-1)))) is False


def test_mqtt_credentials_stale_inside_the_expiry_skew():
    """A cert dying in an hour must not be reused across a restart."""
    assert mqtt_credentials_fresh(_creds(_self_signed(timedelta(hours=1)))) is False


def test_mqtt_credentials_stale_when_a_field_is_missing():
    creds = _creds(_self_signed(timedelta(days=30)))
    del creds["private_key"]
    assert mqtt_credentials_fresh(creds) is False


def test_mqtt_credentials_stale_when_absent():
    assert mqtt_credentials_fresh(None) is False


# ---------------------------------------------------------------------------
# AuthCache
# ---------------------------------------------------------------------------

def test_cache_generates_an_openudid_and_round_trips():
    cache = AuthCache()
    assert len(cache.openudid) == 32
    assert AuthCache.from_dict(cache.to_dict()).openudid == cache.openudid


def test_cache_from_dict_ignores_unknown_keys():
    """A store written by a future version must not crash this one."""
    cache = AuthCache.from_dict({"openudid": "abc", "something_new": 1})
    assert cache.openudid == "abc"


def test_cache_from_dict_handles_a_missing_or_empty_store():
    assert len(AuthCache.from_dict(None).openudid) == 32
    assert len(AuthCache.from_dict({}).openudid) == 32
    assert len(AuthCache.from_dict({"openudid": ""}).openudid) == 32


def test_can_skip_login_requires_a_token_and_a_live_cert():
    fresh = _creds(_self_signed(timedelta(days=30)))
    assert AuthCache(
        session={"access_token": "t"}, user_info={"x": 1}, mqtt_credentials=fresh
    ).can_skip_login is True
    # no token
    assert AuthCache(user_info={"x": 1}, mqtt_credentials=fresh).can_skip_login is False
    # expired cert
    assert AuthCache(
        session={"access_token": "t"},
        user_info={"x": 1},
        mqtt_credentials=_creds(_self_signed(timedelta(days=-1))),
    ).can_skip_login is False


def test_can_skip_login_allows_a_fallback_session_account():
    """Accounts with no user_center have no MQTT creds; that is still complete."""
    assert AuthCache(session={"access_token": "t"}).can_skip_login is True


def test_can_skip_login_allows_a_session_without_mqtt_credentials():
    """init() serves discovery with it and logs in for the MQTT credentials
    unless the login hold-off runs."""
    assert AuthCache(
        session={"access_token": "t"}, user_info={"x": 1}
    ).can_skip_login is True


def test_clear_tokens_keeps_identity_and_probe_memos():
    """Rotating the openudid would invalidate the account's tokens."""
    cache = AuthCache(
        openudid="stable",
        login_label="v1 (Eufy Clean app)",
        tuya_region="US",
        session={"access_token": "t"},
        user_info={"x": 1},
        mqtt_credentials={"a": 1},
        login_hold_until=123.0,
    )
    cache.clear_tokens()
    assert cache.openudid == "stable"
    assert cache.login_label == "v1 (Eufy Clean app)"
    assert cache.tuya_region == "US"
    assert cache.login_hold_until == 123.0
    assert cache.session is None and cache.user_info is None
    assert cache.mqtt_credentials is None


def test_new_openudid_is_random():
    assert new_openudid() != new_openudid()


def test_hold_off_logins_uses_retry_after_else_the_default():
    cache = AuthCache()
    assert cache.login_hold_off_left() is None
    cache.hold_off_logins(120)
    assert 110 < cache.login_hold_off_left() <= 120
    cache = AuthCache()
    cache.hold_off_logins(None)
    assert LOGIN_HOLD_OFF_DEFAULT - 10 < cache.login_hold_off_left() <= LOGIN_HOLD_OFF_DEFAULT


def test_hold_off_logins_is_capped_and_never_shortened():
    cache = AuthCache()
    cache.hold_off_logins(10 * LOGIN_HOLD_OFF_MAX)
    assert cache.login_hold_off_left() <= LOGIN_HOLD_OFF_MAX
    cache = AuthCache()
    cache.hold_off_logins(600)
    cache.hold_off_logins(60)
    assert cache.login_hold_off_left() > 590


def test_an_expired_hold_off_allows_logins():
    assert AuthCache(login_hold_until=time.time() - 1).login_hold_off_left() is None


@pytest.mark.parametrize("value", ["soon", True, None, [1]])
def test_cache_from_dict_drops_a_bad_hold_off(value):
    assert AuthCache.from_dict({"login_hold_until": value}).login_hold_until is None


# ---------------------------------------------------------------------------
# EufyLogin.init() fast path
# ---------------------------------------------------------------------------

def _login_with_cache(cache):
    login = EufyLogin("u", "p", "udid", websession=MagicMock(), auth_cache=cache)
    login.getDevices = AsyncMock()
    login.tuya_login = AsyncMock()
    login.getCloudDevices = AsyncMock()
    login.login = AsyncMock()
    return login


def _usable_cache() -> AuthCache:
    return AuthCache(
        session={"access_token": "t", "user_id": "uid"},
        user_info={"user_center_token": "x", "gtoken": "g"},
        mqtt_credentials=_creds(_self_signed(timedelta(days=30))),
        login_label="v2 (Eufy app)",
        tuya_region="US",
    )


@pytest.mark.asyncio
async def test_init_skips_the_login_when_the_cache_is_usable():
    login = _login_with_cache(_usable_cache())

    async def discover():
        login.mqtt_devices = [{"deviceId": "d1"}]

    login.getDevices.side_effect = discover
    await login.init()

    login.login.assert_not_awaited()
    login.getDevices.assert_awaited_once()


@pytest.mark.asyncio
async def test_init_logs_in_when_there_is_no_cache():
    login = _login_with_cache(AuthCache())
    await login.init()
    login.login.assert_awaited_once()


@pytest.mark.asyncio
async def test_stale_cache_falls_back_to_a_full_login():
    """The safety property: a stale cache must never leave us deviceless.

    The cached attempt finds nothing, so the cache is discarded and the full
    login runs — ending in exactly the state an uncached start would reach.
    """
    cache = _usable_cache()
    login = _login_with_cache(cache)
    calls = {"n": 0}

    async def discover():
        calls["n"] += 1
        # First (cached) pass finds nothing; the post-login pass finds the device.
        login.mqtt_devices = [] if calls["n"] == 1 else [{"deviceId": "d1"}]

    login.getDevices.side_effect = discover
    await login.init()

    login.login.assert_awaited_once()
    assert calls["n"] == 2
    assert login.mqtt_devices == [{"deviceId": "d1"}]


@pytest.mark.asyncio
async def test_stale_cache_clears_tokens_but_keeps_the_openudid():
    cache = _usable_cache()
    cache.openudid = "stable"
    login = _login_with_cache(cache)
    login.getDevices.side_effect = lambda: None  # never finds anything

    await login.init()

    assert cache.openudid == "stable"
    # The failed tokens must not be written back for the next restart.
    assert cache.session is None or cache.session == login.eufyApi.session


@pytest.mark.asyncio
async def test_init_captures_refreshed_tokens_into_the_cache():
    cache = AuthCache()
    login = _login_with_cache(cache)
    login.eufyApi.session = {"access_token": "new"}
    login.eufyApi.user_info = {"user_center_token": "n"}
    login.eufyApi.login_label = "v1 (Eufy Clean app)"
    login.mqtt_credentials = {"certificate_pem": "x"}

    async def discover():
        login.mqtt_devices = [{"deviceId": "d1"}]

    login.getDevices.side_effect = discover
    await login.init()

    assert cache.session == {"access_token": "new"}
    assert cache.login_label == "v1 (Eufy Clean app)"
    assert cache.mqtt_credentials == {"certificate_pem": "x"}
    assert cache.login_hold_until is None


@pytest.mark.asyncio
async def test_a_rate_limit_after_the_login_keeps_the_fresh_tokens():
    """A 429 on the device lists right after a login must not waste that login."""
    cache = AuthCache()
    login = _login_with_cache(cache)

    async def fresh_login(_config):
        login.eufyApi.session = {"access_token": "new", "user_id": "uid"}

    login.login.side_effect = fresh_login
    login.getDevices.side_effect = EufyLoginRateLimitedError("HTTP 429", retry_after=30)

    with pytest.raises(EufyLoginRateLimitedError):
        await login.init()

    assert cache.session == {"access_token": "new", "user_id": "uid"}
    assert 20 < cache.login_hold_off_left() <= 30


@pytest.mark.asyncio
async def test_a_rate_limited_cached_run_keeps_the_session_without_a_login():
    cache = _usable_cache()
    session = dict(cache.session)
    login = _login_with_cache(cache)
    login.getDevices.side_effect = EufyLoginRateLimitedError("HTTP 429", retry_after=30)

    with pytest.raises(EufyLoginRateLimitedError):
        await login.init()

    login.login.assert_not_awaited()
    assert cache.session == session
    assert cache.login_hold_off_left() is not None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("auth_error", "transient_error", "tuya_fails", "logs_in"),
    [
        (False, True, False, False),   # Eufy lists 408/5xx
        (False, False, True, False),   # Tuya unreachable, nothing else found
        (True, True, False, True),     # a rejected token wins over an outage
        (True, False, True, True),
        (False, False, False, True),   # genuinely nothing found
    ],
)
async def test_a_cached_run_that_failed_server_side_keeps_the_session(
    auth_error, transient_error, tuya_fails, logs_in
):
    """An outage on discovery says nothing about the token: no login spent on it."""
    cache = _usable_cache()
    session = dict(cache.session)
    login = _login_with_cache(cache)

    async def discover():
        if login.login.await_count:
            login.mqtt_devices = [{"deviceId": "d1"}]
            return
        login.eufyApi.auth_error = auth_error
        login.eufyApi.transient_error = transient_error

    login.getDevices.side_effect = discover
    if tuya_fails:
        login.tuya_login.side_effect = TimeoutError()

    if logs_in:
        await login.init()
        login.login.assert_awaited_once()
    else:
        with pytest.raises(EufyLoginTransientError):
            await login.init()
        login.login.assert_not_awaited()
        assert cache.session == session


def _fallback_cache(**kwargs) -> AuthCache:
    """A session without a user_center and without MQTT credentials."""
    return AuthCache(session={"access_token": "t", "user_id": "uid"}, **kwargs)


@pytest.mark.asyncio
async def test_a_fallback_session_with_mqtt_robots_logs_in_once():
    """The cached session cannot serve MQTT robots: one real login, then a hold-off."""
    cache = _fallback_cache()
    assert cache.can_skip_login
    login = _login_with_cache(cache)

    async def discover():
        login.mqtt_devices = [{"deviceId": "d1"}]

    login.getDevices.side_effect = discover

    async def still_fallback(_config):
        login.eufyApi.session = {"access_token": "t2", "user_id": "uid"}
        login.eufyApi.user_info = None

    login.login.side_effect = still_fallback
    await login.init()
    login.login.assert_awaited_once()
    assert cache.login_hold_off_left() is not None

    # the next setup reuses the session instead of logging in again
    again = _login_with_cache(cache)

    async def discover_again():
        again.mqtt_devices = [{"deviceId": "d1"}]

    again.getDevices.side_effect = discover_again
    await again.init()
    again.login.assert_not_awaited()
    assert again.mqtt_devices == [{"deviceId": "d1"}]


@pytest.mark.asyncio
async def test_a_fallback_session_with_only_tuya_robots_is_reused():
    login = _login_with_cache(_fallback_cache())

    async def discover():
        login.mqtt_devices = []
        login.cloud_devices = [{"deviceId": "tuya1"}]

    login.getDevices.side_effect = discover
    await login.init()

    login.login.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_cache_of_none_disables_caching_entirely():
    """The config-flow validation path passes no cache and must still work."""
    login = _login_with_cache(None)
    await login.init()
    login.login.assert_awaited_once()


# ---------------------------------------------------------------------------
# Session expiry + trimming (the login response carries `expires_in`)
# ---------------------------------------------------------------------------

def test_trim_session_keeps_only_the_fields_that_are_read():
    """The raw login response carries a refresh token and unrelated account data."""
    raw = {
        "access_token": "tok",
        "user_id": "uid",
        "refresh_token": "SECRET-REFRESH",
        "email": "someone@example.com",
        "devices": [{"id": 1}],
        "has_blood_pressure": False,
    }
    trimmed = trim_session(raw)
    assert trimmed == {"access_token": "tok", "user_id": "uid"}
    assert "refresh_token" not in trimmed
    assert "email" not in trimmed


def test_trim_user_info_keeps_only_the_user_center_fields():
    """The user-center response carries account data that is never read."""
    raw = {
        "user_center_id": "uc1",
        "user_center_token": "uct",
        "gtoken": "g",
        "email": "someone@example.com",
        "nick_name": "Someone",
    }
    assert trim_user_info(raw) == {
        "user_center_id": "uc1",
        "user_center_token": "uct",
        "gtoken": "g",
    }
    assert trim_user_info(None) is None


def test_capture_persists_a_trimmed_user_info():
    """The cache written for the next restart holds only the used fields."""
    cache = AuthCache()
    login = _login_with_cache(cache)
    login.eufyApi.user_info = {
        "user_center_id": "uc1",
        "user_center_token": "uct",
        "gtoken": "g",
        "email": "someone@example.com",
    }

    login._capture_auth_cache()

    assert cache.user_info == {
        "user_center_id": "uc1",
        "user_center_token": "uct",
        "gtoken": "g",
    }


def test_cache_from_dict_trims_a_stored_user_info():
    """A store written with the full response is trimmed on load."""
    cache = AuthCache.from_dict(
        {"user_info": {"user_center_id": "uc1", "email": "someone@example.com"}}
    )
    assert cache.user_info == {"user_center_id": "uc1"}


def test_trim_session_handles_absent_input():
    assert trim_session(None) is None
    assert trim_session({}) is None


def test_session_expiry_uses_expires_in():
    """Observed live: expires_in = 2592000 (30 days)."""
    before = time.time()
    got = session_expiry({"expires_in": 2592000})
    assert got is not None
    assert before + 2592000 <= got <= time.time() + 2592000


def test_session_expiry_is_none_without_a_usable_value():
    assert session_expiry({}) is None
    assert session_expiry({"expires_in": "not a number"}) is None
    assert session_expiry({"expires_in": 0}) is None
    assert session_expiry({"expires_in": -1}) is None
    assert session_expiry(None) is None


def test_can_skip_login_rejects_an_expired_session():
    cache = AuthCache(
        session={"access_token": "t"},
        session_expires_at=time.time() - 1,
        user_info={"x": 1},
        mqtt_credentials=_creds(_self_signed(timedelta(days=30))),
    )
    assert cache.can_skip_login is False


def test_can_skip_login_rejects_a_session_inside_the_expiry_skew():
    """A token dying in an hour must not be carried across a restart."""
    cache = AuthCache(
        session={"access_token": "t"},
        session_expires_at=time.time() + 3600,
        user_info={"x": 1},
        mqtt_credentials=_creds(_self_signed(timedelta(days=30))),
    )
    assert cache.can_skip_login is False


def test_can_skip_login_accepts_a_session_with_time_left():
    cache = AuthCache(
        session={"access_token": "t"},
        session_expires_at=time.time() + 30 * 86400,
        user_info={"x": 1},
        mqtt_credentials=_creds(_self_signed(timedelta(days=30))),
    )
    assert cache.can_skip_login is True


def test_can_skip_login_tolerates_an_unknown_expiry():
    """A cache written before session_expires_at existed must still load."""
    cache = AuthCache(
        session={"access_token": "t"},
        user_info={"x": 1},
        mqtt_credentials=_creds(_self_signed(timedelta(days=30))),
    )
    assert cache.session_expires_at is None
    assert cache.can_skip_login is True


# ---------------------------------------------------------------------------
# Hostile / hand-edited store contents must not crash setup
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "session,user_info,creds",
    [
        ("a string, not a dict", {"x": 1}, None),
        ({"access_token": "t"}, "not a dict", None),
        ({"access_token": "t"}, {"x": 1}, ["not", "a", "dict"]),
        ({"access_token": "t"}, {"x": 1}, "nope"),
    ],
)
def test_can_skip_login_survives_a_corrupt_store(session, user_info, creds):
    cache = AuthCache(session=session, user_info=user_info, mqtt_credentials=creds)
    assert cache.can_skip_login is False  # and, crucially, does not raise


def test_can_skip_login_survives_a_non_numeric_expiry():
    cache = AuthCache(
        session={"access_token": "t"},
        session_expires_at="tomorrow",
        user_info={"x": 1},
        mqtt_credentials=_creds(_self_signed(timedelta(days=30))),
    )
    assert cache.can_skip_login is False


def test_clear_tokens_also_clears_the_expiry():
    cache = AuthCache(session={"access_token": "t"}, session_expires_at=time.time() + 99)
    cache.clear_tokens()
    assert cache.session_expires_at is None


def test_cache_round_trips_through_json():
    """Store serialises to JSON; every field must survive it."""
    cache = AuthCache(
        openudid="u", login_label="v2 (Eufy app)", tuya_region="US",
        session={"access_token": "t", "user_id": "i"},
        session_expires_at=time.time() + 99,
        user_info={"gtoken": "g"}, mqtt_credentials={"certificate_pem": "p"},
        login_hold_until=time.time() + 60,
    )
    restored = AuthCache.from_dict(json.loads(json.dumps(cache.to_dict())))
    assert restored == cache


def test_capture_records_the_probed_region_not_a_redirect_code():
    """TuyaCloudClient rewrites .region to Tuya's own code after a redirect.

    Storing that would put a value like "AZ" in the memo, which is not a probe
    candidate — silently disabling the optimisation forever with no signal.
    """
    cache = AuthCache()
    login = EufyLogin("u", "p", "udid", websession=MagicMock(), auth_cache=cache)
    login.tuya_client = MagicMock()
    login.tuya_client.region = "AZ"      # what a redirect leaves behind
    login._tuya_probe_region = "EU"      # what we actually probed
    login._capture_auth_cache()
    assert cache.tuya_region == "EU"


def test_capture_does_not_erase_a_good_login_label_with_none():
    """The fallback-session path never sets a label; it must not wipe the memo."""
    cache = AuthCache(login_label="v1 (Eufy Clean app)")
    login = EufyLogin("u", "p", "udid", websession=MagicMock(), auth_cache=cache)
    login.eufyApi.login_label = None
    login._capture_auth_cache()
    assert cache.login_label == "v1 (Eufy Clean app)"


# ---------------------------------------------------------------------------
# The real safety property (review finding: the old test was tautological)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_live_tuya_must_not_vouch_for_a_dead_eufy_session():
    """The headline bug the review found.

    Tuya authenticates with the eufy USER ID alone and never sees the bearer
    token, so on an account owning both an MQTT robot and a Tuya robot, Tuya
    discovery succeeds against a completely dead eufy session. Accepting that
    as proof would silently drop every MQTT device AND re-persist the dead
    token, repeating on every restart.
    """
    cache = _usable_cache()
    login = _login_with_cache(cache)
    calls = {"n": 0}

    async def discover():
        calls["n"] += 1
        # Eufy side is dead: the HTTP layer records the 401 rejection ...
        if calls["n"] == 1:
            login.eufyApi.auth_error = True
        login.eufy_api_devices = []
        login.mqtt_devices = []
        # ... while Tuya happily returns a device.
        login.cloud_devices = [{"deviceId": "tuya1"}]

    login.getDevices.side_effect = discover

    async def tuya():
        login.cloud_devices = [{"deviceId": "tuya1"}]

    login.getCloudDevices.side_effect = tuya
    await login.init()

    # It must NOT have accepted the cached run.
    login.login.assert_awaited_once()
    assert calls["n"] == 2, "the eufy session was never re-validated"


@pytest.mark.asyncio
async def test_tuya_only_account_still_uses_the_cache():
    """An account with 0 MQTT + 1 cloud device has empty eufy device lists;
    that must not be read as a dead token."""
    cache = _usable_cache()
    login = _login_with_cache(cache)

    async def discover():
        login.eufy_api_devices = []
        login.mqtt_devices = []
        login.cloud_devices = [{"deviceId": "tuya1"}]

    login.getDevices.side_effect = discover
    await login.init()

    login.login.assert_not_awaited()


def test_auth_error_alone_invalidates_a_cached_session():
    login = _login_with_cache(_usable_cache())
    login.cloud_devices = [{"deviceId": "tuya1"}]
    assert login._eufy_session_proved() is True
    login.eufyApi.auth_error = True
    assert login._eufy_session_proved() is False


@pytest.mark.asyncio
async def test_eufy_session_proof_is_rejection_based_not_emptiness_based():
    """Rejection is the signal; an empty list is not.

    An empty eufy list means "this account owns none of that kind" at least as
    often as it means "the token is dead" — proven live on a 0-MQTT account —
    so only an actual 401/403 invalidates the cache.
    """
    login = _login_with_cache(_usable_cache())
    login.eufy_api_devices, login.mqtt_devices, login.cloud_devices = ["x"], [], []
    assert login._eufy_session_proved() is True
    login.eufy_api_devices, login.mqtt_devices = [], ["y"]
    assert login._eufy_session_proved() is True
    # Tuya-only account: accepted, just nothing on the eufy side.
    login.eufy_api_devices, login.mqtt_devices, login.cloud_devices = [], [], ["z"]
    assert login._eufy_session_proved() is True
    # Nothing found anywhere -> something is wrong regardless.
    login.cloud_devices = []
    assert login._eufy_session_proved() is False
    # An explicit rejection always wins, even with devices present.
    login.cloud_devices = ["z"]
    login.eufyApi.auth_error = True
    assert login._eufy_session_proved() is False


@pytest.mark.asyncio
async def test_stale_cache_actually_clears_the_cached_tokens():
    """Replaces a tautological test that passed even with clear_tokens() a no-op."""
    cache = _usable_cache()
    cache.openudid = "stable"
    original_token = cache.session["access_token"]
    login = _login_with_cache(cache)
    seen = {}

    async def discover():
        # Record what clear_tokens() left behind, before _capture repopulates.
        if "after_reset" not in seen and login.login.await_count == 1:
            seen["after_reset"] = cache.session
        login.eufy_api_devices = ["d"] if login.login.await_count else []

    login.getDevices.side_effect = discover
    await login.init()

    assert seen.get("after_reset") is None, "tokens were not cleared before re-login"
    assert cache.openudid == "stable", "identity must survive a token reset"
    assert cache.session != {"access_token": original_token}


async def test_a_certificate_the_broker_rejected_is_not_reused_after_a_restart(hass):
    """Rejected cached cert, replacement login fails: the next setup logs in."""
    store = AuthStore(hass, "entry")
    await store.async_save(_usable_cache())

    def discover(login):
        login.mqtt_devices = [{"deviceId": "d1"}]

    cache = await store.async_load()
    login = _login_with_cache(cache)
    login.getDevices.side_effect = lambda: discover(login)
    await login.init()
    login.login.assert_not_awaited()

    login.login.side_effect = EufyLoginTransientError("HTTP 503")
    rejected = login.mqtt_credentials
    assert not await login.replace_rejected_mqtt_credentials(
        rejected, lambda: store.async_save(cache)
    )

    restarted = _login_with_cache(await store.async_load())
    restarted.getDevices.side_effect = lambda: discover(restarted)
    await restarted.init()
    restarted.login.assert_awaited_once()


@pytest.mark.asyncio
async def test_a_restart_during_the_hold_off_after_a_dropped_certificate_serves_discovery():
    """The rejected cert left the cache while logins are held off: the cached
    session still discovers the robots, without a login."""
    cache = _usable_cache()
    rejected = cache.mqtt_credentials
    login = _login_with_cache(cache)
    cache.hold_off_logins(3600)
    assert not await login.replace_rejected_mqtt_credentials(rejected, AsyncMock())

    restarted = _login_with_cache(cache)

    async def discover():
        restarted.mqtt_devices = [{"deviceId": "d1"}]
        restarted.cloud_devices = [{"deviceId": "t1"}]

    restarted.getDevices.side_effect = discover
    await restarted.init()

    restarted.login.assert_not_awaited()
    assert restarted.cloud_devices == [{"deviceId": "t1"}]
    assert restarted.mqtt_credentials is None
