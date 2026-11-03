"""Unit tests for the cloud login module."""

import asyncio
import logging
import unittest.mock
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest

from custom_components.robovac_mqtt.api import cloud as cloud_mod
from custom_components.robovac_mqtt.api.cloud import (
    EufyLogin,
    EufyLoginChallengeError,
    EufyLoginError,
    EufyLoginRateLimitedError,
    EufyLoginTransientError,
)
from custom_components.robovac_mqtt.api.throttle import (
    KIND_LOGIN,
    KIND_REQUESTS,
    LOGIN_BUDGET,
    MISSING_CREDENTIALS_HOLD_OFF,
)
from custom_components.robovac_mqtt.api.tuya_cloud import TuyaCloudError
from custom_components.robovac_mqtt.auth_store import AuthCache


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
@pytest.mark.parametrize(
    "eu_error",
    [TimeoutError(), aiohttp.ClientError("reset"), KeyError("publicKey"), TypeError()],
)
async def test_tuya_login_non_tuya_error_still_probes_us(eu_error):
    """A timeout, transport error or malformed EU answer falls through to US."""
    login = _make_login()
    login._eufy_user_id = "test_user_123"

    def make_client(region, **kwargs):
        mock = MagicMock()
        if region == "EU":
            mock.login = AsyncMock(side_effect=eu_error)
        else:
            mock.login = AsyncMock(return_value="us_session")
        return mock

    with patch(
        "custom_components.robovac_mqtt.api.cloud.TuyaCloudClient",
        side_effect=make_client,
    ):
        await login.tuya_login()

    assert login.tuya_client is not None
    assert login._tuya_probe_region == "US"


def _probe_regions(failing: set[str]):
    """A TuyaCloudClient factory failing in *failing*, and the probe order it records."""
    tried: list[str] = []

    def make_client(region, **kwargs):
        tried.append(region)
        mock = MagicMock()
        if region in failing:
            mock.login = AsyncMock(side_effect=TuyaCloudError("ERR", "nope"))
        else:
            mock.login = AsyncMock(return_value="sid")
        return mock

    return tried, make_client


@pytest.mark.asyncio
async def test_tuya_login_tries_the_remembered_region_first():
    """A US account does not pay a failed EU login on every start."""
    login = _make_login()
    login.auth_cache = AuthCache(tuya_region="US")
    login._eufy_user_id = "uid"
    tried, make_client = _probe_regions(failing=set())

    with patch(
        "custom_components.robovac_mqtt.api.cloud.TuyaCloudClient",
        side_effect=make_client,
    ):
        await login.tuya_login()

    assert tried == ["US"]
    assert login._tuya_probe_region == "US"


@pytest.mark.asyncio
async def test_tuya_login_falls_back_when_the_remembered_region_fails():
    """A remembered region is a hint, not a filter."""
    login = _make_login()
    login.auth_cache = AuthCache(tuya_region="US")
    login._eufy_user_id = "uid"
    tried, make_client = _probe_regions(failing={"US"})

    with patch(
        "custom_components.robovac_mqtt.api.cloud.TuyaCloudClient",
        side_effect=make_client,
    ):
        await login.tuya_login()

    assert tried == ["US", "EU"]
    assert login._tuya_probe_region == "EU"


@pytest.mark.asyncio
async def test_tuya_login_raises_when_every_region_fails():
    login = _make_login()
    login._eufy_user_id = "uid"
    _tried, make_client = _probe_regions(failing={"EU", "US"})

    with patch(
        "custom_components.robovac_mqtt.api.cloud.TuyaCloudClient",
        side_effect=make_client,
    ), pytest.raises(TuyaCloudError):
        await login.tuya_login()


@pytest.mark.asyncio
async def test_check_login_skips_fallback_session_account():
    """A session without a user_center has no MQTT credentials to fetch."""
    login = _make_login(mqtt_credentials=None)
    login.eufyApi.session = {"access_token": "tok", "user_id": "u1"}
    login.eufyApi.user_info = None

    await login.checkLogin()

    login.eufyApi.login.assert_not_called()


@pytest.mark.asyncio
async def test_check_login_writes_fresh_credentials_to_the_cache():
    """Credentials fetched by checkLogin reach the auth cache."""
    login = _make_login(mqtt_credentials=None)
    login.eufyApi.session = None
    login.eufyApi.user_info = None
    login.eufyApi.login_label = None
    login.auth_cache = AuthCache()

    await login.checkLogin()

    login.eufyApi.login.assert_awaited_once()
    assert login.auth_cache.mqtt_credentials == {"endpoint": "mqtt.example.com"}


