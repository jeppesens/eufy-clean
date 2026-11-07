"""Unit tests for the map websocket commands (see docs/MAP_WS_CONTRACT.md).

Two things here are load-bearing beyond "the command answers":

* **The ``from`` cursor must stay contiguous.** A client whose local trail length
  disagrees with an event's ``from`` is specified to throw away its state and
  re-fetch geometry, so an off-by-one in the throttle's batching is not a cosmetic
  bug — it makes the map flicker back to a snapshot under load.
* **The call sites must actually call the notifiers.** The fan-out is invisible
  from the coordinator's own behaviour (nothing else reads ``_map_listeners``), so
  a refactor can drop a ``_notify_map_*`` line with every other test still green.
  ``TestCallSitesFireNotifiers`` is the only thing that would catch it.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import replace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.components import websocket_api
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.robovac_mqtt.api.map_stream import MapData
from custom_components.robovac_mqtt.const import CONF_TRAIL_COLOR, DOMAIN
from custom_components.robovac_mqtt.coordinator import EufyCleanCoordinator
from custom_components.robovac_mqtt.models import VacuumState
from custom_components.robovac_mqtt.websocket_api import (
    DATA_WS_REGISTERED,
    ERR_NO_MAP,
    _coordinator_for_entity,
    _find_coordinator,
    async_setup,
    ws_map_geometry,
    ws_map_subscribe,
)

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


# ws_map_geometry is registered through @websocket_api.async_response, which
# hands the real coroutine to hass.async_create_background_task and returns None.
# There is no hass here to run it, so the tests drive the coroutine itself; the
# registration tests below check the decorated function is what is registered.
_ws_map_geometry = ws_map_geometry.__wrapped__


@pytest.fixture(name="mock_hass")
def fixture_mock_hass():
    """Mock the Home Assistant object (hass.data is a real dict)."""
    hass = MagicMock()
    hass.data = {}

    def _close_task(coro, *_args, **_kwargs):
        # The coordinator fires render/save tasks we do not run here; closing the
        # coroutine keeps pytest from reporting "was never awaited".
        if hasattr(coro, "close"):
            coro.close()
        return MagicMock()

    hass.async_create_task = _close_task

    async def _executor(func, *args, **kwargs):
        # ws_map_geometry builds the static layer in an executor; run it inline.
        return func(*args, **kwargs)

    hass.async_add_executor_job = _executor
    return hass


@pytest.fixture(name="mock_login")
def fixture_mock_login():
    """Mock the EufyLogin object."""
    login = MagicMock()
    login.openudid = "test_udid"
    return login


def _make_map(width: int = 4, height: int = 3) -> MapData:
    """A tiny all-floor map — enough for build_map_geometry to produce a payload."""
    cells = width * height
    return MapData(
        raw_pixels=bytes([0b10101010]) * ((cells + 3) // 4),
        width=width,
        height=height,
        origin_x=-100,
        origin_y=-50,
        resolution=5,
        room_names={0: "Hallway", 1: "Kitchen"},
    )


def _make_coordinator(hass, login, device_id: str = "dev1") -> EufyCleanCoordinator:
    """Build a coordinator without touching MQTT or the DPS parser."""
    device_info = {
        "deviceId": device_id,
        "deviceModel": "T2118",
        "deviceName": f"Vac {device_id}",
        "dps": {},
    }
    with patch(
        "custom_components.robovac_mqtt.coordinator.update_state"
    ) as mock_update:
        mock_update.return_value = (VacuumState(), {})
        return EufyCleanCoordinator(hass, login, device_info)


def _register(hass, *coordinators, entry_id: str = "entry1") -> None:
    """Put coordinators into hass.data the way async_setup_entry does."""
    hass.data.setdefault(DOMAIN, {})[entry_id] = {"coordinators": list(coordinators)}


def _only(items: list[Any]) -> Any:
    """The single entry of ``items``; fails unless there is exactly one."""
    assert len(items) == 1, items
    return items[0]


class FakeConnection:
    """Minimal stand-in for websocket_api.ActiveConnection."""

    def __init__(self) -> None:
        self.subscriptions: dict[int, Any] = {}
        self.results: list[tuple[int, Any]] = []
        self.errors: list[tuple[int, str, str]] = []
        self.messages: list[Any] = []

    def send_result(self, msg_id: int, result: Any = None) -> None:
        self.results.append((msg_id, result))

    def send_error(self, msg_id: int, code: str, message: str) -> None:
        self.errors.append((msg_id, code, message))

    def send_message(self, message: Any) -> None:
        self.messages.append(message)

    @property
    def events(self) -> list[dict[str, Any]]:
        """The event payloads that reached the client, in order."""
        return [m["event"] for m in self.messages]


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def test_async_setup_registers_both_commands(mock_hass):
    """Both contract commands land in the websocket registry."""
    with patch.object(websocket_api, "async_register_command") as register:
        async_setup(mock_hass)
    assert register.call_count == 2
    registered = {call.args[1] for call in register.call_args_list}
    assert registered == {ws_map_geometry, ws_map_subscribe}
    assert mock_hass.data[DOMAIN][DATA_WS_REGISTERED] is True


def test_async_setup_is_idempotent_for_two_devices(mock_hass, mock_login):
    """A second config entry must not re-register (that raises in HA core)."""
    with patch.object(websocket_api, "async_register_command") as register:
        async_setup(mock_hass)
        async_setup(mock_hass)
        async_setup(mock_hass)
    assert register.call_count == 2  # not 6


async def test_registration_flag_does_not_confuse_device_lookup(mock_hass, mock_login):
    """The flag shares hass.data[DOMAIN] with the entries; lookup must skip it."""
    with patch.object(websocket_api, "async_register_command"):
        async_setup(mock_hass)
    coordinator = _make_coordinator(mock_hass, mock_login)
    coordinator._map_data = _make_map()
    _register(mock_hass, coordinator)

    connection = FakeConnection()
    await _ws_map_geometry(mock_hass, connection, {"id": 1, "device_id": "dev1"})
    assert not connection.errors
    assert connection.results


# ---------------------------------------------------------------------------
# robovac_mqtt/map/geometry
# ---------------------------------------------------------------------------


async def test_geometry_returns_payload(mock_hass, mock_login):
    """The snapshot carries the contract's fields, including live positions."""
    coordinator = _make_coordinator(mock_hass, mock_login)
    coordinator._map_data = _make_map()
    # map_revision is the PNG frame token; the snapshot must carry the GEOMETRY
    # revision, which is what the client keys its cached static layer on.
    coordinator.map_revision = 99
    coordinator.map_geometry_revision = 7
    coordinator._dock_pixel = (1, 1)
    coordinator._robot_pixel = (2, 2)
    coordinator._robot_trail = [(1, 1), (2, 1), (2, 2)]
    coordinator._robot_trail_types = [1, 0, 1]
    mock_hass.config_entries.async_get_entry.return_value = MagicMock(
        options={CONF_TRAIL_COLOR: [10, 20, 30]}
    )
    _register(mock_hass, coordinator)

    connection = FakeConnection()
    await _ws_map_geometry(mock_hass, connection, {"id": 5, "device_id": "dev1"})

    assert not connection.errors
    msg_id, payload = _only(connection.results)
    assert msg_id == 5
    assert payload["v"] == 3
    assert payload["revision"] == 7
    assert payload["width"] == 4
    assert payload["height"] == 3
    assert payload["origin_x"] == -100
    assert payload["resolution"] == 5
    assert payload["dock"] == [1, 1]
    assert payload["robot"] == [2, 2]
    assert payload["trail"] == [[1, 1], [2, 1], [2, 2]]
    assert payload["trail_types"] == [1, 0, 1]
    assert payload["trail_color"] == [10, 20, 30]
    # trail_seq is the length of the trail shipped in the snapshot, so the next
    # event's "from" lines up with what the client just installed.
    assert payload["trail_seq"] == 3
    assert payload["rooms"] == [{"id": 0, "name": "Hallway"}, {"id": 1, "name": "Kitchen"}]
    assert isinstance(payload["occupancy"], str)
    assert isinstance(payload["rooms_grid"], str)


