"""Coordinator wiring for local-only mode (robot cut off from its cloud)."""

# pylint: disable=redefined-outer-name,protected-access

import json
import time
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest
from homeassistant.exceptions import HomeAssistantError

from custom_components.robovac_mqtt.api.local_tuya import LocalTuyaClient
from custom_components.robovac_mqtt.api.tuya_cloud import TuyaCloudError
from custom_components.robovac_mqtt.coordinator import EufyCleanCoordinator
from custom_components.robovac_mqtt.offline import LOCAL_ONLY_AFTER
from custom_components.robovac_mqtt.vacuum import RoboVacMQTTEntity

_CLOCK = "custom_components.robovac_mqtt.offline.time.monotonic"


@pytest.fixture
def coordinator():
    login = MagicMock()
    login.openudid = "udid"
    login.tuya_client = None
    info = {
        "deviceId": "testdeviceid0000000000",
        "deviceModel": "T2080A",
        "deviceName": "S1 Pro",
        "connection_type": "local",
        "local_key": "k" * 16,
        "local_host": "192.168.1.50",
    }
    coord = EufyCleanCoordinator(MagicMock(), login, info)
    coord.async_set_updated_data = MagicMock()
    return coord


def _go_local_only(coord, now=1000.0):
    """No cloud-only DPS, the cloud says offline, generic DPS still arrive."""
    tracker = coord.local_only_tracker
    tracker.connected_at = now - LOCAL_ONLY_AFTER - 1
    tracker.record({"163": 70}, now=now)
    tracker.note_cloud_status(False, now=now)
    return now


def _push(coord, dps):
    coord._handle_mqtt_message(json.dumps({"payload": {"data": dps}}).encode())


def test_tracker_only_on_local_connections():
    login = MagicMock(openudid="udid", tuya_client=None)
    info = {"deviceId": "d" * 22, "deviceModel": "T2080A", "deviceName": "S1"}
    coord = EufyCleanCoordinator(MagicMock(), login, info)
    assert coord.local_only_tracker is None
    assert coord.local_only is False
    coord.note_intent("cleaning")  # no tracker: a no-op, not a crash
    state, changes = coord._apply_local_only(coord.data, {"x": 1})
    assert state is coord.data and changes == {"x": 1}


def test_state_untouched_while_work_status_flows(coordinator):
    _push(coordinator, {"153": "", "163": 70})
    assert coordinator.local_only is False
    assert coordinator.data.task_status != "Local only"


def test_local_only_activity_published(coordinator):
    with patch(
        "custom_components.robovac_mqtt.offline.time.monotonic", return_value=1000.0
    ):
        _go_local_only(coordinator)
        _push(coordinator, {"163": 70})
    state = coordinator.async_set_updated_data.call_args[0][0]
    assert state.task_status == "Local only"
    assert state.activity == "docked"
    assert state.charging is False  # a guessed dock at 70 %: no rise, so not shown charging


def test_note_intent_publishes_at_once_while_local_only(coordinator):
    with patch(
        "custom_components.robovac_mqtt.offline.time.monotonic", return_value=1000.0
    ):
        _go_local_only(coordinator)
        coordinator.note_intent("cleaning")
    state = coordinator.async_set_updated_data.call_args[0][0]
    assert state.activity == "cleaning"


def test_note_intent_silent_while_online(coordinator):
    coordinator.note_intent("cleaning")
    coordinator.async_set_updated_data.assert_not_called()


def _feed(pose, dock, age=5.0):
    def pt(p):
        return None if p is None else SimpleNamespace(x=p[0], y=p[1])

    return SimpleNamespace(
        state=SimpleNamespace(pose=pt(pose), dock=pt(dock)),
        last_object_at=time.time() - age,
    )


@pytest.mark.parametrize(
    ("pose", "dock", "expected"),
    [
        (None, None, None),
        ((10, 10), (0, 0), False),
        ((200, 0), (0, 0), True),
    ],
)
def test_away_from_dock(coordinator, pose, dock, expected):
    coordinator.p2p = _feed(pose, dock)
    assert coordinator._away_from_dock() is expected


def test_stale_pose_is_ignored(coordinator):
    coordinator.p2p = _feed((200, 0), (0, 0), age=600)
    assert coordinator._away_from_dock() is None
    coordinator.p2p = SimpleNamespace(state=SimpleNamespace(pose=None, dock=None))
    assert coordinator._away_from_dock() is None


