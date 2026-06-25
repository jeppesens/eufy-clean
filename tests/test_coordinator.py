"""Unit tests for the EufyCleanCoordinator."""

# pylint: disable=redefined-outer-name

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.robovac_mqtt.api.map_stream import MapData
from custom_components.robovac_mqtt.coordinator import EufyCleanCoordinator
from custom_components.robovac_mqtt.models import VacuumState


@pytest.fixture
def mock_hass():
    """Mock the Home Assistant object."""
    return MagicMock()


@pytest.fixture
def mock_login():
    """Mock the EufyLogin object."""
    login = MagicMock()
    login.openudid = "test_udid"
    login.checkLogin = AsyncMock()
    return login


def test_coordinator_init(mock_hass, mock_login):
    """Test coordinator initialization."""
    device_info = {
        "deviceId": "test_id",
        "deviceModel": "T2118",
        "deviceName": "Test Vac",
        "dps": {"152": "test_dps"},  # Some initial DPS
    }

    with patch(
        "custom_components.robovac_mqtt.coordinator.update_state"
    ) as mock_update:
        mock_update.return_value = (VacuumState(battery_level=100), {})

        coordinator = EufyCleanCoordinator(mock_hass, mock_login, device_info)

        assert coordinator.device_id == "test_id"
        assert coordinator.device_name == "Test Vac"
        # Verify initial DPS processing
        mock_update.assert_called_once()
        assert coordinator.data.battery_level == 100


def _coordinator_with_map(mock_hass, mock_login, map_data):
    """Build a coordinator and pin its decoded map data (skips MQTT)."""
    device_info = {
        "deviceId": "test_id",
        "deviceModel": "T2118",
        "deviceName": "Test Vac",
        "dps": {},
    }
    with patch(
        "custom_components.robovac_mqtt.coordinator.update_state"
    ) as mock_update:
        mock_update.return_value = (VacuumState(), {})
        coordinator = EufyCleanCoordinator(mock_hass, mock_login, device_info)
    coordinator._map_data = map_data  # pylint: disable=protected-access
    return coordinator


def test_normalized_rects_to_quads_cm_no_map(mock_hass, mock_login):
    """With no map decoded yet, the helper returns [] so callers no-op."""
    coordinator = _coordinator_with_map(mock_hass, mock_login, None)
    assert not coordinator.normalized_rects_to_quads_cm([(0.0, 0.0, 1.0, 1.0)])


def test_normalized_rects_to_quads_cm_orientation(mock_hass, mock_login):
    """A normalized rect maps to a world-cm rectangle with the Y-flip baked in."""
    md = MapData(
        raw_pixels=b"",
        width=400,
        height=300,
        origin_x=-1500,
        origin_y=-1000,
        resolution=5,
    )
    coordinator = _coordinator_with_map(mock_hass, mock_login, md)

    quads = coordinator.normalized_rects_to_quads_cm([(0.0, 0.0, 1.0, 1.0)])
    assert len(quads) == 1
    tl, tr, br, bl = quads[0]

    # Axis-aligned rectangle.
    assert tl[0] == bl[0] and tr[0] == br[0]
    assert tl[1] == tr[1] and bl[1] == br[1]
    # X grows left->right across the image.
    assert tl[0] < tr[0]
    # World Y DECREASES top->bottom of the image (render Y-flip).
    assert tl[1] > bl[1]
    # Exact spot-check of the unambiguous top-left corner
    # (nx=0 -> origin_x; ny=0 -> origin_y + (height-1)*res).
    assert tl == (-1500, -1000 + (300 - 1) * 5)


def test_normalized_rects_to_quads_cm_skips_malformed(mock_hass, mock_login):
    """A rect that isn't four numbers is skipped; valid ones still convert."""
    md = MapData(
        raw_pixels=b"", width=100, height=100, origin_x=0, origin_y=0, resolution=10
    )
    coordinator = _coordinator_with_map(mock_hass, mock_login, md)

    quads = coordinator.normalized_rects_to_quads_cm(
        [(0.0, 0.0, 0.5), (0.0, 0.0, 0.5, 0.5)]  # first has only 3 values
    )
    assert len(quads) == 1