async def test_geometry_unknown_device_errors(mock_hass, mock_login):
    """An unknown device id is ERR_NOT_FOUND, not an exception."""
    coordinator = _make_coordinator(mock_hass, mock_login)
    coordinator._map_data = _make_map()
    _register(mock_hass, coordinator)

    connection = FakeConnection()
    await _ws_map_geometry(mock_hass, connection, {"id": 9, "device_id": "nope"})

    assert not connection.results
    msg_id, code, message = _only(connection.errors)
    assert msg_id == 9
    assert code == websocket_api.const.ERR_NOT_FOUND
    assert "nope" in message


async def test_geometry_no_map_yet_errors_distinctly(mock_hass, mock_login):
    """A known device with nothing decoded gets its own code, not NOT_FOUND.

    The client retries this one; a NOT_FOUND means it addressed the wrong device.
    """
    coordinator = _make_coordinator(mock_hass, mock_login)
    assert coordinator._map_data is None
    _register(mock_hass, coordinator)

    connection = FakeConnection()
    await _ws_map_geometry(mock_hass, connection, {"id": 3, "device_id": "dev1"})

    assert not connection.results
    msg_id, code, _message = _only(connection.errors)
    assert msg_id == 3
    assert code == ERR_NO_MAP
    assert code != websocket_api.const.ERR_NOT_FOUND


async def test_geometry_flushes_pending_events_first(mock_hass, mock_login):
    """flush_map_events runs BEFORE the live half of the snapshot is taken.

    Otherwise the snapshot's trail_seq and the next event's "from" straddle a
    pending batch and the client sees a phantom gap. The static half is built in
    an executor and its content does not depend on the trail, so it may (and now
    does) run first — what must not slip past the flush is the pose/trail read.
    """
    coordinator = _make_coordinator(mock_hass, mock_login)
    coordinator._map_data = _make_map()
    _register(mock_hass, coordinator)

    order: list[str] = []
    real_flush = coordinator.flush_map_events
    with patch.object(
        coordinator,
        "flush_map_events",
        side_effect=lambda: (order.append("flush"), real_flush())[1],
    ):
        with patch(
            "custom_components.robovac_mqtt.websocket_api.build_map_dynamic",
            side_effect=lambda *a, **k: order.append("dynamic") or {},
        ):
            await _ws_map_geometry(mock_hass, FakeConnection(), {"id": 1, "device_id": "dev1"})

    assert order == ["flush", "dynamic"]


async def test_geometry_snapshot_and_next_from_are_contiguous(mock_hass, mock_login):
    """A snapshot taken with a batch pending hands out a matching cursor."""
    coordinator = _make_coordinator(mock_hass, mock_login)
    coordinator._map_data = _make_map(width=40, height=40)
    _register(mock_hass, coordinator)

    connection = FakeConnection()
    ws_map_subscribe(mock_hass, connection, {"id": 1, "device_id": "dev1"})

    # Points arrive and are coalesced (the flush timer has not fired).
    coordinator._last_map_event = _far_future_monotonic()
    coordinator._robot_trail.extend([(1, 1), (2, 2)])
    coordinator._notify_map_trail()

    # Snapshot now: the flush inside the command must drain that batch.
    geo_conn = FakeConnection()
    await _ws_map_geometry(mock_hass, geo_conn, {"id": 2, "device_id": "dev1"})
    _id, payload = _only(geo_conn.results)
    assert payload["trail_seq"] == 2

    # ... and the very next append continues from exactly that cursor.
    coordinator._last_map_event = 0.0
    coordinator._robot_trail.append((3, 3))
    coordinator._notify_map_trail()
    trail_events = [e for e in connection.events if e["t"] == "trail"]
    assert trail_events[-1]["from"] == payload["trail_seq"]