def test_away_from_dock_without_map_feed(coordinator):
    coordinator.p2p = None
    assert coordinator._away_from_dock() is None


def test_pose_off_the_dock_shows_idle(coordinator):
    coordinator.p2p = _feed((300, 0), (0, 0))
    with patch(_CLOCK, return_value=1000.0):
        _go_local_only(coordinator)
        coordinator.data = replace(coordinator.data, activity="docked")
        state, changes = coordinator._apply_local_only(coordinator.data, {})
    assert state.activity == "idle" and changes["activity"] == "idle"
    assert state.charging is False


def test_generic_dps_fill_in_time_area_and_suction_only_while_local_only(coordinator):
    with patch(_CLOCK, return_value=1000.0):
        coordinator.local_only_tracker.record(
            {"6": 3, "7": 12, "9": "strong"}, now=1000
        )
        state, _ = coordinator._apply_local_only(coordinator.data, {})
        assert state is coordinator.data  # online: untouched
        _go_local_only(coordinator)
        state, _ = coordinator._apply_local_only(coordinator.data, {})
    assert (state.cleaning_time, state.cleaning_area, state.fan_speed) == (
        180,
        12,
        "Turbo",
    )


def test_leaving_local_only_restores_the_task_status(coordinator):
    coordinator.data = replace(coordinator.data, task_status="Completed", error_code=7)
    with patch(_CLOCK, return_value=1000.0):
        _go_local_only(coordinator)
        state, _ = coordinator._apply_local_only(coordinator.data, {})
        assert state.task_status == "Local only"
        assert state.error_code == 7  # errors are left alone
        coordinator.local_only_tracker.record({"173": "x"}, now=1000)  # back online
        state, changes = coordinator._apply_local_only(state, {})
    assert state.task_status == "Completed"
    assert changes["task_status"] == "Completed"


def test_no_tracker_for_legacy_robots_on_local_tuya():
    login = MagicMock(openudid="udid", tuya_client=None)
    info = {
        "deviceId": "d" * 22,
        "deviceModel": "T2128",
        "deviceName": "G30",
        "apiType": "legacy",
        "connection_type": "local",
        "local_key": "k" * 16,
        "local_host": "192.168.1.50",
    }
    coord = EufyCleanCoordinator(MagicMock(), login, info)
    assert coord.local_only_tracker is None
    assert coord.update_interval is None


@pytest.mark.asyncio
async def test_update_asks_the_cloud_at_connect_and_then_backs_off(coordinator):
    client = MagicMock(spec=LocalTuyaClient)
    client.poll_status = AsyncMock()
    coordinator.client = client
    cloud = MagicMock()
    cloud.is_device_online = AsyncMock(return_value=False)
    coordinator.eufy_login.tuya_client = cloud
    tracker = coordinator.local_only_tracker
    tracker.connected_at = 0.0
    with patch(_CLOCK, return_value=10.0):
        tracker.record({"163": 70})
        await coordinator._async_update_data()
        assert coordinator.local_only is True  # offline from the start: no 5 min wait
    cloud.is_device_online.assert_awaited_once_with(coordinator.device_id)
    client.poll_status.assert_awaited_once()
    with patch(_CLOCK, return_value=70.0):
        await coordinator._async_update_data()
    cloud.is_device_online.assert_awaited_once()  # not again within 5 min


@pytest.mark.asyncio
async def test_a_push_triggers_the_due_cloud_check(coordinator):
    coordinator.hass.async_create_task = MagicMock(
        side_effect=lambda coro: coro.close()
    )
    with patch(_CLOCK, return_value=10.0):
        coordinator.local_only_tracker.connected_at = 0.0
        _push(coordinator, {"163": 70})
    coordinator.hass.async_create_task.assert_called_once()


@pytest.mark.asyncio
async def test_cloud_check_never_overlaps(coordinator):
    coordinator._cloud_check_running = True
    coordinator.eufy_login.tuya_client = MagicMock(is_device_online=AsyncMock())
    await coordinator._async_cloud_check()
    coordinator.eufy_login.tuya_client.is_device_online.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("tuya_client", "expected"),
    [
        (None, None),
        (MagicMock(is_device_online=AsyncMock(return_value=True)), True),
        (MagicMock(is_device_online=AsyncMock(side_effect=TimeoutError)), False),
        (
            MagicMock(
                is_device_online=AsyncMock(side_effect=aiohttp.ClientConnectionError)
            ),
            False,
        ),
        (MagicMock(is_device_online=AsyncMock(side_effect=ValueError("html"))), None),
    ],
)
async def test_cloud_says_online(coordinator, tuya_client, expected):
    coordinator.eufy_login.tuya_client = tuya_client
    assert await coordinator._cloud_says_online() is expected


