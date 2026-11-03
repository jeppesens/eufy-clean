"""Coordinator lifecycle: setup failure, teardown, background work and transport state.

Complements test_coordinator.py, which covers parsing and the map pipeline.
"""

# pylint: disable=redefined-outer-name, protected-access

import asyncio
import base64
import json
import logging
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.const import CONF_USERNAME
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError

from custom_components.robovac_mqtt.api.cloud import (
    EufyLogin,
    EufyLoginError,
    EufySessionReplacedError,
)
from custom_components.robovac_mqtt.api.legacy_parser import parse_legacy_schedules
from custom_components.robovac_mqtt.api.map_stream import MapData
from custom_components.robovac_mqtt.api.parser import update_state
from custom_components.robovac_mqtt.api.throttle import SESSION_REPLACED_WINDOW
from custom_components.robovac_mqtt.api.tuya_thing import TuyaThingClient
from custom_components.robovac_mqtt.auth_store import AuthCache
from custom_components.robovac_mqtt.coordinator import (
    _AUTH_FAILURE_WARN_AFTER,
    _CONNECTION_LOSS_GRACE,
    _TUYA_SESSION_REFRESH_INTERVAL,
    EufyCleanCoordinator,
    _move_shapes,
)
from custom_components.robovac_mqtt.models import VacuumState

_MOD = "custom_components.robovac_mqtt.coordinator"


