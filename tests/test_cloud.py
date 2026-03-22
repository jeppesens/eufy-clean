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


# ── Tuya Cloud login ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_tuya_login_eu_success():
    """tuya_login succeeds on EU region."""
    login = _make_login()
    login._eufy_user_id = "test_user_123"

    with patch(
        "custom_components.robovac_mqtt.api.cloud.TuyaCloudClient"
    ) as MockClient:
        mock_instance = MockClient.return_value
        mock_instance.login = AsyncMock(return_value="session_id")

        await login.tuya_login()

    assert login.tuya_client is mock_instance
    MockClient.assert_called_once_with("EU")


@pytest.mark.asyncio
async def test_tuya_login_eu_fails_us_succeeds():
    """tuya_login falls back to US when EU fails."""
    login = _make_login()
    login._eufy_user_id = "test_user_123"

    from custom_components.robovac_mqtt.api.tuya_cloud import TuyaCloudError

    call_count = 0

    def make_client(region):
        nonlocal call_count
        call_count += 1
        mock = MagicMock()
        if region == "EU":
            mock.login = AsyncMock(side_effect=TuyaCloudError("ERR", "EU failed"))
        else:
            mock.login = AsyncMock(return_value="us_session")
        return mock

    with patch(
        "custom_components.robovac_mqtt.api.cloud.TuyaCloudClient",
        side_effect=make_client,
    ):
        await login.tuya_login()

    assert login.tuya_client is not None
    assert call_count == 2


@pytest.mark.asyncio
async def test_tuya_login_skips_without_user_id():
    """tuya_login does nothing when no Eufy user_id is available."""
    login = _make_login()
    login._eufy_user_id = None

    await login.tuya_login()

    assert login.tuya_client is None


@pytest.mark.asyncio
async def test_login_stores_user_id():
    """login() should store the Eufy user_id from the session."""
    login = _make_login()
    login.eufyApi.login = AsyncMock(
        return_value={
            "mqtt": {"endpoint": "mqtt.example.com"},
            "session": {"user_id": "eu_123", "access_token": "tok"},
        }
    )

    await login.login({"mqtt": True})

    assert login._eufy_user_id == "eu_123"


# ── Cloud device discovery ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_cloud_devices_populates_list():
    """getCloudDevices should find devices not in MQTT list."""
    login = _make_login(
        eufy_api_devices=[
            {
                "id": "cloud_dev_1",
                "product": {"product_code": "T2210xxx", "name": "G30"},
                "alias_name": "Cloud Vacuum",
                "device_model": "T2210",
            }
        ]
    )
    login.mqtt_devices = [
        {"deviceId": "mqtt_dev_1", "deviceName": "MQTT Vacuum"}
    ]

    mock_tuya = MagicMock()
    mock_tuya.get_device_list = AsyncMock(
        return_value=[
            {"devId": "cloud_dev_1", "dps": {"15": "Running", "104": 80}},
        ]
    )
    login.tuya_client = mock_tuya

    await login.getCloudDevices()

    assert len(login.cloud_devices) == 1
    assert login.cloud_devices[0]["deviceId"] == "cloud_dev_1"
    assert login.cloud_devices[0]["mqtt"] is False


@pytest.mark.asyncio
async def test_get_cloud_devices_skips_mqtt_duplicates():
    """Devices already in MQTT list should be excluded from cloud list."""
    login = _make_login(
        eufy_api_devices=[
            {
                "id": "shared_dev",
                "product": {"product_code": "T2261xxx", "name": "X8"},
                "alias_name": "Shared Vacuum",
                "device_model": "T2261",
            }
        ]
    )
    login.mqtt_devices = [
        {"deviceId": "shared_dev", "deviceName": "Shared Vacuum"}
    ]

    mock_tuya = MagicMock()
    mock_tuya.get_device_list = AsyncMock(
        return_value=[
            {"devId": "shared_dev", "dps": {"153": "something"}},
        ]
    )
    login.tuya_client = mock_tuya

    await login.getCloudDevices()

    assert len(login.cloud_devices) == 0


@pytest.mark.asyncio
async def test_get_cloud_devices_skips_invalid_models():
    """Cloud devices not in eufy_api_devices should be skipped."""
    login = _make_login(eufy_api_devices=[])
    login.mqtt_devices = []

    mock_tuya = MagicMock()
    mock_tuya.get_device_list = AsyncMock(
        return_value=[{"devId": "unknown_dev", "dps": {"15": "Running"}}]
    )
    login.tuya_client = mock_tuya

    await login.getCloudDevices()

    assert len(login.cloud_devices) == 0


@pytest.mark.asyncio
async def test_get_cloud_devices_no_tuya_client():
    """getCloudDevices does nothing when tuya_client is None."""
    login = _make_login()
    login.tuya_client = None

    await login.getCloudDevices()

    assert len(login.cloud_devices) == 0