@pytest.mark.asyncio
async def test_check_login_concurrent_callers_log_in_once():
    """Coordinators starting together share one MQTT-credential login."""
    login = _make_login(mqtt_credentials=None)
    login.eufyApi.session = None
    login.eufyApi.user_info = None

    async def _slow_login():
        await asyncio.sleep(0)
        return {"mqtt": {"endpoint": "mqtt.example.com"}}

    login.eufyApi.login = AsyncMock(side_effect=_slow_login)

    await asyncio.gather(*(login.checkLogin() for _ in range(3)))

    login.eufyApi.login.assert_awaited_once()


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


# ── Rejected MQTT credentials ───────────────────────────────────────

_NEW_CREDENTIALS = {"certificate_pem": "new"}


def _login_with_rejected_credentials():
    """An EufyLogin whose cached MQTT credentials the broker rejects.

    Its login runs through the HTTP client's throttle; only the requests are
    stubbed.
    """
    rejected = {"certificate_pem": "old"}
    login = EufyLogin(
        "user@example.com",
        "password123",
        "open-udid",
        websession=MagicMock(),
        auth_cache=AuthCache(mqtt_credentials=rejected),
    )
    api = login.eufyApi
    api._attempt_login = AsyncMock(return_value={"access_token": "t", "user_id": "u"})
    api.get_user_info = AsyncMock(return_value={"user_center_id": "uc"})
    api.get_mqtt_credentials = AsyncMock(return_value=dict(_NEW_CREDENTIALS))
    return login, rejected, AsyncMock()


@pytest.mark.asyncio
async def test_rejected_credentials_are_replaced_by_one_login():
    """The rejected cert leaves the cache, one budgeted login fetches new ones,
    both persist."""
    login, rejected, save = _login_with_rejected_credentials()

    assert await login.replace_rejected_mqtt_credentials(rejected, save) is True

    assert len(login.auth_cache.throttle["logins"]) == 1
    assert login.mqtt_credentials == _NEW_CREDENTIALS
    assert login.auth_cache.mqtt_credentials == _NEW_CREDENTIALS
    save.assert_awaited_once()


def _spend_login_budget(login):
    for _ in range(LOGIN_BUDGET):
        login.throttle.note_login()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "refuse",
    [
        lambda login: login.throttle.hold_off(KIND_LOGIN, 300),
        lambda login: login.throttle.hold_off(KIND_REQUESTS, 300),
        _spend_login_budget,
    ],
    ids=["login-hold-off", "request-hold-off", "budget-spent"],
)
async def test_rejected_credentials_send_no_login_while_the_throttle_refuses(refuse):
    """No login; the rejected cert still leaves the persisted cache."""
    login, rejected, save = _login_with_rejected_credentials()
    refuse(login)
    logins = list(login.auth_cache.throttle["logins"])

    assert await login.replace_rejected_mqtt_credentials(rejected, save) is False
    assert await login.replace_rejected_mqtt_credentials(rejected, save) is False

    login.eufyApi._attempt_login.assert_not_awaited()
    assert login.auth_cache.throttle["logins"] == logins
    assert login.auth_cache.mqtt_credentials is None
    save.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "refusal",
    [None, EufyLoginChallengeError("needs a code", code=26052)],
    ids=["credentials", "challenge"],
)
async def test_rejected_credentials_after_a_refused_login_send_no_second_login(
    refusal,
):
    """A refused account login raises once; the same rejection never retries it."""
    login, rejected, save = _login_with_rejected_credentials()
    if refusal is None:
        login.eufyApi._attempt_login.return_value = None
    else:
        login.eufyApi._attempt_login.side_effect = refusal

    with pytest.raises(EufyLoginError):
        await login.replace_rejected_mqtt_credentials(rejected, save)
    assert await login.replace_rejected_mqtt_credentials(rejected, save) is False

    assert len(login.auth_cache.throttle["logins"]) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error",
    [
        EufyLoginTransientError("HTTP 503"),
        aiohttp.ClientError("reset"),
        TimeoutError(),
        EufyLoginRateLimitedError("code 100028", retry_after=7200.0, code=100028),
    ],
    ids=["503", "client-error", "timeout", "throttle-answer"],
)
async def test_a_failed_replacement_login_keeps_the_rejected_cert_out(error):
    """An outage or a throttle answer during the login: no replacement and no
    refusal (no reauth); the drop is still persisted."""
    login, rejected, save = _login_with_rejected_credentials()
    login.eufyApi._attempt_login.side_effect = error

    assert await login.replace_rejected_mqtt_credentials(rejected, save) is False

    assert login.auth_cache.mqtt_credentials is None
    save.assert_awaited_once()


