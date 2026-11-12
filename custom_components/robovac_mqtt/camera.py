"""Camera platform for Eufy robot vacuum floor map."""
from __future__ import annotations

import logging
from collections.abc import Callable
from time import monotonic
from typing import Any

from homeassistant.components.camera import Camera, async_get_still_stream
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from ._orphan_cleanup import prune_orphan_entities
from .const import DOMAIN, WORK_STATE_REMOTE_CTRL
from .coordinator import EufyCleanCoordinator
from .entity import API_TYPE_NOVEL, filter_supported_entities
from .video_stream import RobotVideo

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 0

# A clean re-renders up to every 2 s, and each new frame token is a recorder row.
FRAME_WRITE_INTERVAL = 10.0


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Eufy map camera entities."""
    data = hass.data[DOMAIN][config_entry.entry_id]
    coordinators: list[EufyCleanCoordinator] = data["coordinators"]
    entities = []
    for coordinator in coordinators:
        # A map only arrives over Eufy MQTT, the local P2P feed or the legacy Tuya map.
        if coordinator.receives_map:
            entities.extend(
                filter_supported_entities(coordinator, [EufyMapCamera(coordinator)])
            )
        _add_video_camera_when_supported(config_entry, coordinator, async_add_entities)

    # Prune the map camera that older builds registered where no map arrives.
    # The live camera is added later, once P2P is up, so it is always kept.
    prune_orphan_entities(
        hass,
        config_entry.entry_id,
        coordinators,
        added_unique_ids={e.unique_id for e in entities if e.unique_id}
        | {_video_camera_unique_id(c) for c in coordinators},
        platform="camera",
    )

    async_add_entities(entities)


def _video_camera_unique_id(coordinator: EufyCleanCoordinator) -> str:
    return f"{coordinator.device_id}_camera"


def _add_video_camera_when_supported(
    config_entry: ConfigEntry,
    coordinator: EufyCleanCoordinator,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Add the live camera once the robot has told us it has one.

    Only robots with a camera report the video switch (DPS 176), and the local P2P
    link only exists once the Tuya session is up, so neither is known at setup.
    """
    if coordinator.api_type not in EufyVideoCamera.supported_api_types:
        return
    added = False
    unsub: Callable[[], None] | None = None

    @callback
    def _remove_listener() -> None:
        # Called when the camera is added and again on unload: only remove it once,
        # or the coordinator raises KeyError and the entry cannot be unloaded.
        nonlocal unsub
        if unsub is not None:
            unsub()
            unsub = None

    @callback
    def _check() -> None:
        nonlocal added
        if added or coordinator.p2p is None:
            return
        if "camera_enabled" not in coordinator.data.received_fields:
            return
        added = True
        _remove_listener()
        if coordinator.video is None:
            coordinator.video = RobotVideo(coordinator.hass, coordinator)
        async_add_entities([EufyVideoCamera(coordinator, coordinator.video)])

    unsub = coordinator.async_add_listener(_check)
    config_entry.async_on_unload(_remove_listener)
    _check()