def _make_map(width: int = 40, height: int = 40, tag: int = 0) -> MapData:
    cells = width * height
    return MapData(
        raw_pixels=bytes([0b10101010 ^ tag]) * ((cells + 3) // 4),
        width=width,
        height=height,
        origin_x=-100,
        origin_y=-50,
        resolution=5,
    )


@pytest.fixture
def hass():
    """A hass mock whose tasks and executor jobs run on the test loop."""
    hass = MagicMock()
    hass.async_create_task = lambda coro, *a, **kw: asyncio.ensure_future(coro)
    hass.config_entries.async_get_entry.return_value = None

    async def _executor(func, *args):
        return func(*args)

    hass.async_add_executor_job = _executor
    return hass


@pytest.fixture
def login():
    login = MagicMock()
    login.openudid = "test_udid"
    login.checkLogin = AsyncMock()
    login.mqtt_credentials = {
        "user_id": "uid",
        "app_name": "app",
        "thing_name": "thing",
        "certificate_pem": "cert",
        "private_key": "key",
        "endpoint_addr": "broker.example.com",
    }
    return login


def _coordinator(hass, login, **extra) -> EufyCleanCoordinator:
    info = {"deviceId": "dev1", "deviceModel": "T2118", "deviceName": "Test Vac"}
    info.update(extra)
    coordinator = EufyCleanCoordinator(hass, login, info)
    coordinator._store = MagicMock()
    coordinator._store.async_load = AsyncMock(return_value={})
    coordinator._store.async_save = AsyncMock()
    return coordinator


# --- setup failure and teardown -----------------------------------------------


async def test_a_failed_mqtt_connect_disconnects_the_client(hass, login):
    """The client wrote its key files; a failed setup must remove them."""
    coordinator = _coordinator(hass, login)
    with patch(f"{_MOD}.EufyCleanClient") as client_cls:
        client = client_cls.return_value
        client.connect = AsyncMock(side_effect=OSError("no route"))
        client.disconnect = AsyncMock()
        with pytest.raises(OSError):
            await coordinator.initialize()

    client.set_connection_listener.assert_called_once_with(
        coordinator._on_connection_change
    )
    client.disconnect.assert_awaited_once()
    assert coordinator.client is None


async def test_a_failed_local_setup_after_connect_stops_the_listener(hass, login):
    """A raise after connect() must not leave the listen/heartbeat tasks running."""
    coordinator = _coordinator(
        hass, login, connection_type="local", local_key="k" * 16,
        local_host="192.168.1.50",
    )
    coordinator.async_ensure_legacy_map = AsyncMock(side_effect=RuntimeError("boom"))
    client = MagicMock()
    client.connect = AsyncMock()
    client.disconnect = AsyncMock()
    client.version = 3.3
    with patch(f"{_MOD}.LocalTuyaClient", return_value=client):
        with pytest.raises(RuntimeError):
            await coordinator.initialize()

    client.disconnect.assert_awaited_once()
    assert coordinator.client is None


async def test_local_setup_hands_dps_dicts_to_the_coordinator(hass, login):
    """The local transport calls the DPS entry point, not a JSON envelope."""
    coordinator = _coordinator(
        hass, login, connection_type="local", local_key="k" * 16,
        local_host="192.168.1.50",
    )
    client = MagicMock()
    client.connect = AsyncMock()
    client.version = 3.3
    with patch(f"{_MOD}.LocalTuyaClient", return_value=client):
        await coordinator.initialize()

    client.set_on_dps.assert_called_once_with(coordinator._handle_dps)
    client.set_on_message.assert_not_called()


@pytest.mark.parametrize(("tuya_ids", "checked"), [({"dev1"}, True), (set(), False)])
async def test_startup_firmware_check_only_for_a_device_known_to_tuya(
    hass, login, tuya_ids, checked
):
    """The startup firmware query addresses the Tuya devId: an MQTT robot on an
    account whose Tuya login works is not asked."""
    login.tuya_thing_client = MagicMock()
    login.tuya_device_ids = tuya_ids
    coordinator = _coordinator(hass, login)
    coordinator.config_entry = MagicMock()
    with patch(f"{_MOD}.EufyCleanClient") as client_cls:
        client_cls.return_value.connect = AsyncMock()
        await coordinator.initialize()

    tasks = coordinator.config_entry.async_create_background_task.call_args_list
    for task in tasks:
        task.args[1].close()
    names = [task.args[2] for task in tasks]
    assert ("robovac_mqtt_dev1_fw_check" in names) is checked


async def test_teardown_is_safe_on_a_coordinator_that_never_initialized(hass, login):
    """__init__ tears down after any initialize() failure, however early."""
    coordinator = _coordinator(hass, login)
    await coordinator.async_teardown()
    await coordinator.async_teardown()
    # Nothing was loaded, so nothing may overwrite what is on disk.
    coordinator._store.async_save.assert_not_awaited()


async def test_teardown_persists_the_latest_map_state(hass, login):
    """Changes inside the save delay must survive a restart."""
    coordinator = _coordinator(hass, login)
    await coordinator.async_load_storage()
    coordinator._map_data = _make_map()
    coordinator._robot_trail = [(1, 2), (3, 4)]

    await coordinator.async_teardown()

    saved = coordinator._store.async_save.await_args[0][0]
    assert saved["robot_trail"] == [(1, 2), (3, 4)]
    assert saved["map_data"]["width"] == 40


async def test_teardown_ends_every_map_subscription(hass, login):
    """Subscribers get a terminal event so the card resubscribes to the new instance."""
    coordinator = _coordinator(hass, login)
    first, second = [], []

    def _broken(_event):
        raise RuntimeError("dead socket")

    coordinator.async_add_map_listener(_broken)
    coordinator.async_add_map_listener(first.append)
    coordinator.async_add_map_listener(second.append)
    flush_cancel = MagicMock()
    coordinator._map_flush_cancel = flush_cancel

    await coordinator.async_teardown()

    assert first == [{"t": "gone"}]
    assert second == [{"t": "gone"}]
    assert not coordinator._map_listeners
    flush_cancel.assert_called_once()
    assert coordinator._map_flush_cancel is None


# --- teardown racing background work -----------------------------------------


async def test_teardown_during_login_starts_no_pose_stream(hass, login):
    """A login that returns after teardown must not start paho or arm timers."""
    coordinator = _coordinator(hass, login, apiType="legacy")
    thing = MagicMock()
    thing.sid = None

    async def _login(**_kw):
        coordinator.async_shutdown_timers()

    thing.login = AsyncMock(side_effect=_login)
    login.tuya_thing_client = thing
    with patch(f"{_MOD}.build_connect_params", return_value=object()), patch(
        f"{_MOD}.TuyaMobileMQTT"
    ) as mqtt_cls, patch(f"{_MOD}.async_track_time_interval") as track:
        await coordinator.async_start_legacy_pose_stream()

    mqtt_cls.assert_not_called()
    track.assert_not_called()
    assert coordinator._tuya_mqtt is None


async def test_the_refresh_timer_arms_the_keepalive_a_failed_start_skipped(
    hass, login
):
    """After a failed first start, the 90 min reconnect must bring the keepalive too."""
    coordinator = _coordinator(hass, login, apiType="legacy")
    thing = MagicMock()
    thing.sid = "sid"
    thing.login = AsyncMock()
    login.tuya_thing_client = thing
    with patch(f"{_MOD}.build_connect_params", return_value=None), patch(
        f"{_MOD}.async_track_time_interval", return_value=MagicMock()
    ):
        await coordinator.async_start_legacy_pose_stream()
    assert coordinator._map_keepalive_cancel is None, "no stream, no keepalive"

    with patch(f"{_MOD}.build_connect_params", return_value=object()), patch(
        f"{_MOD}.TuyaMobileMQTT"
    ), patch(f"{_MOD}.async_track_time_interval", return_value=MagicMock()):
        await coordinator._async_refresh_legacy_pose_stream()
    assert coordinator._map_keepalive_cancel is not None


async def test_one_session_refresh_moves_every_robot_on_the_account(hass, login):
    """Robots share one Thing session: one refresh, and every subscriber follows it.

    The CONNECT username carries the sid, and paho reuses it on every reconnect,
    so a robot left on the replaced sid loses its live pose at the next drop.
    """
    thing = TuyaThingClient("uid", websession=MagicMock())
    logins = 0

    async def _login_impl():
        nonlocal logins
        logins += 1
        thing.sid = f"sid{logins}"
        thing.partner_identity = "partner"

    login.tuya_thing_client = thing

    async def _run(func, *args):
        return func(*args)

    # Teardown fires stop() without awaiting it, as on the real executor.
    hass.async_add_executor_job = lambda func, *a: asyncio.ensure_future(_run(func, *a))
    robots = [
        _coordinator(hass, login, apiType="legacy", deviceId=dev)
        for dev in ("dev1", "dev2")
    ]
    for robot in robots:
        robot.config_entry = None
    with patch.object(thing, "_login_impl", side_effect=_login_impl), patch(
        f"{_MOD}.TuyaMobileMQTT"
    ) as mqtt_cls, patch(f"{_MOD}.async_track_time_interval", return_value=MagicMock()):
        for robot in robots:
            await robot.async_start_legacy_pose_stream()
        thing._sid_since -= _TUYA_SESSION_REFRESH_INTERVAL.total_seconds()
        await robots[0]._async_refresh_legacy_pose_stream()
        await asyncio.sleep(0)
        usernames = [c.args[0].username for c in mqtt_cls.call_args_list]
        # The other robot's timer fires later: the session is still fresh.
        await robots[1]._async_refresh_legacy_pose_stream()
        await asyncio.sleep(0)

    assert len(usernames) == 4, "two starts, then both robots reconnect at once"
    assert all("_mb_sid1" in u for u in usernames[:2])
    assert all("_mb_sid2" in u for u in usernames[2:])
    assert logins == 2
    assert mqtt_cls.call_count == 4, "nothing left to reconnect"
    for robot in robots:
        await robot.async_teardown()
    assert not thing._session_listeners


async def test_background_work_is_owned_by_the_config_entry(hass, login):
    """Unload cancels entry background tasks; plain hass tasks outlive it."""
    coordinator = _coordinator(hass, login)
    entry = MagicMock()
    coordinator.config_entry = entry

    async def _work():
        return None

    coordinator._spawn(_work(), "probe")
    entry.async_create_background_task.assert_called_once()
    entry.async_create_background_task.call_args[0][1].close()

    coordinator.async_shutdown_timers()
    coro = _work()
    coordinator._spawn(coro, "probe")
    assert entry.async_create_background_task.call_count == 1
    assert coro.cr_frame is None, "closed, never scheduled"


# --- request pacing and persistence ---------------------------------------------


def test_schedule_fetch_retries_at_most_every_cooldown(login):
    """Until a fetch succeeds each DPS message asked again, up to 6 requests each."""
    hass = MagicMock()
    coordinator = _coordinator(hass, login, apiType="legacy")
    login.tuya_thing_client = MagicMock()

    coordinator._maybe_refresh_legacy_schedules()
    coordinator._maybe_refresh_legacy_schedules()
    assert hass.async_create_task.call_count == 1

    coordinator._sched_attempt_ts -= 1000
    coordinator._maybe_refresh_legacy_schedules()
    assert hass.async_create_task.call_count == 2


async def test_concurrent_first_saves_share_one_document(hass, login):
    """Two first writers must not each load a dict and drop the other's keys."""
    coordinator = _coordinator(hass, login)
    gate = asyncio.Event()

    async def _slow_load():
        await gate.wait()
        return {}

    coordinator._store.async_load = AsyncMock(side_effect=_slow_load)
    first = asyncio.ensure_future(coordinator._async_store_save(a=1))
    second = asyncio.ensure_future(coordinator._async_store_save(b=2))
    await asyncio.sleep(0)
    gate.set()
    await asyncio.gather(first, second)

    assert coordinator._store.async_load.await_count == 1
    assert coordinator._store_data == {"a": 1, "b": 2}


# --- one parse path ---------------------------------------------------------------


async def test_cloud_polled_devices_get_error_notifications(hass, login):
    """The cloud-poll path shares the push path's error and dock handling."""
    coordinator = _coordinator(hass, login, mqtt=False, apiType="legacy")
    coordinator._notify_error = MagicMock()
    login.getCloudDevice = AsyncMock(return_value={"106": 5})
    parsed = VacuumState(error_code=5, error_message="stuck", dock_status="Washing")
    with patch.object(
        coordinator, "_parse_dps",
        return_value=(parsed, {"error_code": 5, "dock_status": "Washing"}),
    ), patch(f"{_MOD}.async_call_later") as later:
        state = await coordinator._async_update_data()

    coordinator._notify_error.assert_called_once_with(5, "stuck")
    assert coordinator._pending_dock_status == "Washing"
    later.assert_called_once()
    # Published only once the debounce commits it.
    assert state.dock_status == coordinator.data.dock_status


async def _poll(coordinator, login, dps):
    """One cloud poll returning ``dps``, published as the DataUpdateCoordinator does."""
    login.getCloudDevice = AsyncMock(return_value=dps)
    coordinator.data = await coordinator._async_update_data()


async def test_a_poll_repeating_the_state_renders_saves_and_notifies_nothing(
    hass, login
):
    """A cloud poll returns every DPS; a parked robot's must not churn the map."""
    coordinator = _coordinator(hass, login, mqtt=False, apiType="legacy")
    await coordinator.async_load_storage()
    coordinator._map_data = _make_map()
    coordinator._dock_pixel = (10, 10)
    parked = {"15": "Charging", "104": 80, "106": 5}
    with patch(f"{_MOD}.pn_async_create") as notify, patch(
        f"{_MOD}.async_dispatcher_send"
    ):
        await _poll(coordinator, login, parked)
        revision = coordinator.map_revision
        saves = coordinator._store.async_delay_save.call_count
        for _ in range(3):
            await _poll(coordinator, login, parked)

    assert coordinator.data.activity == "docked"
    assert coordinator.map_revision == revision
    assert coordinator._store.async_delay_save.call_count == saves
    notify.assert_called_once()


async def test_a_poll_redraws_the_badge_when_the_battery_fills(hass, login):
    """The charging badge goes at 100 %; the poll path has no other trigger for it."""
    coordinator = _coordinator(hass, login, mqtt=False, apiType="legacy")
    coordinator._map_data = _make_map()
    with patch(f"{_MOD}.async_dispatcher_send"):
        await _poll(coordinator, login, {"15": "Charging", "104": 98})
        revision = coordinator.map_revision
        await _poll(coordinator, login, {"15": "Charging", "104": 99})
        assert coordinator.map_revision == revision, "same badge, same frame"
        await _poll(coordinator, login, {"15": "Charging", "104": 100})

    assert coordinator.map_revision == revision + 1
    assert coordinator._get_robot_status() is None


def test_a_raw_dps_only_message_does_not_fan_out(login):
    """Only raw_dps changed: no entity state write for any entity."""
    coordinator = _coordinator(MagicMock(), login)
    coordinator.async_set_updated_data = MagicMock()
    new_state = VacuumState(raw_dps={"999": 1})
    with patch(f"{_MOD}.update_state", return_value=(new_state, {"raw_dps": {"999": 1}})):
        coordinator._handle_dps({"999": 1})

    coordinator.async_set_updated_data.assert_not_called()
    assert coordinator.data.raw_dps == {"999": 1}


# --- the novel map stream is decoded off the loop --------------------------------


async def test_a_large_biz_frame_is_decoded_in_the_executor(login):
    """The LZ4/protobuf decode must not run inside the MQTT callback."""
    hass = MagicMock()
    pending: list = []

    def _task(coro, *_a, **_kw):
        pending.append(asyncio.ensure_future(coro))
        return pending[-1]

    hass.async_create_task = _task
    hass.async_add_executor_job = AsyncMock(return_value=("map", _make_map()))
    coordinator = _coordinator(hass, login)
    decode = MagicMock()
    with patch(f"{_MOD}.parse_biz_protocol41", return_value=(3, "ab" * 500)), patch(
        f"{_MOD}.try_extract_map_data", decode
    ), patch(f"{_MOD}.try_extract_map_description", decode):
        coordinator._handle_biz_message(b"frame")
        decode.assert_not_called()
        assert len(pending) == 1
        await pending[0]

    assert hass.async_add_executor_job.await_args.args[1] == "ab" * 500
    assert coordinator._map_data is not None
    assert coordinator._map_data_chan_id == 3


async def test_a_stale_map_decode_does_not_overwrite_a_newer_one(login):
    """Executor jobs can finish out of order; the older frame is dropped."""
    hass = MagicMock()
    pending: list = []

    def _task(coro, *_a, **_kw):
        pending.append(asyncio.ensure_future(coro))
        return pending[-1]

    hass.async_create_task = _task
    maps = {"aa" * 500: _make_map(tag=1), "bb" * 500: _make_map(tag=2)}
    gates = {hex_data: asyncio.Event() for hex_data in maps}

    async def _executor(_func, hex_data, _candidate):
        await gates[hex_data].wait()
        return "map", maps[hex_data]

    hass.async_add_executor_job = _executor
    coordinator = _coordinator(hass, login)
    coordinator._rerender_map = MagicMock()
    for hex_data in ("aa" * 500, "bb" * 500):
        with patch(f"{_MOD}.parse_biz_protocol41", return_value=(3, hex_data)):
            coordinator._handle_biz_message(b"frame")
    older, newer = pending[0], pending[1]
    await asyncio.sleep(0)

    gates["bb" * 500].set()
    await newer
    gates["aa" * 500].set()
    await older

    assert coordinator._map_data is maps["bb" * 500]


# --- logs carry counts, not payloads --------------------------------------------


async def test_logs_carry_no_host_or_command_payload(hass, login, caplog):
    """The LAN address and command contents stay out of the log."""
    caplog.set_level(logging.DEBUG, logger=_MOD)
    coordinator = _coordinator(
        hass, login, connection_type="local", local_key="k" * 16,
        local_host="192.168.1.50",
    )
    client = MagicMock()
    client.connect = AsyncMock()
    client.send_command = AsyncMock()
    client.version = 3.3
    with patch(f"{_MOD}.LocalTuyaClient", return_value=client):
        await coordinator.initialize()
    await coordinator.async_send_command({"154": "c2VjcmV0LXpvbmU="})
    coordinator._on_legacy_pose(12345, 23456, 90)

    text = caplog.text
    assert "192.168.1.50" not in text
    assert "c2VjcmV0LXpvbmU=" not in text
    assert "12345" not in text


# --- service input -----------------------------------------------------------------


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), "nan"])
def test_non_finite_map_points_are_a_validation_error(login, bad):
    """NaN passed the clamp; inf reached round() and raised a raw error."""
    coordinator = _coordinator(MagicMock(), login)
    coordinator._map_data = _make_map()
    with pytest.raises(ServiceValidationError):
        coordinator._normalized_to_cm(bad, 0.5)
    with pytest.raises(ServiceValidationError):
        coordinator.room_id_at_normalized(0.5, bad)
    with pytest.raises(ServiceValidationError):
        _move_shapes([[(0, 0), (10, 0)]], [{"index": 0, "dx": bad}], "walls")
    with pytest.raises(ServiceValidationError):
        _move_shapes([[(0, 0), (10, 0)]], [{"index": 0, "rotate": bad}], "walls")


