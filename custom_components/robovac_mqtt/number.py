from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.number import NumberEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DEVICES, DOMAIN, VACS
from .controllers.SharedConnect import SharedConnect
from .proto.cloud.common_pb2 import Numerical
from .proto.cloud.station_pb2 import AutoActionCfg, CollectDustCfgV2, WashCfg

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    entities = []
    for device_id, device in hass.data[DOMAIN][DEVICES].items():
        _LOGGER.info("Adding number entities for %s", device_id)

        # Wash Frequency Value
        def set_wash_freq_value(cfg, val):
            cfg.wash.wash_freq.time_or_area.value = int(val)

        entities.append(
            DockNumberEntity(
                device,
                "wash_frequency_value",
                "Wash Frequency Value (Time)",
                15,
                25,
                1,  # Min, Max, Step
                lambda cfg: cfg.wash.wash_freq.time_or_area.value,
                set_wash_freq_value,
                "mdi:clock-time-four-outline",
            )
        )

    async_add_entities(entities)


class DockNumberEntity(NumberEntity):
    def __init__(
        self,
        device: SharedConnect,
        id_suffix: str,
        name: str,
        min_val: float,
        max_val: float,
        step_val: float,
        getter: Any,
        setter: Any,
        icon: str = None,
    ) -> None:
        super().__init__()
        self.vacuum = device
        self._attr_unique_id = f"{device.device_id}_{id_suffix}"
        self._attr_name = name
        self._attr_native_min_value = min_val
        self._attr_native_max_value = max_val
        self._attr_native_step = step_val
        self._getter = getter
        self._setter = setter
        if icon:
            self._attr_icon = icon

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device.device_id)},
            name=device.device_model_desc,
            manufacturer="Eufy",
            model=device.device_model,
        )
        self._attr_native_value = None
        self._attr_entity_category = EntityCategory.CONFIG

    async def async_added_to_hass(self):
        await self.async_update()
        self.async_write_ha_state()
        try:
            self.vacuum.add_listener(self._handle_update)
        except Exception:
            _LOGGER.exception(
                "Failed to add update listener for %s", self._attr_unique_id
            )

    async def async_will_remove_from_hass(self):
        try:
            if hasattr(self.vacuum, "_update_listeners"):
                try:
                    self.vacuum._update_listeners.remove(self._handle_update)
                except ValueError:
                    pass
        except Exception:
            _LOGGER.exception(
                "Failed to remove update listener for %s", self._attr_unique_id
            )

    async def _handle_update(self):
        await self.async_update()
        self.async_write_ha_state()

    async def async_update(self):
        try:
            cfg = await self.vacuum.get_auto_action_cfg()
            if cfg:
                try:
                    self._attr_native_value = self._getter(cfg)
                except Exception:
                    pass
        except Exception as e:
            _LOGGER.error(f"Error updating {self._attr_name}: {e}")

    async def async_set_native_value(self, value: float) -> None:
        try:
            cfg = await self.vacuum.get_auto_action_cfg()
            if not cfg:
                cfg = AutoActionCfg()

            self._setter(cfg, value)

            from google.protobuf.json_format import MessageToDict

            cfg_dict = MessageToDict(cfg, preserving_proto_field_name=True)
            await self.vacuum.set_auto_action_cfg(cfg_dict)

            self._attr_native_value = value
            self.async_write_ha_state()
        except Exception as e:
            _LOGGER.error(f"Error setting {self._attr_name}: {e}")
