from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .constants.hass import DEVICES, DOMAIN, VACS
from .controllers.SharedConnect import SharedConnect
from .proto.cloud.station_pb2 import (
    AutoActionCfg,
    CollectDustCfgV2,
    WashCfg,
)
from .proto.cloud.common_pb2 import Switch

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    entities = []
    for device_id, device in hass.data[DOMAIN][DEVICES].items():
        _LOGGER.info("Adding switch entities for %s", device_id)
        
        # Detergent - Removed per user request

        # Collect Dust Enable (V2)
        def set_collect_dust_switch(cfg, val):
            cfg.collectdust_v2.sw.value = bool(val)

        entities.append(DockSwitchEntity(
            device,
            "collect_dust_switch",
            "Auto Empty",
            lambda cfg: cfg.collectdust_v2.sw.value,
            set_collect_dust_switch,
            "mdi:delete-restore"
        ))

        # Auto Mop Washing
        def set_auto_mop_washing(cfg, val):
            cfg.wash.cfg = WashCfg.Cfg.STANDARD if val else WashCfg.Cfg.CLOSE
        
        entities.append(DockSwitchEntity(
            device,
            "auto_mop_washing_switch",
            "Auto Mop Washing",
            lambda cfg: cfg.wash.cfg == WashCfg.Cfg.STANDARD,
            set_auto_mop_washing,
            "mdi:water-sync"
        ))

    async_add_entities(entities)


class DockSwitchEntity(SwitchEntity):
    def __init__(
        self,
        device: SharedConnect,
        id_suffix: str,
        name: str,
        getter: Any,
        setter: Any,
        icon: str = None,
    ) -> None:
        super().__init__()
        self.vacuum = device
        self._attr_unique_id = f"{device.device_id}_{id_suffix}"
        self._attr_name = name
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
        self._attr_is_on = None
        self._attr_entity_category = EntityCategory.CONFIG

    async def async_added_to_hass(self):
        await self.async_update()
        self.async_write_ha_state()
        try:
            self.vacuum.add_listener(self._handle_update)
        except Exception:
            _LOGGER.exception("Failed to add update listener for %s", self._attr_unique_id)

    async def async_will_remove_from_hass(self):
        try:
            if hasattr(self.vacuum, "_update_listeners"):
                try:
                    self.vacuum._update_listeners.remove(self._handle_update)
                except ValueError:
                    pass
        except Exception:
             _LOGGER.exception("Failed to remove update listener for %s", self._attr_unique_id)
    
    async def _handle_update(self):
        await self.async_update()
        self.async_write_ha_state()

    async def async_update(self):
        try:
            cfg = await self.vacuum.get_auto_action_cfg()
            if cfg:
                try:
                    self._attr_is_on = self._getter(cfg)
                except Exception:
                    pass
        except Exception as e:
            _LOGGER.error(f"Error updating {self._attr_name}: {e}")

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._set_state(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._set_state(False)

    async def _set_state(self, state: bool) -> None:
        try:
            cfg = await self.vacuum.get_auto_action_cfg()
            if not cfg:
                cfg = AutoActionCfg()
            
            self._setter(cfg, state)
            
            from google.protobuf.json_format import MessageToDict
            cfg_dict = MessageToDict(cfg, preserving_proto_field_name=True)
            await self.vacuum.set_auto_action_cfg(cfg_dict)
            
            self._attr_is_on = state
            self.async_write_ha_state()
        except Exception as e:
            _LOGGER.error(f"Error setting {self._attr_name}: {e}")