@pytest.mark.parametrize(
    "kwargs",
    [
        {"mode": "room"},
        {"mode": "spot"},
        {"rooms": [1]},
        {"water": "High"},
        {"clean_times": 2},
    ],
)
async def test_scalar_schedules_reject_fields_dps_151_cannot_carry(hass, login, kwargs):
    """Silently ignored fields looked applied in the Schedules sensor."""
    coordinator = _coordinator(hass, login, apiType="scalar")
    coordinator.async_send_command = AsyncMock()
    with pytest.raises(ServiceValidationError):
        await coordinator.async_set_schedule(time="08:00", **kwargs)
    coordinator.async_send_command.assert_not_awaited()


async def test_a_scalar_schedule_reads_back_as_the_parser_reads_dps_151(hass, login):
    """The optimistic list is what the next DPS 151 push will report."""
    coordinator = _coordinator(hass, login, apiType="scalar")
    coordinator.async_send_command = AsyncMock()
    coordinator.data, _ = update_state(
        VacuumState(api_type="scalar", device_model="T2210"),
        {"151": {"l": [{"id": 1, "e": True, "t": "0700", "r": "6", "s": 0, "f": 1}]}},
    )

    await coordinator.async_set_schedule(time="08:00", days="Weekdays", mode="Random")

    (payload,) = coordinator.async_send_command.await_args.args[0].values()
    sent, _ = update_state(
        VacuumState(api_type="scalar", device_model="T2210"), {"151": payload}
    )
    assert coordinator.data.schedules == sent.schedules
    assert [e["pattern"] for e in sent.schedules] == ["Arranged", "Random"]