@pytest.mark.asyncio
async def test_coordinator_initialize_success(mock_hass, mock_login):
    """Test successful initialization of the coordinator."""
    device_info = {
        "deviceId": "test_id",
        "deviceModel": "T2118",
        "deviceName": "Test Vac",
    }

    mock_login.mqtt_credentials = {
        "user_id": "uid",
        "app_name": "app",
        "thing_name": "thing",
        "certificate_pem": "cert",
        "private_key": "key",
        "endpoint_addr": "endpoint",
    }

    coordinator = EufyCleanCoordinator(mock_hass, mock_login, device_info)

    with patch(
        "custom_components.robovac_mqtt.coordinator.EufyCleanClient"
    ) as mock_client_cls:
        mock_client = mock_client_cls.return_value
        mock_client.connect = AsyncMock()

        await coordinator.initialize()

        mock_login.checkLogin.assert_not_called()  # Creds existed
        mock_client_cls.assert_called_once()
        mock_client.connect.assert_called_once()
        assert coordinator.client == mock_client


@pytest.mark.asyncio
async def test_coordinator_initialize_failed_creds(mock_hass, mock_login):
    """Test initialization failure when no credentials."""
    device_info = {
        "deviceId": "test_id",
        "deviceModel": "T2118",
        "deviceName": "Test Vac",
    }
    mock_login.mqtt_credentials = None

    # Even after checkLogin, still None
    async def side_effect_check():
        mock_login.mqtt_credentials = None

    mock_login.checkLogin.side_effect = side_effect_check

    coordinator = EufyCleanCoordinator(mock_hass, mock_login, device_info)

    with pytest.raises(UpdateFailed):
        await coordinator.initialize()

    mock_login.checkLogin.assert_called_once()


def test_handle_mqtt_message(mock_hass, mock_login):
    """Test handling of MQTT messages."""
    device_info = {
        "deviceId": "test_id",
        "deviceModel": "T2118",
        "deviceName": "Test Vac",
    }
    coordinator = EufyCleanCoordinator(mock_hass, mock_login, device_info)
    coordinator.async_set_updated_data = MagicMock()

    # Create dummy payload: {"payload": {"data": {"dps_key": "dps_val"}}}
    payload_str = '{"payload": {"data": {"101": "val"}}}'
    payload_bytes = payload_str.encode()

    with patch(
        "custom_components.robovac_mqtt.coordinator.update_state"
    ) as mock_update:
        new_state = VacuumState(battery_level=50)
        mock_update.return_value = (new_state, {})

        coordinator._handle_mqtt_message(payload_bytes)

        mock_update.assert_called()
        coordinator.async_set_updated_data.assert_called_with(new_state)


@pytest.mark.asyncio
async def test_async_send_command(mock_hass, mock_login):
    """Test sending commands."""
    device_info = {
        "deviceId": "test_id",
        "deviceModel": "T2118",
        "deviceName": "Test Vac",
    }
    coordinator = EufyCleanCoordinator(mock_hass, mock_login, device_info)

    # Mock client
    mock_client = MagicMock()
    mock_client.send_command = AsyncMock()
    coordinator.client = mock_client

    cmd = {"some": "cmd"}
    await coordinator.async_send_command(cmd)

    mock_client.send_command.assert_called_with(cmd)


