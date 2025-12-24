import random
import string
import logging
from typing import Any

from .controllers.Login import EufyLogin
from .controllers.MqttConnect import MqttConnect
_LOGGER = logging.getLogger(__name__)


class EufyClean:
    def __init__(self, username: str, password: str):
        _LOGGER.debug('EufyClean constructor')

        self.username = username
        self.password = password
        self.openudid = ''.join(random.choices(string.hexdigits, k=32))

    async def init(self) -> list[dict[str, Any]]:
        self.eufyCleanApi = EufyLogin(self.username, self.password, self.openudid)
        await self.eufyCleanApi.init()

        return self.eufyCleanApi.mqtt_devices

    async def get_devices(self):
        return self.eufyCleanApi.mqtt_devices

    async def init_device(self, device_id: str) -> MqttConnect:
        devices = await self.get_devices()
        device = next((d for d in devices if d['deviceId'] == device_id), None)

        if not device:
            raise Exception('Device not found')

        if not device['mqtt']:
            raise Exception('Device is not a MQTT device')

        return MqttConnect(device, self.openudid, self.eufyCleanApi)

    async def get_user_info(self):
        return await self.eufyCleanApi.eufyApi.get_user_info()
