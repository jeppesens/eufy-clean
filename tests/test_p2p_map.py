"""Tests for the live P2P map feed and its coordinator wiring.

The P2P session itself is replaced by a scripted fake: these tests cover the
supervision policy (snapshot per session, reconnect on demand, backoff), the
persistence round-trip, and how decoded updates reach coordinator state.
"""

# pylint: disable=redefined-outer-name, protected-access

import asyncio
from dataclasses import replace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.robovac_mqtt import p2p_map
from custom_components.robovac_mqtt.api.p2p import P2PError, P2PRefused
from custom_components.robovac_mqtt.api.p2p.mapdata import (
    CHANGED_MAP,
    CHANGED_ROOMS,
    Obstacle,
    P2PMap,
    Pose,
)
from custom_components.robovac_mqtt.api.p2p.mapimage import (
    build_map_data,
    build_overlay,
)
from custom_components.robovac_mqtt.camera import EufyMapCamera
from custom_components.robovac_mqtt.coordinator import EufyCleanCoordinator
from custom_components.robovac_mqtt.p2p_map import P2PMapFeed

from .test_p2p import _delimited, _outline_msg, _path_obj, _pose_obj, _rooms_msg

_RTC = {"device_password": "pw", "ice_config": {"token": []}}


class _FakeSession:
    """Plays a list of stream objects into on_object, then ends (or raises)."""

    script: list = []
    instances: list = []

    def __init__(self, *, on_object, **kwargs):
        self.on_object = on_object
        self.kwargs = kwargs
        self.closed = False
        _FakeSession.instances.append(self)

    async def run(self):
        step = _FakeSession.script.pop(0) if _FakeSession.script else []
        if isinstance(step, Exception):
            raise step
        # (objects, error): deliver the objects, then end with the error.
        step, error = step if isinstance(step, tuple) else (step, None)
        for name, obj in step:
            self.on_object(name, obj)
        await asyncio.sleep(0)
        if error is not None:
            raise error

    async def close(self):
        self.closed = True


@pytest.fixture(autouse=True)
def fake_session():
    _FakeSession.script = []
    _FakeSession.instances = []
    # Some tests replace run/close on the class; put them back afterwards.
    run, close = _FakeSession.run, _FakeSession.close
    with (
        patch.object(p2p_map, "P2PSession", _FakeSession),
        # No real sockets in tests: the robot counts as reachable.
        patch.object(P2PMapFeed, "_robot_reachable", AsyncMock(return_value=True)),
    ):
        yield _FakeSession
    _FakeSession.run, _FakeSession.close = run, close


def _feed(hass, *, active=False, changes=None, rtc=None):
    return P2PMapFeed(
        hass,
        host="192.168.1.50",
        local_key="0123456789abcdef",
        device_id="dev",
        rtc_config=AsyncMock(return_value=_RTC if rtc is None else rtc),
        is_active=lambda: active,
        on_change=(changes.append if changes is not None else lambda _c: None),
        name="S1 Pro",
    )


async def _until(predicate, timeout=2.0):
    loop = asyncio.get_running_loop()
    end = loop.time() + timeout
    while not predicate():
        if loop.time() > end:
            raise AssertionError("condition not met")
        await asyncio.sleep(0.01)


@pytest.mark.asyncio
async def test_feed_applies_objects_and_reports_changes(hass, fake_session):
    changes: list[set[str]] = []
    fake_session.script = [
        [
            ("map.bin.stream", _delimited(_outline_msg(bytes([2] * 12)))),
            ("map.bin.stream", _delimited(_rooms_msg((0, "Kitchen")))),
        ]
    ]
    feed = _feed(hass, changes=changes)
    feed.start()
    await _until(lambda: len(changes) == 2)
    assert CHANGED_MAP in changes[0] and changes[1] == {CHANGED_ROOMS}
    assert feed.state.rooms[0]["name"] == "Kitchen"
    assert feed.sessions == 1
    assert fake_session.instances[0].kwargs["device_password"] == "pw"
    await feed.stop()


@pytest.mark.asyncio
async def test_feed_reconnects_when_poked_and_takes_a_fresh_path_snapshot(hass, fake_session):
    fake_session.script = [
        [("cleanPath.bin.stream", _path_obj([(1, 1, 2), (2, 2, 2)]))],
        [("cleanPath.bin.stream", _path_obj([(9, 9, 2)]))],
    ]
    feed = _feed(hass)  # idle: would otherwise wait 15 minutes
    feed.start()
    await _until(lambda: feed.sessions == 1 and feed.state.path)
    feed.poke()
    await _until(lambda: feed.sessions == 2 and feed.state.path == [(9, 9, 2)])
    await feed.stop()