def test_async_shutdown_timers_cancels_both(mock_hass, mock_login):
    """Test that async_shutdown_timers cancels dock and segment timers."""
    device_info = {
        "deviceId": "test_id",
        "deviceModel": "T2118",
        "deviceName": "Test Vac",
    }
    coordinator = EufyCleanCoordinator(mock_hass, mock_login, device_info)

    mock_dock_cancel = MagicMock()
    mock_segment_cancel = MagicMock()
    coordinator._dock_idle_cancel = mock_dock_cancel
    coordinator._segment_update_cancel = mock_segment_cancel

    coordinator.async_shutdown_timers()

    mock_dock_cancel.assert_called_once()
    mock_segment_cancel.assert_called_once()
    assert coordinator._dock_idle_cancel is None
    assert coordinator._segment_update_cancel is None


def test_async_shutdown_timers_noop_when_no_timers(mock_hass, mock_login):
    """Test async_shutdown_timers is safe with no active timers."""
    device_info = {
        "deviceId": "test_id",
        "deviceModel": "T2118",
        "deviceName": "Test Vac",
    }
    coordinator = EufyCleanCoordinator(mock_hass, mock_login, device_info)

    assert coordinator._dock_idle_cancel is None
    assert coordinator._segment_update_cancel is None

    # Should not raise
    coordinator.async_shutdown_timers()

    assert coordinator._dock_idle_cancel is None
    assert coordinator._segment_update_cancel is None


@pytest.mark.asyncio
async def test_async_send_command_no_client_raises(mock_hass, mock_login):
    """Test that sending command with no client raises HomeAssistantError."""
    from homeassistant.exceptions import HomeAssistantError

    device_info = {
        "deviceId": "test_id",
        "deviceModel": "T2118",
        "deviceName": "Test Vac",
    }
    coordinator = EufyCleanCoordinator(mock_hass, mock_login, device_info)
    coordinator.client = None

    with pytest.raises(HomeAssistantError, match="no connection available"):
        await coordinator.async_send_command({"some": "cmd"})


@pytest.mark.asyncio
async def test_async_send_command_empty_dict_ignored(mock_hass, mock_login):
    """Test that sending empty command dict is silently ignored."""
    device_info = {
        "deviceId": "test_id",
        "deviceModel": "T2118",
        "deviceName": "Test Vac",
    }
    coordinator = EufyCleanCoordinator(mock_hass, mock_login, device_info)
    mock_client = MagicMock()
    mock_client.send_command = AsyncMock()
    coordinator.client = mock_client

    await coordinator.async_send_command({})


@pytest.mark.asyncio
async def test_async_send_command_wraps_exception_in_ha_error(mock_hass, mock_login):
    """Test that generic exceptions from MQTT send are wrapped in HomeAssistantError."""
    from homeassistant.exceptions import HomeAssistantError

    device_info = {
        "deviceId": "test_id",
        "deviceModel": "T2118",
        "deviceName": "Test Vac",
    }
    coordinator = EufyCleanCoordinator(mock_hass, mock_login, device_info)
    mock_client = MagicMock()
    mock_client.send_command = AsyncMock(side_effect=OSError("Connection lost"))
    coordinator.client = mock_client

    with pytest.raises(HomeAssistantError, match="Failed to send command"):
        await coordinator.async_send_command({"some": "cmd"})


# ── Cloud/Legacy coordinator tests ─────────────────────────────────


def test_coordinator_cloud_init(mock_hass, mock_login):
    """Cloud coordinator should set connection_type and update_interval."""
    device_info = {
        "deviceId": "cloud_dev",
        "deviceModel": "T2210",
        "deviceName": "Cloud Vac",
        "mqtt": False,
        "apiType": "legacy",
        "dps": {"15": "Running", "104": 80},
    }
    coordinator = EufyCleanCoordinator(mock_hass, mock_login, device_info)

    assert coordinator.connection_type == "cloud"
    assert coordinator.api_type == "legacy"
    assert coordinator.update_interval is not None
    assert coordinator.data.activity == "cleaning"
    assert coordinator.data.battery_level == 80


