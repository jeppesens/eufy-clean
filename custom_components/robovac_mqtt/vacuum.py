import logging

from homeassistant.components.vacuum import StateVacuumEntity
from homeassistant.components.vacuum.const import VacuumActivity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (CONF_DESCRIPTION, CONF_ID, CONF_NAME,
                                 CONF_PASSWORD, CONF_USERNAME)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .constants.hass import DOMAIN
from .constants.state import (EUFY_CLEAN_CLEAN_SPEED,
                              EUFY_CLEAN_NOVEL_CLEAN_SPEED)
from .controllers.MqttConnect import MqttConnect
from .main import EufyClean

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Initialize my test integration 2 config entry."""

    username = config_entry[CONF_USERNAME]
    password = config_entry[CONF_PASSWORD]

    eufy_clean = EufyClean(username, password)
    await eufy_clean.init()

    async for vacuum in eufy_clean.get_devices():
        device = await eufy_clean.init_device(vacuum['deviceId'])
        entity = RoboVacMQTTEntity(device)
        hass.data[DOMAIN]['vacuums'][vacuum[device.device_id]] = entity
        async_add_entities([entity])


class RoboVacMQTTEntity(StateVacuumEntity):
    """Representation of a vacuum cleaner."""

    _state: VacuumActivity = None

    @property
    def state(self) -> str | None:
        return self._state

    def __init__(self, item: MqttConnect) -> None:
        """Initialize Eufy Robovac"""
        super().__init__()
        self._attr_battery_level = 0
        self._attr_name = item[CONF_NAME]
        self._attr_unique_id = item.device_id
        self._attr_model_code = item.device_model

        self.vacuum = item

        item.add_listener(self.pushed_update_handler)

        self.update_failures = 0

        self._attr_supported_features = self.vacuum.getHomeAssistantFeatures()
        self._attr_robovac_supported = self.vacuum.getRoboVacFeatures()
        self._attr_fan_speed_list = EUFY_CLEAN_NOVEL_CLEAN_SPEED

        self._attr_mode = None
        self._attr_consumables = None
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, item[CONF_ID])},
            name=item[CONF_NAME],
            manufacturer="Eufy",
            model=item[CONF_DESCRIPTION],
        )

        self.error_code = None

    async def pushed_update_handler(self):
        await self.update_entity_values()
        self.async_write_ha_state()

    async def update_entity_values(self):
        self._attr_battery_level = await self.vacuum.get_battery_level()
        self.tuya_state = await self.vacuum.get_work_status()
        # self._attr_mode = await self.vacuum.get_work_mode()
        # self._attr_fan_speed = await self.vacuum.get_fan_speed()

    async def async_locate(self, **kwargs):
        """Locate the vacuum cleaner."""
        _LOGGER.info("Locate Pressed")
        await self.vacuum.get_find_robot()

    async def async_return_to_base(self, **kwargs):
        """Set the vacuum cleaner to return to the dock."""
        _LOGGER.info("Return home Pressed")
        await self.vacuum.go_home()

    async def async_start(self, **kwargs):
        await self.vacuum.play()

    async def async_pause(self, **kwargs):
        await self.vacuum.pause()

    async def async_stop(self, **kwargs):
        await self.vacuum.stop()

    async def async_clean_spot(self, **kwargs):
        """Perform a spot clean-up."""
        _LOGGER.info("Spot Clean Pressed")
        await self.vacuum.spot_clean()

    async def async_set_fan_speed(self, fan_speed: EUFY_CLEAN_CLEAN_SPEED, **kwargs):
        """Set fan speed."""
        _LOGGER.info("Fan Speed Selected")
        await self.vacuum.set_clean_speed(fan_speed)

    async def async_send_command(
        self, command: str, params: dict | list | None = None, **kwargs
    ) -> None:
        """Send a command to a vacuum cleaner."""
        _LOGGER.info("Send Command %s Pressed", command)
        raise NotImplementedError()
