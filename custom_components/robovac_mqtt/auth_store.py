"""Persisted Eufy/Tuya authentication cache, so a restart skips the cold login.

Holds bearer tokens and an X.509 client key in ``.storage``; never logged.
Staleness is guarded by the session expiry, the certificate ``notAfter``, and
finally by use — ``EufyLogin.init()`` discards the cache and re-logs in if a
cached run yields no devices. The login budget and hold-offs
(api/throttle.py) and the session-replaced state are kept here too.
"""
from __future__ import annotations

import logging
import random
import string
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from cryptography import x509
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

STORAGE_VERSION = 1

# treat a certificate as expired this far ahead of its notAfter
_CERT_EXPIRY_SKEW = timedelta(hours=12)

# same, for the bearer session (issued for ~30 days)
_SESSION_EXPIRY_SKEW = timedelta(days=1)

# the only login-response fields the code reads; the rest (refresh token,
# account data) is deliberately not persisted
_SESSION_FIELDS = ("access_token", "user_id")

# the user-center fields api/http.py reads; the rest of that response is
# account data and is not persisted
_USER_INFO_FIELDS = ("user_center_id", "user_center_token", "gtoken")

# mirrors the dereferences in coordinator._initialize_mqtt
_REQUIRED_MQTT_FIELDS = (
    "user_id",
    "app_name",
    "thing_name",
    "certificate_pem",
    "private_key",
    "endpoint_addr",
)


def trim_session(session: dict[str, Any] | None) -> dict[str, Any] | None:
    """Reduce a raw login response to the fields that are actually used."""
    if not session:
        return None
    return {k: session[k] for k in _SESSION_FIELDS if k in session}


def trim_user_info(user_info: dict[str, Any] | None) -> dict[str, Any] | None:
    """Reduce a user-center response to the fields that are actually used."""
    if not user_info:
        return None
    return {k: user_info[k] for k in _USER_INFO_FIELDS if k in user_info}


def session_expiry(session: dict[str, Any] | None) -> float | None:
    """Absolute POSIX expiry implied by a fresh login response's ``expires_in``."""
    if not session:
        return None
    try:
        expires_in = float(session["expires_in"])
    except (KeyError, TypeError, ValueError):
        return None
    if expires_in <= 0:
        return None
    return time.time() + expires_in


def new_openudid() -> str:
    """Generate a fresh device identity for Eufy's ``openudid`` header."""
    return "".join(random.choices(string.hexdigits, k=32))


def certificate_not_after(certificate_pem: str) -> datetime | None:
    """Expiry of a PEM client certificate, or None if it cannot be read."""
    if not certificate_pem:
        return None
    try:
        cert = x509.load_pem_x509_certificate(certificate_pem.encode())
        try:
            return cert.not_valid_after_utc
        except AttributeError:  # cryptography < 42
            return cert.not_valid_after.replace(tzinfo=timezone.utc)
    except Exception:  # noqa: BLE001 - a bad cert just means "re-fetch"
        _LOGGER.debug("Could not parse cached MQTT certificate expiry", exc_info=True)
        return None


def mqtt_credentials_fresh(credentials: dict[str, Any] | None) -> bool:
    """True when cached MQTT credentials are present and not near expiry."""
    if not isinstance(credentials, dict) or not credentials:
        return False
    # must stay in step with coordinator._initialize_mqtt: a missing key there
    # raises outside init(), where nothing invalidates the cache
    for key in _REQUIRED_MQTT_FIELDS:
        if not credentials.get(key):
            return False
    not_after = certificate_not_after(credentials.get("certificate_pem", ""))
    if not_after is None:
        return False
    return datetime.now(timezone.utc) + _CERT_EXPIRY_SKEW < not_after