def test_coordinator_mqtt_novel_init(mock_hass, mock_login):
    """MQTT novel coordinator should have no polling interval."""
    device_info = {
        "deviceId": "mqtt_dev",
        "deviceModel": "T2261",
        "deviceName": "MQTT Vac",
        "mqtt": True,
        "apiType": "novel",
    }

    coordinator = EufyCleanCoordinator(mock_hass, mock_login, device_info)

    assert coordinator.connection_type == "mqtt"
    assert coordinator.api_type == "novel"
    assert coordinator.update_interval is None


def test_parse_dps_legacy(mock_hass, mock_login):
    """_parse_dps should use legacy parser for legacy api_type."""
    device_info = {
        "deviceId": "dev1",
        "deviceModel": "T2210",
        "deviceName": "Vac",
        "apiType": "legacy",
    }
    coordinator = EufyCleanCoordinator(mock_hass, mock_login, device_info)

    new_state, changes = coordinator._parse_dps({"104": 42})
    assert new_state.battery_level == 42


def test_parse_dps_novel(mock_hass, mock_login):
    """_parse_dps should use novel parser for novel api_type."""
    device_info = {
        "deviceId": "dev1",
        "deviceModel": "T2261",
        "deviceName": "Vac",
        "apiType": "novel",
    }
    coordinator = EufyCleanCoordinator(mock_hass, mock_login, device_info)

    # DPS 163 is novel battery level (plain int)
    new_state, changes = coordinator._parse_dps({"163": 75})
    assert new_state.battery_level == 75


def test_build_device_command_legacy(mock_hass, mock_login):
    """build_device_command should use legacy builder for legacy api_type."""
    device_info = {
        "deviceId": "dev1",
        "deviceModel": "T2210",
        "deviceName": "Vac",
        "apiType": "legacy",
    }
    coordinator = EufyCleanCoordinator(mock_hass, mock_login, device_info)

    cmd = coordinator.build_device_command("start_auto")
    assert cmd == {"2": True, "5": "auto"}


def test_build_device_command_novel(mock_hass, mock_login):
    """build_device_command should use novel builder for novel api_type."""
    device_info = {
        "deviceId": "dev1",
        "deviceModel": "T2261",
        "deviceName": "Vac",
        "apiType": "novel",
    }
    coordinator = EufyCleanCoordinator(mock_hass, mock_login, device_info)

    cmd = coordinator.build_device_command("find_robot", active=True)
    # Novel find_robot uses DPS 160
    assert "160" in cmd


@pytest.mark.asyncio
async def test_cloud_send_command(mock_hass, mock_login):
    """Cloud coordinator should send commands via Tuya Cloud."""
    device_info = {
        "deviceId": "cloud_dev",
        "deviceModel": "T2210",
        "deviceName": "Cloud Vac",
        "mqtt": False,
        "apiType": "legacy",
    }
    mock_login.sendCloudCommand = AsyncMock()
    coordinator = EufyCleanCoordinator(mock_hass, mock_login, device_info)

    await coordinator.async_send_command({"2": True})
    mock_login.sendCloudCommand.assert_called_once_with("cloud_dev", {"2": True})


@pytest.mark.asyncio
async def test_cloud_initialize(mock_hass, mock_login):
    """Cloud coordinator should initialize without MQTT client."""
    device_info = {
        "deviceId": "cloud_dev",
        "deviceModel": "T2210",
        "deviceName": "Cloud Vac",
        "mqtt": False,
        "apiType": "legacy",
    }
    coordinator = EufyCleanCoordinator(mock_hass, mock_login, device_info)

    await coordinator.initialize()

    assert coordinator.client is None


