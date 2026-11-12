from __future__ import annotations

import hashlib
import logging
import time
from collections.abc import Mapping
from datetime import timezone
from email.utils import parsedate_to_datetime
from typing import Any

import aiohttp

from ..const import (
    EUFY_API_DEVICE_LIST,
    EUFY_API_DEVICE_LIST_HOME,
    EUFY_API_DEVICE_V2,
    EUFY_API_LOGIN,
    EUFY_API_LOGIN_V2,
    EUFY_API_MQTT_INFO,
    EUFY_API_USER_INFO,
)

_REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=30)

_LOGGER = logging.getLogger(__name__)


class EufyLoginTransientError(Exception):
    """The login could not be decided: rate limit, server error or network.

    Not a credential rejection; the caller retries later and keeps its tokens.
    """


class EufyLoginRateLimitedError(EufyLoginTransientError):
    """The cloud answered HTTP 429, or a login hold-off refuses the login locally.

    ``retry_after`` is the number of seconds to wait, None when unknown.
    """

    def __init__(self, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


def _is_transient_status(status: int) -> bool:
    """HTTP statuses that say nothing about the credentials."""
    return status in (408, 429) or status >= 500


def _retry_after(response: Any) -> float | None:
    """Seconds from a ``Retry-After`` header (delta-seconds or HTTP-date)."""
    headers = getattr(response, "headers", None)
    if not isinstance(headers, Mapping):
        return None
    value = headers.get("Retry-After")
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return max(float(value), 0.0)
    except ValueError:
        pass
    try:
        when = parsedate_to_datetime(value)
    except (TypeError, ValueError, IndexError):
        return None
    if when.tzinfo is None:  # "-0000": UTC per RFC 5322
        when = when.replace(tzinfo=timezone.utc)
    return max(when.timestamp() - time.time(), 0.0)


def _raise_if_rate_limited(response: Any, where: str) -> None:
    """Raise EufyLoginRateLimitedError for an HTTP 429 answer."""
    if response.status == 429:
        raise EufyLoginRateLimitedError(
            f"{where}: HTTP 429", retry_after=_retry_after(response)
        )


# Tried in order; accounts on the unified Eufy app reject the legacy config.
_LOGIN_CONFIGS: list[dict[str, str]] = [
    {
        "label": "v2 (Eufy app)",
        "url": EUFY_API_LOGIN_V2,
        "client_id": "eufy-app",
        "client_secret": "8FHf22gaTKu7MZXqz5zytw",
        "category": "Health",
    },
    {
        "label": "v1 (Eufy Clean app)",
        "url": EUFY_API_LOGIN,
        "client_id": "eufyhome-app",
        "client_secret": "GQCpr9dSp3uQpsOMgJ4xQ",
        "category": "Home",
    },
]


class EufyHTTPClient:
    """HTTP Client for Eufy Authentication and Device Discovery."""

    def __init__(
        self,
        username: str,
        password: str,
        openudid: str,
        websession: aiohttp.ClientSession,
    ) -> None:
        self.username = username
        self.password = password
        self.openudid = openudid
        self._websession = websession
        self.session: dict[str, Any] | None = None
        self.user_info: dict[str, Any] | None = None
        # _LOGIN_CONFIGS entry that last worked; probing starts there.
        self.login_label: str | None = None
        # The device-list getters collapse every non-200 to [], so only this
        # flag tells a dead token from an account with no such devices.
        self.auth_error: bool = False
        # A 408/5xx on an authenticated call: an outage, not a dead token.
        self.transient_error: bool = False

    async def login(self, validate_only: bool = False) -> dict[str, Any]:
        """Log in, preferring a token that yields a user_center id.

        AIOT/MQTT discovery needs a ``user_center_token``, which some accounts
        only get from the v2 login, so try every config rather than take the
        first access_token. A token without one is kept as a fallback for the
        Tuya path, which needs only the eufy ``user_id``.

        Returns {} when every config rejected the credentials. Raises
        EufyLoginTransientError when a config could not be decided (5xx,
        unreadable body, network error) and none yielded a user_center token,
        and EufyLoginRateLimitedError at the first HTTP 429.
        """
        fallback_session: dict[str, Any] | None = None
        transient: BaseException | None = None
        for config in self._ordered_login_configs():
            try:
                session = await self._attempt_login(config)
            except EufyLoginRateLimitedError:
                # the other config would only add to the rate limit
                raise
            except (EufyLoginTransientError, aiohttp.ClientError, TimeoutError) as err:
                _LOGGER.debug("Login via %s undecided: %s", config["label"], err)
                transient = err
                continue
            if not session:
                continue
            self.session = session
            if validate_only:
                _LOGGER.info("Login (validate) successful via %s", config["label"])
                self.login_label = config["label"]
                return {"session": session}

            try:
                user = await self.get_user_info()  # sets self.user_info
            except EufyLoginRateLimitedError:
                raise
            except (EufyLoginTransientError, aiohttp.ClientError, TimeoutError) as err:
                _LOGGER.debug("User info via %s undecided: %s", config["label"], err)
                transient = err
                continue
            if user and user.get("user_center_id"):
                _LOGGER.info(
                    "Login successful via %s (user_center available)",
                    config["label"],
                )
                self.login_label = config["label"]
                mqtt = await self.get_mqtt_credentials()
                return {"session": session, "user": user, "mqtt": mqtt}

            _LOGGER.debug(
                "Login via %s yielded no user_center; keeping as fallback and "
                "trying the next credential set",
                config["label"],
            )
            if fallback_session is None:
                fallback_session = session

        # An undecided config may be the one that yields a user_center, so a
        # fallback session or a rejection from the others is not conclusive.
        if transient is not None:
            raise EufyLoginTransientError(
                f"Eufy login unavailable: {transient}"
            ) from transient

        if fallback_session is not None:
            _LOGGER.info(
                "No user_center from any login; using fallback session "
                "(Tuya cloud/local discovery only)"
            )
            self.session = fallback_session
            self.user_info = None
            return {"session": fallback_session, "user": None, "mqtt": None}

        _LOGGER.error("All login attempts were rejected")
        return {}

    def _note_auth_status(self, response: Any, where: str) -> None:
        """Classify an authenticated call's answer.

        Raises EufyLoginRateLimitedError on HTTP 429. Records a rejected token
        (``auth_error``) and a server-side failure (``transient_error``), which
        says nothing about the token.
        """
        status = response.status
        _raise_if_rate_limited(response, where)
        if status in (401, 403):
            self.auth_error = True
            _LOGGER.debug("Eufy rejected the session on %s (HTTP %s)", where, status)
        elif _is_transient_status(status):
            self.transient_error = True
            _LOGGER.debug("Eufy %s failed on the server side (HTTP %s)", where, status)

    def _ordered_login_configs(self) -> list[dict[str, str]]:
        """``_LOGIN_CONFIGS`` with a previously successful entry moved to front.

        Reorders only, never filters: a memo that stopped working must still
        fall through to the others.
        """
        if not self.login_label:
            return list(_LOGIN_CONFIGS)
        preferred = [c for c in _LOGIN_CONFIGS if c["label"] == self.login_label]
        if not preferred:
            return list(_LOGIN_CONFIGS)
        return preferred + [c for c in _LOGIN_CONFIGS if c["label"] != self.login_label]

    def restore(
        self,
        session: dict[str, Any] | None,
        user_info: dict[str, Any] | None,
        login_label: str | None = None,
    ) -> None:
        """Adopt a persisted session without contacting the cloud.

        The caller decides whether it is still usable (``can_skip_login``).
        """
        self.session = session
        self.user_info = user_info
        self.login_label = login_label
        self.auth_error = False
        self.transient_error = False

    async def _attempt_login(
        self, config: dict[str, str]
    ) -> dict[str, Any] | None:
        """POST a single credential set; return the session JSON or None.

        None means the server answered and rejected the credentials. Raises
        EufyLoginRateLimitedError for HTTP 429, EufyLoginTransientError for
        another transient status or an unreadable 200.
        """
        _LOGGER.debug(
            "Attempting login via %s: %s", config["label"], config["url"]
        )
        session = self._websession
        async with session.post(
            config["url"],
            timeout=_REQUEST_TIMEOUT,
            headers={
                "category": config["category"],
                "Accept": "*/*",
                "openudid": self.openudid,
                "Content-Type": "application/json",
                "clientType": "1",
                "User-Agent": "EufyHome-Android-3.1.3-753",
                "Connection": "keep-alive",
            },
            json={
                "email": self.username,
                "password": self.password,
                "client_id": config["client_id"],
                "client_secret": config["client_secret"],
            },
        ) as response:
            response_json = None
            try:
                response_json = await response.json()
            except (aiohttp.ContentTypeError, ValueError):
                pass

            _raise_if_rate_limited(response, f"{config['label']} login")
            if _is_transient_status(response.status):
                raise EufyLoginTransientError(
                    f"{config['label']} login: HTTP {response.status}"
                )
            if response.status == 200 and not isinstance(response_json, dict):
                raise EufyLoginTransientError(
                    f"{config['label']} login: unreadable response body"
                )
            if (
                response.status == 200
                and isinstance(response_json, dict)
                and response_json.get("access_token")
            ):
                return response_json

            # Only the status and the API's own error fields: the full body can
            # echo account details back into the log.
            if isinstance(response_json, dict):
                detail = {
                    k: response_json.get(k)
                    for k in ("res_code", "code", "message", "msg")
                    if k in response_json
                }
            else:
                detail = None
            _LOGGER.debug(
                "Login attempt failed for %s: %s %s",
                config["label"],
                response.status,
                detail,
            )
            return None

    async def get_user_info(self) -> dict[str, Any] | None:
        """Get User details; None when the session has no user_center.

        Raises EufyLoginTransientError on a transient HTTP status
        (EufyLoginRateLimitedError for 429).
        """
        if not self.session:
            return None

        session = self._websession
        async with session.get(
            EUFY_API_USER_INFO,
            timeout=_REQUEST_TIMEOUT,
            headers={
                "content-type": "application/x-www-form-urlencoded; charset=UTF-8",
                "user-agent": "EufyHome-Android-3.1.3-753",
                "category": "Home",
                "token": self.session["access_token"],
                "openudid": self.openudid,
                "clienttype": "2",
            },
        ) as response:
            self._note_auth_status(response, "get_user_info")
            if _is_transient_status(response.status):
                raise EufyLoginTransientError(f"user info: HTTP {response.status}")
            if response.status == 200:
                user_info = await response.json()
                # Expected for fallback-session accounts; login() handles it.
                if not isinstance(user_info, dict) or not user_info.get("user_center_id"):
                    _LOGGER.debug("No user_center_id in the user info")
                    self.user_info = None
                    return None

                user_info["gtoken"] = hashlib.md5(
                    user_info["user_center_id"].encode()
                ).hexdigest()
                self.user_info = user_info
                return self.user_info

            _LOGGER.debug("User info request failed: HTTP %s", response.status)
            self.user_info = None
            return None

    async def get_device_list(self) -> list[dict[str, Any]]:
        """Get list of devices."""
        if not self.user_info:
            # Fallback-session accounts have no user_center and no AIOT list.
            _LOGGER.debug("Skipping the AIOT device list: no user_center")
            return []

        session = self._websession
        async with session.post(
            EUFY_API_DEVICE_LIST,
            timeout=_REQUEST_TIMEOUT,
            headers={
                "user-agent": "EufyHome-Android-3.1.3-753",
                "openudid": self.openudid,
                "os-version": "Android",
                "model-type": "PHONE",
                "app-name": "eufy_home",
                "x-auth-token": self.user_info["user_center_token"],
                "gtoken": self.user_info["gtoken"],
                "content-type": "application/json; charset=UTF-8",
            },
            json={"attribute": 3},
        ) as response:
            self._note_auth_status(response, "get_device_list")
            if response.status == 200:
                data = await response.json()
                devices = data.get("data", {}).get("devices")
                if not devices:
                    return []
                return [d["device"] for d in devices if "device" in d]
            return []

    async def get_cloud_device_list(self) -> list[dict[str, Any]]:
        """Get cloud device list, trying legacy endpoint then home-api fallback."""
        if not self.session:
            _LOGGER.error("Cannot get cloud device list: no session")
            return []

        devices = await self._get_cloud_device_list_legacy()
        if devices:
            _LOGGER.debug(
                "Cloud device list (legacy) returned %d device(s)", len(devices)
            )
            return devices

        devices = await self._get_home_device_list()
        if devices:
            _LOGGER.debug(
                "Cloud device list (home-api) returned %d device(s)", len(devices)
            )
            return devices

        _LOGGER.debug("Cloud device list: both endpoints returned 0 devices")
        return []

    async def _get_cloud_device_list_legacy(self) -> list[dict[str, Any]]:
        """Get cloud device list from api.eufylife.com/v1/device/v2."""
        session = self._websession
        async with session.get(
            EUFY_API_DEVICE_V2,
            timeout=_REQUEST_TIMEOUT,
            headers={
                "content-type": "application/x-www-form-urlencoded; charset=UTF-8",
                "user-agent": "EufyHome-Android-3.1.3-753",
                "category": "Home",
                "token": self.session["access_token"],  # type: ignore
                "openudid": self.openudid,
                "clienttype": "2",
            },
        ) as response:
            self._note_auth_status(response, "_get_cloud_device_list_legacy")
            if response.status == 200:
                data = await response.json()
                return data.get("devices", [])
            _LOGGER.debug(
                "Cloud device list (legacy) failed: status=%s", response.status
            )
            return []

    async def _get_home_device_list(self) -> list[dict[str, Any]]:
        """Get device list from home-api.eufylife.com (unified Eufy app endpoint)."""
        session = self._websession
        async with session.get(
            EUFY_API_DEVICE_LIST_HOME,
            timeout=_REQUEST_TIMEOUT,
            headers={
                "content-type": "application/json",
                "token": self.session["access_token"],  # type: ignore
            },
        ) as response:
            self._note_auth_status(response, "_get_home_device_list")
            if response.status == 200:
                data = await response.json()
                _LOGGER.debug(
                    "Home-api device list raw response keys: %s",
                    list(data.keys())
                    if isinstance(data, dict)
                    else type(data).__name__,
                )
                # Response shape varies; try the known structures.
                if isinstance(data, dict):
                    devices = data.get("devices", data.get("data", []))
                    if isinstance(devices, dict):
                        devices = devices.get("devices", [])
                    if isinstance(devices, list):
                        return devices
                return []
            _LOGGER.debug(
                "Home-api device list failed: status=%s", response.status
            )
            return []

    async def get_mqtt_credentials(self) -> dict[str, Any] | None:
        """Get MQTT credentials; raises EufyLoginTransientError on 429/5xx."""
        if not self.user_info:
            _LOGGER.error("Cannot get MQTT credentials: user_info is None")
            return None

        session = self._websession
        async with session.post(
            EUFY_API_MQTT_INFO,
            timeout=_REQUEST_TIMEOUT,
            headers={
                "content-type": "application/json",
                "user-agent": "EufyHome-Android-3.1.3-753",
                "openudid": self.openudid,
                "os-version": "Android",
                "model-type": "PHONE",
                "app-name": "eufy_home",
                "x-auth-token": self.user_info["user_center_token"],
                "gtoken": self.user_info["gtoken"],
            },
        ) as response:
            self._note_auth_status(response, "get_mqtt_credentials")
            if _is_transient_status(response.status):
                raise EufyLoginTransientError(
                    f"MQTT credentials: HTTP {response.status}"
                )
            if response.status == 200:
                return (await response.json()).get("data")
            return None