async def test_enabling_a_scalar_schedule_writes_json_bools(hass, login):
    coordinator = _coordinator(hass, login, apiType="scalar")
    coordinator.async_send_command = AsyncMock()
    coordinator.data, _ = update_state(
        VacuumState(api_type="scalar", device_model="T2210"),
        {"151": {"l": [
            {"id": 1, "e": False, "t": "0700", "r": "6", "s": 0, "f": 1},
            {"id": 2, "e": True, "t": "0800", "r": "7", "s": 0, "f": 1},
        ]}},
    )

    await coordinator.async_set_schedule_status(1, True)

    (payload,) = coordinator.async_send_command.await_args.args[0].values()
    assert [entry["e"] for entry in json.loads(payload)["l"]] == [True, True]
    assert '"e":1' not in payload


@pytest.mark.parametrize("kwargs", [{"suction": "Boost_IQ"}, {"days": "Mondy"}])
async def test_scalar_schedules_reject_unknown_values(hass, login, kwargs):
    """An unknown suction or day is an error, not a silent default."""
    coordinator = _coordinator(hass, login, apiType="scalar")
    coordinator.async_send_command = AsyncMock()
    with pytest.raises(ServiceValidationError):
        await coordinator.async_set_schedule(time="08:00", **kwargs)
    coordinator.async_send_command.assert_not_awaited()