async def test_fractional_cells_match_between_events_and_snapshot(
    mock_hass, mock_login
):
    """Legacy cells are fractional: events and snapshot ship the same 2 dp value.

    The client draws at ``p + 0.5`` either way, so a snapshot that truncated what
    the events sent would shift the dot and the trail on every re-fetch.
    """
    coordinator = _make_coordinator(mock_hass, mock_login)
    coordinator._map_data = _make_map(width=40, height=40)
    _register(mock_hass, coordinator)
    connection = FakeConnection()
    ws_map_subscribe(mock_hass, connection, {"id": 1, "device_id": "dev1"})

    coordinator._robot_pixel = (25.678, 18.7)
    coordinator._dock_pixel = (20.256, 20.0)
    coordinator._last_map_event = 0.0
    coordinator._notify_map_pose()
    coordinator._robot_trail.append((25.678, 18.7))
    coordinator._last_map_event = 0.0
    coordinator._notify_map_trail()
    coordinator._robot_trail[:] = [(26.7, 17.704)]
    coordinator._last_map_event = 0.0
    coordinator._notify_map_trail_reset()

    pose, append, reset = connection.events
    assert pose == {"t": "pose", "robot": [25.68, 18.7], "dock": [20.26, 20.0]}
    assert append["p"] == [[25.68, 18.7]]
    assert reset["p"] == [[26.7, 17.7]]

    geo = FakeConnection()
    await _ws_map_geometry(mock_hass, geo, {"id": 2, "device_id": "dev1"})
    _id, payload = _only(geo.results)
    assert payload["robot"] == pose["robot"]
    assert payload["dock"] == pose["dock"]
    assert payload["trail"] == reset["p"]


async def test_concurrent_snapshots_at_one_revision_share_one_build(
    mock_hass, mock_login
):
    """Every subscriber re-fetches on the same geometry event; one build serves all."""
    coordinator = _make_coordinator(mock_hass, mock_login)
    coordinator._map_data = _make_map()
    coordinator.map_geometry_revision = 1
    _register(mock_hass, coordinator)
    builds = 0

    async def _executor(func, *args, **kwargs):
        nonlocal builds
        builds += 1
        await asyncio.sleep(0)  # an executor hop yields to the other requests
        return func(*args, **kwargs)

    mock_hass.async_add_executor_job = _executor
    connections = [FakeConnection() for _ in range(4)]
    await asyncio.gather(
        *(
            _ws_map_geometry(mock_hass, conn, {"id": i, "device_id": "dev1"})
            for i, conn in enumerate(connections)
        )
    )

    assert builds == 1
    payloads = [_only(conn.results)[1] for conn in connections]
    assert all(p["revision"] == 1 and p["occupancy"] for p in payloads)


# ---------------------------------------------------------------------------
# robovac_mqtt/map/subscribe
# ---------------------------------------------------------------------------


def test_subscribe_registers_and_results_immediately(mock_hass, mock_login):
    """The unsub goes into connection.subscriptions and the result comes first."""
    coordinator = _make_coordinator(mock_hass, mock_login)
    _register(mock_hass, coordinator)

    connection = FakeConnection()
    ws_map_subscribe(mock_hass, connection, {"id": 11, "device_id": "dev1"})

    assert connection.results == [(11, None)]
    assert 11 in connection.subscriptions
    assert callable(connection.subscriptions[11])
    assert len(coordinator._map_listeners) == 1

    connection.subscriptions[11]()
    assert not coordinator._map_listeners


def test_subscribe_unknown_device_errors(mock_hass, mock_login):
    """No subscription is created for a device that does not exist."""
    _register(mock_hass, _make_coordinator(mock_hass, mock_login))
    connection = FakeConnection()
    ws_map_subscribe(mock_hass, connection, {"id": 4, "device_id": "ghost"})

    assert connection.errors[0][1] == websocket_api.const.ERR_NOT_FOUND
    assert not connection.subscriptions
    assert not connection.results


def test_subscribe_does_not_need_a_map(mock_hass, mock_login):
    """Subscribing before the first map decode is legal — geometry tells it when."""
    coordinator = _make_coordinator(mock_hass, mock_login)
    assert coordinator._map_data is None
    _register(mock_hass, coordinator)

    connection = FakeConnection()
    ws_map_subscribe(mock_hass, connection, {"id": 1, "device_id": "dev1"})
    assert not connection.errors
    assert 1 in connection.subscriptions


def _far_future_monotonic() -> float:
    """A _last_map_event value that keeps the 2 Hz window firmly closed."""
    return time.monotonic() + 3600.0


