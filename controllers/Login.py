
from api.EufyApi import EufyApi
from controllers.Base import Base


class EufyLogin(Base):
    def __init__(self, username: str, password: str, openudid: str):
        super().__init__()
        self.eufyApi = EufyApi(username, password, openudid)
        self.username = username
        self.password = password
        self.sid = None
        self.mqttCredentials = None
        self.cloudDevices = []
        self.mqttDevices = []
        self.eufyApiDevices = []

    async def init(self):
        await self.login({'mqtt': True})
        return await self.getDevices()

    async def login(self, config: dict):
        eufyLogin = None

        if not config['mqtt']:
            raise Exception('MQTT login is required')

        eufyLogin = self.eufyApi.login()

        if not eufyLogin:
            raise Exception('Login failed')

        if not config['mqtt']:
            raise Exception('MQTT login is required')

        self.mqttCredentials = eufyLogin['mqtt']

    async def checkLogin(self):
        if not self.sid:
            await self.login({'mqtt': True})

    async def getDevices(self):
        self.eufyApiDevices = self.eufyApi.get_cloud_device_list()

        self.mqttDevices = self.eufyApi.get_device_list()
        self.mqttDevices = [
            {
                **self.findModel(device['device_sn']),
                'apiType': self.checkApiType(device.get('dps', {})),
                'mqtt': True,
                'dps': device.get('dps', {})
            }
            for device in self.mqttDevices
        ]

        self.mqttDevices = [device for device in self.mqttDevices if not device['invalid']]

    async def getMqttDevice(self, deviceId: str):
        return self.eufyApi.get_device_list(deviceId)

    def checkApiType(self, dps: dict):
        if any(k in dps for k in self.novel_dps_map.values()):
            return 'novel'
        return 'legacy'

    def findModel(self, deviceId: str):
        device = next((d for d in self.eufyApiDevices if d['id'] == deviceId), None)

        if device:
            return {
                'deviceId': deviceId,
                'deviceModel': device.get('product', {}).get('product_code', '')[:5] or device.get('device_model', '')[:5],
                'deviceName': device.get('alias_name') or device.get('device_name') or device.get('name'),
                'deviceModelName': device.get('product', {}).get('name'),
                'invalid': False
            }

        return {'deviceId': deviceId, 'deviceModel': '', 'deviceName': '', 'deviceModelName': '', 'invalid': True}