@pytest.mark.asyncio
async def test_a_retry_after_a_failed_replacement_persists_its_result():
    """The cache is already dropped; the later successful login is still saved."""
    login, rejected, save = _login_with_rejected_credentials()
    session = login.eufyApi._attempt_login.return_value
    login.eufyApi._attempt_login.side_effect = EufyLoginTransientError("HTTP 503")
    await login.replace_rejected_mqtt_credentials(rejected, save)
    login.eufyApi._attempt_login.side_effect = None
    login.eufyApi._attempt_login.return_value = session

    assert await login.replace_rejected_mqtt_credentials(rejected, save) is True

    assert save.await_count == 2
    assert login.auth_cache.mqtt_credentials == _NEW_CREDENTIALS


@pytest.mark.asyncio
async def test_a_replacement_login_without_mqtt_credentials_holds_off_logins():
    """A login that yields no MQTT credentials must not repeat at every rejection."""
    login, rejected, save = _login_with_rejected_credentials()
    login.eufyApi.get_mqtt_credentials.return_value = None

    assert await login.replace_rejected_mqtt_credentials(rejected, save) is False
    assert await login.replace_rejected_mqtt_credentials(rejected, save) is False

    assert len(login.auth_cache.throttle["logins"]) == 1
    assert login.throttle.held_off(KIND_LOGIN) == pytest.approx(
        MISSING_CREDENTIALS_HOLD_OFF, abs=10
    )
    assert login.throttle.held_off(KIND_REQUESTS) is None


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
    # getCloudDevices awaits get_device_schema for legacy devices.
    mock_tuya.get_device_schema = AsyncMock(return_value={})
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
async def test_get_cloud_devices_keeps_every_tuya_device_id():
    """Every devId on the Tuya list is kept, including ones not set up as cloud
    devices, so firmware entities can be limited to devices Tuya knows."""
    login = _make_login()
    login.mqtt_devices = [{"deviceId": "both_dev", "deviceName": "MQTT Vacuum"}]
    mock_tuya = MagicMock()
    mock_tuya.get_device_schema = AsyncMock(return_value={})
    mock_tuya.get_device_list = AsyncMock(
        return_value=[
            {"devId": "both_dev", "dps": {"15": "Running"}},
            {"devId": "unknown_model", "dps": {}},
            {"name": "no id"},
        ]
    )
    login.tuya_client = mock_tuya

    await login.getCloudDevices()

    assert login.tuya_device_ids == {"both_dev", "unknown_model"}


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
    # getCloudDevices awaits get_device_schema for legacy devices.
    mock_tuya.get_device_schema = AsyncMock(return_value={})
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
    # getCloudDevices awaits get_device_schema for legacy devices.
    mock_tuya.get_device_schema = AsyncMock(return_value={})
    mock_tuya.get_device_list = AsyncMock(
        return_value=[{"devId": "unknown_dev", "dps": {"15": "Running"}}]
    )
    login.tuya_client = mock_tuya

    await login.getCloudDevices()

    assert len(login.cloud_devices) == 0


@pytest.mark.asyncio
async def test_get_cloud_devices_records_a_failed_tuya_list():
    """A failed Tuya list read is an outage, not an account without devices."""
    login = _make_login()
    login.tuya_client = MagicMock()
    login.tuya_client.get_device_list = AsyncMock(
        side_effect=TuyaCloudError("ERR", "down")
    )

    await login.getCloudDevices()

    assert not login.cloud_devices
    assert login._tuya_failed is True


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
async def test_send_cloud_command_delegates_to_tuya(caplog):
    """sendCloudCommand calls tuya_client.send_command and logs only DPS keys."""
    login = _make_login()
    mock_tuya = MagicMock()
    mock_tuya.send_command = AsyncMock()
    login.tuya_client = mock_tuya
    dps = {"2": True, "124": "c2VjcmV0LXJvb20tbmFtZQ=="}

    with caplog.at_level(logging.DEBUG, logger=cloud_mod.__name__):
        await login.sendCloudCommand("dev_123", dps)

    mock_tuya.send_command.assert_called_once_with("dev_123", dps)
    assert "succeeded" in caplog.text
    assert dps["124"] not in caplog.text