# ── Cloud device polling and commands ───────────────────────────────


@pytest.mark.asyncio
async def test_get_cloud_device_delegates_to_tuya():
    """getCloudDevice should call tuya_client.get_device."""
    login = _make_login()
    mock_tuya = MagicMock()
    mock_tuya.get_device = AsyncMock(return_value={"15": "Charging", "104": 100})
    login.tuya_client = mock_tuya

    result = await login.getCloudDevice("dev_123")

    assert result == {"15": "Charging", "104": 100}
    mock_tuya.get_device.assert_called_once_with("dev_123")


@pytest.mark.asyncio
async def test_send_cloud_command_delegates_to_tuya():
    """sendCloudCommand should call tuya_client.send_command."""
    login = _make_login()
    mock_tuya = MagicMock()
    mock_tuya.send_command = AsyncMock()
    login.tuya_client = mock_tuya

    await login.sendCloudCommand("dev_123", {"2": True})

    mock_tuya.send_command.assert_called_once_with("dev_123", {"2": True})


@pytest.mark.asyncio
async def test_get_cloud_device_no_tuya_client():
    """getCloudDevice returns None when no Tuya client."""
    login = _make_login()
    login.tuya_client = None

    result = await login.getCloudDevice("dev_123")

    assert result is None


# ── Cloud re-login on SID expiration ──────────────────────────────


@pytest.mark.asyncio
async def test_get_cloud_device_relogins_on_failure():
    """getCloudDevice should re-login and retry on TuyaCloudError."""
    from custom_components.robovac_mqtt.api.tuya_cloud import TuyaCloudError

    login = _make_login()
    login._eufy_user_id = "test_user"
    mock_tuya = MagicMock()
    # First call fails, second (after re-login) succeeds
    mock_tuya.get_device = AsyncMock(
        side_effect=[
            TuyaCloudError("EXPIRED", "Session expired"),
            {"15": "Running", "104": 50},
        ]
    )
    mock_tuya.sid = "old_sid"
    login.tuya_client = mock_tuya

    with patch.object(login, "tuya_login", new_callable=AsyncMock) as mock_relogin:
        result = await login.getCloudDevice("dev_123")

    mock_relogin.assert_called_once()
    assert result == {"15": "Running", "104": 50}
    assert mock_tuya.get_device.call_count == 2


@pytest.mark.asyncio
async def test_get_cloud_device_relogin_also_fails():
    """getCloudDevice returns None when re-login also fails."""
    from custom_components.robovac_mqtt.api.tuya_cloud import TuyaCloudError

    login = _make_login()
    login._eufy_user_id = "test_user"
    mock_tuya = MagicMock()
    mock_tuya.get_device = AsyncMock(
        side_effect=TuyaCloudError("EXPIRED", "Session expired")
    )
    mock_tuya.sid = "old_sid"
    login.tuya_client = mock_tuya

    with patch.object(
        login, "tuya_login", new_callable=AsyncMock,
        side_effect=TuyaCloudError("LOGIN_FAIL", "Bad credentials"),
    ):
        result = await login.getCloudDevice("dev_123")

    assert result is None


@pytest.mark.asyncio
async def test_send_cloud_command_relogins_on_failure():
    """sendCloudCommand should re-login and retry on TuyaCloudError."""
    from custom_components.robovac_mqtt.api.tuya_cloud import TuyaCloudError

    login = _make_login()
    login._eufy_user_id = "test_user"
    mock_tuya = MagicMock()
    # First call fails, second (after re-login) succeeds
    mock_tuya.send_command = AsyncMock(
        side_effect=[TuyaCloudError("EXPIRED", "Session expired"), None]
    )
    mock_tuya.sid = "old_sid"
    login.tuya_client = mock_tuya

    with patch.object(login, "tuya_login", new_callable=AsyncMock) as mock_relogin:
        await login.sendCloudCommand("dev_123", {"2": True})

    mock_relogin.assert_called_once()
    assert mock_tuya.send_command.call_count == 2


@pytest.mark.asyncio
async def test_send_cloud_command_relogin_also_fails():
    """sendCloudCommand silently fails when re-login also fails."""
    from custom_components.robovac_mqtt.api.tuya_cloud import TuyaCloudError

    login = _make_login()
    login._eufy_user_id = "test_user"
    mock_tuya = MagicMock()
    mock_tuya.send_command = AsyncMock(
        side_effect=TuyaCloudError("EXPIRED", "Session expired")
    )
    mock_tuya.sid = "old_sid"
    login.tuya_client = mock_tuya

    with patch.object(
        login, "tuya_login", new_callable=AsyncMock,
        side_effect=TuyaCloudError("LOGIN_FAIL", "Bad credentials"),
    ):
        # Should not raise
        await login.sendCloudCommand("dev_123", {"2": True})