def test_pose_trail_and_geometry_events_reach_the_subscriber(mock_hass, mock_login):
    """All three event kinds arrive wrapped in websocket event messages."""
    coordinator = _make_coordinator(mock_hass, mock_login)
    coordinator._map_data = _make_map()
    _register(mock_hass, coordinator)

    connection = FakeConnection()
    ws_map_subscribe(mock_hass, connection, {"id": 8, "device_id": "dev1"})

    coordinator._last_map_event = 0.0
    coordinator._robot_pixel = (2, 2)
    coordinator._dock_pixel = (1, 1)
    coordinator._notify_map_pose()

    coordinator._last_map_event = 0.0
    coordinator._robot_trail.append((2, 2))
    coordinator._notify_map_trail()

    # Geometry carries its OWN monotonic counter, not the PNG frame token.
    coordinator.map_revision = 12
    coordinator._set_map_data(_make_map())

    # Every message is addressed to this subscription's msg id.
    assert all(m["id"] == 8 and m["type"] == "event" for m in connection.messages)
    events = connection.events
    assert {"t": "pose", "robot": [2, 2], "dock": [1, 1]} in events
    assert {"t": "trail", "from": 0, "p": [[2, 2]], "types": [0]} in events
    assert {"t": "geometry", "revision": 1} in events


def test_geometry_event_suppressed_when_map_data_unchanged(mock_hass, mock_login):
    """A pose-only re-render bumps the revision but must not cost a refetch."""
    coordinator = _make_coordinator(mock_hass, mock_login)
    coordinator._map_data = _make_map()
    _register(mock_hass, coordinator)

    connection = FakeConnection()
    ws_map_subscribe(mock_hass, connection, {"id": 1, "device_id": "dev1"})

    coordinator._notify_map_geometry()  # first: the map is new to subscribers
    coordinator.map_revision += 1
    coordinator._notify_map_geometry()  # same MapData object -> silent

    geometry_events = [e for e in connection.events if e["t"] == "geometry"]
    assert len(geometry_events) == 1


def test_dock_is_only_sent_when_it_changes(mock_hass, mock_login):
    """"dock only when it changes" — it is static for most of a session."""
    coordinator = _make_coordinator(mock_hass, mock_login)
    _register(mock_hass, coordinator)
    connection = FakeConnection()
    ws_map_subscribe(mock_hass, connection, {"id": 1, "device_id": "dev1"})

    coordinator._dock_pixel = (1, 1)
    coordinator._robot_pixel = (1, 1)
    coordinator._last_map_event = 0.0
    coordinator._notify_map_pose()

    coordinator._robot_pixel = (2, 2)
    coordinator._last_map_event = 0.0
    coordinator._notify_map_pose()

    pose_events = [e for e in connection.events if e["t"] == "pose"]
    assert "dock" in pose_events[0]
    assert "dock" not in pose_events[1]


def test_trail_clear_emits_reset_from_zero(mock_hass, mock_login):
    """A cleared trail is a reset event, never a negative-length append."""
    coordinator = _make_coordinator(mock_hass, mock_login)
    _register(mock_hass, coordinator)
    connection = FakeConnection()
    ws_map_subscribe(mock_hass, connection, {"id": 1, "device_id": "dev1"})

    coordinator._robot_trail.extend([(1, 1), (2, 2), (3, 3)])
    coordinator._last_map_event = 0.0
    coordinator._notify_map_trail()
    assert connection.events[-1] == {"t": "trail", "from": 0, "p": [[1, 1], [2, 2], [3, 3]], "types": [0, 0, 0]}

    coordinator._robot_trail.clear()
    coordinator._robot_trail.append((9, 9))
    coordinator._last_map_event = 0.0
    coordinator._notify_map_trail_reset()

    assert connection.events[-1] == {
        "t": "trail",
        "from": 0,
        "reset": True,
        "p": [[9, 9]],
        "types": [0],
    }
    # The cursor was re-baselined, so the next append continues from 1.
    coordinator._robot_trail.append((10, 10))
    coordinator._last_map_event = 0.0
    coordinator._notify_map_trail()
    assert connection.events[-1] == {"t": "trail", "from": 1, "p": [[10, 10]], "types": [0]}


def test_shrunken_trail_without_a_reset_flag_is_treated_as_a_reset(mock_hass, mock_login):
    """A clear we never saw notified must not produce a negative-length append."""
    coordinator = _make_coordinator(mock_hass, mock_login)
    _register(mock_hass, coordinator)
    connection = FakeConnection()
    ws_map_subscribe(mock_hass, connection, {"id": 1, "device_id": "dev1"})

    coordinator._robot_trail.extend([(1, 1), (2, 2), (3, 3)])
    coordinator._last_map_event = 0.0
    coordinator._notify_map_trail()

    del coordinator._robot_trail[1:]  # silently shorter
    coordinator._last_map_event = 0.0
    coordinator._notify_map_trail()

    assert connection.events[-1] == {
        "t": "trail",
        "from": 0,
        "reset": True,
        "p": [[1, 1]],
        "types": [0],
    }


def test_from_cursor_stays_contiguous_across_batched_appends(mock_hass, mock_login):
    """Concatenating every event's points must reproduce the whole trail exactly."""
    coordinator = _make_coordinator(mock_hass, mock_login)
    _register(mock_hass, coordinator)
    connection = FakeConnection()
    ws_map_subscribe(mock_hass, connection, {"id": 1, "device_id": "dev1"})

    expected: list[list[int]] = []
    for batch in range(1, 6):
        for i in range(batch):
            point = (batch, i)
            coordinator._robot_trail.append(point)
            expected.append([batch, i])
            coordinator._notify_map_trail()  # notified per point, flushed per batch
        coordinator._last_map_event = 0.0
        coordinator.flush_map_events()
        coordinator._last_map_event = _far_future_monotonic()

    client: list[list[int]] = []
    for event in connection.events:
        assert event["t"] == "trail"
        assert event["from"] == len(client), "cursor gap — the client would resync"
        client.extend(event["p"])
    assert client == expected


