"""Unit tests for the map camera entity and the lazy PNG render behind it.

The render is LAZY: ``render_map_png`` costs ~83 ms of largely GIL-holding Python
for a ~208 KiB image, and a card in ``client_render`` mode never fetches it. So
nothing may render until the camera entity is actually read — which is what most
of this file pins down, since a regression here is invisible (the map still looks
right, it just costs a render per map frame again).
"""

# pylint: disable=redefined-outer-name, protected-access

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.robovac_mqtt.api.map_stream import MapData
from custom_components.robovac_mqtt.camera import FRAME_WRITE_INTERVAL, EufyMapCamera
from custom_components.robovac_mqtt.coordinator import EufyCleanCoordinator
from custom_components.robovac_mqtt.models import VacuumState


def _make_map(width: int = 4, height: int = 3) -> MapData:
    """A tiny all-floor map — enough to be a renderable map."""
    cells = width * height
    return MapData(
        raw_pixels=bytes([0b10101010]) * ((cells + 3) // 4),
        width=width,
        height=height,
        origin_x=-100,
        origin_y=-50,
        resolution=5,
    )


@pytest.fixture
def live_hass():
    """A hass mock whose task/executor plumbing actually runs on this event loop.

    ``MagicMock()`` is enough for most coordinator tests, but the lazy render is
    all about *when* tasks run, so the two calls it depends on have to be real.
    """
    hass = MagicMock()
    hass.async_create_task = lambda coro, *a, **kw: asyncio.ensure_future(coro)
    hass.config_entries.async_get_entry.return_value = None

    async def _executor(func, *args):
        return func(*args)

    hass.async_add_executor_job = _executor
    return hass


@pytest.fixture
def mock_login():
    login = MagicMock()
    login.openudid = "test_udid"
    login.checkLogin = AsyncMock()
    return login


def _coordinator(hass, login) -> EufyCleanCoordinator:
    device_info = {
        "deviceId": "dev1",
        "deviceModel": "T2118",
        "deviceName": "Test Vac",
        "dps": {},
    }
    with patch(
        "custom_components.robovac_mqtt.coordinator.update_state"
    ) as mock_update:
        mock_update.return_value = (VacuumState(), {})
        coordinator = EufyCleanCoordinator(hass, login, device_info)
    coordinator._store = MagicMock()
    coordinator._store.async_load = AsyncMock(return_value={})
    coordinator._store.async_save = AsyncMock()
    # The camera reads CONF_TRAIL_COLOR out of the config entry's options.
    coordinator.config_entry = MagicMock()
    coordinator.config_entry.options = {}
    return coordinator


def _mapped(hass, login) -> EufyCleanCoordinator:
    """A coordinator with a decoded map installed through the normal funnel."""
    coordinator = _coordinator(hass, login)
    coordinator._set_map_data(_make_map())
    return coordinator


# ── The render is lazy ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_map_change_does_not_render(live_hass, mock_login):
    """The whole point: a map/pose change costs no render at all."""
    coordinator = _mapped(live_hass, mock_login)

    with patch(
        "custom_components.robovac_mqtt.coordinator.render_map_png"
    ) as render, patch(
        "custom_components.robovac_mqtt.coordinator.async_dispatcher_send"
    ):
        for _ in range(5):
            coordinator._rerender_map()
        await asyncio.sleep(0)

    render.assert_not_called()
    assert coordinator.map_image is None


@pytest.mark.asyncio
async def test_map_change_still_bumps_map_revision(live_hass, mock_login):
    """``map_revision`` is the camera's cache key and the card's ``?v=``.

    If it only advanced when a render happened, every PNG-path card would freeze
    on a stale frame with no error anywhere — and with client rendering on, no
    render ever happens.
    """
    coordinator = _mapped(live_hass, mock_login)

    with patch(
        "custom_components.robovac_mqtt.coordinator.render_map_png"
    ) as render, patch(
        "custom_components.robovac_mqtt.coordinator.async_dispatcher_send"
    ) as dispatch:
        coordinator._rerender_map()
        coordinator._rerender_map()
        await asyncio.sleep(0)

    assert coordinator.map_revision == 2
    render.assert_not_called()
    # The camera must still learn there is a new frame to fetch.
    assert dispatch.call_count == 2
    assert dispatch.call_args[0][1] == "robovac_mqtt_dev1_map_updated"


@pytest.mark.asyncio
async def test_camera_read_renders_once_per_frame(live_hass, mock_login):
    """A read renders; a second read of the same frame serves the cache."""
    coordinator = _mapped(live_hass, mock_login)
    camera = EufyMapCamera(coordinator)

    with patch(
        "custom_components.robovac_mqtt.coordinator.render_map_png",
        return_value=b"PNG-1",
    ) as render, patch(
        "custom_components.robovac_mqtt.coordinator.async_dispatcher_send"
    ):
        coordinator._rerender_map()
        assert await camera.async_camera_image() == b"PNG-1"
        assert render.call_count == 1

        assert await camera.async_camera_image() == b"PNG-1"
        assert render.call_count == 1

        # A new frame invalidates the cache, and the next read re-renders.
        render.return_value = b"PNG-2"
        coordinator._rerender_map()
        assert await camera.async_camera_image() == b"PNG-2"
        assert render.call_count == 2


@pytest.mark.asyncio
async def test_concurrent_reads_share_one_render(live_hass, mock_login):
    """Two readers must not each start a render; the second joins the first."""
    coordinator = _mapped(live_hass, mock_login)
    camera = EufyMapCamera(coordinator)
    started = asyncio.Event()
    release = asyncio.Event()
    calls = 0

    async def _slow_executor(func, *args):
        nonlocal calls
        calls += 1
        started.set()
        await release.wait()
        return b"PNG"

    live_hass.async_add_executor_job = _slow_executor

    with patch("custom_components.robovac_mqtt.coordinator.async_dispatcher_send"):
        coordinator._rerender_map()
        first = asyncio.ensure_future(camera.async_camera_image())
        await started.wait()
        second = asyncio.ensure_future(camera.async_camera_image())
        await asyncio.sleep(0)
        release.set()
        assert await first == b"PNG"
        assert await second == b"PNG"

    assert calls == 1


@pytest.mark.asyncio
async def test_a_frame_that_went_stale_mid_render_is_redrawn(live_hass, mock_login):
    """Coalescing, not cancelling: one more pass, however many triggers arrive."""
    coordinator = _mapped(live_hass, mock_login)
    camera = EufyMapCamera(coordinator)
    started = asyncio.Event()
    release = asyncio.Event()
    calls = 0

    async def _slow_executor(func, *args):
        nonlocal calls
        calls += 1
        if calls == 1:
            started.set()
            await release.wait()
        return f"PNG-{calls}".encode()

    live_hass.async_add_executor_job = _slow_executor

    with patch("custom_components.robovac_mqtt.coordinator.async_dispatcher_send"):
        coordinator._rerender_map()
        first = asyncio.ensure_future(camera.async_camera_image())
        await started.wait()
        # Three more frames land while PIL is busy; they must cost ONE re-render.
        for _ in range(3):
            coordinator._rerender_map()
        second = asyncio.ensure_future(camera.async_camera_image())
        await asyncio.sleep(0)
        release.set()
        await first
        assert await second == b"PNG-2"

    assert calls == 2


@pytest.mark.asyncio
async def test_read_without_a_map_renders_nothing(live_hass, mock_login):
    """No map decoded yet: no render, and no bundled placeholder either."""
    coordinator = _coordinator(live_hass, mock_login)
    camera = EufyMapCamera(coordinator)

    with patch(
        "custom_components.robovac_mqtt.coordinator.render_map_png"
    ) as render:
        assert await camera.async_camera_image() is None

    render.assert_not_called()


@pytest.mark.asyncio
async def test_a_failed_render_serves_the_previous_frame(live_hass, mock_login):
    """A render that raises must not propagate into the camera response."""
    coordinator = _mapped(live_hass, mock_login)
    camera = EufyMapCamera(coordinator)
    coordinator.map_image = b"OLD"
    coordinator._map_frame_dirty = True

    async def _boom(func, *args):
        raise RuntimeError("PIL exploded")

    live_hass.async_add_executor_job = _boom

    assert await camera.async_camera_image() == b"OLD"


# ── The camera entity itself ────────────────────────────────────────


def test_camera_publishes_the_frame_token(live_hass, mock_login):
    """``entity_picture`` carries a rotating token, not a content hash."""
    coordinator = _mapped(live_hass, mock_login)
    camera = EufyMapCamera(coordinator)
    camera.async_write_ha_state = MagicMock()
    coordinator.map_revision = 7
    camera._handle_map_update()

    assert camera.extra_state_attributes == {
        "map_revision": 7,
        "trail_color": [255, 140, 0],  # CONF_TRAIL_COLOR default
    }
    assert camera.unique_id == "dev1_map"


def test_the_frame_token_stays_out_of_the_recorded_attributes(live_hass, mock_login):
    """It changes per written frame; the attributes JSON need not keep each value.

    Every write that changes it still adds a states row; the write throttle
    below bounds those.
    """
    camera = EufyMapCamera(_mapped(live_hass, mock_login))

    assert "map_revision" in camera.extra_state_attributes
    assert "map_revision" in camera._unrecorded_attributes


class _Clock:
    """A monotonic clock plus the async_call_later timers armed against it."""

    def __init__(self):
        self.now = 1000.0
        self.timers: list[list] = []

    def call_later(self, _hass, delay, action):
        timer = [self.now + delay, action]
        self.timers.append(timer)
        return lambda: timer in self.timers and self.timers.remove(timer)

    def advance(self, seconds):
        self.now += seconds
        for timer in [t for t in self.timers if t[0] <= self.now]:
            self.timers.remove(timer)
            timer[1](None)


def test_a_clean_writes_the_map_state_at_most_every_interval(live_hass, mock_login):
    """A pose re-render every 2 s: 1800 states rows per cleaning hour unthrottled.

    Writes are capped at one per FRAME_WRITE_INTERVAL (360 per hour), and the
    last frame of the clean is still written.
    """
    coordinator = _mapped(live_hass, mock_login)
    camera = EufyMapCamera(coordinator)
    camera.hass = live_hass
    written: list[int] = []
    camera.async_write_ha_state = lambda: written.append(
        camera.extra_state_attributes["map_revision"]
    )
    clock = _Clock()
    with patch(
        "custom_components.robovac_mqtt.camera.monotonic", lambda: clock.now
    ), patch(
        "custom_components.robovac_mqtt.camera.async_call_later", clock.call_later
    ), patch("custom_components.robovac_mqtt.coordinator.async_dispatcher_send"):
        for _ in range(3600 // 2):
            coordinator._rerender_map()
            camera._handle_map_update()
            # A coordinator update in between repeats the token it last wrote.
            camera._handle_coordinator_update()
            clock.advance(2)
        rows = len(set(written))
        clock.advance(FRAME_WRITE_INTERVAL)

    assert rows <= 3600 / FRAME_WRITE_INTERVAL + 1
    assert written[-1] == coordinator.map_revision, "the final frame is written"


@pytest.mark.asyncio
async def test_a_failed_render_leaves_the_frame_stale(live_hass, mock_login):
    """A frame that was not drawn must stay dirty, or nothing ever retries it."""
    coordinator = _mapped(live_hass, mock_login)
    camera = EufyMapCamera(coordinator)
    calls = 0

    async def _flaky(func, *args):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("PIL exploded")
        return b"PNG"

    live_hass.async_add_executor_job = _flaky

    with patch("custom_components.robovac_mqtt.coordinator.async_dispatcher_send"):
        coordinator._rerender_map()
        assert await camera.async_camera_image() is None
        assert coordinator._map_frame_dirty is True
        assert await camera.async_camera_image() == b"PNG"

    assert calls == 2
