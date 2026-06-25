from __future__ import annotations

import logging
from typing import Any

from ..const import DPS_MAP, EUFY_CLEAN_DEVICES, SCALAR_DPS, TUYA_PRODUCT_MODELS
from ..utils import is_protobuf_dps_value
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
        # Unified-app (v2) accounts often return an empty AIOT device list even
        # though the cloud device list has entries. Reconstruct minimal AIOT
        # entries from the cloud list so findModel (via aiot/v2 metadata) and
        # MQTT setup still work.
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
                **self.findModel(device.get("device_sn", ""), aiot_device=device),
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
        """Fetch devices from Tuya Cloud and add those not already in MQTT list.

        Per device the Tuya cloud returns ``localKey`` and the last-known
        ``ip``. The local key is the credential needed to talk the Tuya v3
        protocol on port 6668; the ``ip`` is the public address the dock used
        to reach the cloud, which is rarely usable as a LAN target — the user
        normally supplies the LAN address through the integration's options
        (handled in __init__.py).
        """
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

            model_info = self.findModel(dev_id, tuya_device=device)
            if model_info["invalid"]:
                _LOGGER.debug(
                    "Cloud device %s: skipping (no model and no localKey)", dev_id
                )
                continue
            if not model_info["deviceModel"]:
                _LOGGER.warning(
                    "Cloud device %s kept with unknown model "
                    "(productId=%s, name=%s); report this so a "
                    "TUYA_PRODUCT_MODELS mapping can be added",
                    dev_id,
                    device.get("productId") or device.get("productKey"),
                    device.get("name"),
                )

            dps = self._coerce_dps(device.get("dps"))
            local_key = device.get("localKey") or ""
            self.cloud_devices.append(
                {
                    **model_info,
                    "apiType": self.checkApiType(dps),
                    "mqtt": False,
                    "dps": dps,
                    "softVersion": "",
                    # Surface the local-Tuya credentials so the coordinator
                    # (or user-supplied LAN address in options) can promote
                    # the connection to direct local push.
                    "local_key": local_key,
                    "tuya_public_ip": device.get("ip") or "",
                }
            )

        if self.cloud_devices:
            _LOGGER.info(
                "Found %d Tuya Cloud device(s): %s",
                len(self.cloud_devices),
                [d["deviceName"] for d in self.cloud_devices],
            )

    @staticmethod
    def _coerce_dps(value: Any) -> dict[str, Any]:
        """Tuya cloud may return dps as a JSON string OR a dict — normalise."""
        if isinstance(value, str):
            try:
                import json as _json  # local import to avoid module-top dep
                parsed = _json.loads(value)
                return parsed if isinstance(parsed, dict) else {}
            except Exception:  # noqa: BLE001
                return {}
        if isinstance(value, dict):
            return value
        return {}

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

    @staticmethod
    def _resolve_model(code: str) -> str:
        """Return the best device model code, falling back to first 5 chars."""
        if code in EUFY_CLEAN_DEVICES:
            return code
        truncated = code[:5]
        if truncated in EUFY_CLEAN_DEVICES:
            return truncated
        return code

    @staticmethod
    def _resolve_tuya_model(tuya_device: dict[str, Any]) -> str:
        """Best-effort model code for a Tuya-cloud device whose devId does not
        match any Eufy v2 device id.

        Tries the productId/productKey -> model table first, then an EXACT
        model code embedded in the device name. Returns "" when no known model
        can be determined — the caller decides validity.
        """
        product_id = (
            tuya_device.get("productId")
            or tuya_device.get("productKey")
            or ""
        )
        if product_id in TUYA_PRODUCT_MODELS:
            return TUYA_PRODUCT_MODELS[product_id]
        # Only accept a name token that is an EXACT known model code — routing
        # arbitrary tokens through _resolve_model()'s 5-char truncation would
        # false-positive (e.g. "T22610" -> "T2261") on user-set device names.
        name = tuya_device.get("name") or ""
        for token in name.replace("-", " ").split():
            if token in EUFY_CLEAN_DEVICES:
                return token
        return ""

    def findModel(
        self,
        deviceId: str,
        aiot_device: dict | None = None,
        tuya_device: dict | None = None,
    ):
        device = next((d for d in self.eufy_api_devices if d.get("id") == deviceId), None)

        if device:
            raw_code = (
                device.get("product", {}).get("product_code", "")
                or device.get("device_model", "")
            )
            return {
                "deviceId": deviceId,
                "deviceModel": self._resolve_model(raw_code),
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
            # Use the shared resolver (not a raw [:5] slice) so 6-char codes
            # like T2080A (S1 Pro) aren't truncated to T2080 (S1) and
            # misidentified.
            model_code = self._resolve_model(aiot_device.get("device_model") or "")
            return {
                "deviceId": deviceId,
                "deviceModel": model_code,
                "deviceName": aiot_device.get("alias_name")
                or aiot_device.get("device_name")
                or "Eufy Robovac",
                "deviceModelName": None,
                "invalid": not bool(model_code),
            }

        # Fallback: a Tuya-cloud device (legacy transport) whose devId is not in
        # the Eufy v2 list. Resolve the model from the Tuya record rather than
        # skipping the device. A device that exposes a localKey is a real,
        # controllable Tuya device even when its exact model is unknown — keep
        # it (so the legacy/local transport works) and only flag it invalid when
        # there is neither a resolvable model nor a localKey (issue #131).
        if tuya_device is not None:
            model = self._resolve_tuya_model(tuya_device)
            has_local_key = bool(tuya_device.get("localKey"))
            return {
                "deviceId": deviceId,
                "deviceModel": model,
                "deviceName": tuya_device.get("name") or "Eufy Robovac (cloud)",
                "deviceModelName": None,
                "invalid": not (model or has_local_key),
            }

        return {
            "deviceId": deviceId,
            "deviceModel": "",
            "deviceName": "",
            "deviceModelName": "",
            "invalid": True,
        }
