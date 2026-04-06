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

    def __init__(self, username: str, password: str, openudid: str) -> None:
        self.username = username
        self.password = password
        self.openudid = openudid
        self.session: dict[str, Any] | None = None
        self.user_info: dict[str, Any] | None = None

    async def login(self, validate_only: bool = False) -> dict[str, Any]:
        """Perform login flow."""
        session = await self.eufy_login()
        if not session:
            return {}

        if validate_only:
            return {"session": session}

        user = await self.get_user_info()
        mqtt = await self.get_mqtt_credentials()
        return {"session": session, "user": user, "mqtt": mqtt}

    async def eufy_login(self) -> dict[str, Any] | None:
        """Login to Eufy Cloud. Tries v2 (new Eufy app) first, falls back to v1."""
        last_error: str | None = None

        for config in _LOGIN_CONFIGS:
            _LOGGER.debug("Attempting login via %s: %s", config["label"], config["url"])
            async with aiohttp.ClientSession(timeout=_REQUEST_TIMEOUT) as session:
                async with session.post(
                    config["url"],
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

                    if response.status == 200 and response_json:
                        if response_json.get("access_token"):
                            _LOGGER.info("Login successful via %s", config["label"])
                            self.session = response_json
                            return response_json

                    body = response_json or await response.text()
                    last_error = f"{config['label']}: {response.status} {body}"
                    _LOGGER.debug(
                        "Login attempt failed for %s: %s %s",
                        config["label"],
                        response.status,
                        body,
                    )

        _LOGGER.error("All login attempts failed. Last error: %s", last_error)
        return None

    async def get_user_info(self) -> dict[str, Any] | None:
        """Get User details."""
        if not self.session:
            return None

        async with aiohttp.ClientSession(timeout=_REQUEST_TIMEOUT) as session:
            async with session.get(
                EUFY_API_USER_INFO,
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
                    self.user_info = await response.json()
                    _LOGGER.debug(
                        "get_user_info response keys: %s",
                        list(self.user_info.keys()) if self.user_info else "None",
                    )
                    if self.user_info is None or not self.user_info.get(
                        "user_center_id"
                    ):
                        _LOGGER.error(
                            "No user_center_id found in user_info response"
                        )
                        return None

                    # Generate GToken
                    self.user_info["gtoken"] = hashlib.md5(
                        self.user_info["user_center_id"].encode()
                    ).hexdigest()
                    _LOGGER.debug(
                        "get_user_info: user_center_id=%s, has user_center_token=%s",
                        self.user_info["user_center_id"][:8] + "...",
                        bool(self.user_info.get("user_center_token")),
                    )
                    return self.user_info

                body = await response.text()
                _LOGGER.error(
                    "get_user_info failed: status=%s body=%s",
                    response.status,
                    body[:200],
                )
                return None

    async def get_device_list(self) -> list[dict[str, Any]]:
        """Get list of devices."""
        if not self.user_info:
            _LOGGER.error("Cannot get device list: user_info is None")
            return []

        async with aiohttp.ClientSession(timeout=_REQUEST_TIMEOUT) as session:
            async with session.post(
                EUFY_API_DEVICE_LIST,
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
                        _LOGGER.debug("AIOT get_device_list returned 0 devices")
                        return []
                    result = [device["device"] for device in devices]
                    _LOGGER.debug(
                        "AIOT get_device_list returned %d device(s): %s",
                        len(result),
                        [d.get("device_sn", "?") for d in result],
                    )
                    return result
                body = await response.text()
                _LOGGER.debug(
                    "AIOT get_device_list failed: status=%s body=%s",
                    response.status,
                    body[:200],
                )
                return []

    async def get_cloud_device_list(self) -> list[dict[str, Any]]:
        """Get cloud device list, trying legacy endpoint then home-api fallback."""
        if not self.session:
            _LOGGER.error("Cannot get cloud device list: no session")
            return []

        # Try the legacy api.eufylife.com endpoint first
        devices = await self._get_cloud_device_list_legacy()
        if devices:
            _LOGGER.debug(
                "Cloud device list (legacy) returned %d device(s)", len(devices)
            )
            return devices

        # Fallback: try the home-api endpoint (unified Eufy app)
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
        async with aiohttp.ClientSession(timeout=_REQUEST_TIMEOUT) as session:
            async with session.get(
                EUFY_API_DEVICE_V2,
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
                    data = await response.json()
                    return data.get("devices", [])
                _LOGGER.debug(
                    "Cloud device list (legacy) failed: status=%s", response.status
                )
                return []

    async def _get_home_device_list(self) -> list[dict[str, Any]]:
        """Get device list from home-api.eufylife.com (unified Eufy app endpoint)."""
        async with aiohttp.ClientSession(timeout=_REQUEST_TIMEOUT) as session:
            async with session.get(
                EUFY_API_DEVICE_LIST_HOME,
                headers={
                    "content-type": "application/json",
                    "token": self.session["access_token"],
                },
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    _LOGGER.debug(
                        "Home-api device list raw response keys: %s",
                        list(data.keys()) if isinstance(data, dict) else type(data).__name__,
                    )
                    # The response format may vary; try known structures
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

        async with aiohttp.ClientSession(timeout=_REQUEST_TIMEOUT) as session:
            async with session.post(
                EUFY_API_MQTT_INFO,
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
                    data = (await response.json()).get("data")
                    _LOGGER.debug(
                        "get_mqtt_credentials: got=%s endpoint=%s",
                        bool(data),
                        data.get("endpoint_addr", "?")[:30] if data else "N/A",
                    )
                    return data
                body = await response.text()
                _LOGGER.debug(
                    "get_mqtt_credentials failed: status=%s body=%s",
                    response.status,
                    body[:200],
                )
                return None
