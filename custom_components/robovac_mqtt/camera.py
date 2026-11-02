"""Camera platform for Eufy robot vacuum floor map."""
from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from homeassistant.components.camera import Camera
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, WORK_STATE_REMOTE_CTRL
from .coordinator import EufyCleanCoordinator
from .entity import API_TYPE_NOVEL, filter_supported_entities
from .video_stream import RobotVideo

_LOGGER = logging.getLogger(__name__)


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
        entities.extend(filter_supported_entities(coordinator, [EufyMapCamera(coordinator)]))
        _add_video_camera_when_supported(config_entry, coordinator, async_add_entities)
    async_add_entities(entities)


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

    def __init__(self, coordinator: EufyCleanCoordinator) -> None:
        CoordinatorEntity.__init__(self, coordinator)
        Camera.__init__(self)
        self._attr_unique_id = f"{coordinator.device_id}_map"
        self._attr_device_info = coordinator.device_info

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Calibration for map cards, plus the live rooms on the map."""
        attrs: dict[str, Any] = {}
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
        return self.coordinator.map_image

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                f"{DOMAIN}_{self.coordinator.device_id}_map_updated",
                self._handle_map_update,
            )
        )

    @callback
    def _handle_map_update(self) -> None:
        self.async_write_ha_state()


class EufyVideoCamera(CoordinatorEntity[EufyCleanCoordinator], Camera):
    """The robot's own camera.

    The robot only streams after its camera has been switched on at the robot
    (hold Start/Pause and Recharge for 10 s), which is what this entity mirrors: it
    is unavailable until then and while manual control is disabled. The camera
    never changes the robot's control mode. Viewing it opens the stream; the last viewer to leave
    closes it again after a short linger.
    """

    supported_api_types = (API_TYPE_NOVEL,)
    _attr_has_entity_name = True
    _attr_name = "Camera"
    _attr_content_type = "image/jpeg"
    _attr_frame_interval = 0.2

    def __init__(self, coordinator: EufyCleanCoordinator, video: RobotVideo) -> None:
        CoordinatorEntity.__init__(self, coordinator)
        Camera.__init__(self)
        self._video = video
        self._attr_unique_id = f"{coordinator.device_id}_camera"
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
            return await self.handle_async_still_stream(request, self._attr_frame_interval)