@pytest.mark.asyncio
async def test_cloud_update_data(mock_hass, mock_login):
    """Cloud coordinator should poll via Tuya Cloud API."""
    device_info = {
        "deviceId": "cloud_dev",
        "deviceModel": "T2210",
        "deviceName": "Cloud Vac",
        "mqtt": False,
        "apiType": "legacy",
    }
    mock_login.getCloudDevice = AsyncMock(
        return_value={"15": "Charging", "104": 100}
    )
    coordinator = EufyCleanCoordinator(mock_hass, mock_login, device_info)

    result = await coordinator._async_update_data()

    assert result.battery_level == 100
    assert result.activity == "docked"
    mock_login.getCloudDevice.assert_called_once_with("cloud_dev")


# ── Cloud polling backoff ─────────────────────────────────────────


def _make_cloud_coordinator(mock_hass, mock_login):
    """Helper to create a cloud/legacy coordinator."""
    device_info = {
        "deviceId": "cloud_dev",
        "deviceModel": "T2210",
        "deviceName": "Cloud Vac",
        "mqtt": False,
        "apiType": "legacy",
    }
    return EufyCleanCoordinator(mock_hass, mock_login, device_info)


@pytest.mark.asyncio
async def test_cloud_poll_failure_increments_counter(mock_hass, mock_login):
    """Poll failure should increment consecutive failure counter."""
    mock_login.getCloudDevice = AsyncMock(return_value=None)
    coordinator = _make_cloud_coordinator(mock_hass, mock_login)

    await coordinator._async_update_data()

    assert coordinator._consecutive_cloud_failures == 1


@pytest.mark.asyncio
async def test_cloud_poll_success_resets_counter(mock_hass, mock_login):
    """Successful poll should reset failure counter and restore interval."""
    from datetime import timedelta

    mock_login.getCloudDevice = AsyncMock(return_value=None)
    coordinator = _make_cloud_coordinator(mock_hass, mock_login)
    base_interval = coordinator.update_interval

    # Simulate 3 failures
    for _ in range(3):
        await coordinator._async_update_data()
    assert coordinator._consecutive_cloud_failures == 3
    assert coordinator.update_interval > base_interval

    # Now succeed
    mock_login.getCloudDevice = AsyncMock(
        return_value={"15": "Charging", "104": 100}
    )
    await coordinator._async_update_data()

    assert coordinator._consecutive_cloud_failures == 0
    assert coordinator.update_interval == base_interval


@pytest.mark.asyncio
async def test_cloud_poll_backoff_increases_interval(mock_hass, mock_login):
    """Each failure should increase the polling interval."""
    mock_login.getCloudDevice = AsyncMock(return_value=None)
    coordinator = _make_cloud_coordinator(mock_hass, mock_login)
    base_interval = coordinator.update_interval

    await coordinator._async_update_data()
    interval_after_1 = coordinator.update_interval

    await coordinator._async_update_data()
    interval_after_2 = coordinator.update_interval

    assert interval_after_1 > base_interval
    assert interval_after_2 > interval_after_1


@pytest.mark.asyncio
async def test_cloud_poll_raises_after_threshold(mock_hass, mock_login):
    """After threshold consecutive failures, UpdateFailed should be raised."""
    mock_login.getCloudDevice = AsyncMock(return_value=None)
    coordinator = _make_cloud_coordinator(mock_hass, mock_login)

    # First 4 failures return stale data
    for _ in range(4):
        result = await coordinator._async_update_data()
        assert isinstance(result, VacuumState)

    # 5th failure should raise
    with pytest.raises(UpdateFailed, match="unreachable after 5"):
        await coordinator._async_update_data()


@pytest.mark.asyncio
async def test_cloud_poll_backoff_caps_at_max(mock_hass, mock_login):
    """Backoff interval should not exceed 5 minutes."""
    from datetime import timedelta

    mock_login.getCloudDevice = AsyncMock(return_value=None)
    coordinator = _make_cloud_coordinator(mock_hass, mock_login)

    # Run up to threshold - 1 failures (before UpdateFailed)
    for _ in range(4):
        await coordinator._async_update_data()

    assert coordinator.update_interval <= timedelta(minutes=5)
