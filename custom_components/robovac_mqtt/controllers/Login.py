import logging
from typing import Any

from ..api.EufyApi import EufyApi
from ..api.TuyaCloudApi import TuyaCloudApi
from ..controllers.Base import Base

_LOGGER = logging.getLogger(__name__)


class EufyLogin(Base):
    def __init__(self, username: str, password: str, openudid: str, region: str):
        super().__init__()
        self.eufyApi = EufyApi(username, password, openudid)
        self.username = username
        self.password = password
        self.sid: str = None  # Tuya Cloud session ID
        self.mqtt_credentials = None
        self.mqtt_devices = []
        self.eufy_api_devices = []
        self.tuya_api: TuyaCloudApi = None
        self.region = region

    async def init(self):
        await self.login()
        return await self.getDevices()

    async def login(self):
        eufyLogin = None

        eufyLogin = await self.eufyApi.login()

        if not eufyLogin:
            raise Exception('Login failed')

        self.mqtt_credentials = eufyLogin.get('mqtt')
        if not self.mqtt_credentials:
            _LOGGER.warning('No MQTT credentials found')

        #self.tuya_api = TuyaCloudApi(self.username, self.password, eufyLogin['session']['user_id'], self.region)
        #self.sid = await self.tuya_api.login()


        self.tuya_api = TuyaCloudApi(self.username, self.region, 0, '44')
        self.sid = self.tuya_api.acquire_session()
        

    async def checkLogin(self):
        if not self.sid:
            await self.login({'mqtt': True})

    async def getDevices(self) -> None:
        self.eufy_api_devices = await self.eufyApi.get_cloud_device_list()
        devices = await self.eufyApi.get_device_list()
        devices = [
            {
                **self.findModel(device['device_sn']),
                'apiType': self.checkApiType(device.get('dps', {})),
                'mqtt': True,
                'dps': device.get('dps', {})
            }
            for device in devices
        ]
        self.mqtt_devices = [d for d in devices if not d['invalid']]

    async def getMqttDevice(self, deviceId: str):
        return await self.eufyApi.get_device_list(deviceId)

    async def get_cloud_device(self, deviceId: str):
        try:
            #await self.checkLogin()
            return await self.tuya_api.get_device(deviceId)
        except Exception as e:
            self.sid = None
            raise e

    def checkApiType(self, dps: dict):
        if any(k in dps for k in self.dps_map.values()):
            return 'novel'
        return 'legacy'

    def findModel(self, deviceId: str):
        device = next((d for d in self.eufy_api_devices if d['id'] == deviceId), None)

        if device:
            return {
                'deviceId': deviceId,
                'deviceModel': device.get('product', {}).get('product_code', '')[:5] or device.get('device_model', '')[:5],
                'deviceName': device.get('alias_name') or device.get('device_name') or device.get('name'),
                'deviceModelName': device.get('product', {}).get('name'),
                'invalid': False
            }

        return {'deviceId': deviceId, 'deviceModel': '', 'deviceName': '', 'deviceModelName': '', 'invalid': True}

    async def send_cloud_command(self, deviceId: str, dps: dict[str, Any]) -> None:
        try:
            await self.checkLogin()
            return await self.tuya_api.send_command(deviceId, dps)
        except Exception as error:
            self.sid = None
            raise error