def _legacy_schedule_coordinator(hass, login, timers):
    """A legacy coordinator whose loaded schedules are ``timers`` as Tuya lists them."""
    login.tuya_thing_client = MagicMock()
    coordinator = _coordinator(hass, login, apiType="legacy")
    coordinator.data = VacuumState(
        api_type="legacy", map_id=6, schedules=parse_legacy_schedules(timers)
    )
    coordinator._tuya_timer_call = AsyncMock(return_value=({"success": True}, None))
    coordinator.async_refresh_legacy_schedules = AsyncMock(return_value=False)
    return coordinator


def _sent_timer(coordinator):
    """(action key, fields, decoded DPS 124 doc) of the one timer write."""
    call = coordinator._tuya_timer_call.await_args
    fields = call.kwargs
    return call.args[0], fields, json.loads(base64.b64decode(fields["dps"]["124"]))


_KITCHEN_HALL_WEEKDAYS = {
    "timerId": 5, "status": 0, "time": "08:00", "loops": "0111110",
    "dps": {"124": base64.b64encode(json.dumps({
        "method": "scheduleRoomsClean",
        "data": {"mapId": 2, "cleanMode": "customize", "cleanLevel": "Max",
                 "waterMode": "High", "property": [{"roomId": 3}, {"roomId": 4}],
                 "cleanTimes": 2},
        "timestamp": 1_700_000_000_000,
    }).encode()).decode()},
}