@dataclass
class AuthCache:
    """Reusable slice of the Eufy/Tuya handshake for one config entry."""

    openudid: str = field(default_factory=new_openudid)
    login_label: str | None = None
    tuya_region: str | None = None
    session: dict[str, Any] | None = None
    # absolute POSIX expiry of the session token; None means unknown
    session_expires_at: float | None = None
    user_info: dict[str, Any] | None = None
    mqtt_credentials: dict[str, Any] | None = None
    # Login budget and hold-offs (api/throttle.py); outlives clear_tokens().
    throttle: dict[str, Any] = field(default_factory=dict)
    # When the login a body code 26084 caused was made (see init()).
    replaced_relogin_at: float | None = None
    # When the session-replaced latch was set; set, no automatic login.
    session_replaced_at: float | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> AuthCache:
        """Rebuild from stored JSON, dropping anything of the wrong shape.

        Type-check every field: a wrong-typed value would raise in
        ``EufyLogin.__init__``, before setup's try/except, leaving the entry in
        the non-retried SETUP_ERROR state.
        """
        if not isinstance(data, dict):
            return cls()

        cache = cls()
        openudid = data.get("openudid")
        if isinstance(openudid, str) and openudid:
            cache.openudid = openudid
        for name in ("login_label", "tuya_region"):
            value = data.get(name)
            if isinstance(value, str):
                setattr(cache, name, value)
        for name in ("session", "user_info", "mqtt_credentials"):
            value = data.get(name)
            if isinstance(value, dict):
                setattr(cache, name, value)
        cache.user_info = trim_user_info(cache.user_info)
        for name in ("session_expires_at", "replaced_relogin_at", "session_replaced_at"):
            value = data.get(name)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                setattr(cache, name, float(value))
        throttle = data.get("throttle")
        if isinstance(throttle, dict):
            cache.throttle = throttle
        # A store without a throttle kept its login hold-off as login_hold_until.
        hold_until = data.get("login_hold_until")
        if (
            not cache.throttle
            and isinstance(hold_until, (int, float))
            and not isinstance(hold_until, bool)
        ):
            cache.throttle = {"hold_off": {"login": float(hold_until)}}
        return cache

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def can_skip_login(self) -> bool:
        """True when the cache holds everything ``login()`` would have produced.

        ``user_info`` may legitimately be absent (fallback-session accounts have
        no user_center and no MQTT credential).
        """
        if not isinstance(self.session, dict) or not self.session.get("access_token"):
            return False
        if self.session_expires_at is not None:
            try:
                expires_at = float(self.session_expires_at)
            except (TypeError, ValueError):
                return False
            if time.time() + _SESSION_EXPIRY_SKEW.total_seconds() >= expires_at:
                return False
        if not isinstance(self.user_info, dict):
            # None: fallback session; EufyLogin.init() logs in again when it
            # finds MQTT robots that this session cannot serve
            return self.user_info is None and self.mqtt_credentials is None
        return mqtt_credentials_fresh(self.mqtt_credentials)

    def clear_tokens(self) -> None:
        """Drop the credentials but keep the identity, the probe memos, the
        throttle state and the session-replaced state.

        The openudid must survive: rotating it invalidates the account's tokens
        and re-registers the device.
        """
        self.session = None
        self.session_expires_at = None
        self.user_info = None
        self.mqtt_credentials = None


class AuthStore:
    """``.storage``-backed home for one config entry's :class:`AuthCache`."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        # private=True writes the file 0600; it holds bearer tokens and an X.509
        # private key, and the rest of .storage is world-readable 0644
        self._store: Store = Store(
            hass,
            STORAGE_VERSION,
            f"{DOMAIN}.auth.{entry_id}",
            private=True,
            atomic_writes=True,
        )
        self._cache: AuthCache | None = None

    async def async_load(self) -> AuthCache:
        """Load the cache, creating a fresh identity on first run."""
        try:
            raw = await self._store.async_load()
        except Exception:  # noqa: BLE001 - a corrupt store must not block setup
            _LOGGER.debug("Auth cache unreadable; starting fresh", exc_info=True)
            raw = None
        self._cache = AuthCache.from_dict(raw)
        return self._cache

    async def async_remove(self) -> None:
        """Delete the stored tokens and client key when the entry is removed."""
        try:
            await self._store.async_remove()
        except Exception:  # noqa: BLE001
            _LOGGER.debug("Could not remove the auth cache", exc_info=True)

    async def async_save(self, cache: AuthCache) -> None:
        """Persist the cache. Never raises: caching is an optimisation only."""
        self._cache = cache
        try:
            await self._store.async_save(cache.to_dict())
        except Exception:  # noqa: BLE001
            _LOGGER.debug("Could not persist the auth cache", exc_info=True)