class EufyMapCamera(CoordinatorEntity[EufyCleanCoordinator], Camera):
    """Camera entity that displays the robot's live floor map."""

    supported_api_types = (API_TYPE_NOVEL,)
    _attr_has_entity_name = True
    _attr_name = "Map"
    _attr_content_type = "image/png"
    # Kept out of the attributes JSON: the revision changes per frame and the pose
    # every ~2 s while cleaning. Each state write is still a states row, so frame
    # writes are throttled to FRAME_WRITE_INTERVAL.
    _unrecorded_attributes = frozenset({"map_revision", "robot"})

    def __init__(self, coordinator: EufyCleanCoordinator) -> None:
        CoordinatorEntity.__init__(self, coordinator)
        Camera.__init__(self)
        self._attr_unique_id = f"{coordinator.device_id}_map"
        self._attr_device_info = coordinator.device_info
        # The token last written; coordinator updates in between repeat it.
        self._published_revision = coordinator.map_revision
        self._last_frame_write = float("-inf")
        self._frame_write_cancel: CALLBACK_TYPE | None = None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Frame token, trail colour, calibration and the live rooms on the map.

        The camera's state string never changes, so publishing the revision is
        what makes the attributes differ per frame and gives clients an exact
        cache key instead of a timed cache-bust.
        """
        trail_color = self.coordinator.trail_color
        attrs: dict[str, Any] = {
            "map_revision": self._published_revision,
            "trail_color": list(trail_color) if trail_color else None,
        }
        if points := self.coordinator.calibration_points():
            attrs["calibration_points"] = points
        if rooms := self.coordinator.data.rooms:
            attrs["rooms"] = {str(r["id"]): r.get("name", "") for r in rooms}
        if self.coordinator.p2p is not None:
            state = self.coordinator.p2p.state
            if state.pose is not None:
                attrs["robot"] = {"x": state.pose.x, "y": state.pose.y, "theta": state.pose.theta}
            if state.dock is not None:
                attrs["dock"] = {"x": state.dock.x, "y": state.dock.y}
            # Objects the robot recognised on its last runs, in world centimetres.
            attrs["obstacles"] = [
                {"type": o.object_type, "x": o.points[0][0], "y": o.points[0][1]}
                for o in self.coordinator.p2p.state.obstacles
                if o.points
            ]
        return attrs

    async def async_camera_image(
        self, width: int | None = None, height: int | None = None
    ) -> bytes | None:
        """Return the map PNG, rendering it here if this frame has not been drawn.

        The render is lazy and only this read drives it: it is expensive and a
        client-rendering card never fetches it. The coordinator coalesces
        concurrent readers and caches unchanged frames.
        """
        return await self.coordinator.async_get_map_image()

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                f"{DOMAIN}_{self.coordinator.device_id}_map_updated",
                self._handle_map_update,
            )
        )
        self.async_on_remove(self._cancel_frame_write)

    @callback
    def _handle_map_update(self) -> None:
        """Publish a new frame now, or at the end of the write interval.

        Trailing edge: the last frame of a burst (the end of a clean) is always
        written.
        """
        wait = FRAME_WRITE_INTERVAL - (monotonic() - self._last_frame_write)
        if wait <= 0:
            self._write_frame()
        elif self._frame_write_cancel is None:
            self._frame_write_cancel = async_call_later(
                self.hass, wait, self._async_frame_write_due
            )

    @callback
    def _async_frame_write_due(self, _now: Any) -> None:
        self._frame_write_cancel = None
        self._write_frame()

    @callback
    def _write_frame(self) -> None:
        self._cancel_frame_write()
        self._published_revision = self.coordinator.map_revision
        self._last_frame_write = monotonic()
        self.async_write_ha_state()

    @callback
    def _cancel_frame_write(self) -> None:
        if self._frame_write_cancel is not None:
            self._frame_write_cancel()
            self._frame_write_cancel = None


class EufyVideoCamera(CoordinatorEntity[EufyCleanCoordinator], Camera):
    """The robot's own camera.

    The robot only streams after its camera has been switched on at the robot
    (hold Start/Pause and Recharge for 10 s), which is what this entity mirrors: it
    is unavailable until then and while manual control is disabled. The camera
    never changes the robot's control mode. Viewing it opens the stream; the last
    viewer to leave closes it again after a short linger.
    """

    supported_api_types = (API_TYPE_NOVEL,)
    _attr_has_entity_name = True
    _attr_name = "Camera"
    _attr_content_type = "image/jpeg"
    _attr_frame_interval = 0.2
    _unrecorded_attributes = frozenset({"frame_age_seconds"})

    def __init__(self, coordinator: EufyCleanCoordinator, video: RobotVideo) -> None:
        CoordinatorEntity.__init__(self, coordinator)
        Camera.__init__(self)
        self._video = video
        self._attr_unique_id = _video_camera_unique_id(coordinator)
        self._attr_device_info = coordinator.device_info

    @property
    def available(self) -> bool:
        return (
            super().available
            and self.coordinator.data.camera_enabled is True
            and self.coordinator.data.status_code == WORK_STATE_REMOTE_CTRL
        )

    @property
    def is_streaming(self) -> bool:
        return self._video.streaming

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        attrs: dict[str, Any] = {
            "camera_switch": self.coordinator.data.camera_enabled,
            "manual_control": self.coordinator.data.status_code == WORK_STATE_REMOTE_CTRL,
        }
        if (age := self._video.frame_age) is not None:
            attrs["frame_age_seconds"] = round(age, 1)
        if self._video.last_error:
            attrs["last_error"] = self._video.last_error
        return attrs

    async def async_camera_image(
        self, width: int | None = None, height: int | None = None
    ) -> bytes | None:
        async with self._video.hold():
            return await self._video.wait_for_frame()

    async def handle_async_mjpeg_stream(self, request):
        """Hold the robot's stream open for as long as the viewer stays connected."""
        async with self._video.hold():
            await self._video.wait_for_frame()
            return await async_get_still_stream(
                request, self._video.wait_for_frame, self.content_type, self._attr_frame_interval
            )