@pytest.mark.asyncio
async def test_feed_backs_off_after_failures_and_keeps_going(hass, fake_session):
    fake_session.script = [OSError("refused"), [("navPath.bin", _pose_obj(1, 2, 3))]]
    with patch.object(p2p_map, "_ACTIVE_RETRY", 0.01):
        feed = _feed(hass, active=True)
        feed.start()
        await _until(lambda: feed.state.pose == Pose(1, 2, 3))
    assert feed.failures == 1
    assert feed.last_error is None  # cleared by the good session
    await feed.stop()


@pytest.mark.asyncio
async def test_feed_records_missing_credentials(hass, fake_session):
    feed = _feed(hass, rtc={})
    feed.start()
    await _until(lambda: feed.failures >= 1)
    assert "credentials" in feed.last_error
    assert not fake_session.instances
    await feed.stop()


def test_feed_dump_restore_roundtrip(hass):
    feed = _feed(hass)
    feed.decoder.state = P2PMap(
        map_id=1,
        width=4,
        height=3,
        origin_x=-10,
        origin_y=-5,
        docks=[Pose(1, -29, 157)],
        outline=bytes(range(12)),
        rooms=[{"id": 0, "name": "Kitchen", "order": 1, "scene": 0}],
        obstacles=[Obstacle("Shoe", ((5, 6),))],
        virtual_walls=[((1, 2), (3, 4))],
        forbidden_zones=[[(0, 0), (1, 0), (1, 1), (0, 1)]],
        path=[(-277, 1163, 0x12), (3, 58, 4)],
        pose=Pose(3, 58, 152),
    )
    dumped = feed.dump()
    other = _feed(hass)
    other.restore(dumped)
    restored = other.state
    original = feed.state
    for attr in (
        "map_id", "width", "height", "origin_x", "origin_y", "docks", "outline",
        "rooms", "obstacles", "virtual_walls", "forbidden_zones", "path", "pose",
    ):
        assert getattr(restored, attr) == getattr(original, attr), attr


def test_feed_restore_ignores_garbage(hass):
    feed = _feed(hass)
    feed.restore({"map_id": 1})
    assert not feed.state.has_map


# ---------------------------------------------------------------------------
# coordinator wiring
# ---------------------------------------------------------------------------


def _local_coordinator(hass, **info_extra) -> EufyCleanCoordinator:
    login = MagicMock()
    login.openudid = "udid"
    login.tuya_client = MagicMock()
    login.get_rtc_config = AsyncMock(return_value=_RTC)
    info = {
        "deviceId": "dev",
        "deviceModel": "T2080A",
        "deviceName": "S1 Pro",
        "connection_type": "local",
        "local_key": "0123456789abcdef",
        "local_host": "192.168.1.50",
        **info_extra,
    }
    return EufyCleanCoordinator(hass, login, info)


@pytest.mark.asyncio
async def test_coordinator_takes_rooms_and_map_id_from_p2p(hass, fake_session):
    coordinator = _local_coordinator(hass)
    fake_session.script = [
        [
            ("map.bin.stream", _delimited(_outline_msg(bytes([2] * 12)))),
            ("map.bin.stream", _delimited(_rooms_msg((0, "Kitchen"), (1, "")))),
        ]
    ]
    with patch.object(coordinator, "_rerender_map") as rerender:
        coordinator._start_p2p_feed()
        await _until(lambda: coordinator.data.rooms)
        assert coordinator.data.rooms == [
            {"id": 0, "name": "Kitchen"},
            {"id": 1, "name": "Room 2"},
        ]
        assert coordinator.data.map_id == 1
        assert {"rooms", "map_id"} <= coordinator.data.received_fields
        assert coordinator._map_data is not None
        await _until(lambda: rerender.called, timeout=3)
    coordinator.async_shutdown_timers()
    await coordinator.async_stop_p2p()


@pytest.mark.asyncio
async def test_coordinator_skips_p2p_without_tuya_session(hass):
    coordinator = _local_coordinator(hass)
    coordinator.eufy_login.tuya_client = None
    coordinator._start_p2p_feed()
    assert coordinator.p2p is None