async def test_changing_a_legacy_schedule_time_keeps_everything_else(hass, login):
    """Only the passed field changes: days, state, rooms, levels and map stay."""
    coordinator = _legacy_schedule_coordinator(hass, login, [_KITCHEN_HALL_WEEKDAYS])

    await coordinator.async_set_schedule(schedule_id=5, time="10:00")

    key, fields, doc = _sent_timer(coordinator)
    assert key == "timer.modify"
    assert (fields["timerId"], fields["time"], fields["loops"], fields["status"]) == (
        5, "10:00", "0111110", 0,
    )
    assert doc["method"] == "scheduleRoomsClean"
    assert doc["data"] == {
        "mapId": 2, "cleanMode": "customize", "cleanLevel": "Max", "waterMode": "High",
        "property": [{"roomId": 3}, {"roomId": 4}], "cleanTimes": 2,
    }


async def test_passed_fields_override_a_legacy_schedule(hass, login):
    """New rooms are on the active map; an empty list is a whole-home clean."""
    coordinator = _legacy_schedule_coordinator(hass, login, [_KITCHEN_HALL_WEEKDAYS])

    await coordinator.async_set_schedule(
        schedule_id=5, enabled=True, rooms=[], days="Sat", suction="Quiet"
    )

    _, fields, doc = _sent_timer(coordinator)
    assert (fields["time"], fields["loops"], fields["status"]) == ("08:00", "0000001", 1)
    assert doc["method"] == "scheduleAutoClean"
    assert doc["data"]["property"] == []
    assert doc["data"]["mapId"] == 6
    assert doc["data"]["cleanLevel"] == "Quiet"
    assert doc["data"]["waterMode"] == "High"


async def test_a_new_legacy_schedule_takes_the_defaults(hass, login):
    coordinator = _legacy_schedule_coordinator(hass, login, [])

    await coordinator.async_set_schedule(time="07:30")

    key, fields, doc = _sent_timer(coordinator)
    assert key == "timer.add"
    assert (fields["time"], fields["loops"], fields["status"]) == ("07:30", "1111111", 1)
    assert doc["data"] == {
        "mapId": 6, "cleanMode": "general", "cleanLevel": "Standard",
        "waterMode": "medium", "property": [], "cleanTimes": 1,
    }


async def test_an_unknown_legacy_schedule_is_looked_up_once_then_refused(hass, login):
    """Modifying blind would reset the timer, so a missing id is an error."""
    coordinator = _legacy_schedule_coordinator(hass, login, [])

    with pytest.raises(HomeAssistantError, match="not found"):
        await coordinator.async_set_schedule(schedule_id=9, time="07:30")

    coordinator.async_refresh_legacy_schedules.assert_awaited_once()
    coordinator._tuya_timer_call.assert_not_awaited()


async def test_changing_a_scalar_schedule_time_keeps_everything_else(hass, login):
    coordinator = _coordinator(hass, login, apiType="scalar")
    coordinator.async_send_command = AsyncMock()
    disabled = {"id": 1, "e": False, "t": "0700", "r": "13", "s": 3, "f": 2}
    other = {"id": 2, "e": True, "t": "0800", "r": "7", "s": 0, "f": 1}
    coordinator.data, _ = update_state(
        VacuumState(api_type="scalar", device_model="T2210"),
        {"151": {"l": [disabled, other]}},
    )

    await coordinator.async_set_schedule(schedule_id=1, time="10:00")

    (payload,) = coordinator.async_send_command.await_args.args[0].values()
    assert json.loads(payload)["l"] == [{**disabled, "t": "1000"}, other]


@pytest.mark.parametrize("api_type", ["legacy", "scalar"])
async def test_a_new_schedule_needs_a_time(hass, login, api_type):
    coordinator = _legacy_schedule_coordinator(hass, login, [])
    coordinator.api_type = api_type
    coordinator.async_send_command = AsyncMock()

    with pytest.raises(ServiceValidationError, match="needs a time"):
        await coordinator.async_set_schedule(days="Mon")

    coordinator._tuya_timer_call.assert_not_awaited()
    coordinator.async_send_command.assert_not_awaited()


# --- transport availability ----------------------------------------------------------


def _armed(later: MagicMock):
    """The callback the last async_call_later was given."""
    return later.call_args.args[2]


def test_a_short_disconnect_keeps_entities_available(login):
    """Paho reconnects within seconds; flapping to unavailable is noise."""
    coordinator = _coordinator(MagicMock(), login)
    cancel = MagicMock()
    with patch(f"{_MOD}.async_call_later", return_value=cancel) as later:
        coordinator._on_connection_change(False, False)
        assert later.call_args.args[1] == _CONNECTION_LOSS_GRACE
        coordinator._on_connection_change(True, False)

    cancel.assert_called_once()
    assert coordinator.last_update_success is True


def test_a_sustained_disconnect_marks_entities_unavailable(login):
    """Down for the whole grace period: unavailable until the broker is back."""
    coordinator = _coordinator(MagicMock(), login)
    listener = MagicMock()
    coordinator.async_add_listener(listener)
    with patch(f"{_MOD}.async_call_later", return_value=MagicMock()) as later:
        coordinator._on_connection_change(False, False)
    _armed(later)(None)
    assert coordinator.last_update_success is False

    # An optimistic write while down must not flip it back.
    coordinator.async_set_updated_data(VacuumState(battery_level=10))
    assert coordinator.last_update_success is False

    coordinator._on_connection_change(True, False)
    assert coordinator.last_update_success is True
    assert listener.call_count >= 2