def test_throttle_coalesces_without_losing_points(mock_hass, mock_login):
    """Points arriving inside the 2 Hz window are batched, never dropped."""
    coordinator = _make_coordinator(mock_hass, mock_login)
    _register(mock_hass, coordinator)
    connection = FakeConnection()
    ws_map_subscribe(mock_hass, connection, {"id": 1, "device_id": "dev1"})

    scheduled: list[Any] = []

    def _fake_call_later(_hass, _delay, action):
        scheduled.append(action)
        return MagicMock()

    coordinator._last_map_event = _far_future_monotonic()
    with patch(
        "custom_components.robovac_mqtt.coordinator.async_call_later",
        side_effect=_fake_call_later,
    ):
        for i in range(10):
            coordinator._robot_trail.append((i, i))
            coordinator._notify_map_trail()

    # Exactly one timer for the whole burst, and nothing sent yet.
    assert len(scheduled) == 1
    assert not connection.events

    coordinator._last_map_event = 0.0
    scheduled[0](None)  # the throttle timer fires

    (event,) = connection.events
    assert event["t"] == "trail"
    assert event["from"] == 0
    assert event["p"] == [[i, i] for i in range(10)]


def test_zero_subscribers_builds_no_payload(mock_hass, mock_login):
    """Every notifier returns before building anything while nobody is watching."""
    coordinator = _make_coordinator(mock_hass, mock_login)
    coordinator._map_data = _make_map()
    coordinator._robot_trail.extend([(1, 1), (2, 2)])
    coordinator._robot_pixel = (2, 2)

    with patch.object(coordinator, "_send_map_event") as send:
        with patch.object(coordinator, "_schedule_map_flush") as schedule:
            coordinator._notify_map_pose()
            coordinator._notify_map_trail()
            coordinator._notify_map_trail_reset()
            coordinator._notify_map_geometry()
    send.assert_not_called()
    schedule.assert_not_called()
    # No cursor state was touched either, so the first subscriber re-baselines.
    assert coordinator._map_trail_sent == 0
    assert coordinator._map_pose_dirty is False


def test_first_subscriber_rebaselines_the_cursor(mock_hass, mock_login):
    """A subscriber's first "from" matches the snapshot it fetches, not 0."""
    coordinator = _make_coordinator(mock_hass, mock_login)
    coordinator._robot_trail.extend([(1, 1), (2, 2), (3, 3)])  # grown while unwatched
    _register(mock_hass, coordinator)

    connection = FakeConnection()
    ws_map_subscribe(mock_hass, connection, {"id": 1, "device_id": "dev1"})
    assert coordinator._map_trail_sent == 3

    coordinator._robot_trail.append((4, 4))
    coordinator._last_map_event = 0.0
    coordinator._notify_map_trail()
    assert connection.events[-1] == {"t": "trail", "from": 3, "p": [[4, 4]], "types": [0]}


def test_two_subscribers_share_one_serialization(mock_hass, mock_login):
    """The payload dict is built once and handed to every listener."""
    coordinator = _make_coordinator(mock_hass, mock_login)
    _register(mock_hass, coordinator)
    conn_a, conn_b = FakeConnection(), FakeConnection()
    ws_map_subscribe(mock_hass, conn_a, {"id": 1, "device_id": "dev1"})
    ws_map_subscribe(mock_hass, conn_b, {"id": 2, "device_id": "dev1"})

    coordinator._robot_pixel = (5, 5)
    coordinator._last_map_event = 0.0
    coordinator._notify_map_pose()

    assert conn_a.events and conn_b.events
    assert conn_a.events[0] is conn_b.events[0]
    assert conn_a.messages[0]["id"] == 1
    assert conn_b.messages[0]["id"] == 2


def test_a_broken_subscriber_does_not_stall_the_others(mock_hass, mock_login):
    """One raising listener must not swallow the event for everyone else."""
    coordinator = _make_coordinator(mock_hass, mock_login)
    _register(mock_hass, coordinator)

    def _boom(_event):
        raise RuntimeError("client went away")

    coordinator.async_add_map_listener(_boom)
    connection = FakeConnection()
    ws_map_subscribe(mock_hass, connection, {"id": 1, "device_id": "dev1"})

    coordinator._robot_pixel = (1, 2)
    coordinator._last_map_event = 0.0
    coordinator._notify_map_pose()
    assert connection.events


async def test_lookup_spans_multiple_config_entries(mock_hass, mock_login):
    """Devices from a second entry are addressable too."""
    first = _make_coordinator(mock_hass, mock_login, "dev1")
    second = _make_coordinator(mock_hass, mock_login, "dev2")
    second._map_data = _make_map()
    _register(mock_hass, first, entry_id="entry1")
    _register(mock_hass, second, entry_id="entry2")

    connection = FakeConnection()
    await _ws_map_geometry(mock_hass, connection, {"id": 1, "device_id": "dev2"})
    assert not connection.errors
    assert connection.results[0][1]["width"] == 4


async def test_a_coordinator_in_teardown_is_not_found(mock_hass, mock_login):
    """Between ``gone`` and the entry's removal both commands answer not_found.

    A subscription accepted there would never get an event or a second ``gone``.
    """
    coordinator = _make_coordinator(mock_hass, mock_login)
    coordinator._map_data = _make_map()
    _register(mock_hass, coordinator)
    coordinator.async_shutdown_timers()

    connection = FakeConnection()
    ws_map_subscribe(mock_hass, connection, {"id": 1, "device_id": "dev1"})
    await _ws_map_geometry(mock_hass, connection, {"id": 2, "device_id": "dev1"})

    assert [(e[0], e[1]) for e in connection.errors] == [
        (1, websocket_api.const.ERR_NOT_FOUND),
        (2, websocket_api.const.ERR_NOT_FOUND),
    ]
    assert not connection.subscriptions
    assert not connection.results
    assert not coordinator._map_listeners


