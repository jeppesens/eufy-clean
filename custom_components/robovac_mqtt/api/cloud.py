from __future__ import annotations

import json
import logging
from collections.abc import Callable
from typing import Any

from ..const import (
    DPS_MAP,
    EUFY_APPLIANCE_CLEANING,
    EUFY_CLEAN_DEVICES,
    SCALAR_DPS,
    TUYA_IGNORED_PRODUCT_IDS,
    TUYA_PRODUCT_MODELS,
)
from ..utils import is_protobuf_dps_value
from .http import EufyHTTPClient
from .mega_http import (
    DEFAULT_COUNTRY_CODE,
    MegaCaptchaRequiredError,
    MegaSessionExpiredError,
    MegaTwoFactorRequiredError,
)
from .tuya_cloud import TuyaCloudClient, TuyaCloudError

_LOGGER = logging.getLogger(__name__)


def _is_scalar_state_value(value: Any) -> bool:
    """Is DPS 15 a scalar (G50) status — i.e. numeric, not a Tuya status string?"""
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return True
    if isinstance(value, str):
        return value.strip().lstrip("-").isdigit()
    return False


class EufyLoginError(Exception):
    """Eufy Login Error."""


class EufyLogin:
    def __init__(
        self,
        username: str,
        password: str,
        openudid: str,
        websession: Any | None = None,
        country_code: str = DEFAULT_COUNTRY_CODE,
        mega_session: dict[str, Any] | None = None,
        on_session_updated: Callable[[dict[str, Any]], None] | None = None,
    ):
        self.eufyApi = EufyHTTPClient(
            username,
            password,
            openudid,
            websession=websession,
            country_code=country_code,
            mega_session=mega_session,
            on_session_updated=on_session_updated,
        )
        self.username = username
        self.password = password
        self.openudid = openudid or getattr(
            getattr(self.eufyApi, "mega", None), "openudid", ""
        )
        self._websession = websession
        self.mqtt_credentials: dict[str, Any] | None = None
        self.mqtt_devices: list[dict[str, Any]] = []
        self.cloud_devices: list[dict[str, Any]] = []
        self.eufy_api_devices: list[dict[str, Any]] = []
        self.tuya_client: TuyaCloudClient | None = None
        self._eufy_user_id: str | None = None

    def export_session(self) -> dict[str, Any]:
        """Export persisted Mega session data."""
        return self.eufyApi.export_session()

    async def init(self) -> None:
        _LOGGER.debug("EufyLogin.init() starting: HTTP login + device discovery")
        await self.login({"mqtt": True})
        await self._discover_all_devices()

        # If legacy v2/v1 logged in (e.g. stale token or fallback session) but
        # returned no usable MQTT or Tuya Cloud devices, fall back to Mega v6.
        has_usable_mqtt = bool(self.mqtt_devices and self.mqtt_credentials)
        has_usable_cloud = bool(self.cloud_devices)
        if not self.eufyApi.use_mega and not has_usable_mqtt and not has_usable_cloud:
            _LOGGER.info(
                "Legacy login returned no usable devices; falling back to Eufy Mega v6 API"
            )
            try:
                mega_login = await self.eufyApi.login_mega()
            except (
                MegaCaptchaRequiredError,
                MegaTwoFactorRequiredError,
                MegaSessionExpiredError,
            ):
                raise
            except Exception as err:  # noqa: BLE001
                _LOGGER.warning("Eufy Mega v6 fallback login failed: %s", err)
                return

            self._store_login_result(mega_login)
            await self._discover_all_devices()

    async def solve_captcha(self, answer: str) -> None:
        """Continue Mega login with a captcha answer and finish discovery."""
        eufy_login = await self.eufyApi.solve_captcha(answer)
        self._store_login_result(eufy_login)
        await self._discover_all_devices()

    async def submit_verify_code(self, code: str) -> None:
        """Continue Mega login with a 2FA code and finish discovery."""
        eufy_login = await self.eufyApi.submit_verify_code(code)
        self._store_login_result(eufy_login)
        await self._discover_all_devices()

    def _store_login_result(self, eufy_login: dict[str, Any]) -> None:
        if not eufy_login:
            raise EufyLoginError("Login failed")
        self.mqtt_credentials = eufy_login.get("mqtt")
        session = eufy_login.get("session") or {}
        self._eufy_user_id = session.get("user_id")
        _LOGGER.debug(
            "HTTP login successful; mqtt_creds=%s, eufy_user_id=%s",
            "present" if self.mqtt_credentials else "missing",
            "present" if self._eufy_user_id else "missing",
        )

    async def _discover_all_devices(self) -> None:
        self.mqtt_devices = []
        self.cloud_devices = []
        await self.getDevices()

        # Attempt Tuya Cloud login for legacy cloud devices
        try:
            await self.tuya_login()
            await self.getCloudDevices()
        except Exception as e:  # noqa: BLE001
            _LOGGER.warning(
                "Tuya Cloud login failed; legacy cloud devices will be unavailable: %s",
                e,
            )

    async def login(self, config: dict):
        if not config["mqtt"]:
            raise EufyLoginError("MQTT login is required")

        eufy_login = await self.eufyApi.login()
        self._store_login_result(eufy_login)

    async def checkLogin(self):
        if not self.mqtt_credentials:
            await self.login({"mqtt": True})

    async def tuya_login(self) -> None:
        """Attempt Tuya Cloud login using Eufy user_id (EU first, then US)."""
        if not self._eufy_user_id:
            _LOGGER.debug("No Eufy user_id available; skipping Tuya Cloud login")
            return

        try:
            client = TuyaCloudClient("EU", websession=self._websession)
            await client.login(self._eufy_user_id)
            self.tuya_client = client
            _LOGGER.debug("Tuya Cloud login successful (EU)")
            return
        except TuyaCloudError as e:
            _LOGGER.debug("Tuya Cloud EU login failed: %s", e)

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
        _LOGGER.debug(
            "Eufy API returned %d devices from cloud list", len(self.eufy_api_devices)
        )
        devices = await self.eufyApi.get_device_list()
        if not devices and self.eufy_api_devices:
            _LOGGER.info(
                "AIOT device list empty — constructing device entries from cloud device list"
            )
            devices = []
            for record in self.eufy_api_devices:
                if not record.get("id"):
                    continue
                if not self._is_vacuum_record(record):
                    continue
                devices.append(
                    {"device_sn": record["id"], "dps": {}, "_reconstructed": True}
                )

        parsed_devices: list[dict[str, Any]] = []
        for device in devices:
            sn = device.get("device_sn")
            if not sn:
                continue
            model_info = self.findModel(sn, aiot_device=device)
            dps = device.get("dps") or {}
            reconstructed = bool(device.get("_reconstructed", False))
            if dps:
                api_type = self.checkApiType(dps)
            elif not reconstructed:
                # Confirmed AIoT/Mega MQTT device with no initial DPS snapshot:
                # default to novel protobuf (G50 T2210 uses scalar).
                api_type = "scalar" if model_info["deviceModel"] == "T2210" else "novel"
            else:
                api_type = "legacy"

            parsed_devices.append(
                {
                    **model_info,
                    "apiType": api_type,
                    "mqtt": True,
                    "dps": dps,
                    "softVersion": device.get("main_sw_version")
                    or device.get("soft_version")
                    or "",
                    "reconstructed": reconstructed,
                }
            )

        self.mqtt_devices = [d for d in parsed_devices if not d["invalid"]]
        _LOGGER.debug(
            "MQTT devices: %d valid out of %d total (%s)",
            len(self.mqtt_devices),
            len(parsed_devices),
            [
                (d["deviceName"], d["deviceModel"], d["apiType"])
                for d in self.mqtt_devices
            ],
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

        confirmed_ids = {
            d["deviceId"] for d in self.mqtt_devices if not d.get("reconstructed")
        }
        reconstructed_ids = {
            d["deviceId"] for d in self.mqtt_devices if d.get("reconstructed")
        }
        superseded_ids: set[str] = set()
        ignored_ids: set[str] = set()
        seen_cloud_ids: set[str] = set()

        for device in tuya_devices:
            dev_id = device.get("devId")
            if not dev_id or dev_id in seen_cloud_ids:
                continue
            product_id = self._tuya_product_id(device)
            if product_id in TUYA_IGNORED_PRODUCT_IDS:
                if dev_id in reconstructed_ids:
                    ignored_ids.add(dev_id)
                continue
            if dev_id in confirmed_ids:
                continue
            if dev_id in reconstructed_ids:
                superseded_ids.add(dev_id)

            model_info = self.findModel(dev_id, tuya_device=device)
            if model_info["invalid"]:
                continue

            dps = self._coerce_dps(device.get("dps"))
            local_key = device.get("localKey") or ""
            self.cloud_devices.append(
                {
                    **model_info,
                    "apiType": self.checkApiType(dps),
                    "mqtt": False,
                    "dps": dps,
                    "softVersion": "",
                    "local_key": local_key,
                    "tuya_public_ip": device.get("ip") or "",
                }
            )
            seen_cloud_ids.add(dev_id)

        dropped_ids = superseded_ids | ignored_ids
        if dropped_ids:
            self.mqtt_devices = [
                d for d in self.mqtt_devices if d["deviceId"] not in dropped_ids
            ]

        if not superseded_ids:
            leftover = [
                d
                for d in self.mqtt_devices
                if d.get("reconstructed") and d["deviceId"] not in seen_cloud_ids
            ]
            keyed_cloud = [d for d in self.cloud_devices if d.get("local_key")]
            if len(leftover) == 1 and len(keyed_cloud) == 1:
                self.mqtt_devices = [
                    d for d in self.mqtt_devices if d is not leftover[0]
                ]

        if self.cloud_devices:
            _LOGGER.info(
                "Found %d Tuya Cloud device(s): %s",
                len(self.cloud_devices),
                [d["deviceName"] for d in self.cloud_devices],
            )

    @staticmethod
    def _coerce_dps(value: Any) -> dict[str, Any]:
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
                return parsed if isinstance(parsed, dict) else {}
            except Exception:  # noqa: BLE001
                return {}
        if isinstance(value, dict):
            return value
        return {}

    async def get_rtc_config(self, device_id: str) -> dict[str, Any] | None:
        if not self.tuya_client:
            raise TuyaCloudError("NO_SESSION", "no Tuya Cloud session")
        try:
            return await self.tuya_client.get_rtc_config(device_id)
        except TuyaCloudError as e:
            self.tuya_client.sid = None
            await self.tuya_login()
            if not self.tuya_client:
                raise TuyaCloudError(
                    "NO_SESSION", "no Tuya Cloud session after re-login"
                ) from e
            return await self.tuya_client.get_rtc_config(device_id)

    async def getCloudDevice(self, device_id: str) -> dict[str, Any] | None:
        if not self.tuya_client:
            _LOGGER.warning("Cannot poll cloud device: no Tuya client")
            return None

        try:
            return await self.tuya_client.get_device(device_id)
        except TuyaCloudError:
            self.tuya_client.sid = None
            try:
                await self.tuya_login()
                return await self.tuya_client.get_device(device_id)
            except Exception as retry_err:  # noqa: BLE001
                _LOGGER.warning(
                    "Failed to poll cloud device %s after re-login: %s",
                    device_id,
                    retry_err,
                )
                return None

    async def sendCloudCommand(
        self, device_id: str, dps: dict[str, Any]
    ) -> None:
        if not self.tuya_client:
            raise EufyLoginError("Cannot send cloud command: no Tuya client")

        try:
            await self.tuya_client.send_command(device_id, dps)
        except TuyaCloudError:
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
        for key in (DPS_MAP["WORK_STATUS"], DPS_MAP["CLEANING_PARAMETERS"]):
            val = dps.get(key)
            if val is not None:
                return "novel" if is_protobuf_dps_value(val) else "scalar"
        state_val = dps.get(SCALAR_DPS["STATE"])
        if state_val is not None and _is_scalar_state_value(state_val):
            return "scalar"
        if any(k in dps for k in DPS_MAP.values()):
            return "novel"
        return "legacy"

    @staticmethod
    def _resolve_model(code: str) -> str:
        if code in EUFY_CLEAN_DEVICES:
            return code
        truncated = code[:5]
        if truncated in EUFY_CLEAN_DEVICES:
            return truncated
        return code

    @staticmethod
    def _cloud_record_model(record: dict[str, Any]) -> str:
        raw_code = (
            (record.get("product") or {}).get("product_code", "")
            or record.get("device_model", "")
        )
        return EufyLogin._resolve_model(raw_code)

    @staticmethod
    def _is_vacuum_record(record: dict[str, Any]) -> bool:
        product = record.get("product") or {}
        return (
            product.get("appliance") == EUFY_APPLIANCE_CLEANING
            or EufyLogin._cloud_record_model(record) in EUFY_CLEAN_DEVICES
        )

    @staticmethod
    def _tuya_product_id(tuya_device: dict[str, Any]) -> str:
        return tuya_device.get("productId") or tuya_device.get("productKey") or ""

    @staticmethod
    def _resolve_tuya_model(tuya_device: dict[str, Any]) -> str:
        product_id = EufyLogin._tuya_product_id(tuya_device)
        if product_id in TUYA_PRODUCT_MODELS:
            return TUYA_PRODUCT_MODELS[product_id]
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
        device = next(
            (d for d in self.eufy_api_devices if d.get("id") == deviceId), None
        )
        _LOGGER.debug(
            "Device %s: raw model codes: V2 product_code=%r, V2 device_model=%r, "
            "AIOT device_model=%r",
            deviceId,
            ((device or {}).get("product") or {}).get("product_code"),
            (device or {}).get("device_model"),
            (aiot_device or {}).get("device_model"),
        )

        if device:
            return {
                "deviceId": deviceId,
                "deviceModel": self._cloud_record_model(device),
                "deviceName": device.get("alias_name")
                or device.get("device_name")
                or device.get("name"),
                "deviceModelName": (device.get("product") or {}).get("name"),
                "invalid": False,
            }

        if aiot_device:
            model_code = self._resolve_model(aiot_device.get("device_model") or "")
            return {
                "deviceId": deviceId,
                "deviceModel": model_code,
                "deviceName": aiot_device.get("alias_name")
                or aiot_device.get("device_name")
                or "Eufy Robovac",
                "deviceModelName": EUFY_CLEAN_DEVICES.get(model_code),
                "invalid": not bool(model_code),
            }

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