@pytest.mark.asyncio
async def test_cloud_api_error_relogs_in_once_and_never_means_offline(coordinator):
    err = TuyaCloudError("1010", "token invalid")
    coordinator.eufy_login.tuya_client = MagicMock(
        is_device_online=AsyncMock(side_effect=[err, True])
    )
    coordinator.eufy_login.tuya_login = AsyncMock()
    assert await coordinator._cloud_says_online() is True
    coordinator.eufy_login.tuya_login.assert_awaited_once()
    coordinator.eufy_login.tuya_client.is_device_online = AsyncMock(side_effect=err)
    assert await coordinator._cloud_says_online() is None
    coordinator.eufy_login.tuya_login = AsyncMock(side_effect=OSError)
    assert await coordinator._cloud_says_online() is None


@pytest.mark.asyncio
async def test_resume_while_local_only_sends_play_not_a_new_clean(coordinator):
    coordinator.async_send_command = AsyncMock()
    coordinator.build_device_command = MagicMock(
        side_effect=lambda cmd, **_: {"cmd": cmd}
    )
    vac = RoboVacMQTTEntity(coordinator)
    with patch(_CLOCK, return_value=1000.0):
        _go_local_only(coordinator)
        coordinator.data = replace(coordinator.data, activity="paused")
        await vac.async_start()
    coordinator.async_send_command.assert_awaited_once_with({"cmd": "play"})


@pytest.mark.asyncio
async def test_failed_send_records_no_intent(coordinator):
    coordinator.async_send_command = AsyncMock(side_effect=HomeAssistantError("boom"))
    coordinator.build_device_command = MagicMock(return_value={"cmd": "x"})
    with pytest.raises(HomeAssistantError):
        await RoboVacMQTTEntity(coordinator).async_return_to_base()
    assert coordinator.local_only_tracker.intent is None


@pytest.mark.asyncio
async def test_whole_house_start_refused_while_local_only(coordinator):
    coordinator.async_send_command = AsyncMock()
    coordinator.build_device_command = MagicMock(
        side_effect=lambda cmd, **_: {"cmd": cmd}
    )
    vac = RoboVacMQTTEntity(coordinator)
    with patch(_CLOCK, return_value=1000.0):
        _go_local_only(coordinator)
        coordinator.data = replace(coordinator.data, activity="docked")
        with pytest.raises(HomeAssistantError, match="lose the saved map"):
            await vac.async_start()
        with pytest.raises(HomeAssistantError, match="force: true"):
            await vac.async_send_command("start_auto")
        coordinator.async_send_command.assert_not_awaited()
        await vac.async_send_command("start_auto", {"force": True})
    coordinator.async_send_command.assert_awaited_once_with({"cmd": "start_auto"})


@pytest.mark.asyncio
async def test_whole_house_start_allowed_while_online(coordinator):
    coordinator.async_send_command = AsyncMock()
    coordinator.build_device_command = MagicMock(
        side_effect=lambda cmd, **_: {"cmd": cmd}
    )
    coordinator.data = replace(coordinator.data, activity="docked")
    await RoboVacMQTTEntity(coordinator).async_start()
    coordinator.async_send_command.assert_awaited_once_with({"cmd": "start_auto"})


def test_local_only_battery_comes_from_the_live_dps(coordinator):
    """The published battery is the tracker's DPS 8, not the frozen 163."""
    with patch(_CLOCK, return_value=1000.0):
        _go_local_only(coordinator)
        coordinator.local_only_tracker.record({"8": 68, "163": 100}, now=1000)
        state, changes = coordinator._apply_local_only(
            replace(coordinator.data, battery_level=100), {}
        )
    assert state.battery_level == 68 and changes["battery_level"] == 68


def test_charging_needs_a_rising_battery_not_a_guess(coordinator):
    with patch(_CLOCK, return_value=1000.0):
        _go_local_only(coordinator)
        coordinator.local_only_tracker.record({"8": 68}, now=1000)
        state, _ = coordinator._apply_local_only(replace(coordinator.data, activity="docked"), {})
        assert state.charging is False  # docked is only a guess here
        coordinator.local_only_tracker.record({"8": 69}, now=1000)
        state, _ = coordinator._apply_local_only(state, {})
    assert state.activity == "docked" and state.charging is True