@pytest.mark.asyncio
async def test_get_cloud_device_no_tuya_client():
    """getCloudDevice returns None when no Tuya client."""
    login = _make_login()
    login.tuya_client = None

    result = await login.getCloudDevice("dev_123")

    assert result is None


# ── Cloud re-login on SID expiration ──────────────────────────────


def _tuya_client_mock(sid: str = "old_sid") -> MagicMock:
    """A Tuya cloud client whose login() installs a new sid."""
    mock_tuya = MagicMock()
    mock_tuya.sid = sid

    async def _login(_user_id):
        mock_tuya.sid = "new_sid"
        return "new_sid"

    mock_tuya.login = AsyncMock(side_effect=_login)
    return mock_tuya


@pytest.mark.asyncio
async def test_get_cloud_device_relogins_on_failure():
    """A session error re-logs in the existing client and retries once."""
    login = _make_login()
    login._eufy_user_id = "test_user"
    mock_tuya = _tuya_client_mock()
    mock_tuya.get_device = AsyncMock(
        side_effect=[
            TuyaCloudError("USER_SESSION_INVALID", "Session expired"),
            {"15": "Running", "104": 50},
        ]
    )
    login.tuya_client = mock_tuya
    thing = login.tuya_thing_client = MagicMock()

    with patch.object(login, "tuya_login", new_callable=AsyncMock) as full_login:
        result = await login.getCloudDevice("dev_123")

    full_login.assert_not_called()
    mock_tuya.login.assert_awaited_once_with("test_user")
    assert login.tuya_client is mock_tuya
    assert login.tuya_thing_client is thing
    assert result == {"15": "Running", "104": 50}
    assert mock_tuya.get_device.call_count == 2


@pytest.mark.asyncio
async def test_get_cloud_device_non_session_error_does_not_relogin():
    """A request error that is not a session error never triggers a login."""
    login = _make_login()
    login._eufy_user_id = "test_user"
    mock_tuya = _tuya_client_mock()
    mock_tuya.get_device = AsyncMock(
        side_effect=TuyaCloudError("DEVICE_OFFLINE", "Device is offline")
    )
    login.tuya_client = mock_tuya

    result = await login.getCloudDevice("dev_123")

    assert result is None
    mock_tuya.login.assert_not_called()
    assert mock_tuya.get_device.call_count == 1


@pytest.mark.asyncio
async def test_send_cloud_command_non_session_error_does_not_relogin():
    """A rejected command raises without a re-login."""
    login = _make_login()
    login._eufy_user_id = "test_user"
    mock_tuya = _tuya_client_mock()
    mock_tuya.send_command = AsyncMock(
        side_effect=TuyaCloudError("PARAM_ERROR", "Bad dps")
    )
    login.tuya_client = mock_tuya

    with pytest.raises(EufyLoginError):
        await login.sendCloudCommand("dev_123", {"2": True})

    mock_tuya.login.assert_not_called()
    assert mock_tuya.send_command.call_count == 1


@pytest.mark.asyncio
async def test_concurrent_session_errors_share_one_relogin():
    """N devices hitting the same dead sid cause one login, not N."""
    login = _make_login()
    login._eufy_user_id = "test_user"
    mock_tuya = _tuya_client_mock()

    async def _get_device(device_id):
        if mock_tuya.sid == "old_sid":
            await asyncio.sleep(0)
            raise TuyaCloudError("USER_SESSION_INVALID", "Session expired")
        return {"15": device_id}

    async def _slow_login(_user_id):
        await asyncio.sleep(0)
        mock_tuya.sid = "new_sid"
        return "new_sid"

    mock_tuya.get_device = AsyncMock(side_effect=_get_device)
    mock_tuya.login = AsyncMock(side_effect=_slow_login)
    login.tuya_client = mock_tuya

    results = await asyncio.gather(
        *(login.getCloudDevice(f"dev_{i}") for i in range(4))
    )

    assert results == [{"15": f"dev_{i}"} for i in range(4)]
    mock_tuya.login.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_cloud_device_relogin_also_fails():
    """getCloudDevice returns None when re-login also fails."""
    login = _make_login()
    login._eufy_user_id = "test_user"
    mock_tuya = _tuya_client_mock()
    mock_tuya.get_device = AsyncMock(
        side_effect=TuyaCloudError("EXPIRED", "Session expired")
    )
    mock_tuya.login = AsyncMock(
        side_effect=TuyaCloudError("LOGIN_FAIL", "Bad credentials")
    )
    login.tuya_client = mock_tuya

    result = await login.getCloudDevice("dev_123")

    assert result is None


