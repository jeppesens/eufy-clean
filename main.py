import random
import string

from controllers.CloudConnect import CloudConnect
# from controllers.LocalConnect import LocalConnect
from controllers.Login import EufyLogin
from controllers.MqttConnect import MqttConnect


class EufyClean:
    def __init__(self, username=None, password=None):
        print('EufyClean constructor')

        self.username = username
        self.password = password
        self.openudid = ''.join(random.choices(string.hexdigits, k=32))

    async def init(self):
        print('EufyClean init')

        self.eufyCleanApi = EufyLogin(self.username, self.password, self.openudid)
        await self.eufyCleanApi.init()

        return {
            'cloudDevices': self.eufyCleanApi.cloudDevices,
            'mqttDevices': self.eufyCleanApi.mqttDevices
        }

    async def getCloudDevices(self):
        return self.eufyCleanApi.cloudDevices

    async def getMqttDevices(self):
        return self.eufyCleanApi.mqttDevices

    async def getAllDevices(self):
        return self.eufyCleanApi.cloudDevices + self.eufyCleanApi.mqttDevices

    async def initDevice(self, deviceConfig):
        # if 'localKey' in deviceConfig and 'ip' in deviceConfig and deviceConfig['localKey']:
        #     print('LocalConnect is deprecated, use CloudConnect instead')
        #     return LocalConnect(deviceConfig)

        devices = await self.getAllDevices()
        device = next((d for d in devices if d['deviceId'] == deviceConfig['deviceId']), None)

        if not device:
            return None

        if 'localKey' not in deviceConfig and not device['mqtt']:
            return CloudConnect({**device, 'autoUpdate': deviceConfig.get('autoUpdate'), 'debug': deviceConfig.get('debug')}, self.eufyCleanApi)

        if 'localKey' not in deviceConfig and device['mqtt']:
            return MqttConnect({**device, 'autoUpdate': deviceConfig.get('autoUpdate'), 'debug': deviceConfig.get('debug')}, self.openudid, self.eufyCleanApi)
