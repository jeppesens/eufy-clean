import random
import string
from typing import Any

from .controllers import CloudConnect, EufyLogin, MqttConnect, SharedConnect


class EufyClean:
    def __init__(self, username: str, password: str, region: str = 'EU'):
        print('EufyClean constructor')

        self.username = username
        self.password = password
        self.openudid = ''.join(random.choices(string.hexdigits, k=32))
        self.region = region

    async def init(self) -> list[dict[str, Any]]:
        self.eufyCleanApi = EufyLogin(self.username, self.password, self.openudid, self.region)
        await self.eufyCleanApi.init()

    async def get_devices(self):
        return self.eufyCleanApi.mqtt_devices + self.eufyCleanApi.eufy_api_devices

    async def init_device(self, device_id: str) -> SharedConnect:
        devices = await self.get_devices()
        device = next((d for d in devices if d['deviceId'] == device_id), None)

        if not device:
            raise Exception('Device not found')

        if device['mqtt']:
            return MqttConnect(device, self.openudid, self.eufyCleanApi)
        else:
            return CloudConnect(device, self.openudid, self.eufyCleanApi)

    async def get_user_info(self):
        return await self.eufyCleanApi.eufyApi.get_user_info()
