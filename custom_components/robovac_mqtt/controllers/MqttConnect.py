import asyncio
import json
import ssl
import time
from os import path

from google.protobuf.message import Message
from paho.mqtt import client as mqtt

from ..controllers.Login import EufyLogin
from ..utils import sleep
from .SharedConnect import SharedConnect


class MqttConnect(SharedConnect):
    def __init__(self, config, openudid: str, eufyCleanApi: EufyLogin):
        super().__init__(config)
        self.deviceId = config['deviceId']
        self.deviceModel = config['deviceModel']
        self.config = config
        self.debugLog = config.get('debug', False)
        self.openudid = openudid
        self.eufyCleanApi = eufyCleanApi
        self.mqttClient = None
        self.mqttCredentials = None

    async def connect(self):
        await self.eufyCleanApi.login({'mqtt': True})
        await self.connectMqtt(self.eufyCleanApi.mqtt_credentials)
        await self.updateDevice(True)
        await sleep(2000)

    async def updateDevice(self, checkApiType=False):
        try:
            if not checkApiType:
                return
            device = await self.eufyCleanApi.getMqttDevice(self.deviceId)
            if checkApiType:
                await self.check_api_type(device.get('dps'))
            await self.map_data(device.get('dps'))
        except Exception as error:
            print(error)

    async def connectMqtt(self, mqttCredentials):
        if mqttCredentials:
            print('MQTT Credentials found')
            self.mqttCredentials = mqttCredentials
            username = self.mqttCredentials['thing_name']
            client_id = f"android-{self.mqttCredentials['app_name']}-eufy_android_{self.openudid}_{self.mqttCredentials['user_id']}-{int(time.time() * 1000)}"
            print('Setup MQTT Connection', {
                'clientId': client_id,
                'username': username,
            })
            if self.mqttClient:
                self.mqttClient.disconnect()
            self.mqttClient = mqtt.Client(
                client_id=client_id,
                transport='tcp',
            )
            self.mqttClient.username_pw_set(username)
            with open('ca.pem', 'w') as f:
                f.write(self.mqttCredentials['certificate_pem'])
            with open('key.key', 'w') as f:
                f.write(self.mqttCredentials['private_key'])
            self.mqttClient.tls_set(
                certfile=path.abspath('ca.pem'),
                keyfile=path.abspath('key.key'),
                cert_reqs=ssl.CERT_OPTIONAL,
            )
            self.mqttClient.connect_timeout = 30

            self.setupListeners()
            self.mqttClient.connect(self.mqttCredentials['endpoint_addr'], port=8883)
            self.mqttClient.loop_start()

    def setupListeners(self):
        self.mqttClient.on_connect = self.on_connect
        self.mqttClient.on_message = self.on_message
        self.mqttClient.on_disconnect = self.on_disconnect

    def on_connect(self, client, userdata, flags, rc):
        print('Connected to MQTT')
        print(f"Subscribe to cmd/eufy_home/{self.deviceModel}/{self.deviceId}/res")
        self.mqttClient.subscribe(f"cmd/eufy_home/{self.deviceModel}/{self.deviceId}/res")

    def on_message(self, client, userdata, msg: Message):
        messageParsed = json.loads(msg.payload.decode())
        print(f"Received message on {msg.topic}: ", messageParsed.get('payload', {}).get('data'))
        asyncio.run(
            self.map_data(messageParsed.get('payload', {}).get('data'))
        )

    def on_disconnect(self, client, userdata, rc):
        if rc != 0:
            print('Unexpected MQTT disconnection. Will auto-reconnect')

    async def send_command(self, dataPayload):
        try:
            payload = json.dumps({
                'account_id': self.mqttCredentials['user_id'],
                'data': dataPayload,
                'device_sn': self.deviceId,
                'protocol': 2,
                't': int(time.time()) * 1000,
            })
            mqttVal = {
                'head': {
                    'client_id': f"android-{self.mqttCredentials['app_name']}-eufy_android_{self.openudid}_{self.mqttCredentials['user_id']}",
                    'cmd': 65537,
                    'cmd_status': 2,
                    'msg_seq': 1,
                    'seed': '',
                    'sess_id': f"android-{self.mqttCredentials['app_name']}-eufy_android_{self.openudid}_{self.mqttCredentials['user_id']}",
                    'sign_code': 0,
                    'timestamp': int(time.time()) * 1000,
                    'version': '1.0.0.1'
                },
                'payload': payload,
            }
            if self.debugLog:
                print(json.dumps(mqttVal))
            print(f"Sending command to device {self.deviceId}", payload)
            self.mqttClient.publish(f"cmd/eufy_home/{self.deviceModel}/{self.deviceId}/req", json.dumps(mqttVal))
        except Exception as error:
            print(error)
