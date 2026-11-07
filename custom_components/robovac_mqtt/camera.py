"""Camera platform for Eufy robot vacuum floor map."""
from __future__ import annotations

import logging
from time import monotonic
from typing import Any

from homeassistant.components.camera import Camera
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import API_TYPE_NOVEL, DOMAIN
from .coordinator import EufyCleanCoordinator
from .entity import filter_supported_entities

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
        entities.extend(filter_supported_entities(coordinator, [EufyMapCamera(coordinator)]))
    async_add_entities(entities)


class EufyMapCamera(CoordinatorEntity[EufyCleanCoordinator], Camera):
    """Camera entity that displays the robot's live floor map."""

    supported_api_types = (API_TYPE_NOVEL,)
    _attr_has_entity_name = True
    _attr_name = "Map"
    _attr_content_type = "image/png"
    # Kept out of the attributes JSON; each state write that bumps it is still a
    # states row, so frame writes are throttled to FRAME_WRITE_INTERVAL.
    _unrecorded_attributes = frozenset({"map_revision"})

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
        """Expose the frame token so viewers can cache the image safely.

        The camera's state string never changes, so publishing the revision is
        what makes the attributes differ per frame and gives clients an exact
        cache key instead of a timed cache-bust.
        """
        trail_color = self.coordinator.trail_color
        return {
            "map_revision": self._published_revision,
            "trail_color": list(trail_color) if trail_color else None,
        }

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
