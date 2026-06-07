from __future__ import annotations

import logging
from typing import Any

from ..const import DPS_MAP, SCALAR_DPS
from ..utils import is_protobuf_dps_value
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
        devices = await self.eufyApi.get_device_list()
        devices = [
            {
                **self.findModel(device["device_sn"], aiot_device=device),
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

    async def getMqttDevice(self, deviceId: str):
        devices = await self.eufyApi.get_device_list()
        return next((d for d in devices if d.get("device_sn") == deviceId), None)

    @staticmethod
    def checkApiType(dps: dict):
        """Classify a device's DPS protocol from its initial state snapshot.

        - "novel"  : Anker protobuf DPS (WORK_STATUS/CLEANING_PARAMETERS as base64)
        - "scalar" : Tuya-style plain int/JSON DPS over MQTT (e.g. T2210/G50) —
                     reuses the protobuf DPS *numbers* but with int values
        - "legacy" : no protobuf DPS at all (pure Tuya cloud devices, PR #110)

        Value-shape based: a key-presence check alone misclassifies scalar
        devices (which carry protobuf DPS numbers with int values) as novel.
        """
        for key in (DPS_MAP["WORK_STATUS"], DPS_MAP["CLEANING_PARAMETERS"]):
            val = dps.get(key)
            if val is not None:
                return "novel" if is_protobuf_dps_value(val) else "scalar"
        if SCALAR_DPS["STATE"] in dps:
            return "scalar"
        if any(k in dps for k in DPS_MAP.values()):
            return "novel"
        return "legacy"

    def findModel(self, deviceId: str, aiot_device: dict | None = None):
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

        # Fallback: accounts where the V2 endpoint returns no metadata for a
        # device (e.g. devices added through the modern Eufy Clean app rather
        # than the legacy EufyHome app) still get a usable entry from the
        # AIOT device-list response, which carries device_model and
        # device_name directly.
        if aiot_device:
            model_code = (aiot_device.get("device_model") or "")[:5]
            return {
                "deviceId": deviceId,
                "deviceModel": model_code,
                "deviceName": aiot_device.get("alias_name")
                or aiot_device.get("device_name")
                or "Eufy Robovac",
                "deviceModelName": None,
                "invalid": not bool(model_code),
            }

        return {
            "deviceId": deviceId,
            "deviceModel": "",
            "deviceName": "",
            "deviceModelName": "",
            "invalid": True,
        }