@pytest.mark.asyncio
async def test_send_cloud_command_relogins_on_failure():
    """sendCloudCommand re-logs in the existing client on a session error."""
    login = _make_login()
    login._eufy_user_id = "test_user"
    mock_tuya = _tuya_client_mock()
    mock_tuya.send_command = AsyncMock(
        side_effect=[TuyaCloudError("EXPIRED", "Session expired"), None]
    )
    login.tuya_client = mock_tuya

    await login.sendCloudCommand("dev_123", {"2": True})

    mock_tuya.login.assert_awaited_once_with("test_user")
    assert login.tuya_client is mock_tuya
    assert mock_tuya.send_command.call_count == 2


@pytest.mark.asyncio
async def test_send_cloud_command_relogin_also_fails():
    """sendCloudCommand raises EufyLoginError when re-login also fails."""
    login = _make_login()
    login._eufy_user_id = "test_user"
    mock_tuya = _tuya_client_mock()
    mock_tuya.send_command = AsyncMock(
        side_effect=TuyaCloudError("EXPIRED", "Session expired")
    )
    mock_tuya.login = AsyncMock(
        side_effect=TuyaCloudError("LOGIN_FAIL", "Bad credentials")
    )
    login.tuya_client = mock_tuya

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
    # getCloudDevices awaits get_device_schema for legacy devices.
    mock_tuya.get_device_schema = AsyncMock(return_value={})
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


# ── Tuya device vs reconstructed MQTT placeholder (issue #131 beta) ──


@pytest.mark.asyncio
async def test_tuya_device_supersedes_reconstructed_mqtt_placeholder():
    """#131: when AIOT is empty, the device reconstructed as a legacy-MQTT
    placeholder must be SUPERSEDED by the matching Tuya cloud device (carrying
    its localKey) so it uses the Tuya cloud/local path — not left stuck on the
    MQTT path the S1 Pro can't answer."""
    login = _make_login()
    # The home-api cloud list returns the S1 Pro; its id matches the Tuya devId
    # (both are Tuya-backed).
    login.eufyApi.get_cloud_device_list = AsyncMock(
        return_value=[
            {
                "id": "s1pro_dev",
                "product": {"product_code": "T2080A", "name": "S1 Pro"},
                "alias_name": "S1 Pro",
                "device_model": "T2080A",
            }
        ]
    )
    login.eufyApi.get_device_list = AsyncMock(return_value=[])  # AIOT empty

    await login.getDevices()
    # Reconstructed as a placeholder MQTT device.
    assert len(login.mqtt_devices) == 1
    assert login.mqtt_devices[0]["reconstructed"] is True

    mock_tuya = MagicMock()
    # getCloudDevices awaits get_device_schema for legacy devices.
    mock_tuya.get_device_schema = AsyncMock(return_value={})
    mock_tuya.get_device_list = AsyncMock(
        return_value=[
            {
                "devId": "s1pro_dev",
                "localKey": "secret",
                "name": "S1 Pro",
                "dps": {"15": "Running"},
            }
        ]
    )
    login.tuya_client = mock_tuya

    await login.getCloudDevices()

    # Placeholder gone; device is now a Tuya cloud device with its local key.
    assert not login.mqtt_devices
    assert len(login.cloud_devices) == 1
    dev = login.cloud_devices[0]
    assert dev["deviceId"] == "s1pro_dev"
    assert dev["deviceModel"] == "T2080A"
    assert dev["mqtt"] is False
    assert dev["local_key"] == "secret"
    # DPS 15 here is a status string ("Running") -> a Tuya Cloud legacy device,
    # not scalar; it must use the legacy parser/command builder.
    assert dev["apiType"] == "legacy"


