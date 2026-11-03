"""Client-side limits on Eufy cloud logins and requests, persisted per config entry.

The cloud locks an account after repeated logins (code 100028 for 1-2 h, a 24 h
lock after failed passwords) and blocks a client that sends requests too fast,
restarting the block for requests sent during it. The limits are unpublished;
the values below sit at the long end of the reported ones.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any, Final

from .errors import EufyLoginRateLimitedError

# At most this many login attempts per rolling window, whatever their outcome.
LOGIN_BUDGET: Final = 3
LOGIN_BUDGET_WINDOW: Final = 6 * 3600.0

REQUEST_HOLD_OFF: Final = 3600.0
LOGIN_HOLD_OFF: Final = 2 * 3600.0
LOCKOUT_HOLD_OFF: Final = 24 * 3600.0

KIND_REQUESTS: Final = "requests"
KIND_LOGIN: Final = "login"
# Set by the integration itself (MQTT credentials missing or rejected): holds
# the logins it starts on its own, not one the user starts in a config flow.
KIND_AUTO_LOGIN: Final = "auto_login"

# Body codes that throttle or lock: (what is held off, for how long).
THROTTLE_CODES: Final[dict[int, tuple[str, float]]] = {
    26145: (KIND_REQUESTS, REQUEST_HOLD_OFF),  # API request limit
    250999: (KIND_REQUESTS, REQUEST_HOLD_OFF),  # "The request is too fast"
    100028: (KIND_LOGIN, LOGIN_HOLD_OFF),  # too many logins
    10019: (KIND_LOGIN, LOCKOUT_HOLD_OFF),  # too many wrong passwords
    100056: (KIND_LOGIN, LOCKOUT_HOLD_OFF),  # five wrong passwords
    26053: (KIND_LOGIN, LOCKOUT_HOLD_OFF),  # too many verification codes
}

# The login needs an e-mailed code or a captcha.
CHALLENGE_CODES: Final = frozenset({26050, 26051, 26052, 26054, 26167, 100032, 100033})

# Credentials wrong, or the account cannot log in as it is.
CREDENTIAL_CODES: Final = frozenset({22008, 26006, 26015, 26055, 26105, 26108})

# The session was ended; seen after another client logged in with the account.
SESSION_REPLACED_CODE: Final = 26084

# A session rejected again this soon after the login a 26084 caused means a
# second client keeps logging in with the account: a client in use logs in
# again within minutes, an ordinary expiry recurs only after the session's
# 30-day lifetime.
SESSION_REPLACED_WINDOW: Final = 3600.0

# KIND_AUTO_LOGIN hold-off after a login that brought no MQTT credentials (e.g.
# a user-center outage) or ones the broker rejected: later setups reuse the
# session instead of logging in again this soon.
MQTT_CREDENTIALS_HOLD_OFF: Final = 15 * 60.0

# Body codes of an expired or unknown token.
TOKEN_INVALID_CODES: Final = frozenset({401, -401})


def body_code(body: Any) -> int | None:
    """The API's own result code (``res_code``, else ``code``), if it carries one."""
    if not isinstance(body, dict):
        return None
    for key in ("res_code", "code"):
        value = body.get(key)
        if isinstance(value, bool):
            continue
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.strip().lstrip("-").isdigit():
            return int(value)
    return None


