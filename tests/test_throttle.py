"""Tests for the login budget and cloud hold-offs (api/throttle.py)."""

from __future__ import annotations

import pytest

from custom_components.robovac_mqtt.api.errors import EufyLoginRateLimitedError
from custom_components.robovac_mqtt.api.throttle import (
    LOCKOUT_HOLD_OFF,
    LOGIN_BUDGET,
    LOGIN_BUDGET_WINDOW,
    LOGIN_HOLD_OFF,
    REQUEST_HOLD_OFF,
    CloudThrottle,
    body_code,
)


class Clock:
    def __init__(self, now: float = 1_000_000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


def test_login_budget_refuses_the_attempt_after_the_last_allowed():
    clock = Clock()
    throttle = CloudThrottle(clock=clock)
    for _ in range(LOGIN_BUDGET):
        throttle.check_login()
        throttle.note_login()
        clock.now += 60

    with pytest.raises(EufyLoginRateLimitedError) as err:
        throttle.check_login()
    assert err.value.retry_after is not None
    assert 0 < err.value.retry_after <= LOGIN_BUDGET_WINDOW


def test_login_budget_frees_up_once_the_oldest_attempt_leaves_the_window():
    clock = Clock()
    throttle = CloudThrottle(clock=clock)
    for _ in range(LOGIN_BUDGET):
        throttle.note_login()
    clock.now += LOGIN_BUDGET_WINDOW + 1

    throttle.check_login()
    assert throttle.recent_logins() == []


def test_state_round_trips_through_the_persisted_dict():
    clock = Clock()
    first = CloudThrottle(clock=clock)
    first.note_login()
    first.hold_off("requests", 120)

    second = CloudThrottle(dict(first.state), clock=clock)
    assert len(second.recent_logins()) == 1
    with pytest.raises(EufyLoginRateLimitedError):
        second.check_request()


def test_malformed_state_is_dropped_not_raised():
    throttle = CloudThrottle({"logins": ["x", True, 5.0], "hold_off": {"bogus": 1, "login": "y"}})
    assert throttle.state == {"logins": [5.0], "hold_off": {}}
    bad = CloudThrottle("not a dict")
    assert bad.state == {"logins": [], "hold_off": {}}


@pytest.mark.parametrize(
    ("code", "kind", "seconds"),
    [
        (250999, "requests", REQUEST_HOLD_OFF),
        (26145, "requests", REQUEST_HOLD_OFF),
        (100028, "login", LOGIN_HOLD_OFF),
        (10019, "login", LOCKOUT_HOLD_OFF),
        (100056, "login", LOCKOUT_HOLD_OFF),
    ],
)
def test_throttle_codes_start_their_hold_off(code, kind, seconds):
    clock = Clock()
    throttle = CloudThrottle(clock=clock)

    err = throttle.throttled(code, 200, None, "login")

    assert isinstance(err, EufyLoginRateLimitedError)
    assert err.code == code
    assert throttle.held_off(kind) == pytest.approx(seconds)


def test_http_429_honours_a_longer_retry_after():
    throttle = CloudThrottle(clock=Clock())
    err = throttle.throttled(None, 429, REQUEST_HOLD_OFF * 2, "device list")
    assert err is not None
    assert err.retry_after == pytest.approx(REQUEST_HOLD_OFF * 2)


def test_a_request_hold_off_also_stops_logins():
    throttle = CloudThrottle(clock=Clock())
    throttle.hold_off("requests", 60)
    with pytest.raises(EufyLoginRateLimitedError):
        throttle.check_login()


def test_a_login_hold_off_leaves_requests_alone():
    throttle = CloudThrottle(clock=Clock())
    throttle.hold_off("login", 60)
    throttle.check_request()
    with pytest.raises(EufyLoginRateLimitedError):
        throttle.check_login()


def test_a_shorter_hold_off_never_shortens_a_running_one():
    throttle = CloudThrottle(clock=Clock())
    throttle.hold_off("login", LOCKOUT_HOLD_OFF)
    throttle.hold_off("login", 60)
    assert throttle.held_off("login") == pytest.approx(LOCKOUT_HOLD_OFF)


def test_a_hold_off_is_capped_at_the_lockout_length():
    throttle = CloudThrottle(clock=Clock())
    throttle.throttled(None, 429, 10 * LOCKOUT_HOLD_OFF, "login")
    assert throttle.held_off("requests") == pytest.approx(LOCKOUT_HOLD_OFF)


def test_login_allowed_follows_the_hold_off_and_the_budget():
    clock = Clock()
    throttle = CloudThrottle(clock=clock)
    assert throttle.login_allowed()
    throttle.hold_off("login", 60)
    assert not throttle.login_allowed()
    clock.now += 61
    assert throttle.login_allowed()
    for _ in range(LOGIN_BUDGET):
        throttle.note_login()
    assert not throttle.login_allowed()


def test_an_ordinary_answer_starts_no_hold_off():
    throttle = CloudThrottle(clock=Clock())
    assert throttle.throttled(26006, 200, None, "login") is None
    assert throttle.throttled(None, 503, None, "login") is None
    assert throttle.held_off("login") is None


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ({"res_code": 100028}, 100028),
        ({"code": "26084"}, 26084),
        ({"res_code": True, "code": 401}, 401),
        ({"message": "x"}, None),
        (None, None),
        ([1], None),
    ],
)
def test_body_code(body, expected):
    assert body_code(body) == expected