@pytest.mark.asyncio
async def test_confirmed_mqtt_device_not_superseded_by_tuya_duplicate():
    """A genuine MQTT device (real AIOT dps, not reconstructed) keeps the MQTT
    push path even if Tuya Cloud also lists the same id."""
    login = _make_login(
        eufy_api_devices=[
            {
                "id": "x8_dev",
                "product": {"product_code": "T2261", "name": "X8 Pro"},
                "alias_name": "X8",
                "device_model": "T2261",
            }
        ]
    )
    login.eufyApi.get_cloud_device_list = AsyncMock(
        return_value=login.eufy_api_devices
    )
    # AIOT returns the device with real protobuf dps -> a confirmed MQTT device.
    login.eufyApi.get_device_list = AsyncMock(
        return_value=[{"device_sn": "x8_dev", "dps": {"153": "CgYIBRABGAU="}}]
    )

    await login.getDevices()
    assert len(login.mqtt_devices) == 1
    assert login.mqtt_devices[0].get("reconstructed") is False

    mock_tuya = MagicMock()
    # getCloudDevices awaits get_device_schema for legacy devices.
    mock_tuya.get_device_schema = AsyncMock(return_value={})
    mock_tuya.get_device_list = AsyncMock(
        return_value=[{"devId": "x8_dev", "localKey": "k", "dps": {}}]
    )
    login.tuya_client = mock_tuya

    await login.getCloudDevices()

    # MQTT (push) device kept; the Tuya duplicate is not added.
    assert len(login.mqtt_devices) == 1
    assert not login.cloud_devices


def test_check_api_type_dps15_string_is_legacy_int_is_scalar():
    """DPS 15 as a status string is a Tuya Cloud legacy device; as an int it is
    the scalar (G50) status."""
    # Tuya Cloud legacy (S1 Pro) reports a word status -> legacy.
    assert EufyLogin.checkApiType({"15": "Running"}) == "legacy"
    assert EufyLogin.checkApiType({"15": "Charging"}) == "legacy"
    # Scalar (G50) reports an int (or numeric string) status -> scalar.
    assert EufyLogin.checkApiType({"15": 5}) == "scalar"
    assert EufyLogin.checkApiType({"15": "5"}) == "scalar"


@pytest.mark.asyncio
async def test_tuya_duplicate_record_added_once():
    """A Tuya list that repeats the same devId must yield a single cloud device."""
    login = _make_login(eufy_api_devices=[])
    login.mqtt_devices = []
    mock_tuya = MagicMock()
    # getCloudDevices awaits get_device_schema for legacy devices.
    mock_tuya.get_device_schema = AsyncMock(return_value={})
    mock_tuya.get_device_list = AsyncMock(
        return_value=[
            {"devId": "dup_dev", "localKey": "k", "name": "S1 Pro", "dps": {}},
            {"devId": "dup_dev", "localKey": "k", "name": "S1 Pro", "dps": {}},
        ]
    )
    login.tuya_client = mock_tuya

    await login.getCloudDevices()

    assert len(login.cloud_devices) == 1
    assert login.cloud_devices[0]["deviceId"] == "dup_dev"


@pytest.mark.asyncio
async def test_tuya_supersedes_placeholder_on_id_mismatch_single_robot():
    """#131 edge: one reconstructed placeholder + one localKey Tuya device whose
    devId differs (Eufy cloud id != Tuya devId) is the same physical robot, so
    the placeholder is dropped — not left as a second coordinator."""
    login = _make_login()
    login.eufyApi.get_cloud_device_list = AsyncMock(
        return_value=[
            {
                "id": "eufy_id",  # Eufy cloud id
                "product": {"product_code": "T2080A", "name": "S1 Pro"},
                "alias_name": "S1 Pro",
                "device_model": "T2080A",
            }
        ]
    )
    login.eufyApi.get_device_list = AsyncMock(return_value=[])  # AIOT empty
    await login.getDevices()
    assert len(login.mqtt_devices) == 1  # reconstructed placeholder

    mock_tuya = MagicMock()
    # getCloudDevices awaits get_device_schema for legacy devices.
    mock_tuya.get_device_schema = AsyncMock(return_value={})
    mock_tuya.get_device_list = AsyncMock(
        return_value=[
            {"devId": "tuya_devid", "localKey": "k", "name": "S1 Pro", "dps": {}}
        ]
    )
    login.tuya_client = mock_tuya

    await login.getCloudDevices()

    # Placeholder dropped; only the Tuya cloud device remains (one robot).
    assert not login.mqtt_devices
    assert len(login.cloud_devices) == 1
    assert login.cloud_devices[0]["deviceId"] == "tuya_devid"
    assert login.cloud_devices[0]["local_key"] == "k"
