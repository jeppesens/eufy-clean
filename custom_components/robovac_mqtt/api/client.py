from __future__ import annotations

import asyncio
import json
import logging
import ssl
import tempfile
import time
from collections.abc import Callable
from functools import partial
from os import unlink
from typing import Any

from paho.mqtt import client as mqtt

_LOGGER = logging.getLogger(__name__)


def get_blocking_mqtt_client(
    client_id: str,
    username: str,
    certificate_pem: str,
    private_key: str,
) -> tuple[mqtt.Client, str, str]:
    """Create a blocking Paho MQTT client with specific TLS settings.

    Returns:
        Tuple of (client, cert_path, key_path) - caller must clean up cert files
    """
    client = mqtt.Client(
        client_id=client_id,
        transport="tcp",
    )
    client.username_pw_set(username)

    # Create persistent temp files for certs
    # IMPORTANT: Paho MQTT keeps file path references and reads them on reconnect
    # These files MUST persist for the lifetime of the MQTT client
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".pem") as ca_file:
        ca_file.write(certificate_pem)
        ca_path = ca_file.name

    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".key") as key_file:
        key_file.write(private_key)
        key_path = key_file.name

    client.tls_set(
        certfile=ca_path,
        keyfile=key_path,
        cert_reqs=ssl.CERT_REQUIRED,
        tls_version=ssl.PROTOCOL_TLSv1_2,
    )

    return client, ca_path, key_path


class EufyCleanClient:
    """Handles low-level MQTT connectivity and protocol transport."""

    def __init__(
        self,
        device_id: str,
        user_id: str,
        app_name: str,
        thing_name: str,
        access_key: str,  # Unused in MQTT connecting but part of credential set
        ticket: str,  # Unused in MQTT connecting
        openudid: str,
        certificate_pem: str,
        private_key: str,
        device_model: str,
        endpoint: str,
    ) -> None:
        self.device_id = device_id
        self.user_id = user_id
        self.app_name = app_name
        self.thing_name = thing_name
        self.openudid = openudid
        self.certificate_pem = certificate_pem
        self.private_key = private_key
        self.device_model = device_model
        self.endpoint = endpoint

        self._mqtt_client: mqtt.Client | None = None
        self._cert_path: str | None = None
        self._key_path: str | None = None
        self._on_message_callback: Callable[[bytes], None] | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._connected_event = asyncio.Event()

    def set_on_message(self, callback: Callable[[bytes], None]):
        """Set callback for incoming raw MQTT payloads."""
        self._on_message_callback = callback

    async def send_command(self, data_payload: dict[str, Any]) -> None:
        """Send a formatted command to the device."""
        if not self._mqtt_client or not self._mqtt_client.is_connected():
            _LOGGER.error("Cannot send command: MQTT client not connected")
            return

        try:
            timestamp = int(time.time() * 1000)

            # Inner payload
            payload = json.dumps(
                {
                    "account_id": self.user_id,
                    "data": data_payload,
                    "device_sn": self.device_id,
                    "protocol": 2,
                    "t": timestamp,
                }
            )

            # Outer wrapper
            # client_id needs to match what Eufy expects for the session?
            # MqttConnect uses:
            # f"android-{self.mqttCredentials['app_name']}-eufy_android_{self.openudid}_{self.mqttCredentials['user_id']}"
            client_id = (
                f"android-{self.app_name}-eufy_android_{self.openudid}_{self.user_id}"
            )

            mqtt_val = {
                "head": {
                    "client_id": client_id,
                    "cmd": 65537,
                    "cmd_status": 2,
                    "msg_seq": 1,
                    "seed": "",
                    "sess_id": client_id,
                    "sign_code": 0,
                    "timestamp": timestamp,
                    "version": "1.0.0.1",
                },
                "payload": payload,
            }

            topic = f"cmd/eufy_home/{self.device_model}/{self.device_id}/req"
            _LOGGER.debug("Sending command to %s: %s", topic, data_payload)

            await self.send_bytes(topic, json.dumps(mqtt_val).encode())

        except Exception as e:
            _LOGGER.error("Error sending command: %s", e)

    async def connect(self):
        """Connect to MQTT broker."""
        self._loop = asyncio.get_running_loop()

        client_id = (
            f"android-{self.app_name}-eufy_android_{self.openudid}_{self.user_id}"
            f"-{int(time.time() * 1000)}"
        )

        _LOGGER.debug("Initializing MQTT client with ID: %s", client_id)

        if self._mqtt_client:
            await self.disconnect()

        # get_blocking_mqtt_client now returns (client, cert_path, key_path)
        result = await self._loop.run_in_executor(
            None,
            partial(
                get_blocking_mqtt_client,
                client_id=client_id,
                username=self.thing_name,
                certificate_pem=self.certificate_pem,
                private_key=self.private_key,
            ),
        )
        self._mqtt_client, self._cert_path, self._key_path = result

        self._mqtt_client.on_connect = self._on_connect
        self._mqtt_client.on_message = self._on_message
        self._mqtt_client.on_disconnect = self._on_disconnect

        # Async connect
        _LOGGER.debug("Connecting to MQTT broker at %s...", self.endpoint)
        await self._loop.run_in_executor(
            None, partial(self._mqtt_client.connect, self.endpoint, 8883, 60)
        )
        self._mqtt_client.loop_start()

    async def disconnect(self):
        """Disconnect from MQTT and clean up certificate files."""
        if self._mqtt_client:
            _LOGGER.debug("Disconnecting MQTT client...")
            self._mqtt_client.loop_stop()
            await self._loop.run_in_executor(None, self._mqtt_client.disconnect)
            self._mqtt_client = None

        # Clean up temporary certificate files
        if self._cert_path:
            try:
                unlink(self._cert_path)
                _LOGGER.debug("Cleaned up certificate file: %s", self._cert_path)
            except OSError as e:
                _LOGGER.warning("Failed to delete cert file %s: %s", self._cert_path, e)
            self._cert_path = None

        if self._key_path:
            try:
                unlink(self._key_path)
                _LOGGER.debug("Cleaned up key file: %s", self._key_path)
            except OSError as e:
                _LOGGER.warning("Failed to delete key file %s: %s", self._key_path, e)
            self._key_path = None

    def _on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            _LOGGER.info("Connected to MQTT Broker!")
            self._connected_event.set()
            # Subscribe to specific device topic
            topic = f"cmd/eufy_home/{self.device_model}/{self.device_id}/res"
            _LOGGER.debug("Subscribing to %s", topic)
            client.subscribe(topic)
        else:
            _LOGGER.error("Failed to connect to MQTT, return code %d", rc)

    def _on_disconnect(self, client, userdata, rc):
        _LOGGER.warning("Disconnected from MQTT broker, rc=%d", rc)
        self._connected_event.clear()

    def _on_message(self, client, userdata, msg):
        """Handle incoming MQTT messages."""
        try:
            payload = msg.payload
            _LOGGER.debug("Received MQTT message on %s: %s", msg.topic, payload)
            if self._on_message_callback:
                if self._loop:
                    self._loop.call_soon_threadsafe(self._on_message_callback, payload)
        except Exception as e:
            _LOGGER.exception("Error handling MQTT message: %s", e)

    async def send_bytes(self, topic: str, payload: bytes):
        """Send raw bytes to the device."""
        if not self._mqtt_client or not self._loop:
            _LOGGER.error("Cannot send message: MQTT client not connected")
            return

        await self._loop.run_in_executor(
            None, partial(self._mqtt_client.publish, topic, payload)
        )
