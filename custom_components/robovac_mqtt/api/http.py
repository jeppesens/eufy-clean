from __future__ import annotations

import hashlib
import logging
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

# Login endpoints tried in order: the new unified "Eufy" app (v2) first, then
# the legacy "Eufy Clean" app (v1). Accounts migrated to the unified app no
# longer authenticate against the v1 endpoint, so v2 must be attempted first.
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

    async def login(self, validate_only: bool = False) -> dict[str, Any]:
        """Log in, preferring a credential set whose token yields a user_center id.

        AIOT/MQTT discovery (get_device_list, get_mqtt_credentials) needs a
        ``user_center_token``, which some accounts — notably ones migrated to the
        new unified Eufy app — only obtain from the v2 ``eufy-app`` login; the v1
        token authenticates but returns no user_center (issues #121/#124/#131).
        So rather than use the FIRST login that returns an access_token, try each
        and prefer one whose token actually yields a ``user_center_id``. Fall
        back to any working token — the Tuya cloud path only needs the eufy
        ``user_id``.
        """
        fallback_session: dict[str, Any] | None = None
        for config in _LOGIN_CONFIGS:
            session = await self._attempt_login(config)
            if not session:
                continue
            self.session = session
            if validate_only:
                _LOGGER.info("Login (validate) successful via %s", config["label"])
                return {"session": session}

            user = await self.get_user_info()  # sets self.user_info
            if user and user.get("user_center_id"):
                _LOGGER.info(
                    "Login successful via %s (user_center available)",
                    config["label"],
                )
                mqtt = await self.get_mqtt_credentials()
                return {"session": session, "user": user, "mqtt": mqtt}

            _LOGGER.debug(
                "Login via %s yielded no user_center; keeping as fallback and "
                "trying the next credential set",
                config["label"],
            )
            if fallback_session is None:
                fallback_session = session

        if fallback_session is not None:
            # No login produced a user_center id (e.g. user_center_info returns
            # 401 for this account). Use the fallback so the Tuya cloud/local
            # path can still discover the device via the eufy user_id.
            _LOGGER.info(
                "No user_center from any login; using fallback session "
                "(Tuya cloud/local discovery only)"
            )
            self.session = fallback_session
            self.user_info = None
            return {"session": fallback_session, "user": None, "mqtt": None}

        _LOGGER.error("All login attempts failed.")
        return {}

    async def _attempt_login(
        self, config: dict[str, str]
    ) -> dict[str, Any] | None:
        """POST a single credential set; return the session JSON or None."""
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
            except Exception:
                pass

            if (
                response.status == 200
                and response_json
                and response_json.get("access_token")
            ):
                return response_json

            body = response_json or await response.text()
            _LOGGER.debug(
                "Login attempt failed for %s: %s %s",
                config["label"],
                response.status,
                body,
            )
            return None

    async def get_user_info(self) -> dict[str, Any] | None:
        """Get User details."""
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
            if response.status == 200:
                user_info = await response.json()
                if user_info is None or not user_info.get("user_center_id"):
                    _LOGGER.error("No user_center_id found")
                    self.user_info = None
                    return None

                # Generate GToken
                user_info["gtoken"] = hashlib.md5(
                    user_info["user_center_id"].encode()
                ).hexdigest()
                self.user_info = user_info
                return self.user_info

            _LOGGER.error("get user center info failed")
            self.user_info = None
            return None

    async def get_device_list(self) -> list[dict[str, Any]]:
        """Get list of devices."""
        if not self.user_info:
            _LOGGER.error("Cannot get device list: user_info is None")
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

        # Try the legacy api.eufylife.com endpoint first.
        devices = await self._get_cloud_device_list_legacy()
        if devices:
            _LOGGER.debug(
                "Cloud device list (legacy) returned %d device(s)", len(devices)
            )
            return devices

        # Fallback: the home-api endpoint (unified Eufy app).
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
            if response.status == 200:
                data = await response.json()
                _LOGGER.debug(
                    "Home-api device list raw response keys: %s",
                    list(data.keys())
                    if isinstance(data, dict)
                    else type(data).__name__,
                )
                # The response format may vary; try known structures.
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
        """Get MQTT credentials."""
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
            if response.status == 200:
                return (await response.json()).get("data")
            return None
