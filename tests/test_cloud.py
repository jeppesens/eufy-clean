"""Unit tests for the cloud login module."""

import unittest.mock
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.robovac_mqtt.api import cloud as cloud_mod
from custom_components.robovac_mqtt.api.cloud import EufyLogin, EufyLoginError
from custom_components.robovac_mqtt.api.tuya_cloud import TuyaCloudError


def _make_login(
    mqtt_credentials=None,
    eufy_api_devices=None,
) -> EufyLogin:
    """Create an EufyLogin with a mocked eufyApi."""
    with patch(
        "custom_components.robovac_mqtt.api.cloud.EufyHTTPClient", autospec=True
    ):
        login = EufyLogin("user@example.com", "password123", "open-udid", websession=MagicMock())
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
                "product": {"product_code": "T2261", "name": "X8 Pro"},
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
                "device_model": "T2210",
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


def test_find_model_six_char_product_code():
    """findModel preserves full product code for 6-char codes like T2080A (S1 Pro)."""
    login = _make_login(
        eufy_api_devices=[
            {
                "id": "DEV003",
                "product": {"product_code": "T2080A", "name": "S1 Pro"},
                "alias_name": "S1 Pro Vacuum",
                "device_model": "T2080A",
            }
        ]
    )

    result = login.findModel("DEV003")

    assert result["deviceModel"] == "T2080A"


def test_find_model_truncation_fallback():
    """findModel falls back to first 5 chars if full code is not in EUFY_CLEAN_DEVICES."""
    login = _make_login(
        eufy_api_devices=[
            {
                "id": "DEV004",
                "product": {"product_code": "T2261X", "name": "X8 Pro Variant"},
                "alias_name": "Hallway Vacuum",
                "device_model": "T2261X",
            }
        ]
    )

    result = login.findModel("DEV004")

    # T2261X not in EUFY_CLEAN_DEVICES, but T2261 is -> falls back to T2261
    assert result["deviceModel"] == "T2261"
    assert result["deviceName"] == "Hallway Vacuum"
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
    MockClient.assert_called_once_with("EU", websession=unittest.mock.ANY)


@pytest.mark.asyncio
async def test_tuya_login_eu_fails_us_succeeds():
    """tuya_login falls back to US when EU fails."""
    login = _make_login()
    login._eufy_user_id = "test_user_123"

    call_count = 0

    def make_client(region, **kwargs):
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
    """sendCloudCommand raises EufyLoginError when re-login also fails."""
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
        with pytest.raises(EufyLoginError, match="Failed to send cloud command"):
            await login.sendCloudCommand("dev_123", {"2": True})


# ── AIOT-empty device reconstruction (PR #122 unified-app login) ─────


@pytest.mark.asyncio
async def test_get_devices_constructs_from_cloud_when_aiot_empty():
    """Unified-app (v2) accounts return an empty AIOT device list; getDevices
    must reconstruct entries from the cloud device list so MQTT setup still
    discovers the device (regression guard for PR #122)."""
    login = _make_login()
    login.eufyApi.get_cloud_device_list = AsyncMock(
        return_value=[
            {
                "id": "cloud_only_dev",
                "product": {"product_code": "T2080A", "name": "S1 Pro"},
                "alias_name": "S1 Pro",
                "device_model": "T2080A",
            }
        ]
    )
    login.eufyApi.get_device_list = AsyncMock(return_value=[])  # AIOT empty

    await login.getDevices()

    assert len(login.mqtt_devices) == 1
    dev = login.mqtt_devices[0]
    assert dev["deviceId"] == "cloud_only_dev"
    assert dev["deviceModel"] == "T2080A"
    # Reconstructed entries carry an empty dps -> classified legacy.
    assert dev["apiType"] == "legacy"


# ── Tuya-discovered device model resolution (issue #131) ─────────────


def test_find_model_tuya_fallback_by_product_id(monkeypatch):
    """A Tuya device whose devId isn't in the v2 list resolves via productId."""
    monkeypatch.setattr(cloud_mod, "TUYA_PRODUCT_MODELS", {"prod_s1pro": "T2080A"})
    login = _make_login(eufy_api_devices=[])

    result = login.findModel(
        "tuya_devid",
        tuya_device={"productId": "prod_s1pro", "localKey": "k", "name": "Vac"},
    )

    assert result["deviceModel"] == "T2080A"
    assert result["invalid"] is False


def test_find_model_tuya_fallback_name_embedded_code():
    """Falls back to a model code embedded in the Tuya device name."""
    login = _make_login(eufy_api_devices=[])

    result = login.findModel(
        "tuya_devid",
        tuya_device={"name": "Eufy S1 Pro T2080A", "localKey": "k"},
    )

    assert result["deviceModel"] == "T2080A"
    assert result["invalid"] is False


def test_find_model_tuya_unknown_model_but_localkey_kept():
    """A localKey-bearing device with an unresolvable model is kept, not skipped."""
    login = _make_login(eufy_api_devices=[])

    result = login.findModel(
        "tuya_devid",
        tuya_device={"productId": "unmapped", "localKey": "k", "name": "Mystery"},
    )

    assert result["deviceModel"] == ""
    assert result["invalid"] is False  # kept because a localKey is present


def test_find_model_tuya_no_model_no_localkey_invalid():
    """Without a resolvable model or a localKey, the Tuya device stays invalid."""
    login = _make_login(eufy_api_devices=[])

    result = login.findModel("tuya_devid", tuya_device={"name": "x"})

    assert result["invalid"] is True


@pytest.mark.asyncio
async def test_get_cloud_devices_keeps_localkey_device_with_unknown_model():
    """#131 regression: an S1-Pro-like device with a localKey but no v2 match
    is KEPT in cloud_devices (previously it was wrongly skipped)."""
    login = _make_login(eufy_api_devices=[])
    login.mqtt_devices = []

    mock_tuya = MagicMock()
    mock_tuya.get_device_list = AsyncMock(
        return_value=[
            {
                "devId": "s1pro_dev",
                "localKey": "secret_key",
                "name": "S1 Pro",
                "dps": {"15": "Running"},
            }
        ]
    )
    login.tuya_client = mock_tuya

    await login.getCloudDevices()

    assert len(login.cloud_devices) == 1
    dev = login.cloud_devices[0]
    assert dev["deviceId"] == "s1pro_dev"
    assert dev["local_key"] == "secret_key"
    assert dev["mqtt"] is False


def test_find_model_aiot_fallback_preserves_six_char_code():
    """AIOT fallback must resolve T2080A (S1 Pro), not truncate it to T2080 (S1)."""
    login = _make_login(eufy_api_devices=[])

    result = login.findModel(
        "DEVX",
        aiot_device={
            "device_sn": "DEVX",
            "device_model": "T2080A",
            "device_name": "S1 Pro",
        },
    )

    assert result["deviceModel"] == "T2080A"
    assert result["invalid"] is False


def test_resolve_tuya_model_name_token_requires_exact_match():
    """A name token sharing only a 5-char prefix must not false-match a model."""
    login = _make_login(eufy_api_devices=[])

    # 'T22610' starts with the known prefix 'T2261' but is not a real model.
    result = login.findModel(
        "tuya_devid",
        tuya_device={"name": "My T22610 device", "localKey": "k"},
    )

    # Kept (localKey present) but with NO wrongly-inferred model.
    assert result["deviceModel"] == ""
    assert result["invalid"] is False
