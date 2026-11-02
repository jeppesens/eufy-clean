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
from custom_components.robovac_mqtt.api.p2p import P2PRefused
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
        for name, obj in step:
            self.on_object(name, obj)
        await asyncio.sleep(0)

    async def close(self):
        self.closed = True


@pytest.fixture(autouse=True)
def fake_session():
    _FakeSession.script = []
    _FakeSession.instances = []
    with (
        patch.object(p2p_map, "P2PSession", _FakeSession),
        # No real sockets in tests: the robot counts as reachable.
        patch.object(P2PMapFeed, "_robot_reachable", AsyncMock(return_value=True)),
    ):
        yield _FakeSession


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


def _local_coordinator(hass) -> EufyCleanCoordinator:
    login = MagicMock()
    login.openudid = "udid"
    login.tuya_client = MagicMock()
    login.tuya_client.get_rtc_config = AsyncMock(return_value=_RTC)
    info = {
        "deviceId": "dev",
        "deviceModel": "T2080A",
        "deviceName": "S1 Pro",
        "connection_type": "local",
        "local_key": "0123456789abcdef",
        "local_host": "192.168.1.50",
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
    (P2PRefused("robot sent disconnect"), 1, p2p_map._REFUSAL_COOLDOWN),
])
async def test_activity_changes_cannot_bypass_failure_cooldowns(hass, fake_session, error, failures, cooldown):
    fake_session.script = [error] * 10
    waiting = asyncio.Event()
    release = asyncio.Event()
    real_sleep = asyncio.sleep

    async def sleep(delay):
        if delay >= cooldown:
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
