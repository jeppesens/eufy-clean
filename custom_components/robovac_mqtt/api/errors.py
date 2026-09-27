"""Exceptions raised by the Eufy cloud login and session layer."""

from __future__ import annotations


class EufyLoginError(Exception):
    """The Eufy cloud rejected the credentials.

    Transient failures (429, 5xx, network) raise EufyLoginTransientError, which
    is not a subclass.
    """


class EufyLoginChallengeError(EufyLoginError):
    """The login needs an e-mailed verification code or a captcha.

    The integration cannot answer it; signing in once in the Eufy app clears it.
    """

    def __init__(self, message: str, code: int | None = None) -> None:
        super().__init__(message)
        self.code = code


class EufyLoginTransientError(Exception):
    """The login could not be decided: rate limit, server error or network.

    Not a credential rejection; the caller retries later and keeps its tokens.
    """


class EufyLoginRateLimitedError(EufyLoginTransientError):
    """The cloud throttled us, or a local hold-off or login budget refuses the call.

    ``retry_after`` is the number of seconds until the next attempt is allowed.
    """

    def __init__(
        self, message: str, retry_after: float | None = None, code: int | None = None
    ) -> None:
        super().__init__(message)
        self.retry_after = retry_after
        self.code = code


class EufySessionReplacedError(Exception):
    """Another client logged in with this account and ended the cached session.

    No automatic login follows: two consumers of one account would log each
    other out until the account locks. A reauth or reconfigure takes it back.
    """
