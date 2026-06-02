from __future__ import annotations

from dataclasses import replace
from datetime import time as dt_time

from homeassistant.components.time import TimeEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api.commands import build_command
from .const import DOMAIN
from .coordinator import EufyCleanCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up DND time entities."""
    data = hass.data[DOMAIN][config_entry.entry_id]
    coordinators: list[EufyCleanCoordinator] = data["coordinators"]

    entities = []
    for coordinator in coordinators:
        entities.append(DoNotDisturbStartTimeEntity(coordinator))
        entities.append(DoNotDisturbEndTimeEntity(coordinator))

    async_add_entities(entities)


class _DoNotDisturbTimeEntity(CoordinatorEntity[EufyCleanCoordinator], TimeEntity):
    """Base class for Do Not Disturb time entities."""

    _field_prefix: str

    def __init__(
        self,
        coordinator: EufyCleanCoordinator,
        unique_id_suffix: str,
        name: str,
        icon: str,
    ) -> None:
        """Initialize the DND time entity."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.device_id}_{unique_id_suffix}"
        self._attr_has_entity_name = True
        self._attr_name = name
        self._attr_icon = icon
        self._attr_entity_category = EntityCategory.CONFIG
        self._attr_device_info = coordinator.device_info

    @property
    def available(self) -> bool:
        """Return whether the entity is available."""
        return (
            super().available
            and "do_not_disturb" in self.coordinator.data.received_fields
        )

    @property
    def native_value(self) -> dt_time:
        """Return the current DND time value."""
        data = self.coordinator.data
        hour = getattr(data, f"{self._field_prefix}_hour")
        minute = getattr(data, f"{self._field_prefix}_minute")
        return dt_time(hour=hour, minute=minute)

    async def async_set_value(self, value: dt_time) -> None:
        """Update the DND schedule time."""
        data = self.coordinator.data
        command = build_command(
            "set_do_not_disturb",
            api_type=self.coordinator.data.api_type,
            active=data.dnd_enabled,
            begin_hour=(
                value.hour if self._field_prefix == "dnd_start" else data.dnd_start_hour
            ),
            begin_minute=(
                value.minute
                if self._field_prefix == "dnd_start"
                else data.dnd_start_minute
            ),
            end_hour=(
                value.hour if self._field_prefix == "dnd_end" else data.dnd_end_hour
            ),
            end_minute=(
                value.minute if self._field_prefix == "dnd_end" else data.dnd_end_minute
            ),
        )
        await self.coordinator.async_send_command(command)
        self.coordinator.async_set_updated_data(
            replace(
                data,
                **{
                    f"{self._field_prefix}_hour": value.hour,
                    f"{self._field_prefix}_minute": value.minute,
                },
            )
        )


class DoNotDisturbStartTimeEntity(_DoNotDisturbTimeEntity):
    """Time entity for DND start time."""

    _field_prefix = "dnd_start"

    def __init__(self, coordinator: EufyCleanCoordinator) -> None:
        """Initialize the start time entity."""
        super().__init__(
            coordinator,
            "do_not_disturb_start",
            "Do Not Disturb Start",
            "mdi:clock-start",
        )


class DoNotDisturbEndTimeEntity(_DoNotDisturbTimeEntity):
    """Time entity for DND end time."""

    _field_prefix = "dnd_end"

    def __init__(self, coordinator: EufyCleanCoordinator) -> None:
        """Initialize the end time entity."""
        super().__init__(
            coordinator,
            "do_not_disturb_end",
            "Do Not Disturb End",
            "mdi:clock-end",
        )