@pytest.mark.asyncio
async def test_coordinator_pokes_feed_on_activity_change(hass, fake_session):
    coordinator = _local_coordinator(hass)
    coordinator._start_p2p_feed()
    coordinator.p2p.poke = MagicMock()
    with patch(
        "custom_components.robovac_mqtt.coordinator.update_state",
        return_value=(replace(coordinator.data, activity="cleaning"), {"activity": "cleaning"}),
    ):
        coordinator._handle_mqtt_message(b'{"payload": {"data": {"153": "x"}}}')
    coordinator.p2p.poke.assert_called_once()
    await coordinator.async_stop_p2p()


@pytest.mark.asyncio
async def test_coordinator_restores_stored_p2p_map(hass, fake_session):
    coordinator = _local_coordinator(hass)
    feed = _feed(hass)
    feed.decoder.state = P2PMap(
        map_id=1, width=4, height=3, outline=bytes([2] * 12),
        rooms=[{"id": 0, "name": "Kitchen", "order": 1, "scene": 0}],
    )
    coordinator._restore_p2p = feed.dump()
    fake_session.script = [OSError("offline")]
    with patch.object(coordinator, "_rerender_map"):
        coordinator._start_p2p_feed()
        assert coordinator.data.rooms == [{"id": 0, "name": "Kitchen"}]
        assert coordinator._map_data is not None
    coordinator.async_shutdown_timers()
    await coordinator.async_stop_p2p()


@pytest.mark.asyncio
async def test_camera_exposes_rooms_and_obstacles(hass, fake_session):
    coordinator = _local_coordinator(hass)
    coordinator._start_p2p_feed()
    coordinator.p2p.decoder.state.obstacles = [Obstacle("Shoe", ((-103, 442),))]
    coordinator.data = replace(coordinator.data, rooms=[{"id": 0, "name": "Kitchen"}])
    attrs = EufyMapCamera(coordinator).extra_state_attributes
    assert attrs["rooms"] == {"0": "Kitchen"}
    assert attrs["obstacles"] == [{"type": "Shoe", "x": -103, "y": 442}]
    coordinator.p2p.decoder.state.pose = Pose(3, -4, 157)
    coordinator.p2p.decoder.state.docks = [Pose(1, -29, 0)]
    attrs = EufyMapCamera(coordinator).extra_state_attributes
    assert attrs["robot"] == {"x": 3, "y": -4, "theta": 157}
    assert attrs["dock"] == {"x": 1, "y": -29}
    await coordinator.async_stop_p2p()


# -- the cloud config is single-use ------------------------------------------------


@pytest.mark.asyncio
async def test_each_session_fetches_a_fresh_config_and_uses_its_cloud_session(hass, fake_session):
    """Every fetch reserves a slot on the robot until a session uses it, so never cache."""
    configs = [
        {"device_password": "pw", "ice_config": {}, "session": {"sessionId": "first"}},
        {"device_password": "pw", "ice_config": {}, "session": {"sessionId": "second"}},
    ]
    fetch = AsyncMock(side_effect=configs)
    fake_session.script = [[("navPath.bin", _pose_obj(1, 2, 3))], [("navPath.bin", _pose_obj(4, 5, 6))]]
    feed = P2PMapFeed(
        hass, host="192.168.1.50", local_key="0123456789abcdef", device_id="dev",
        rtc_config=fetch, is_active=lambda: True, on_change=lambda _c: None, name="S1 Pro",
    )
    with patch.object(p2p_map, "_ACTIVE_RETRY", 0.01):
        feed.start()
        await _until(lambda: len(fake_session.instances) >= 2)
    await feed.stop()
    assert fetch.await_count >= 2
    assert [i.kwargs["cloud_session"]["sessionId"] for i in fake_session.instances[:2]] == ["first", "second"]


@pytest.mark.asyncio
async def test_no_config_is_fetched_when_the_robot_is_unreachable(hass, fake_session):
    fetch = AsyncMock(return_value=_RTC)
    feed = P2PMapFeed(
        hass, host="192.168.1.50", local_key="0123456789abcdef", device_id="dev",
        rtc_config=fetch, is_active=lambda: False, on_change=lambda _c: None, name="S1 Pro",
    )
    with patch.object(P2PMapFeed, "_robot_reachable", AsyncMock(return_value=False)):
        feed.start()
        await _until(lambda: feed.failures >= 1)
    await feed.stop()
    fetch.assert_not_awaited()
    assert "not reachable" in feed.last_error
    assert not fake_session.instances


