import logging
from typing import Literal

from homeassistant.components.vacuum import (
    StateVacuumEntity,
    VacuumEntityFeature,
    VacuumActivity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import Entity, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .constants.hass import DOMAIN, VACS
from .constants.state import EUFY_CLEAN_CLEAN_SPEED, EUFY_CLEAN_NOVEL_CLEAN_SPEED
from .controllers.MqttConnect import MqttConnect
from .EufyClean import EufyClean

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    username = config_entry.data[CONF_USERNAME]
    password = config_entry.data[CONF_PASSWORD]

    eufy_clean = EufyClean(username, password)
    await eufy_clean.init()

    for vacuum in await eufy_clean.get_devices():
        device = await eufy_clean.init_device(vacuum['deviceId'])
        await device.connect()
        _LOGGER.info("Adding vacuum %s", device.device_id)
        entity = RoboVacMQTTEntity(device, hass)
        hass.data[DOMAIN][VACS][device.device_id] = entity
        async_add_entities([entity])

        battery_sensor = RobovacBatterySensor(device)
        async_add_entities([battery_sensor])

        await entity.pushed_update_handler()

class RobovacBatterySensor(Entity):
    def __init__(self, robovac):
        self.robovac = robovac
        self._attr_unique_id = f"{robovac.device_id}_battery"
        self._attr_name = f"{robovac.device_model_desc} Battery Level"
        self._state = None

    async def async_update(self):
        if hasattr(self.robovac, "get_battery_level"):
            self._state = await self.robovac.get_battery_level()

    @property
    def state(self):
        return self._state

    @property
    def unit_of_measurement(self):
        return "%"

    @property
    def device_class(self):
        return "battery"

class RoboVacMQTTEntity(StateVacuumEntity):
    def __init__(self, item: MqttConnect, hass: HomeAssistant) -> None:
        super().__init__()
        self.vacuum = item
        self.hass = hass
        self._attr_unique_id = item.device_id
        self._attr_name = item.device_model_desc
        self._attr_model = item.device_model
        self._attr_available = True
        self._attr_fan_speed_list = EUFY_CLEAN_NOVEL_CLEAN_SPEED
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, item.device_id)},
            name=item.device_model_desc,
            manufacturer="Eufy",
            model=item.device_model,
        )
        self._state = None
        self._attr_battery_level = None
        self._attr_fan_speed = None
        self._attr_supported_features = (
            VacuumEntityFeature.START
            | VacuumEntityFeature.PAUSE
            | VacuumEntityFeature.STOP
            | VacuumEntityFeature.STATUS
            | VacuumEntityFeature.STATE
            | VacuumEntityFeature.BATTERY
            | VacuumEntityFeature.FAN_SPEED
            | VacuumEntityFeature.RETURN_HOME
            | VacuumEntityFeature.SEND_COMMAND
        )

        def _threadsafe_update():
            self.hass.loop.call_soon_threadsafe(
                lambda: self.hass.async_create_task(self.pushed_update_handler())
            )

        item.add_listener(_threadsafe_update)

    @property
    def activity(self) -> VacuumActivity | None:
        if not self._state:
            return None

        state = self._state.lower()

        if state in ("docked", "charging"):
            return VacuumActivity.DOCKED
        elif state in ("cleaning", "auto_cleaning", "spot_cleaning"):
            return VacuumActivity.CLEANING
        elif state in ("paused",):
            return VacuumActivity.PAUSED
        elif state in ("returning", "returning_to_base"):
            return VacuumActivity.RETURNING
        elif state in ("error", "stuck"):
            return VacuumActivity.ERROR
        elif state in ("idle", "standby"):
            return VacuumActivity.IDLE
        else:
            return None

    @property
    def extra_state_attributes(self):
        return {
            "battery_level": self._attr_battery_level,
            "fan_speed": self._attr_fan_speed,
            "status": self._state,
        }

    async def pushed_update_handler(self):
        await self.update_entity_values()
        self.async_write_ha_state()

    async def update_entity_values(self):
        self._attr_battery_level = await self.vacuum.get_battery_level()
        self._state = await self.vacuum.get_work_status()

        try:
            fan_speed = await self.vacuum.get_clean_speed()
            if isinstance(fan_speed, str):
                self._attr_fan_speed = fan_speed.lower()
            elif isinstance(fan_speed, int):
                self._attr_fan_speed = str(fan_speed)
            else:
                self._attr_fan_speed = None
        except Exception as e:
            _LOGGER.warning("Failed to get fan speed: %s", e)
            self._attr_fan_speed = None

        _LOGGER.debug("Vacuum state: %s", self._state)

    async def async_return_to_base(self, **kwargs):
        await self.vacuum.go_home()

    async def async_start(self, **kwargs):
        await self.vacuum.auto_clean()

    async def async_pause(self, **kwargs):
        await self.vacuum.pause()

    async def async_stop(self, **kwargs):
        await self.vacuum.stop()

    async def async_clean_spot(self, **kwargs):
        await self.vacuum.spot_clean()

    async def async_set_fan_speed(self, fan_speed: str, **kwargs):
        if fan_speed not in EUFY_CLEAN_CLEAN_SPEED:
            raise ValueError(f"Invalid fan speed: {fan_speed}")
        await self.vacuum.set_clean_speed(fan_speed)

    async def async_send_command(
        self,
        command: Literal['scene_clean', 'room_clean'],
        params: dict | list | None = None,
        **kwargs,
    ) -> None:
        if command == "scene_clean":
            if not params or not isinstance(params, dict) or "scene" not in params:
                raise ValueError("params[scene] is required for scene_clean command")
            scene = params["scene"]
            await self.vacuum.scene_clean(scene)
        elif command == "room_clean":
            if not params or not isinstance(params, dict) or not isinstance(params.get("rooms"), list):
                raise ValueError("params[rooms] is required for room_clean command")
            rooms = [int(r) for r in params['rooms']]
            map_id = int(params.get("map_id", 0))
            await self.vacuum.room_clean(rooms, map_id)
        else:
            raise NotImplementedError(f"Command {command} not implemented")

