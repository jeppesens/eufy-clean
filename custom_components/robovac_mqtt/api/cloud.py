from __future__ import annotations

import logging
from typing import Any

from ..const import DPS_MAP
from .http import EufyHTTPClient
from .tuya_cloud import TuyaCloudClient, TuyaCloudError

_LOGGER = logging.getLogger(__name__)


class EufyLoginError(Exception):
    """Eufy Login Error."""


class EufyLogin:
    def __init__(
        self,
        username: str,
        password: str,
        openudid: str,
        websession: Any | None = None,
    ):
        self.eufyApi = EufyHTTPClient(username, password, openudid, websession=websession)
        self.username = username
        self.password = password
        self.openudid = openudid
        self._websession = websession
        self.mqtt_credentials: dict[str, Any] | None = None
        self.mqtt_devices: list[dict[str, Any]] = []
        self.cloud_devices: list[dict[str, Any]] = []
        self.eufy_api_devices: list[dict[str, Any]] = []
        self.tuya_client: TuyaCloudClient | None = None
        self._eufy_user_id: str | None = None

    async def init(self):
        _LOGGER.debug("EufyLogin.init() starting: HTTP login + device discovery")
        await self.login({"mqtt": True})
        await self.getDevices()

        # Attempt Tuya Cloud login for legacy cloud devices
        try:
            await self.tuya_login()
            await self.getCloudDevices()
        except Exception as e:
            _LOGGER.warning(
                "Tuya Cloud login failed; legacy cloud devices will be unavailable: %s", e
            )

    async def login(self, config: dict):
        eufyLogin = None

        if not config["mqtt"]:
            raise EufyLoginError("MQTT login is required")

        eufyLogin = await self.eufyApi.login()

        if not eufyLogin:
            raise EufyLoginError("Login failed")

        self.mqtt_credentials = eufyLogin["mqtt"]
        _LOGGER.debug("HTTP login successful, MQTT credentials obtained")

        # Store user_id for Tuya Cloud login
        session = eufyLogin.get("session", {})
        self._eufy_user_id = session.get("user_id")
        _LOGGER.debug("Eufy user_id: %s", "present" if self._eufy_user_id else "missing")

    async def checkLogin(self):
        if not self.mqtt_credentials:
            await self.login({"mqtt": True})

    async def tuya_login(self) -> None:
        """Attempt Tuya Cloud login using Eufy user_id.

        Tries EU region first, falls back to US.
        """
        if not self._eufy_user_id:
            _LOGGER.debug("No Eufy user_id available; skipping Tuya Cloud login")
            return

        # Try EU first
        try:
            client = TuyaCloudClient("EU", websession=self._websession)
            await client.login(self._eufy_user_id)
            self.tuya_client = client
            _LOGGER.debug("Tuya Cloud login successful (EU)")
            return
        except TuyaCloudError as e:
            _LOGGER.debug("Tuya Cloud EU login failed: %s", e)

        # Fall back to US
        try:
            client = TuyaCloudClient("US", websession=self._websession)
            await client.login(self._eufy_user_id)
            self.tuya_client = client
            _LOGGER.debug("Tuya Cloud login successful (US)")
        except TuyaCloudError as e:
            _LOGGER.debug("Tuya Cloud US login failed: %s", e)
            raise

    async def getDevices(self) -> None:
        self.eufy_api_devices = await self.eufyApi.get_cloud_device_list()
        _LOGGER.debug("Eufy API returned %d devices from cloud list", len(self.eufy_api_devices))
        devices = await self.eufyApi.get_device_list()
        devices = [
            {
                **self.findModel(device.get("device_sn", "")),
                "apiType": self.checkApiType(device.get("dps", {})),
                "mqtt": True,
                "dps": device.get("dps", {}),
                "softVersion": device.get("main_sw_version")
                or device.get("soft_version")
                or "",
            }
            for device in devices
            if device.get("device_sn")
        ]
        self.mqtt_devices = [d for d in devices if not d["invalid"]]
        _LOGGER.debug(
            "MQTT devices: %d valid out of %d total (%s)",
            len(self.mqtt_devices),
            len(devices),
            [(d["deviceName"], d["apiType"]) for d in self.mqtt_devices],
        )

    async def getCloudDevices(self) -> None:
        """Fetch devices from Tuya Cloud and add those not already in MQTT list."""
        if not self.tuya_client:
            return

        try:
            tuya_devices = await self.tuya_client.get_device_list()
        except TuyaCloudError as e:
            _LOGGER.warning("Failed to fetch Tuya Cloud device list: %s", e)
            return

        # Device IDs already known via MQTT
        mqtt_device_ids = {d["deviceId"] for d in self.mqtt_devices}

        for device in tuya_devices:
            dev_id = device.get("devId")
            if not dev_id or dev_id in mqtt_device_ids:
                _LOGGER.debug("Cloud device %s: skipping (duplicate or no ID)", dev_id)
                continue

            model_info = self.findModel(dev_id)
            if model_info["invalid"]:
                _LOGGER.debug("Cloud device %s: skipping (unknown model)", dev_id)
                continue

            dps = device.get("dps", {})
            self.cloud_devices.append(
                {
                    **model_info,
                    "apiType": self.checkApiType(dps),
                    "mqtt": False,
                    "dps": dps,
                    "softVersion": "",
                }
            )

        if self.cloud_devices:
            _LOGGER.info(
                "Found %d Tuya Cloud device(s): %s",
                len(self.cloud_devices),
                [d["deviceName"] for d in self.cloud_devices],
            )

    async def getCloudDevice(self, device_id: str) -> dict[str, Any] | None:
        """Poll a cloud device's DPS via Tuya Cloud API.

        On failure, attempts re-login and retries once.
        """
        if not self.tuya_client:
            _LOGGER.warning("Cannot poll cloud device: no Tuya client")
            return None

        try:
            result = await self.tuya_client.get_device(device_id)
            _LOGGER.debug(
                "Cloud device %s poll: %s",
                device_id,
                f"{len(result)} DPS keys" if result else "not found",
            )
            return result
        except TuyaCloudError as e:
            _LOGGER.debug("Cloud device %s poll failed: %s; attempting re-login", device_id, e)
            self.tuya_client.sid = None
            try:
                await self.tuya_login()
                return await self.tuya_client.get_device(device_id)
            except Exception as retry_err:
                _LOGGER.warning(
                    "Failed to poll cloud device %s after re-login: %s",
                    device_id,
                    retry_err,
                )
                return None

    async def sendCloudCommand(
        self, device_id: str, dps: dict[str, Any]
    ) -> None:
        """Send a command to a cloud device via Tuya Cloud API.

        On failure, attempts re-login and retries once.
        """
        if not self.tuya_client:
            raise EufyLoginError("Cannot send cloud command: no Tuya client")

        try:
            await self.tuya_client.send_command(device_id, dps)
            _LOGGER.debug("Cloud command to %s succeeded: %s", device_id, dps)
        except TuyaCloudError as e:
            _LOGGER.debug("Cloud command to %s failed: %s; attempting re-login", device_id, e)
            self.tuya_client.sid = None
            try:
                await self.tuya_login()
                await self.tuya_client.send_command(device_id, dps)
            except Exception as retry_err:
                raise EufyLoginError(
                    f"Failed to send cloud command to {device_id}: {retry_err}"
                ) from retry_err

    async def getMqttDevice(self, deviceId: str):
        devices = await self.eufyApi.get_device_list()
        return next((d for d in devices if d.get("device_sn") == deviceId), None)

    @staticmethod
    def checkApiType(dps: dict):
        if any(k in dps for k in DPS_MAP.values()):
            return "novel"
        return "legacy"

    def findModel(self, deviceId: str):
        device = next((d for d in self.eufy_api_devices if d.get("id") == deviceId), None)

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