@pytest.mark.asyncio
@pytest.mark.parametrize(("error", "failures", "cooldown"), [
    (OSError("unreachable"), 3, p2p_map._FAILURE_COOLDOWN),
    (P2PRefused("robot sent disconnect"), 1, p2p_map.REFUSAL_COOLDOWN),
])
async def test_activity_changes_cannot_bypass_failure_cooldowns(hass, fake_session, error, failures, cooldown):
    fake_session.script = [error] * 10
    waiting = asyncio.Event()
    release = asyncio.Event()
    real_sleep = asyncio.sleep

    async def sleep(delay):
        if delay >= cooldown - 5:  # the refusal deadline has ticked a little by now
            waiting.set()
            await release.wait()
        else:
            await real_sleep(delay)

    with patch.object(p2p_map, "_ACTIVE_RETRY", 0.001), patch.object(p2p_map.asyncio, "sleep", sleep):
        feed = _feed(hass, active=True)
        feed.start()
        try:
            await asyncio.wait_for(waiting.wait(), 2)
            feed.poke()
            await real_sleep(0.01)
            assert feed.failures == failures
            assert feed._rtc_config.await_count == failures
        finally:
            await feed.stop()


@pytest.mark.asyncio
async def test_the_map_session_holds_the_slot_so_the_camera_cannot_overlap_it(hass, fake_session):
    seen: list[bool] = []
    feed = _feed(hass, active=False)

    async def run(self):
        seen.append(feed.session_slot.locked())

    fake_session.run = run
    fake_session.script = [[]]
    feed.start()
    await _until(lambda: seen)
    await feed.stop()
    assert seen == [True]
    assert not feed.session_slot.locked()


@pytest.mark.asyncio
async def test_the_camera_can_take_the_slot_from_a_long_running_map_session(hass, fake_session):
    """A faulted robot never ends its map session, so the camera has to be able to preempt it."""
    ended = asyncio.Event()

    async def run(self):
        self.on_object("navPath.bin", _pose_obj(1, 2, 3))  # connected: it can be asked to yield
        await ended.wait()  # a session that never ends by itself

    async def close(self):
        ended.set()
        self.closed = True

    fake_session.run, fake_session.close = run, close
    fake_session.script = [[]]
    feed = _feed(hass, active=False)
    feed.start()
    await _until(feed.session_slot.locked)
    await feed.acquire_slot(2.0)  # must not time out
    assert feed.session_slot.locked() and fake_session.instances[0].closed
    feed.release_slot()
    await feed.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize(("activity", "charging", "docked"), [("idle", False, False), ("docked", False, True), ("idle", True, True)])
async def test_idle_off_dock_uses_the_actual_pose(hass, activity, charging, docked):
    coordinator = _local_coordinator(hass)
    coordinator.data = replace(coordinator.data, activity=activity, charging=charging)
    coordinator.p2p = _feed(hass)
    coordinator.p2p.decoder.state = P2PMap(
        map_id=1, width=4, height=3, outline=bytes([2] * 12),
        pose=Pose(5, 5, 100), docks=[Pose(0, 0, 0)],
    )
    coordinator._map_data = build_map_data(coordinator.p2p.state)
    coordinator._async_save_map_image = AsyncMock()
    with patch("custom_components.robovac_mqtt.coordinator.build_overlay", wraps=build_overlay) as overlay:
        await coordinator._async_rerender_map()
    assert overlay.call_args.kwargs["docked"] is docked


@pytest.mark.asyncio
async def test_a_session_that_delivered_objects_is_a_normal_end_even_when_it_raises(hass, fake_session):
    """A docked robot closes the session ~15 s after the map arrives (an error here).

    Those ends must not count towards the quick-failure cooldown, or after a few
    docked refreshes the feed sleeps 30 minutes and ignores poke().
    """
    pose = [("navPath.bin", _pose_obj(1, 2, 3))]
    fake_session.script = [(pose, P2PError("robot closed the session"))] * 5
    feed = _feed(hass)  # idle: only poke() or the 15 min timer starts a session
    feed.start()
    for n in range(1, 5):
        await _until(lambda n=n: feed.sessions == n)
        feed.poke()
    await _until(lambda: feed.sessions == 5)
    await feed.stop()
    assert feed._failures_in_a_row == 0 and feed.failures == 0


@pytest.mark.asyncio
async def test_sessions_that_never_connect_still_count_towards_the_cooldown(hass, fake_session):
    fake_session.script = [P2PError("closed before any object")] * 10
    with patch.object(p2p_map, "_ACTIVE_RETRY", 0.001):
        feed = _feed(hass, active=True)
        feed.start()
        await _until(lambda: feed._failures_in_a_row >= p2p_map._MAX_QUICK_FAILURES)
        await feed.stop()


