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


@pytest.mark.asyncio
async def test_get_devices_constructs_from_cloud_when_aiot_empty():
    """When AIOT returns no devices but cloud list has entries, construct from cloud."""
    cloud_devices = [
        {
            "id": "SN123",
            "product": {"product_code": "T2276xxx", "name": "X10 Pro Omni"},
            "alias_name": "Living Room",
            "device_model": "T2276",
        }
    ]

    login = _make_login(eufy_api_devices=[])
    login.eufyApi.get_cloud_device_list = AsyncMock(return_value=cloud_devices)
    login.eufyApi.get_device_list = AsyncMock(return_value=[])

    await login.getDevices()

    assert len(login.mqtt_devices) == 1
    assert login.mqtt_devices[0]["deviceId"] == "SN123"
    assert login.mqtt_devices[0]["deviceModel"] == "T2276"
    assert login.mqtt_devices[0]["deviceName"] == "Living Room"
    assert login.mqtt_devices[0]["dps"] == {}
    assert login.mqtt_devices[0]["apiType"] == "legacy"