def test_repeated_auth_refusals_warn_once(login, caplog):
    """One WARNING on the third refusal in a row, not one per retry."""
    coordinator = _coordinator(MagicMock(), login)
    with patch(f"{_MOD}.async_call_later", return_value=MagicMock()):
        for _ in range(5):
            coordinator._on_connection_change(False, True)
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    login.checkLogin.assert_not_called()


def _account_login(credentials):
    """A real EufyLogin holding cached MQTT credentials; logins yield new ones."""
    login = EufyLogin(
        "u", "p", "test_udid", websession=MagicMock(),
        auth_cache=AuthCache(mqtt_credentials=credentials),
    )
    issued = iter(range(1, 100))

    async def _login(_config):
        login.mqtt_credentials = {**credentials, "certificate_pem": f"new{next(issued)}"}

    login.login = AsyncMock(side_effect=_login)
    return login


async def _settle() -> None:
    for _ in range(20):
        await asyncio.sleep(0)


async def _connected_coordinators(hass, login, count, client_cls):
    """``count`` MQTT coordinators of one account, each connected once."""
    client_cls.side_effect = lambda **_kw: MagicMock(
        connect=AsyncMock(), disconnect=AsyncMock()
    )
    coordinators = []
    for n in range(count):
        coordinator = _coordinator(hass, login, deviceId=f"dev{n}")
        await coordinator.initialize()
        coordinators.append(coordinator)
    return coordinators


def _entry() -> MagicMock:
    """A config entry whose background tasks run on the test loop."""
    entry = MagicMock()
    entry.async_create_background_task = (
        lambda _hass, coro, _name: asyncio.ensure_future(coro)
    )
    return entry


def _refuse(coordinator, times: int) -> None:
    for _ in range(times):
        coordinator._on_connection_change(False, True)


async def test_a_refusal_streak_reconnects_with_new_credentials(hass, login):
    """The broker keeps rejecting the cert: one login, then a new client."""
    account = _account_login(login.mqtt_credentials)
    with patch(f"{_MOD}.EufyCleanClient") as client_cls, patch(
        f"{_MOD}.async_call_later", return_value=MagicMock()
    ):
        (coordinator,) = await _connected_coordinators(hass, account, 1, client_cls)
        old_client = coordinator.client
        _refuse(coordinator, _AUTH_FAILURE_WARN_AFTER)
        await _settle()

    account.login.assert_awaited_once()
    old_client.set_connection_listener.assert_called_with(None)
    old_client.disconnect.assert_awaited_once()
    assert client_cls.call_args.kwargs["certificate_pem"] == "new1"
    coordinator.client.connect.assert_awaited_once()
    assert coordinator._auth_failures == 0
    assert account.auth_cache.mqtt_credentials["certificate_pem"] == "new1"


async def test_coordinators_of_one_account_share_one_replacement(hass, login):
    """Two robots rejected together: one login, both reconnect with its result."""
    account = _account_login(login.mqtt_credentials)
    with patch(f"{_MOD}.EufyCleanClient") as client_cls, patch(
        f"{_MOD}.async_call_later", return_value=MagicMock()
    ):
        first, second = await _connected_coordinators(hass, account, 2, client_cls)
        _refuse(first, _AUTH_FAILURE_WARN_AFTER)
        _refuse(second, _AUTH_FAILURE_WARN_AFTER)
        await _settle()

    account.login.assert_awaited_once()
    assert first._mqtt_credentials is account.mqtt_credentials
    assert second._mqtt_credentials is account.mqtt_credentials


async def test_a_rejected_replacement_does_not_loop(hass, login):
    """The new cert is rejected too: no second login, no further reconnect."""
    account = _account_login(login.mqtt_credentials)
    with patch(f"{_MOD}.EufyCleanClient") as client_cls, patch(
        f"{_MOD}.async_call_later", return_value=MagicMock()
    ):
        (coordinator,) = await _connected_coordinators(hass, account, 1, client_cls)
        _refuse(coordinator, _AUTH_FAILURE_WARN_AFTER)
        await _settle()
        clients = client_cls.call_count
        for _ in range(4):
            _refuse(coordinator, _AUTH_FAILURE_WARN_AFTER)
            await _settle()

    account.login.assert_awaited_once()
    assert client_cls.call_count == clients
    assert account.auth_cache.mqtt_credentials is None


async def test_an_accepted_replacement_rearms_the_next_one(hass, login):
    """A connect on the new cert ends the streak; a later rotation is replaced."""
    account = _account_login(login.mqtt_credentials)
    with patch(f"{_MOD}.EufyCleanClient") as client_cls, patch(
        f"{_MOD}.async_call_later", return_value=MagicMock()
    ):
        (coordinator,) = await _connected_coordinators(hass, account, 1, client_cls)
        _refuse(coordinator, _AUTH_FAILURE_WARN_AFTER)
        await _settle()
        coordinator._on_connection_change(True, False)
        # outside the window in which a second replacement latches the kick-out
        account._replacement_login_at = time.monotonic() - SESSION_REPLACED_WINDOW
        _refuse(coordinator, _AUTH_FAILURE_WARN_AFTER)
        await _settle()

    assert account.login.await_count == 2
    assert client_cls.call_args.kwargs["certificate_pem"] == "new2"