async def test_teardown_during_a_snapshot_build_is_not_found(mock_hass, mock_login):
    """A snapshot whose build outlived the start of teardown is not sent."""
    coordinator = _make_coordinator(mock_hass, mock_login)
    coordinator._map_data = _make_map()
    _register(mock_hass, coordinator)
    real_build = coordinator.async_map_static_geometry

    async def _build_then_teardown():
        built = await real_build()
        coordinator.async_shutdown_timers()
        return built

    connection = FakeConnection()
    with patch.object(
        coordinator, "async_map_static_geometry", side_effect=_build_then_teardown
    ):
        await _ws_map_geometry(mock_hass, connection, {"id": 3, "device_id": "dev1"})

    assert not connection.results
    assert _only(connection.errors)[:2] == (3, websocket_api.const.ERR_NOT_FOUND)


# ---------------------------------------------------------------------------
# The wired call sites
# ---------------------------------------------------------------------------


class TestCallSitesFireNotifiers:
    """Each place that mutates pose/trail/geometry must notify the fan-out.

    These are the assertions that catch a dropped ``_notify_map_*`` line: nothing
    else in the coordinator reads ``_map_listeners``, so the fan-out can be
    silently orphaned by a refactor with the whole rest of the suite green.
    """

    @staticmethod
    def _spy(coordinator) -> dict[str, MagicMock]:
        spies = {
            name: MagicMock()
            for name in (
                "_notify_map_pose",
                "_notify_map_trail",
                "_notify_map_trail_reset",
                "_notify_map_geometry",
            )
        }
        for name, spy in spies.items():
            setattr(coordinator, name, spy)
        return spies

    def test_legacy_pose_notifies(self, mock_hass, mock_login):
        """_on_legacy_pose moving the robot pixel is a pose event."""
        coordinator = _make_coordinator(mock_hass, mock_login)
        coordinator._map_data = MapData(
            raw_pixels=b"\x00" * 100,
            width=40,
            height=40,
            dock_pixel=(20, 20),
        )
        spies = self._spy(coordinator)
        coordinator._on_legacy_pose(10, 10, 0)
        spies["_notify_map_pose"].assert_called_once()

    def test_legacy_trail_append_notifies(self, mock_hass, mock_login):
        """_on_legacy_trail appending points is a trail event.

        Trail points are dock-relative in the same frame as the pose, so placement
        needs a dock cell and no anchor state at all.
        """
        coordinator = _make_coordinator(mock_hass, mock_login)
        coordinator._map_data = MapData(
            raw_pixels=b"\x00" * 100,
            width=40,
            height=40,
            dock_pixel=(20, 20),
        )
        coordinator.data = VacuumState(activity="cleaning")
        spies = self._spy(coordinator)
        coordinator._on_legacy_trail(1, [(10, 10, 0)])
        assert coordinator._robot_trail
        spies["_notify_map_trail"].assert_called_once()

    async def test_legacy_map_fetch_dock_notifies(self, mock_hass, mock_login):
        """The Tuya map blob's dock cell becomes the dock marker.

        The LIVE 0x75 dock then goes back on top of the blob's stale copy, or the
        pose transform (which reads the dock) reverts with it.
        """
        coordinator = _make_coordinator(mock_hass, mock_login)
        coordinator.api_type = "legacy"
        blob = MapData(raw_pixels=b"", width=40, height=40, dock_pixel=(20, 20))
        tuya_map = MagicMock()
        tuya_map.as_entity_rooms.return_value = coordinator.data.rooms
        coordinator._map_storage = MagicMock()
        coordinator._map_storage.async_fetch_map = AsyncMock(return_value=tuya_map)
        mock_hass.async_add_executor_job = AsyncMock(return_value=blob)
        coordinator._rerender_map = MagicMock()
        spies = self._spy(coordinator)
        dock_seen: list[Any] = []
        coordinator._apply_legacy_dock_pose = MagicMock(
            side_effect=lambda: dock_seen.append(coordinator._dock_pixel)
        )

        assert await coordinator._async_install_legacy_map(None) is True

        spies["_notify_map_pose"].assert_called_once()
        assert dock_seen == [(20, 20)]

    def test_new_session_clear_notifies_reset(self, mock_hass, mock_login):
        """A new cleaning session clears the trail -> reset + pose."""
        coordinator = _make_coordinator(mock_hass, mock_login)
        coordinator._map_data = _make_map()
        coordinator._robot_trail.extend([(1, 1), (2, 2)])
        coordinator._dock_arrival_time = None
        spies = self._spy(coordinator)

        coordinator._track_activity_change(
            "docked", VacuumState(activity="cleaning"), {"activity": "cleaning"}
        )
        spies["_notify_map_trail_reset"].assert_called_once()
        spies["_notify_map_pose"].assert_called_once()

    def test_dock_seed_point_notifies_trail(self, mock_hass, mock_login):
        """The dock point seeded into a fresh trail is an append like any other."""
        coordinator = _make_coordinator(mock_hass, mock_login)
        coordinator._map_data = _make_map()
        coordinator._dock_pixel = (3, 3)
        spies = self._spy(coordinator)

        coordinator._track_activity_change(
            "idle", VacuumState(activity="cleaning"), {"activity": "cleaning"}
        )
        assert coordinator._robot_trail == [(3, 3)]
        spies["_notify_map_trail"].assert_called_once()

    def test_docking_moves_the_robot_marker(self, mock_hass, mock_login):
        """Docking snaps a legacy robot's marker to the map's dock -> pose event."""
        coordinator = _make_coordinator(mock_hass, mock_login)
        coordinator.api_type = "legacy"
        coordinator._map_data = _make_map()
        coordinator._dock_pixel = (3, 3)
        spies = self._spy(coordinator)

        coordinator._track_activity_change(
            "cleaning", VacuumState(activity="docked"), {"activity": "docked"}
        )
        assert coordinator._robot_pixel == (3, 3)
        spies["_notify_map_pose"].assert_called_once()

    def test_dock_capture_notifies(self, mock_hass, mock_login):
        """Capturing the dock position for the first time is a pose event."""
        coordinator = _make_coordinator(mock_hass, mock_login)
        coordinator._map_data = _make_map()
        coordinator._robot_pixel = (2, 2)
        spies = self._spy(coordinator)

        coordinator._track_activity_change(
            "cleaning", VacuumState(activity="docked"), {"activity": "docked"}
        )
        assert coordinator._dock_pixel == (2, 2)
        spies["_notify_map_pose"].assert_called_once()

    def test_biz_pose_and_trail_notify(self, mock_hass, mock_login):
        """The novel biz/ pose path notifies both pose and trail."""
        coordinator = _make_coordinator(mock_hass, mock_login)
        coordinator._map_data = _make_map(width=40, height=40)
        coordinator.data = VacuumState(activity="cleaning")
        spies = self._spy(coordinator)

        with patch(
            "custom_components.robovac_mqtt.coordinator.parse_biz_protocol41",
            return_value=(1, "ab" * 10),
        ), patch(
            "custom_components.robovac_mqtt.coordinator.try_extract_map_description",
            return_value=None,
        ), patch(
            "custom_components.robovac_mqtt.coordinator.try_decode_as_dynamic_data",
            return_value=(0, 0),
        ):
            coordinator._handle_biz_message(b"x")

        assert coordinator._robot_pixel is not None
        spies["_notify_map_pose"].assert_called_once()
        spies["_notify_map_trail"].assert_called_once()

    async def test_render_does_not_notify_geometry(self, mock_hass, mock_login):
        """A PNG re-render is NOT a geometry event.

        map_revision is a frame token that also bumps on pose-only re-renders
        (~every 2 s while cleaning); geometry is published from _set_map_data
        instead. Tying the two would both spam viewers with refetches and make
        the lazy-PNG phase silently stop geometry updates altogether.
        """
        coordinator = _make_coordinator(mock_hass, mock_login)
        coordinator._map_data = _make_map()
        spies = self._spy(coordinator)

        async def _executor(func, *args):
            return b"png"

        mock_hass.async_add_executor_job = _executor
        mock_hass.config_entries.async_get_entry.return_value = None
        with patch("custom_components.robovac_mqtt.coordinator.async_dispatcher_send"):
            await coordinator._async_rerender_map()

        assert coordinator.map_revision == 1
        spies["_notify_map_geometry"].assert_not_called()

    @staticmethod
    async def test_set_map_data_notifies_geometry_once_per_change(
        mock_hass, mock_login
    ):
        """Geometry is content-gated: same map twice is one event, not two."""
        coordinator = _make_coordinator(mock_hass, mock_login)
        events: list[dict] = []
        coordinator.async_add_map_listener(events.append)

        coordinator._set_map_data(_make_map())
        assert coordinator.map_geometry_revision == 1
        assert [e["t"] for e in events] == ["geometry"]

        # Re-installing an identical map (the novel path reassigns _map_data on
        # EVERY frame) must not cost subscribers a refetch.
        coordinator._set_map_data(_make_map())
        assert coordinator.map_geometry_revision == 1
        assert len(events) == 1

        # A genuinely different grid does.
        changed = _make_map()
        changed.raw_pixels = bytes(len(changed.raw_pixels))
        coordinator._set_map_data(changed)
        assert coordinator.map_geometry_revision == 2
        assert [e["t"] for e in events] == ["geometry", "geometry"]
        assert events[-1]["revision"] == 2


