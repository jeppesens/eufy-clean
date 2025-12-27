from __future__ import annotations

import asyncio
import json
import logging
import time
from functools import partial
from os import path
from threading import Thread

from google.protobuf.message import Message
from paho.mqtt import client as mqtt

from ..controllers.Login import EufyLogin
from ..utils import sleep
from .SharedConnect import SharedConnect

_LOGGER = logging.getLogger(__name__)


def get_blocking_mqtt_client(
    client_id: str, username: str, certificate_pem: str, private_key: str
):
    client = mqtt.Client(
        client_id=client_id,
        transport="tcp",
    )
    client.username_pw_set(username)

    current_dir = path.dirname(path.abspath(__file__))
    ca_path = path.join(current_dir, "ca.pem")
    key_path = path.join(current_dir, "key.key")

    with open(ca_path, "w") as f:
        f.write(certificate_pem)
    with open(key_path, "w") as f:
        f.write(private_key)

    client.tls_set(
        certfile=path.abspath(ca_path),
        keyfile=path.abspath(key_path),
    )
    return client


class MqttConnect(SharedConnect):
    def __init__(self, config, openudid: str, eufyCleanApi: EufyLogin):
        super().__init__(config)
        self.deviceId = config["deviceId"]
        self.deviceModel = config["deviceModel"]
        self.config = config
        self.debugLog = config.get("debug", False)
        self.openudid = openudid
        self.eufyCleanApi = eufyCleanApi
        self.mqttClient = None
        self.mqttCredentials = None
        self._loop = None  # Store reference to the event loop

    async def connect(self):
        # Store the current event loop for later use
        self._loop = asyncio.get_running_loop()

        await self.eufyCleanApi.login({"mqtt": True})
        await self.connectMqtt(self.eufyCleanApi.mqtt_credentials)
        await self.updateDevice(True)
        await sleep(2000)

    async def updateDevice(self, checkApiType=False):
        try:
            if not checkApiType:
                return
            device = await self.eufyCleanApi.getMqttDevice(self.deviceId)
            if device and device.get("dps"):
                await self._map_data(device.get("dps"))
        except Exception as error:
            _LOGGER.error(f"Error updating device: {error}")

    async def connectMqtt(self, mqttCredentials):
        if mqttCredentials:
            _LOGGER.debug("MQTT Credentials found")
            self.mqttCredentials = mqttCredentials
            username = self.mqttCredentials["thing_name"]
            client_id = f"android-{self.mqttCredentials['app_name']}-eufy_android_{self.openudid}_{self.mqttCredentials['user_id']}-{int(time.time() * 1000)}"
            _LOGGER.debug(
                "Setup MQTT Connection",
                {
                    "clientId": client_id,
                    "username": username,
                },
            )
            if self.mqttClient:
                self.mqttClient.disconnect()
            # When calling a blocking function in your library code
            loop = asyncio.get_running_loop()
            self.mqttClient = await loop.run_in_executor(
                None,
                partial(
                    get_blocking_mqtt_client,
                    client_id=client_id,
                    username=username,
                    certificate_pem=self.mqttCredentials["certificate_pem"],
                    private_key=self.mqttCredentials["private_key"],
                ),
            )
            self.mqttClient.connect_timeout = 30

            self.setupListeners()
            self.mqttClient.connect_async(
                self.mqttCredentials["endpoint_addr"], port=8883
            )
            self.mqttClient.loop_start()

    def setupListeners(self):
        self.mqttClient.on_connect = self.on_connect
        self.mqttClient.on_message = self.on_message
        self.mqttClient.on_disconnect = self.on_disconnect

    def on_connect(self, client, userdata, flags, rc):
        _LOGGER.debug("Connected to MQTT")
        _LOGGER.info(
            f"Subscribe to cmd/eufy_home/{self.deviceModel}/{self.deviceId}/res"
        )
        self.mqttClient.subscribe(
            f"cmd/eufy_home/{self.deviceModel}/{self.deviceId}/res"
        )

    def on_message(self, client, userdata, msg: Message):
        """Fixed: Properly handle async message processing from sync callback"""
        messageParsed = json.loads(msg.payload.decode())
        _LOGGER.debug(f"Received message on {msg.topic}: %s", messageParsed)

        try:
            # Get the payload data
            payload_data = messageParsed.get("payload", {}).get("data")
            if payload_data:
                # Schedule the async function to run in the event loop
                if self._loop and not self._loop.is_closed():
                    asyncio.run_coroutine_threadsafe(
                        self._map_data(payload_data), self._loop
                    )
                else:
                    _LOGGER.warning("Event loop not available for message processing")
        except Exception as error:
            _LOGGER.error("Could not parse data", exc_info=error)

    def on_disconnect(self, client, userdata, rc):
        if rc != 0:
            _LOGGER.warning("Unexpected MQTT disconnection. Will auto-reconnect")

    async def send_command(self, dataPayload) -> None:
        try:
            if not self.mqttCredentials:
                _LOGGER.error("No MQTT credentials available")
                return

            payload = json.dumps(
                {
                    "account_id": self.mqttCredentials["user_id"],
                    "data": dataPayload,
                    "device_sn": self.deviceId,
                    "protocol": 2,
                    "t": int(time.time()) * 1000,
                }
            )
            mqttVal = {
                "head": {
                    "client_id": f"android-{self.mqttCredentials['app_name']}-eufy_android_{self.openudid}_{self.mqttCredentials['user_id']}",
                    "cmd": 65537,
                    "cmd_status": 2,
                    "msg_seq": 1,
                    "seed": "",
                    "sess_id": f"android-{self.mqttCredentials['app_name']}-eufy_android_{self.openudid}_{self.mqttCredentials['user_id']}",
                    "sign_code": 0,
                    "timestamp": int(time.time()) * 1000,
                    "version": "1.0.0.1",
                },
                "payload": payload,
            }
            if self.debugLog:
                _LOGGER.debug(json.dumps(mqttVal))
            _LOGGER.debug(f"Sending command to device {self.deviceId}: %s", payload)

            if self.mqttClient and self.mqttClient.is_connected():
                self.mqttClient.publish(
                    f"cmd/eufy_home/{self.deviceModel}/{self.deviceId}/req",
                    json.dumps(mqttVal),
                )
            else:
                _LOGGER.error("MQTT client not connected")
        except Exception as error:
            _LOGGER.error(f"Error sending command: {error}")