@pytest.mark.asyncio
async def test_a_refusal_noted_by_the_camera_holds_the_map_feed_off(hass, fake_session):
    """One refusal deadline per robot: the poke after a refused camera session is not a licence to knock."""
    waits: list[float] = []
    release = asyncio.Event()
    real_sleep = asyncio.sleep

    async def sleep(delay):
        if delay > 100:
            waits.append(delay)
            await release.wait()
        else:
            await real_sleep(delay)

    feed = _feed(hass, active=True)
    feed.note_refusal()
    with patch.object(p2p_map.asyncio, "sleep", sleep):
        feed.start()
        await _until(lambda: waits)
        feed.poke()
        await real_sleep(0.02)
        await feed.stop()
    assert waits[0] > p2p_map.REFUSAL_COOLDOWN - 5
    assert not fake_session.instances
    feed._rtc_config.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_refused_map_session_sets_the_shared_deadline(hass, fake_session):
    fake_session.script = [P2PRefused("robot sent disconnect")]
    release = asyncio.Event()
    real_sleep = asyncio.sleep

    async def sleep(delay):
        if delay > 100:
            await release.wait()
        else:
            await real_sleep(delay)

    feed = _feed(hass, active=True)
    with patch.object(p2p_map.asyncio, "sleep", sleep):
        feed.start()
        await _until(lambda: feed.failures == 1)
        await real_sleep(0)
        assert p2p_map.REFUSAL_COOLDOWN - 5 < feed.refusal_remaining() <= p2p_map.REFUSAL_COOLDOWN
        await feed.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("version", [3.4, 3.5])
async def test_no_p2p_feed_for_tuya_versions_the_signalling_cannot_speak(hass, fake_session, version):
    """3.4/3.5 framing is unsupported: every attempt would reserve a robot session and fail."""
    coordinator = _local_coordinator(hass, local_version=version)
    coordinator._start_p2p_feed()
    assert coordinator.p2p is None
    coordinator.eufy_login.get_rtc_config.assert_not_awaited()


@pytest.mark.asyncio
async def test_station_state_flips_do_not_poke_the_feed(hass, fake_session):
    """At the station the raw state moves between wash and charge; the activity stays docked."""
    coordinator = _local_coordinator(hass)
    coordinator._start_p2p_feed()
    coordinator.data = replace(coordinator.data, activity="docked")
    coordinator.p2p.poke = MagicMock()
    with patch(
        "custom_components.robovac_mqtt.coordinator.update_state",
        return_value=(replace(coordinator.data, status_code=9), {"activity": "docked", "status_code": 9}),
    ):
        coordinator._handle_mqtt_message(b'{"payload": {"data": {"153": "x"}}}')
    coordinator.p2p.poke.assert_not_called()
    await coordinator.async_stop_p2p()


def _targeted_state() -> P2PMap:
    return P2PMap(
        map_id=1, width=4, height=3, outline=bytes([2] * 12),
        rooms=[{"id": 0, "name": "Kitchen"}, {"id": 2, "name": "Hall"}],
        target_room_ids=[2], target_zones=[[(0, 0), (10, 0), (10, 10), (0, 10)]],
    )


@pytest.mark.parametrize(("cleaning", "rooms", "zones"), [(True, {2}, 1), (False, set(), 0)])
def test_stale_targets_are_drawn_only_while_a_clean_runs(cleaning, rooms, zones):
    """The robot never clears its last targets, so they must not dim rooms once the clean is over."""
    state = _targeted_state()
    overlay = build_overlay(build_map_data(state), state, cleaning=cleaning)
    assert set(overlay.target_rooms) == rooms
    assert len(overlay.target_zones) == zones


@pytest.mark.asyncio
async def test_the_coordinator_passes_whether_a_clean_is_running(hass):
    coordinator = _local_coordinator(hass)
    coordinator.data = replace(coordinator.data, activity="docked")
    coordinator.p2p = _feed(hass)
    coordinator.p2p.decoder.state = _targeted_state()
    coordinator._map_data = build_map_data(coordinator.p2p.state)
    coordinator._async_save_map_image = AsyncMock()
    with patch("custom_components.robovac_mqtt.coordinator.build_overlay", wraps=build_overlay) as overlay:
        await coordinator._async_rerender_map()
        coordinator.data = replace(coordinator.data, activity="cleaning")
        await coordinator._async_rerender_map()
    assert [c.kwargs["cleaning"] for c in overlay.call_args_list] == [False, True]


