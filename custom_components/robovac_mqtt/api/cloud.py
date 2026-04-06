from __future__ import annotations

import logging
from typing import Any

from ..const import DPS_MAP
from .http import EufyHTTPClient

_LOGGER = logging.getLogger(__name__)


class EufyLoginError(Exception):
    """Eufy Login Error."""


class EufyLogin:
    def __init__(self, username: str, password: str, openudid: str):
        self.eufyApi = EufyHTTPClient(username, password, openudid)
        self.username = username
        self.password = password
        self.openudid = openudid
        self.mqtt_credentials: dict[str, Any] | None = None
        self.mqtt_devices: list[dict[str, Any]] = []
        self.eufy_api_devices: list[dict[str, Any]] = []

    async def init(self):
        await self.login({"mqtt": True})
        return await self.getDevices()

    async def login(self, config: dict):
        eufyLogin = None

        if not config["mqtt"]:
            raise EufyLoginError("MQTT login is required")

        eufyLogin = await self.eufyApi.login()

        if not eufyLogin:
            raise EufyLoginError("Login failed")

        self.mqtt_credentials = eufyLogin["mqtt"]

    async def checkLogin(self):
        if not self.mqtt_credentials:
            await self.login({"mqtt": True})

    async def getDevices(self) -> None:
        self.eufy_api_devices = await self.eufyApi.get_cloud_device_list()
        _LOGGER.debug(
            "Cloud device list: %d device(s): %s",
            len(self.eufy_api_devices),
            [d.get("id", "?") for d in self.eufy_api_devices],
        )

        devices = await self.eufyApi.get_device_list()
        _LOGGER.debug(
            "AIOT device list: %d device(s): %s",
            len(devices),
            [d.get("device_sn", "?") for d in devices],
        )

        # If AIOT returned nothing, construct entries from cloud device list
        # so devices registered only in the new unified app can still be found.
        if not devices and self.eufy_api_devices:
            _LOGGER.info(
                "AIOT device list empty — constructing device entries from cloud device list"
            )
            devices = [
                {"device_sn": d["id"], "dps": {}}
                for d in self.eufy_api_devices
                if d.get("id")
            ]

        devices = [
            {
                **self.findModel(device["device_sn"]),
                "apiType": self.checkApiType(device.get("dps", {})),
                "mqtt": True,
                "dps": device.get("dps", {}),
                "softVersion": device.get("main_sw_version")
                or device.get("soft_version")
                or "",
            }
            for device in devices
        ]
        self.mqtt_devices = [d for d in devices if not d["invalid"]]
        _LOGGER.debug(
            "Final mqtt_devices: %d device(s): %s",
            len(self.mqtt_devices),
            [(d["deviceId"], d["deviceModel"]) for d in self.mqtt_devices],
        )

    async def getMqttDevice(self, deviceId: str):
        devices = await self.eufyApi.get_device_list()
        return next((d for d in devices if d.get("device_sn") == deviceId), None)

    @staticmethod
    def checkApiType(dps: dict):
        if any(k in dps for k in DPS_MAP.values()):
            return "novel"
        return "legacy"

    def findModel(self, deviceId: str):
        device = next((d for d in self.eufy_api_devices if d["id"] == deviceId), None)

        if device:
            return {
                "deviceId": deviceId,
                "deviceModel": device.get("product", {}).get("product_code", "")[:5]
                or device.get("device_model", "")[:5],
                "deviceName": device.get("alias_name")
                or device.get("device_name")
                or device.get("name"),
                "deviceModelName": device.get("product", {}).get("name"),
                "invalid": False,
            }

        return {
            "deviceId": deviceId,
            "deviceModel": "",
            "deviceName": "",
            "deviceModelName": "",
            "invalid": True,
        }