# ---------------------------------------------------------------------------
# Addressing: entity_id vs the eufy device_id
# ---------------------------------------------------------------------------


class TestAddressing:
    """Two id spaces meet in these commands; conflating them matches no coordinator.

    ``coordinator.device_id`` is the EUFY id (``eb00112233445566778899``). Home
    Assistant's device registry keys on an unrelated UUID, which is what a browser
    sees as ``hass.entities[entity_id].device_id``. The card must send the eufy id
    or the ``entity_id``; the registry UUID as ``device_id`` matches no coordinator,
    and without a frontend registry entry the card has no id to send at all.
    """

    @staticmethod
    async def test_entity_id_resolves_through_the_device_registry(
        hass, mock_login
    ):
        entry = MockConfigEntry(domain=DOMAIN, entry_id="addr_entry")
        entry.add_to_hass(hass)
        device = dr.async_get(hass).async_get_or_create(
            config_entry_id=entry.entry_id,
            identifiers={(DOMAIN, "eufy-abc123")},
            name="Vac",
        )
        entity = er.async_get(hass).async_get_or_create(
            "vacuum", DOMAIN, "eufy-abc123-vac",
            config_entry=entry, device_id=device.id,
        )
        coordinator = _make_coordinator(hass, mock_login, device_id="eufy-abc123")
        hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
            "coordinators": [coordinator]
        }

        assert _coordinator_for_entity(hass, entity.entity_id) is coordinator

        # The HA device UUID is NOT the eufy id — sending it as device_id must not
        # resolve, which is exactly the failure the entity_id path exists to avoid.
        assert device.id != "eufy-abc123"
        assert _find_coordinator(hass, device.id) is None

    @staticmethod
    async def test_unknown_entity_is_not_found(hass, mock_login):
        assert _coordinator_for_entity(hass, "vacuum.does_not_exist") is None

    @staticmethod
    async def test_addressing_is_required(mock_hass, mock_login):
        """Neither form supplied is a client bug, not a missing device."""
        coordinator = _make_coordinator(mock_hass, mock_login)
        coordinator._map_data = _make_map()
        _register(mock_hass, coordinator)

        connection = FakeConnection()
        await _ws_map_geometry(mock_hass, connection, {"id": 1})
        assert connection.errors
        assert connection.errors[0][1] == websocket_api.const.ERR_INVALID_FORMAT

    @staticmethod
    async def test_device_id_still_addresses_directly(mock_hass, mock_login):
        """The eufy device id keeps working for scripted callers."""
        coordinator = _make_coordinator(mock_hass, mock_login, device_id="dev1")
        coordinator._map_data = _make_map()
        _register(mock_hass, coordinator)

        connection = FakeConnection()
        await _ws_map_geometry(mock_hass, connection, {"id": 2, "device_id": "dev1"})
        assert not connection.errors
        assert connection.results


