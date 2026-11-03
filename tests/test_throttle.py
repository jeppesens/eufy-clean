"""Tests for the login budget and cloud hold-offs (api/throttle.py)."""

from __future__ import annotations

import pytest

from custom_components.robovac_mqtt.api.errors import EufyLoginRateLimitedError
from custom_components.robovac_mqtt.api.throttle import (
    KIND_AUTO_LOGIN,
    KIND_LOGIN,
    KIND_REQUESTS,
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
    first.hold_off(KIND_AUTO_LOGIN, 900)

    second = CloudThrottle(dict(first.state), clock=clock)
    assert len(second.recent_logins()) == 1
    with pytest.raises(EufyLoginRateLimitedError):
        second.check_request()
    assert second.held_off(KIND_AUTO_LOGIN) == pytest.approx(900)


def test_malformed_state_is_dropped_not_raised():
    throttle = CloudThrottle({"logins": ["x", True, 5.0], "hold_off": {"bogus": 1, "login": "y"}})
    assert throttle.state == {"logins": [5.0], "hold_off": {}}
    bad = CloudThrottle("not a dict")
    assert bad.state == {"logins": [], "hold_off": {}}


# A clock that boots this far ahead (no working RTC) until NTP corrects it.
_CLOCK_AHEAD = 30 * 86400.0


def test_times_recorded_with_the_clock_ahead_are_bounded_on_load():
    """A budget and hold-offs saved while the clock ran ahead count from now
    and expire on the corrected clock."""
    clock = Clock()
    ahead = clock.now + _CLOCK_AHEAD
    state = {
        "logins": [ahead] * LOGIN_BUDGET,
        "hold_off": {"login": ahead, "requests": ahead},
    }
    throttle = CloudThrottle(state, clock=clock)

    capped = clock.now + LOCKOUT_HOLD_OFF
    assert throttle.state == {
        "logins": [clock.now] * LOGIN_BUDGET,
        "hold_off": {"login": capped, "requests": capped},
    }
    clock.now += LOCKOUT_HOLD_OFF + 1
    assert throttle.login_allowed()


@pytest.mark.parametrize("first_use", ["held_off", "recent_logins", "hold_off"])
def test_times_recorded_with_the_clock_ahead_are_bounded_on_use(first_use):
    """The clock is corrected while running: whichever call comes first bounds
    the stored times, so they expire on the corrected clock."""
    clock = Clock(1_000_000.0 + _CLOCK_AHEAD)
    throttle = CloudThrottle(clock=clock)
    for _ in range(LOGIN_BUDGET):
        throttle.note_login()
    throttle.hold_off(KIND_LOGIN, LOCKOUT_HOLD_OFF)
    clock.now -= _CLOCK_AHEAD

    if first_use == "held_off":
        assert throttle.held_off(KIND_LOGIN) == LOCKOUT_HOLD_OFF
    elif first_use == "recent_logins":
        assert throttle.recent_logins() == [clock.now] * LOGIN_BUDGET
    else:
        assert throttle.hold_off(KIND_LOGIN, 60) == LOCKOUT_HOLD_OFF

    assert throttle.state == {
        "logins": [clock.now] * LOGIN_BUDGET,
        "hold_off": {"login": clock.now + LOCKOUT_HOLD_OFF},
    }
    clock.now += LOCKOUT_HOLD_OFF + 1
    assert throttle.login_allowed()


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


def _spend_budget(throttle: CloudThrottle) -> None:
    for _ in range(LOGIN_BUDGET):
        throttle.note_login()


@pytest.mark.parametrize(
    ("refuse", "user_refused"),
    [
        (lambda t: t.hold_off(KIND_AUTO_LOGIN, 900), False),
        (lambda t: t.hold_off(KIND_LOGIN, 900), True),
        (lambda t: t.hold_off(KIND_REQUESTS, 900), True),
        (_spend_budget, True),
    ],
    ids=["auto-login-hold-off", "login-hold-off", "request-hold-off", "budget-spent"],
)
def test_a_user_started_login_skips_only_the_integrations_own_hold_off(
    refuse, user_refused
):
    """Both share one persisted state; the user's login waits for the cloud's
    hold-offs and the budget, an automatic login for all of them."""
    clock = Clock()
    automatic = CloudThrottle(clock=clock)
    user = CloudThrottle(automatic.state, clock=clock, user_started=True)
    refuse(automatic)

    assert not automatic.login_allowed()
    assert user.login_allowed() is not user_refused


def test_a_shorter_hold_off_never_shortens_a_running_one():
    throttle = CloudThrottle(clock=Clock())
    throttle.hold_off("login", LOCKOUT_HOLD_OFF)
    throttle.hold_off("login", 60)
    assert throttle.held_off("login") == pytest.approx(LOCKOUT_HOLD_OFF)


def test_a_hold_off_is_capped_at_the_lockout_length():
    throttle = CloudThrottle(clock=Clock())
    throttle.throttled(None, 429, 10 * LOCKOUT_HOLD_OFF, "login")
    assert throttle.held_off("requests") == pytest.approx(LOCKOUT_HOLD_OFF)


def test_login_wait_follows_the_hold_off_and_the_budget():
    clock = Clock()
    throttle = CloudThrottle(clock=clock)
    assert throttle.login_allowed()
    assert throttle.login_wait() is None
    throttle.hold_off("login", 60)
    assert not throttle.login_allowed()
    assert throttle.login_wait() == pytest.approx(60)
    clock.now += 61
    assert throttle.login_allowed()
    for _ in range(LOGIN_BUDGET):
        throttle.note_login()
        clock.now += 3600
    # logins at 0, 1 h and 2 h, now 3 h: the oldest leaves the window first
    assert not throttle.login_allowed()
    assert throttle.login_wait() == pytest.approx(LOGIN_BUDGET_WINDOW - LOGIN_BUDGET * 3600)


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