@pytest.mark.asyncio
@pytest.mark.parametrize("reason", ["refused", "yield", "stopping"])
async def test_a_queued_session_steps_aside_if_things_changed_while_waiting_for_the_slot(hass, fake_session, reason):
    """Nothing may be reserved on the robot after the refusal/yield/unload that happened in the queue."""
    feed = _feed(hass, active=True)
    if reason == "refused":
        feed.note_refusal()
    elif reason == "yield":
        feed._yield_requested.set()
    else:
        feed.begin_stop()
    await feed._run_session()
    feed._rtc_config.assert_not_awaited()
    assert not fake_session.instances


@pytest.mark.asyncio
async def test_current_room_comes_from_the_p2p_pose_on_local_tuya_robots(hass):
    """There is no MQTT pose stream here, so the sensor must resolve the room from the P2P pose."""
    coordinator = _local_coordinator(hass)
    coordinator.p2p = _feed(hass)
    # 4x3 grid, room 0 (Kitchen) on the left half, room 1 on the right.
    outline = bytes(((0 if x < 2 else 1) << 2) | 2 for _y in range(3) for x in range(4))
    coordinator.p2p.decoder.state = P2PMap(
        map_id=1, width=4, height=3, outline=outline, origin_x=0, origin_y=0,
        rooms=[{"id": 0, "name": "Kitchen"}, {"id": 1, "name": "Hall"}],
        pose=Pose(5, 5, 0),  # world cm -> grid cell (1, 1) at 5 cm per cell
    )
    coordinator._map_data = build_map_data(coordinator.p2p.state)
    assert coordinator.current_room() == (0, "Kitchen")  # room 0 is a real room
    coordinator.p2p.decoder.state.pose = Pose(16, 5, 0)
    assert coordinator.current_room() == (1, "Hall")


@pytest.mark.asyncio
async def test_a_release_poke_while_queued_does_not_cause_a_second_session(hass, fake_session):
    feed = _feed(hass)  # idle
    await feed.acquire_slot(1)  # the camera holds the slot
    feed.start()
    await asyncio.sleep(0.05)  # the supervisor is queued behind it
    feed.release_slot()  # pokes
    await asyncio.sleep(0.3)
    await feed.stop()
    assert feed.sessions == 1


@pytest.mark.asyncio
async def test_stepping_aside_does_not_wipe_a_failure_streak(hass, fake_session):
    feed = _feed(hass)
    feed._failures_in_a_row = 2
    feed.last_error = "boom"
    feed.note_refusal()
    assert await feed._run_session() is False
    # the supervisor only does its success bookkeeping when a session ran
    fake_session.script = [[]]
    feed._refused_until = 0.0
    assert await feed._run_session() is True


@pytest.mark.asyncio
async def test_a_camera_request_during_the_config_fetch_does_not_waste_the_reservation(hass, fake_session):
    """The yield is honoured only once the session has connected, not before it has used its config."""
    fetching = asyncio.Event()
    go = asyncio.Event()
    connected_before_close = []

    async def slow_rtc():
        fetching.set()
        await go.wait()
        return _RTC

    async def run(self):
        await asyncio.sleep(0.05)
        self.on_object("navPath.bin", _pose_obj(1, 2, 3))
        await asyncio.sleep(10)

    async def close(self):
        connected_before_close.append(feed.connected)

    fake_session.run, fake_session.close = run, close
    feed = _feed(hass)
    feed._rtc_config = slow_rtc
    feed.start()
    await fetching.wait()
    camera = asyncio.ensure_future(feed.acquire_slot(3))  # arrives mid-fetch
    await asyncio.sleep(0.01)
    go.set()
    await asyncio.wait_for(camera, 3)
    assert connected_before_close == [True]  # the session ran before it yielded
    feed.release_slot()
    await feed.stop()


@pytest.mark.parametrize(("model", "transport", "expected"), [
    ("T2080A", "local", True), ("T2080A", "cloud", True), ("T2080A", "mqtt", False),
    ("T2351", "local", False), ("T2080", "cloud", False),
])
def test_string_suction_and_boost_dps_are_only_for_verified_s1_pro_robots(hass, model, transport, expected):
    coordinator = _local_coordinator(hass)
    coordinator.device_model, coordinator.connection_type = model, transport
    assert coordinator.tuya_transport is expected
