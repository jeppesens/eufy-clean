"""Camera platform for Eufy robot vacuum floor map."""
from __future__ import annotations

import logging

from homeassistant.components.camera import Camera
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import EufyCleanCoordinator
from .entity import API_TYPE_NOVEL, filter_supported_entities

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
    async_add_entities(entities)


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
