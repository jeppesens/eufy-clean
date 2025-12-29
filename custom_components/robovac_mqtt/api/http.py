from __future__ import annotations

import hashlib
import logging
from typing import Any

import aiohttp

from ..const import (
    EUFY_API_DEVICE_LIST,
    EUFY_API_DEVICE_V2,
    EUFY_API_LOGIN,
    EUFY_API_MQTT_INFO,
    EUFY_API_USER_INFO,
)

_LOGGER = logging.getLogger(__name__)


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
        """Login to Eufy Cloud."""
        async with aiohttp.ClientSession() as session:
            async with session.post(
                EUFY_API_LOGIN,
                headers={
                    "category": "Home",
                    "Accept": "*/*",
                    "openudid": self.openudid,
                    "Content-Type": "application/json",
                    "clientType": "1",
                    "User-Agent": "EufyHome-iOS-2.14.0-6",
                    "Connection": "keep-alive",
                },
                json={
                    "email": self.username,
                    "password": self.password,
                    "client_id": "eufyhome-app",
                    "client_secret": "GQCpr9dSp3uQpsOMgJ4xQ",
                },
            ) as response:
                if response.status == 200:
                    response_json = await response.json()
                    if response_json.get("access_token"):
                        _LOGGER.debug("eufyLogin successful")
                        self.session = response_json
                        return response_json
                _LOGGER.error(f"Login failed: {await response.json()}")
                return None

    async def get_user_info(self) -> dict[str, Any] | None:
        """Get User details."""
        if not self.session:
            return None

        async with aiohttp.ClientSession() as session:
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
                    if not self.user_info.get("user_center_id"):  # type: ignore
                        _LOGGER.error("No user_center_id found")
                        return None

                    # Generate GToken
                    self.user_info["gtoken"] = hashlib.md5(  # type: ignore
                        self.user_info["user_center_id"].encode()  # type: ignore
                    ).hexdigest()
                    return self.user_info

                _LOGGER.error("get user center info failed")
                return None

    async def get_device_list(self) -> list[dict[str, Any]]:
        """Get list of devices."""
        async with aiohttp.ClientSession() as session:
            async with session.post(
                EUFY_API_DEVICE_LIST,
                headers={
                    "user-agent": "EufyHome-Android-3.1.3-753",
                    "openudid": self.openudid,
                    "os-version": "Android",
                    "model-type": "PHONE",
                    "app-name": "eufy_home",
                    "x-auth-token": self.user_info["user_center_token"],  # type: ignore
                    "gtoken": self.user_info["gtoken"],  # type: ignore
                    "content-type": "application/json; charset=UTF-8",
                },
                json={"attribute": 3},
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    devices = data.get("data", {}).get("devices")
                    if not devices:
                        return []
                    return [device["device"] for device in devices]
                return []

    async def get_cloud_device_list(self) -> list[dict[str, Any]]:
        """Get cloud device list (V2)."""
        async with aiohttp.ClientSession() as session:
            async with session.get(
                EUFY_API_DEVICE_V2,
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
                return []

    async def get_mqtt_credentials(self) -> dict[str, Any] | None:
        """Get MQTT credentials."""
        async with aiohttp.ClientSession() as session:
            async with session.post(
                EUFY_API_MQTT_INFO,
                headers={
                    "content-type": "application/json",
                    "user-agent": "EufyHome-Android-3.1.3-753",
                    "openudid": self.openudid,
                    "os-version": "Android",
                    "model-type": "PHONE",
                    "app-name": "eufy_home",
                    "x-auth-token": self.user_info["user_center_token"],  # type: ignore
                    "gtoken": self.user_info["gtoken"],  # type: ignore
                },
            ) as response:
                if response.status == 200:
                    return (await response.json()).get("data")
                return None