class CloudThrottle:
    """Login budget and hold-offs over a JSON-serialisable ``state`` dict.

    ``state`` is the caller's persisted dict, updated in place:
    ``{"logins": [epoch, ...], "hold_off": {kind: until_epoch}}``.
    Its times are bounded by the clock on load and on every use (see
    ``_clamp_to_clock``), so a clock that was far ahead cannot strand them.
    ``user_started``: logins the user starts, which skip KIND_AUTO_LOGIN.
    """

    def __init__(
        self,
        state: dict[str, Any] | None = None,
        clock: Callable[[], float] = time.time,
        *,
        user_started: bool = False,
    ) -> None:
        self._clock = clock
        self._login_kinds: tuple[str, ...] = (KIND_REQUESTS, KIND_LOGIN)
        if not user_started:
            self._login_kinds += (KIND_AUTO_LOGIN,)
        self.state: dict[str, Any] = state if isinstance(state, dict) else {}
        logins = self.state.get("logins")
        self.state["logins"] = [
            float(t)
            for t in (logins if isinstance(logins, list) else [])
            if isinstance(t, (int, float)) and not isinstance(t, bool)
        ]
        hold = self.state.get("hold_off")
        self.state["hold_off"] = {
            k: float(v)
            for k, v in (hold.items() if isinstance(hold, dict) else [])
            if k in (KIND_LOGIN, KIND_REQUESTS, KIND_AUTO_LOGIN)
            and isinstance(v, (int, float))
            and not isinstance(v, bool)
        }
        self._clamp_to_clock()

    def _clamp_to_clock(self) -> float:
        """Bound the stored times by the clock; returns the clock's time.

        A time recorded while the clock ran ahead is later than any real one:
        a login counts from now (it was sent no later than now), a hold-off
        ends at most LOCKOUT_HOLD_OFF from now. Written back, so a bounded
        time expires.
        """
        now = self._clock()
        self.state["logins"] = [min(t, now) for t in self.state["logins"]]
        hold = self.state["hold_off"]
        latest = now + LOCKOUT_HOLD_OFF
        hold.update({k: min(until, latest) for k, until in hold.items()})
        return now

    def held_off(self, kind: str) -> float | None:
        """Seconds left on ``kind``'s hold-off; a login also waits for requests
        and, unless user-started, for KIND_AUTO_LOGIN."""
        now = self._clamp_to_clock()
        kinds = self._login_kinds if kind == KIND_LOGIN else (kind,)
        left = [
            until - now
            for k in kinds
            if (until := self.state["hold_off"].get(k)) is not None and until > now
        ]
        return max(left) if left else None

    def recent_logins(self) -> list[float]:
        """Login attempts inside the budget window, oldest first."""
        cutoff = self._clamp_to_clock() - LOGIN_BUDGET_WINDOW
        return sorted(t for t in self.state["logins"] if t > cutoff)

    def check_request(self) -> None:
        """Refuse locally while a request hold-off runs."""
        if (left := self.held_off(KIND_REQUESTS)) is not None:
            raise EufyLoginRateLimitedError(
                f"holding off the Eufy cloud after it throttled ({left:.0f}s left)",
                retry_after=left,
            )

    def check_login(self) -> None:
        """Refuse locally during a hold-off or once the login budget is spent."""
        if (left := self.held_off(KIND_LOGIN)) is not None:
            raise EufyLoginRateLimitedError(
                f"holding off Eufy logins ({left:.0f}s left)",
                retry_after=left,
            )
        recent = self.recent_logins()
        if len(recent) >= LOGIN_BUDGET:
            left = max(recent[-LOGIN_BUDGET] + LOGIN_BUDGET_WINDOW - self._clock(), 0.0)
            raise EufyLoginRateLimitedError(
                f"{len(recent)} Eufy logins in the last "
                f"{LOGIN_BUDGET_WINDOW / 3600:.0f} h; next allowed in {left:.0f}s",
                retry_after=left,
            )

    def login_wait(self) -> float | None:
        """Seconds until check_login() lets a login through; None when it does now."""
        try:
            self.check_login()
        except EufyLoginRateLimitedError as err:
            return err.retry_after or 0.0
        return None

    def login_allowed(self) -> bool:
        """Would check_login() let a login through now?"""
        return self.login_wait() is None

    def note_login(self) -> None:
        """Count a login attempt; called before it is sent (a timeout may still land)."""
        self.state["logins"] = [*self.recent_logins(), self._clock()]

    def hold_off(self, kind: str, seconds: float) -> float:
        """Start or extend ``kind``'s hold-off; returns the seconds now left."""
        seconds = min(max(seconds, 0.0), LOCKOUT_HOLD_OFF)
        until = self._clamp_to_clock() + seconds
        current = self.state["hold_off"].get(kind, 0.0)
        self.state["hold_off"][kind] = max(current, until)
        return self.state["hold_off"][kind] - self._clock()

    def throttled(
        self, code: int | None, status: int, retry_after: float | None, where: str
    ) -> EufyLoginRateLimitedError | None:
        """Record the hold-off a throttling answer starts and return its error, else None."""
        if status == 429:
            kind, seconds = KIND_REQUESTS, max(REQUEST_HOLD_OFF, retry_after or 0.0)
        elif code in THROTTLE_CODES:
            kind, seconds = THROTTLE_CODES[code]
        else:
            return None
        left = self.hold_off(kind, seconds)
        what = "logins" if kind == KIND_LOGIN else "requests"
        return EufyLoginRateLimitedError(
            f"Eufy cloud throttled {where} (HTTP {status}, code {code}); "
            f"no {what} for {left / 60:.0f} min",
            retry_after=left,
            code=code,
        )