class TestPreviousTrail:
    """A finished run is retained rather than dropped when the next clean starts."""

    @staticmethod
    async def test_geometry_snapshot_carries_the_previous_run(
        mock_hass, mock_login
    ):
        coordinator = _make_coordinator(mock_hass, mock_login)
        coordinator._map_data = _make_map()
        coordinator._previous_trail = [(4, 4), (5, 5)]
        _register(mock_hass, coordinator)

        connection = FakeConnection()
        await _ws_map_geometry(mock_hass, connection, {"id": 1, "device_id": "dev1"})
        _, payload = _only(connection.results)
        assert payload["prev_trail"] == [[4, 4], [5, 5]]

    @staticmethod
    async def test_a_live_trail_outranks_the_previous_run(mock_hass, mock_login):
        """Parked, the live slot still holds the last clean — that is the run to draw.

        A client draws at most one trail, so shipping both hands it a choice it
        cannot make: the two are drawn identically and would simply overlap.
        """
        coordinator = _make_coordinator(mock_hass, mock_login)
        coordinator._map_data = _make_map()
        coordinator._robot_trail = [(1, 1), (2, 2)]
        coordinator._previous_trail = [(4, 4), (5, 5)]
        _register(mock_hass, coordinator)

        connection = FakeConnection()
        await _ws_map_geometry(mock_hass, connection, {"id": 1, "device_id": "dev1"})
        _, payload = _only(connection.results)
        assert payload["trail"] == [[1, 1], [2, 2]]
        assert payload["prev_trail"] == []

    @staticmethod
    async def test_a_running_session_outranks_it_even_with_no_points_yet(
        mock_hass, mock_login
    ):
        """The first seconds of a clean, before the device publishes any point.

        This is the case that was reported: the live slot is empty, so the previous
        run was shipped and drawn — putting the last clean back on the map at the
        exact moment the new one started.
        """
        coordinator = _make_coordinator(mock_hass, mock_login)
        coordinator._map_data = _make_map()
        coordinator._robot_trail = []
        coordinator._previous_trail = [(4, 4), (5, 5)]
        coordinator.data = replace(coordinator.data, activity="cleaning")
        _register(mock_hass, coordinator)

        connection = FakeConnection()
        await _ws_map_geometry(mock_hass, connection, {"id": 1, "device_id": "dev1"})
        _, payload = _only(connection.results)
        assert payload["prev_trail"] == []


class TestConnectionTeardown:
    """A dropped browser must leave nothing fanning events at a dead socket.

    Home Assistant calls every entry of ``connection.subscriptions`` when a socket
    closes and then replaces ``send_message`` with a no-op, so our push path cannot
    outlive the connection. That is core's guarantee, not ours — this pins it,
    because a listener that survived would keep the coordinator building and
    fanning payloads forever, once per closed tab.
    """

    @staticmethod
    def test_close_removes_the_listener(mock_hass, mock_login):
        coordinator = _make_coordinator(mock_hass, mock_login)
        coordinator._map_data = _make_map()
        _register(mock_hass, coordinator)

        connection = FakeConnection()
        ws_map_subscribe(mock_hass, connection, {"id": 9, "device_id": "dev1"})
        assert len(coordinator._map_listeners) == 1

        # what ActiveConnection.async_handle_close does
        for unsub in connection.subscriptions.values():
            unsub()
        connection.subscriptions.clear()

        assert not coordinator._map_listeners

        # and nothing is queued for it afterwards
        before = len(connection.messages)
        coordinator._robot_pixel = (5, 5)
        coordinator._notify_map_pose()
        coordinator.flush_map_events()
        assert len(connection.messages) == before

    @staticmethod
    def test_close_cancels_the_pending_flush_timer(mock_hass, mock_login):
        """The 2 Hz timer must not outlive the last subscriber."""
        coordinator = _make_coordinator(mock_hass, mock_login)
        coordinator._map_data = _make_map()
        _register(mock_hass, coordinator)

        connection = FakeConnection()
        ws_map_subscribe(mock_hass, connection, {"id": 10, "device_id": "dev1"})
        coordinator._last_map_event = time.monotonic()  # force the timer path
        coordinator._robot_pixel = (7, 7)
        coordinator._notify_map_pose()
        assert coordinator._map_flush_cancel is not None

        for unsub in connection.subscriptions.values():
            unsub()
        assert coordinator._map_flush_cancel is None
