from __future__ import annotations

import hashlib
import logging
from collections.abc import Callable
from typing import Any

import aiohttp

from ..const import (
    EUFY_API_DEVICE_LIST,
    EUFY_API_DEVICE_LIST_HOME,
    EUFY_API_DEVICE_LIST_MEGA,
    EUFY_API_DEVICE_V2,
    EUFY_API_LOGIN,
    EUFY_API_LOGIN_V2,
    EUFY_API_MQTT_INFO,
    EUFY_API_USER_INFO,
)
from .mega_http import (
    DEFAULT_COUNTRY_CODE,
    MegaCaptchaRequiredError,
    MegaHTTPClient,
    MegaSessionExpiredError,
    MegaTwoFactorRequiredError,
)

_REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=30)

_LOGGER = logging.getLogger(__name__)

# Legacy login endpoints tried first when no Mega v6 session is saved.
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
        country_code: str = DEFAULT_COUNTRY_CODE,
        mega_session: dict[str, Any] | None = None,
        on_session_updated: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self.username = username
        self.password = password
        self.openudid = openudid
        self._websession = websession
        self.session: dict[str, Any] | None = None
        self.user_info: dict[str, Any] | None = None
        self.use_mega: bool = False
        self.mega = MegaHTTPClient(
            email=username,
            password=password,
            websession=websession,
            country_code=country_code,
            openudid=openudid,
            session_data=mega_session,
            on_session_updated=on_session_updated,
        )

    def export_session(self) -> dict[str, Any]:
        """Export persisted Mega session state if authenticated via Mega."""
        return self.mega.export_session() if self.use_mega else {}

    async def _finalize_mega_login(
        self, mega_result: dict[str, Any], validate_only: bool = False
    ) -> dict[str, Any]:
        self.use_mega = True
        self.session = mega_result
        self.user_info = {
            "user_center_id": self.mega.account_user_id or self.mega.user_id,
            "user_center_token": self.mega.auth_token,
        }
        if validate_only:
            return {"session": mega_result}
        mqtt = await self.get_mqtt_credentials()
        return {"session": mega_result, "user": self.user_info, "mqtt": mqtt}

    async def login_mega(self, validate_only: bool = False) -> dict[str, Any]:
        """Authenticate using the Eufy Mega (v6 unified app) API."""
        mega_result = await self.mega.login()
        _LOGGER.info("Login successful via Eufy Mega v6 API")
        return await self._finalize_mega_login(mega_result, validate_only=validate_only)

    async def solve_captcha(self, answer: str) -> dict[str, Any]:
        """Submit captcha answer to the Mega login flow."""
        mega_result = await self.mega.solve_captcha(answer)
        return await self._finalize_mega_login(mega_result)

    async def submit_verify_code(self, code: str) -> dict[str, Any]:
        """Submit 2FA verification code to the Mega login flow."""
        mega_result = await self.mega.submit_verify_code(code)
        return await self._finalize_mega_login(mega_result)

    async def login(self, validate_only: bool = False) -> dict[str, Any]:
        """Log in via persisted Mega session, else legacy v2/v1 first with Mega fallback."""
        # If this account already has a saved Mega v6 session, reuse it directly.
        if self.mega.has_valid_session:
            return await self.login_mega(validate_only=validate_only)

        # Try legacy v2/v1 endpoints first so unmigrated accounts are unaffected.
        self.use_mega = False
        fallback_session: dict[str, Any] | None = None
        for config in _LOGIN_CONFIGS:
            session = await self._attempt_login(config)
            if not session:
                continue
            self.session = session
            if validate_only:
                _LOGGER.info("Login (validate) successful via %s", config["label"])
                return {"session": session}

            user = await self.get_user_info()
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
            _LOGGER.info(
                "No user_center from legacy login; using fallback session "
                "(Tuya cloud/local discovery before Mega fallback)"
            )
            self.session = fallback_session
            self.user_info = None
            return {"session": fallback_session, "user": None, "mqtt": None}

        # All legacy login endpoints failed — fall back to Mega v6 API.
        _LOGGER.info("Legacy login attempts failed; trying Eufy Mega v6 API")
        try:
            return await self.login_mega(validate_only=validate_only)
        except (
            MegaCaptchaRequiredError,
            MegaTwoFactorRequiredError,
            MegaSessionExpiredError,
        ):
            raise
        except Exception as err:  # noqa: BLE001
            _LOGGER.error("All login attempts failed. Mega v6 error: %s", err)
            return {}

    async def _attempt_login(
        self, config: dict[str, str]
    ) -> dict[str, Any] | None:
        """POST a single legacy credential set; return the session JSON or None."""
        _LOGGER.debug(
            "Attempting legacy login via %s: %s", config["label"], config["url"]
        )
        async with self._websession.post(
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
            except Exception:  # noqa: BLE001
                pass

            if (
                response.status == 200
                and response_json
                and response_json.get("access_token")
            ):
                return response_json

            body = response_json or await response.text()
            _LOGGER.debug(
                "Legacy login failed for %s: %s %s",
                config["label"],
                response.status,
                body,
            )
            return None

    async def get_user_info(self) -> dict[str, Any] | None:
        """Get legacy User Center details."""
        if self.use_mega:
            return self.user_info
        if not self.session:
            return None

        async with self._websession.get(
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

                user_info["gtoken"] = hashlib.md5(
                    user_info["user_center_id"].encode()
                ).hexdigest()
                self.user_info = user_info
                return self.user_info

            _LOGGER.error("get user center info failed")
            self.user_info = None
            return None

    async def get_device_list(self) -> list[dict[str, Any]]:
        """Discover devices via Mega v6 or legacy AIOT endpoints."""
        if self.use_mega:
            return await self.mega.discover_vacuum_devices()

        if not self.user_info:
            _LOGGER.error("Cannot get device list: user_info is None")
            return []

        headers = {
            "user-agent": "EufyHome-Android-3.1.3-753",
            "openudid": self.openudid,
            "os-version": "Android",
            "model-type": "PHONE",
            "app-name": "eufy_home",
            "x-auth-token": self.user_info["user_center_token"],
            "gtoken": self.user_info["gtoken"],
            "content-type": "application/json; charset=UTF-8",
        }

        endpoints = [
            (EUFY_API_DEVICE_LIST, 3, "standard"),
            (EUFY_API_DEVICE_LIST_MEGA, 7, "mega"),
            (EUFY_API_DEVICE_LIST_MEGA, 3, "mega-standard"),
        ]

        for url, attribute, label in endpoints:
            try:
                async with self._websession.post(
                    url,
                    timeout=_REQUEST_TIMEOUT,
                    headers=headers,
                    json={"attribute": attribute},
                ) as response:
                    if response.status != 200:
                        continue
                    data = await response.json()
                    if not isinstance(data, dict):
                        continue
                    payload = data.get("data", data)
                    if not isinstance(payload, dict):
                        continue
                    devices = payload.get("devices", [])
                    if isinstance(devices, dict):
                        devices = devices.get("devices", [])
                    if not isinstance(devices, list):
                        continue
                    result = []
                    for item in devices:
                        if not isinstance(item, dict):
                            continue
                        device = item.get("device", item)
                        if isinstance(device, dict) and device.get("device_sn"):
                            result.append(device)
                    if result:
                        _LOGGER.info(
                            "AIOT %s discovery found %d device(s)", label, len(result)
                        )
                        return result
            except (aiohttp.ClientError, TimeoutError, ValueError) as err:
                _LOGGER.debug("AIOT %s discovery error: %s", label, err)

        _LOGGER.warning("All AIOT device discovery attempts returned no devices")
        return []

    async def get_cloud_device_list(self) -> list[dict[str, Any]]:
        """Get legacy cloud device list (unused on Mega v6, which merges house metadata)."""
        if self.use_mega:
            return []
        if not self.session:
            _LOGGER.error("Cannot get cloud device list: no session")
            return []

        devices = await self._get_cloud_device_list_legacy()
        if devices:
            return devices

        devices = await self._get_home_device_list()
        if devices:
            return devices

        return []

    async def _get_cloud_device_list_legacy(self) -> list[dict[str, Any]]:
        async with self._websession.get(
            EUFY_API_DEVICE_V2,
            timeout=_REQUEST_TIMEOUT,
            headers={
                "content-type": "application/x-www-form-urlencoded; charset=UTF-8",
                "user-agent": "EufyHome-Android-3.1.3-753",
                "category": "Home",
                "token": self.session["access_token"],  # type: ignore[index]
                "openudid": self.openudid,
                "clienttype": "2",
            },
        ) as response:
            if response.status == 200:
                data = await response.json()
                return data.get("devices", [])
            return []

    async def _get_home_device_list(self) -> list[dict[str, Any]]:
        async with self._websession.get(
            EUFY_API_DEVICE_LIST_HOME,
            timeout=_REQUEST_TIMEOUT,
            headers={
                "content-type": "application/json",
                "token": self.session["access_token"],  # type: ignore[index]
            },
        ) as response:
            if response.status == 200:
                data = await response.json()
                if isinstance(data, dict):
                    devices = data.get("devices", data.get("data", []))
                    if isinstance(devices, dict):
                        devices = devices.get("devices", [])
                    if isinstance(devices, list):
                        return devices
            return []

    async def get_mqtt_credentials(self) -> dict[str, Any] | None:
        """Get MQTT credentials via Mega v6 or legacy AIOT endpoint."""
        if self.use_mega:
            creds = await self.mega.get_user_mqtt_info()
            return creds or None

        if not self.user_info:
            _LOGGER.error("Cannot get MQTT credentials: user_info is None")
            return None

        async with self._websession.post(
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