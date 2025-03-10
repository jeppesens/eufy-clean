import hashlib
import logging
from typing import Any

import aiohttp

_LOGGER = logging.getLogger(__name__)


class EufyApi:
    def __init__(self, username: str, password: str, openudid: str) -> None:
        self.username = username
        self.password = password
        self.openudid = openudid
        self.session = None
        self.user_info = None

    async def login(self, validate_only: bool = False) -> dict[str, Any]:
        _LOGGER.debug('EufyApi login', {'username': self.username})
        session = await self.eufy_login()
        if validate_only:
            return {'session': session}
        user = await self.get_user_info()
        mqtt = await self.get_mqtt_credentials()
        return {'session': session, 'user': user, 'mqtt': mqtt}

    async def eufy_login(self) -> dict[str, Any]:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                'https://home-api.eufylife.com/v1/user/email/login',
                headers={
                    'category': 'Home',
                    'Accept': '*/*',
                    'openudid': self.openudid,
                    'Content-Type': 'application/json',
                    'clientType': '1',
                    'User-Agent': 'EufyHome-iOS-2.14.0-6',
                    'Connection': 'keep-alive',
                },
                json={
                    'email': self.username,
                    'password': self.password,
                    'client_id': 'eufyhome-app',
                    'client_secret': 'GQCpr9dSp3uQpsOMgJ4xQ',
                }
            ) as response:
                if response.status == 200:
                    response_json = await response.json()
                    if response_json.get('access_token'):
                        _LOGGER.info('eufyLogin successful')
                        self.session = response_json
                        return response_json
                _LOGGER.debug(f'Login failed: {await response.json()}')
                return None

    async def get_user_info(self) -> dict[str, Any]:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                'https://api.eufylife.com/v1/user/user_center_info',
                headers={
                    'content-type': 'application/x-www-form-urlencoded; charset=UTF-8',
                    'user-agent': 'EufyHome-Android-3.1.3-753',
                    'category': 'Home',
                    'token': self.session['access_token'],
                    'openudid': self.openudid,
                    'clienttype': '2',
                }
            ) as response:
                if response.status == 200:
                    self.user_info = await response.json()
                    if not self.user_info.get('user_center_id'):
                        _LOGGER.warning('No user_center_id found')
                        return None
                    self.user_info['gtoken'] = hashlib.md5(self.user_info['user_center_id'].encode()).hexdigest()
                    return self.user_info
                _LOGGER.warning('get user center info failed')
                _LOGGER.debug(await response.json())
                return None

    async def get_mqtt_device_list(self, device_sn=None) -> list[dict[str, Any]]:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                'https://aiot-clean-api-pr.eufylife.com/app/devicerelation/get_device_list',
                headers={
                    'user-agent': 'EufyHome-Android-3.1.3-753',
                    'openudid': self.openudid,
                    'os-version': 'Android',
                    'model-type': 'PHONE',
                    'app-name': 'eufy_home',
                    'x-auth-token': self.user_info['user_center_token'],
                    'gtoken': self.user_info['gtoken'],
                    'content-type': 'application/json; charset=UTF-8',
                },
                json={'attribute': 3}
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    if data['data']['devices'] is None:
                        _LOGGER.info('Found 0 devices via Eufy MQTT')
                        return []
                    device_array = [device['device'] for device in data['data']['devices']]
                    if device_sn:
                        return next((device for device in device_array if device['device_sn'] == device_sn), None)
                    _LOGGER.info(f'Found {len(device_array)} devices via Eufy MQTT')
                    return device_array
                _LOGGER.warning('update device failed')
                _LOGGER.debug(await response.json())
                return []

    async def get_cloud_device_list(self):
        async with aiohttp.ClientSession() as session:
            async with session.get(
                'https://api.eufylife.com/v1/device/v2',
                headers={
                    'content-type': 'application/x-www-form-urlencoded; charset=UTF-8',
                    'user-agent': 'EufyHome-Android-3.1.3-753',
                    'category': 'Home',
                    'token': self.session['access_token'],
                    'openudid': self.openudid,
                    'clienttype': '2',
                }
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    _LOGGER.debug(data['devices'])
                    _LOGGER.info(f'Found {len(data["devices"])} devices via Eufy Cloud')
                    return data['devices']
                _LOGGER.warning('get device list failed')
                _LOGGER.debug(await response.json())
                return []

    async def get_device_properties(self, device_model):
        async with aiohttp.ClientSession() as session:
            async with session.post(
                'https://aiot-clean-api-pr.eufylife.com/app/things/get_product_data_point',
                headers={
                    'user-agent': 'EufyHome-Android-3.1.3-753',
                    'openudid': self.openudid,
                    'os-version': 'Android',
                    'model-type': 'PHONE',
                    'app-name': 'eufy_home',
                    'x-auth-token': self.user_info['user_center_token'],
                    'gtoken': self.user_info['gtoken'],
                    'content-type': 'application/json; charset=UTF-8',
                },
                json={'code': device_model}
            ) as response:
                if response.status == 200:
                    _LOGGER.debug(await response.json())
                else:
                    _LOGGER.warning('get product data point failed')
                    _LOGGER.debug(await response.json())

    async def get_mqtt_credentials(self):
        _LOGGER.debug('EufyApi get_mqtt_credentials')
        async with aiohttp.ClientSession() as session:
            async with session.post(
                'https://aiot-clean-api-pr.eufylife.com/app/devicemanage/get_user_mqtt_info',
                headers={
                    'content-type': 'application/json',
                    'user-agent': 'EufyHome-Android-3.1.3-753',
                    'openudid': self.openudid,
                    'os-version': 'Android',
                    'model-type': 'PHONE',
                    'app-name': 'eufy_home',
                    'x-auth-token': self.user_info['user_center_token'],
                    'gtoken': self.user_info['gtoken'],
                }
            ) as response:
                if response.status == 200:
                    return (await response.json()).get('data')
                _LOGGER.warning('get mqtt failed')
                _LOGGER.debug(await response.json())
                return None