async def test_refusals_during_a_replacement_start_no_second_one(hass, login):
    """More refusals while the login runs do not queue another replacement."""
    login.replace_rejected_mqtt_credentials = AsyncMock(return_value=False)
    with patch(f"{_MOD}.EufyCleanClient") as client_cls, patch(
        f"{_MOD}.async_call_later", return_value=MagicMock()
    ):
        (coordinator,) = await _connected_coordinators(hass, login, 1, client_cls)
        _refuse(coordinator, 3 * _AUTH_FAILURE_WARN_AFTER)
        await _settle()
        _refuse(coordinator, _AUTH_FAILURE_WARN_AFTER)
        await _settle()

    assert login.replace_rejected_mqtt_credentials.await_count == 2


@pytest.mark.parametrize(
    ("error", "kicked_out"),
    [
        (EufyLoginError("Login failed"), False),
        (EufySessionReplacedError("kicked out"), True),
    ],
    ids=["login-refused", "session-replaced"],
)
async def test_a_refused_replacement_login_starts_reauth(hass, login, error, kicked_out):
    """The account login is refused (password changed), or another client
    keeps taking the account: ask the user; the latter with a repair issue."""
    login.replace_rejected_mqtt_credentials = AsyncMock(side_effect=error)
    with patch(f"{_MOD}.EufyCleanClient") as client_cls, patch(
        f"{_MOD}.async_call_later", return_value=MagicMock()
    ), patch(f"{_MOD}.async_create_session_replaced_issue") as create_issue:
        (coordinator,) = await _connected_coordinators(hass, login, 1, client_cls)
        coordinator.config_entry = _entry()
        coordinator.config_entry.entry_id = "entry"
        coordinator.config_entry.data = {CONF_USERNAME: "user@example.com"}
        _refuse(coordinator, _AUTH_FAILURE_WARN_AFTER)
        await _settle()

    coordinator.config_entry.async_start_reauth.assert_called_once_with(hass)
    assert client_cls.call_count == 1
    if kicked_out:
        create_issue.assert_called_once_with(hass, "entry", "user@example.com")
    else:
        create_issue.assert_not_called()


@pytest.mark.parametrize("during", ["login", "connect"])
async def test_a_teardown_during_a_replacement_leaves_no_client(hass, login, during):
    """Unload while the login or the reconnect runs: nothing outlives it."""
    with patch(f"{_MOD}.EufyCleanClient") as client_cls, patch(
        f"{_MOD}.async_call_later", return_value=MagicMock()
    ):
        (coordinator,) = await _connected_coordinators(hass, login, 1, client_cls)

        async def _close(*_args):
            coordinator._closing = True
            return True

        if during == "login":
            login.replace_rejected_mqtt_credentials = AsyncMock(side_effect=_close)
        else:
            login.replace_rejected_mqtt_credentials = AsyncMock(return_value=True)
            client_cls.side_effect = lambda **_kw: MagicMock(
                connect=AsyncMock(side_effect=_close), disconnect=AsyncMock()
            )
        _refuse(coordinator, _AUTH_FAILURE_WARN_AFTER)
        await _settle()

    assert client_cls.call_count == (1 if during == "login" else 2)
    if during == "connect":
        assert coordinator.client is None


async def test_a_failed_reconnect_reloads_the_entry(hass, login):
    """The new client cannot connect: the entry reload retries the transport."""
    account = _account_login(login.mqtt_credentials)
    with patch(f"{_MOD}.EufyCleanClient") as client_cls, patch(
        f"{_MOD}.async_call_later", return_value=MagicMock()
    ):
        (coordinator,) = await _connected_coordinators(hass, account, 1, client_cls)
        coordinator.config_entry = _entry()
        coordinator.entry_id = "entry"
        client_cls.side_effect = lambda **_kw: MagicMock(
            connect=AsyncMock(side_effect=OSError("no route")), disconnect=AsyncMock()
        )
        with patch(f"{_MOD}.AuthStore") as store_cls:
            store_cls.return_value.async_save = AsyncMock()
            _refuse(coordinator, _AUTH_FAILURE_WARN_AFTER)
            await _settle()

    hass.config_entries.async_schedule_reload.assert_called_once_with("entry")
    assert coordinator.client is None
    store_cls.return_value.async_save.assert_awaited_with(account.auth_cache)


def test_teardown_cancels_the_pending_unavailable_timer(login):
    """A timer firing on a torn-down coordinator would touch dead entities."""
    coordinator = _coordinator(MagicMock(), login)
    cancel = MagicMock()
    with patch(f"{_MOD}.async_call_later", return_value=cancel):
        coordinator._on_connection_change(False, False)
    coordinator.async_shutdown_timers()
    cancel.assert_called_once()
    # Late events from paho's queue are ignored.
    coordinator._on_connection_change(False, False)
    assert coordinator._connection_loss_cancel is None
