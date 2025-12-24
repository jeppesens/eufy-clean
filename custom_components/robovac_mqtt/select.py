from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .constants.hass import DEVICES, DOMAIN, VACS
from .controllers.SharedConnect import SharedConnect
from .proto.cloud.station_pb2 import (
    AutoActionCfg,
    WashCfg,
    DryCfg,
    CollectDustCfg,
    CollectDustCfgV2,
    Duration,
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
        _LOGGER.info("Adding select entities for %s", device_id)
        
        # Wash Frequency Mode
        def set_wash_freq_mode(cfg, val):
            cfg.wash.wash_freq.mode = WashCfg.BackwashFreq.Mode.ByPartition if val == "ByRoom" else WashCfg.BackwashFreq.Mode.ByTime

        entities.append(DockSelectEntity(
            device,
            "wash_frequency_mode",
            "Wash Frequency Mode",
            ["ByRoom", "ByTime"],
            lambda cfg: "ByRoom" if cfg.wash.wash_freq.mode == WashCfg.BackwashFreq.Mode.ByPartition else "ByTime",
            set_wash_freq_mode,
            "mdi:calendar-sync"
        ))

        # Dry Duration
        def set_dry_duration(cfg, val):
            cfg.dry.duration.level = ["2h", "3h", "4h"].index(val)

        entities.append(DockSelectEntity(
            device,
            "dry_duration",
            "Dry Duration",
            ["2h", "3h", "4h"],
             lambda cfg: "3h" if not cfg.HasField("dry") else ("2h" if cfg.dry.duration.level == 0 else ("3h" if cfg.dry.duration.level == 1 else "4h")),
            set_dry_duration,
            "mdi:timer-sand"
        ))

        # Collect Dust Mode (V2)
        def get_collect_dust_mode(cfg):
            # Check for value 2 (SMART)
            if cfg.collectdust_v2.mode.value == 2:
                return "Smart"
            # Fallback to BY_TASK as "Smart" (legacy check)
            elif cfg.collectdust_v2.mode.value == CollectDustCfgV2.Mode.Value.BY_TASK:
                return "Smart" 
            elif cfg.collectdust_v2.mode.value == CollectDustCfgV2.Mode.Value.BY_TIME:
                return f"{cfg.collectdust_v2.mode.time} min"
            return "Smart"

        def set_collect_dust_mode(cfg, val):
            if val == "Smart":
                cfg.collectdust_v2.mode.value = 2 # SMART
            else:
                try:
                    minutes = int(val.split(' ')[0])
                    cfg.collectdust_v2.mode.value = CollectDustCfgV2.Mode.Value.BY_TIME
                    cfg.collectdust_v2.mode.time = minutes
                except ValueError:
                    _LOGGER.error(f"Invalid collect dust mode value: {val}")

        entities.append(DockSelectEntity(
            device,
            "collect_dust_mode",
            "Auto Empty Mode",
            ["Smart", "15 min", "30 min", "45 min", "60 min"],
            get_collect_dust_mode,
            set_collect_dust_mode,
            "mdi:delete-restore"
        ))

    async_add_entities(entities)


class DockSelectEntity(SelectEntity):
    def __init__(
        self,
        device: SharedConnect,
        id_suffix: str,
        name: str,
        options: list[str],
        getter: Any,
        setter: Any,
        icon: str = None,
    ) -> None:
        super().__init__()
        self.vacuum = device
        self._attr_unique_id = f"{device.device_id}_{id_suffix}"
        self._attr_name = name
        self._attr_options = options
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
        self._attr_current_option = None
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
                    self._attr_current_option = self._getter(cfg)
                except Exception:
                    pass
        except Exception as e:
            _LOGGER.error(f"Error updating {self._attr_name}: {e}")

    async def async_select_option(self, option: str) -> None:
        try:
            cfg = await self.vacuum.get_auto_action_cfg()
            if not cfg:
                cfg = AutoActionCfg()
            
            self._setter(cfg, option)
            
            from google.protobuf.json_format import MessageToDict
            cfg_dict = MessageToDict(cfg, preserving_proto_field_name=True)
            await self.vacuum.set_auto_action_cfg(cfg_dict)
            
            self._attr_current_option = option
            self.async_write_ha_state()
        except Exception as e:
            _LOGGER.error(f"Error setting {self._attr_name}: {e}")
