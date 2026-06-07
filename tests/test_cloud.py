"""Unit tests for the cloud login module."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.robovac_mqtt.api.cloud import EufyLogin


def _make_login(
    mqtt_credentials=None,
    eufy_api_devices=None,
) -> EufyLogin:
    """Create an EufyLogin with a mocked eufyApi."""
    with patch(
        "custom_components.robovac_mqtt.api.cloud.EufyHTTPClient", autospec=True
    ):
        login = EufyLogin("user@example.com", "password123", "open-udid")
    login.eufyApi = MagicMock()
    login.eufyApi.login = AsyncMock(
        return_value={"mqtt": {"endpoint": "mqtt.example.com"}}
    )
    login.eufyApi.get_device_list = AsyncMock(return_value=[])
    login.eufyApi.get_cloud_device_list = AsyncMock(return_value=[])
    if mqtt_credentials is not None:
        login.mqtt_credentials = mqtt_credentials
    if eufy_api_devices is not None:
        login.eufy_api_devices = eufy_api_devices
    return login


@pytest.mark.asyncio
async def test_check_login_uses_mqtt_credentials():
    """When mqtt_credentials is None, checkLogin() calls login().
    When mqtt_credentials is already set, checkLogin() does NOT call login()."""
    login = _make_login(mqtt_credentials=None)

    await login.checkLogin()
    login.eufyApi.login.assert_called_once()

    # Reset and set credentials
    login.eufyApi.login.reset_mock()
    login.mqtt_credentials = {"endpoint": "mqtt.example.com"}

    await login.checkLogin()
    login.eufyApi.login.assert_not_called()


def test_check_api_type_novel():
    """checkApiType returns 'novel' when DPS contains a known key (e.g. '153')."""
    assert EufyLogin.checkApiType({"153": "some_value"}) == "novel"


def test_check_api_type_legacy():
    """checkApiType returns 'legacy' when DPS contains no known keys."""
    assert EufyLogin.checkApiType({"999": "value"}) == "legacy"


def test_check_api_type_scalar():
    """Scalar (Tuya, e.g. G50) devices reuse protobuf DPS numbers with int values.

    A key-presence check would misclassify these as 'novel'; value-shape
    classification must return 'scalar'.
    """
    # Real G50 snapshot shape: 153/154 present as plain ints
    assert EufyLogin.checkApiType({"153": 0, "154": 2, "104": 86}) == "scalar"
    # 154 int alone
    assert EufyLogin.checkApiType({"154": 2}) == "scalar"
    # Numeric strings are scalar too
    assert EufyLogin.checkApiType({"154": "2"}) == "scalar"
    # Scalar-only state DPS 15 is a positive signal
    assert EufyLogin.checkApiType({"15": 5}) == "scalar"
    # Genuine protobuf base64 stays novel even alongside scalar-looking keys
    assert EufyLogin.checkApiType({"153": "CgYIBRABGAU="}) == "novel"


def test_find_model_found():
    """findModel returns device info with invalid=False for a known device."""
    login = _make_login(
        eufy_api_devices=[
            {
                "id": "DEV001",
                "product": {"product_code": "T2261xxx", "name": "X8 Pro"},
                "alias_name": "Living Room Vacuum",
                "device_model": "T2261",
            }
        ]
    )

    result = login.findModel("DEV001")

    assert result["deviceId"] == "DEV001"
    assert result["deviceModel"] == "T2261"
    assert result["deviceName"] == "Living Room Vacuum"
    assert result["invalid"] is False


def test_find_model_not_found():
    """findModel returns invalid=True and empty strings for unknown device."""
    login = _make_login(eufy_api_devices=[])

    result = login.findModel("UNKNOWN")

    assert result["deviceId"] == "UNKNOWN"
    assert result["deviceModel"] == ""
    assert result["deviceName"] == ""
    assert result["invalid"] is True


def test_find_model_empty_product_code():
    """When product_code is empty, findModel falls back to device_model."""
    login = _make_login(
        eufy_api_devices=[
            {
                "id": "DEV002",
                "product": {"product_code": "", "name": "Some Vacuum"},
                "alias_name": "Kitchen Vacuum",
                "device_model": "T2210fallback",
            }
        ]
    )

    result = login.findModel("DEV002")

    assert result["deviceModel"] == "T2210"
    assert result["deviceName"] == "Kitchen Vacuum"
    assert result["invalid"] is False


def test_find_model_aiot_fallback_when_v2_empty():
    """When V2 device list is empty, fall back to AIOT data from get_device_list.

    Reproduces the bug where accounts that only have devices registered through
    the modern Eufy Clean app (not the legacy EufyHome app) get an empty V2
    device list, causing every AIOT device to be marked invalid and filtered
    out — leaving the integration with zero discovered vacuums.
    """
    login = _make_login(eufy_api_devices=[])

    aiot_device = {
        "device_sn": "ACN4A00F46300847",
        "device_model": "T2081",
        "device_name": "Robovac",
        "alias_name": None,
    }
    result = login.findModel("ACN4A00F46300847", aiot_device=aiot_device)

    assert result["deviceId"] == "ACN4A00F46300847"
    assert result["deviceModel"] == "T2081"
    assert result["deviceName"] == "Robovac"
    assert result["invalid"] is False


def test_find_model_aiot_fallback_prefers_alias_name():
    """The AIOT fallback prefers alias_name (user-set) over device_name."""
    login = _make_login(eufy_api_devices=[])

    aiot_device = {
        "device_sn": "DEV003",
        "device_model": "T2080",
        "device_name": "Robovac",
        "alias_name": "Upstairs Vacuum",
    }
    result = login.findModel("DEV003", aiot_device=aiot_device)

    assert result["deviceName"] == "Upstairs Vacuum"


def test_find_model_aiot_fallback_invalid_without_model():
    """When neither V2 nor AIOT supply a model code, the device stays invalid."""
    login = _make_login(eufy_api_devices=[])

    aiot_device = {
        "device_sn": "DEV004",
        "device_model": "",
        "device_name": "Mystery Device",
    }
    result = login.findModel("DEV004", aiot_device=aiot_device)

    assert result["deviceModel"] == ""
    assert result["invalid"] is True


def test_find_model_v2_takes_precedence_over_aiot():
    """When V2 has the device, its richer metadata wins over the AIOT fallback."""
    login = _make_login(
        eufy_api_devices=[
            {
                "id": "DEV005",
                "product": {"product_code": "T2261xx", "name": "X8 Pro"},
                "alias_name": "From V2",
                "device_model": "T2261",
            }
        ]
    )

    aiot_device = {
        "device_sn": "DEV005",
        "device_model": "T2081",
        "device_name": "From AIOT",
    }
    result = login.findModel("DEV005", aiot_device=aiot_device)

    assert result["deviceModel"] == "T2261"
    assert result["deviceName"] == "From V2"
    assert result["deviceModelName"] == "X8 Pro"
