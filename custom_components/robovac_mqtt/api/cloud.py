from __future__ import annotations

from typing import Any

from ..const import DPS_MAP
from .http import EufyHTTPClient


class EufyLoginError(Exception):
    """Eufy Login Error."""


class EufyLogin:
    def __init__(self, username: str, password: str, openudid: str):
        self.eufyApi = EufyHTTPClient(username, password, openudid)
        self.username = username
        self.password = password
        self.openudid = openudid
        self.sid = None
        self.mqtt_credentials = None
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
        if not self.sid:
            await self.login({"mqtt": True})

    async def getDevices(self) -> None:
        self.eufy_api_devices = await self.eufyApi.get_cloud_device_list()
        devices = await self.eufyApi.get_device_list()
        devices = [
            {
                **self.findModel(device["device_sn"]),
                "apiType": self.checkApiType(device.get("dps", {})),
                "mqtt": True,
                "dps": device.get("dps", {}),
            }
            for device in devices
        ]
        self.mqtt_devices = [d for d in devices if not d["invalid"]]

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
