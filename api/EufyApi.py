import hashlib

import requests


class EufyApi:
    def __init__(self, username: str, password: str, openudid: str):
        self.username = username
        self.password = password
        self.openudid = openudid
        self.session = None
        self.user_info = None
        self.request_client = requests.Session()

    def login(self):
        session = self.eufy_login()
        user = self.get_userinfo()
        mqtt = self.get_mqtt_credentials()
        return {'session': session, 'user': user, 'mqtt': mqtt}

    def sof_login(self):
        session = self.eufy_login()
        return {'session': session}

    def eufy_login(self):
        response = self.request_client.post(
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
        )
        if response.status_code == 200 and response.json().get('access_token'):
            print('eufyLogin successful')
            self.session = response.json()
            return response.json()
        else:
            print(f'Login failed: {response.json()}')
            return None

    def get_userinfo(self):
        response = self.request_client.get(
            'https://api.eufylife.com/v1/user/user_center_info',
            headers={
                'content-type': 'application/x-www-form-urlencoded; charset=UTF-8',
                'user-agent': 'EufyHome-Android-3.1.3-753',
                'category': 'Home',
                'token': self.session['access_token'],
                'openudid': self.openudid,
                'clienttype': '2',
            }
        )
        if response.status_code == 200:
            self.user_info = response.json()
            if not self.user_info.get('user_center_id'):
                print('No user_center_id found')
                return None
            self.user_info['gtoken'] = hashlib.md5(self.user_info['user_center_id'].encode()).hexdigest()
        else:
            print('get user center info failed')
            print(response.json())
            return None

    def get_cloud_device_list(self):
        response = self.request_client.get(
            'https://api.eufylife.com/v1/device/v2',
            headers={
                'content-type': 'application/x-www-form-urlencoded; charset=UTF-8',
                'user-agent': 'EufyHome-Android-3.1.3-753',
                'category': 'Home',
                'token': self.session['access_token'],
                'openudid': self.openudid,
                'clienttype': '2',
            }
        )
        if response.status_code == 200:
            data = response.json().get('data', response.json())
            print(f'Found {len(data["devices"])} devices via Eufy Cloud')
            return data['devices']
        else:
            print('get device list failed')
            print(response.json())
            return []

    def get_device_list(self, device_sn=None):
        response = self.request_client.post(
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
        )
        if response.status_code == 200:
            data = response.json().get('data', response.json())
            device_array = [device['device'] for device in data['devices']]
            if device_sn:
                return next((device for device in device_array if device['device_sn'] == device_sn), None)
            print(f'Found {len(device_array)} devices via Eufy MQTT')
            return device_array
        else:
            print('update device failed')
            print(response.json())
            return []

    def get_device_properties(self, device_model):
        response = self.request_client.post(
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
        )
        if response.status_code == 200:
            print(response.json())
        else:
            print('get product data point failed')
            print(response.json())

    def get_mqtt_credentials(self):
        response = self.request_client.post(
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
        )
        if response.status_code == 200:
            return response.json().get('data')
        else:
            print('get mqtt failed')
            print(response.json())
            return None
