from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import ssl
import tempfile
import time
from collections.abc import Callable
from functools import partial
from os import unlink
from typing import Any

from paho.mqtt import client as mqtt

from ..const import MQTT_SUBACK_FAILURE

_LOGGER = logging.getLogger(__name__)


def _mqtt_uuid_from(install_id: str) -> str:
    """Deterministic 16-hex mqttUuid derived from openudid (matches eufy-sdk)."""
    return hashlib.sha256(install_id.encode("utf-8")).hexdigest()[:16]


def get_blocking_mqtt_client(
    client_id: str,
    username: str | None,
    certificate_pem: str,
    private_key: str,
    ca_certs_pem: str | None = None,
) -> tuple[mqtt.Client, str, str, str | None]:
    """Create a blocking Paho MQTT client with mutual TLS settings.

    Returns:
        Tuple of (client, cert_path, key_path, root_ca_path) - caller cleans up files.
    """
    client = mqtt.Client(
        client_id=client_id,
        transport="tcp",
    )
    if username:
        client.username_pw_set(username)

    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".pem") as cert_file:
        cert_file.write(certificate_pem)
        cert_path = cert_file.name

    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".key") as key_file:
        key_file.write(private_key)
        key_path = key_file.name
    os.chmod(key_path, 0o600)

    root_ca_path: str | None = None
    if ca_certs_pem:
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".ca.pem") as ca_file:
            ca_file.write(ca_certs_pem)
            root_ca_path = ca_file.name

    client.tls_set(
        ca_certs=root_ca_path,
        certfile=cert_path,
        keyfile=key_path,
        cert_reqs=ssl.CERT_REQUIRED,
        tls_version=ssl.PROTOCOL_TLSv1_2,
    )

    return client, cert_path, key_path, root_ca_path


class EufyCleanClient:
    """Handles low-level MQTT connectivity and protocol transport."""

    def __init__(
        self,
        device_id: str,
        user_id: str,
        app_name: str,
        thing_name: str,
        access_key: str,
        ticket: str,
        openudid: str,
        certificate_pem: str,
        private_key: str,
        device_model: str,
        endpoint: str,
        ca_certs_pem: str | None = None,
        port: int = 8883,
    ) -> None:
        self.device_id = device_id
        self.user_id = user_id
        self.app_name = app_name
        self.thing_name = thing_name
        self.openudid = openudid
        self.certificate_pem = certificate_pem
        self.private_key = private_key
        self.ca_certs_pem = ca_certs_pem
        self.device_model = device_model
        self.endpoint = endpoint
        self.port = port

        self._mqtt_client: mqtt.Client | None = None
        self._cert_path: str | None = None
        self._key_path: str | None = None
        self._root_ca_path: str | None = None
        self._client_id: str | None = None
        self._use_thing_name_id: bool = False
        self._pending_subscriptions: dict[int, str] = {}
        self._on_message_callback: Callable[[bytes], None] | None = None
        self._on_biz_message_callback: Callable[[bytes], None] | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._connected_event = asyncio.Event()

    def set_on_message(self, callback: Callable[[bytes], None]):
        """Set callback for incoming raw MQTT payloads."""
        self._on_message_callback = callback

    def set_on_biz_message(self, callback: Callable[[bytes], None]):
        """Set callback for biz/ MQTT topic payloads (map stream data)."""
        self._on_biz_message_callback = callback

    def _build_client_id(self) -> str:
        if self._use_thing_name_id and self.thing_name:
            return self.thing_name
        if self.app_name == "eufy_mega":
            mqtt_uuid = _mqtt_uuid_from(self.openudid)
            return f"android-{self.app_name}-{self.user_id}-{mqtt_uuid}-{int(time.time())}"
        return (
            f"android-{self.app_name}-eufy_android_{self.openudid}_{self.user_id}"
            f"-{int(time.time() * 1000)}"
        )

    async def send_command(self, data_payload: dict[str, Any]) -> None:
        """Send a formatted command to the device."""
        if not self._mqtt_client or not self._mqtt_client.is_connected():
            _LOGGER.error("Cannot send command: MQTT client not connected")
            return

        try:
            timestamp = int(time.time() * 1000)

            payload = json.dumps(
                {
                    "account_id": self.user_id,
                    "data": data_payload,
                    "device_sn": self.device_id,
                    "protocol": 2,
                    "t": timestamp,
                }
            )

            client_id = self._client_id or self._build_client_id()

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

        except Exception as e:  # noqa: BLE001
            _LOGGER.error("Error sending command: %s", e)

    async def connect(self):
        """Connect to MQTT broker."""
        self._loop = asyncio.get_running_loop()

        client_id = self._build_client_id()
        self._client_id = client_id

        _LOGGER.debug("Initializing MQTT client with ID: %s", client_id)

        if self._mqtt_client:
            await self.disconnect()

        # eufy_mega mTLS certs authenticate purely by certificate; legacy uses thing_name.
        username = None if self.app_name == "eufy_mega" else self.thing_name

        result = await self._loop.run_in_executor(
            None,
            partial(
                get_blocking_mqtt_client,
                client_id=client_id,
                username=username,
                certificate_pem=self.certificate_pem,
                private_key=self.private_key,
                ca_certs_pem=self.ca_certs_pem,
            ),
        )
        self._mqtt_client, self._cert_path, self._key_path, self._root_ca_path = result

        self._mqtt_client.on_connect = self._on_connect
        self._mqtt_client.on_subscribe = self._on_subscribe
        self._mqtt_client.on_message = self._on_message
        self._mqtt_client.on_disconnect = self._on_disconnect

        _LOGGER.debug("Connecting to MQTT broker at %s:%s...", self.endpoint, self.port)
        await self._loop.run_in_executor(
            None, partial(self._mqtt_client.connect, self.endpoint, self.port, 60)
        )
        self._mqtt_client.loop_start()

    async def _reconnect_with_thing_name(self) -> None:
        self._use_thing_name_id = True
        await self.connect()

    async def disconnect(self):
        """Disconnect from MQTT and clean up certificate files."""
        if self._mqtt_client:
            _LOGGER.debug("Disconnecting MQTT client...")
            self._mqtt_client.loop_stop()
            loop = self._loop or asyncio.get_running_loop()
            await loop.run_in_executor(None, self._mqtt_client.disconnect)
            self._mqtt_client = None

        for attr in ("_cert_path", "_key_path", "_root_ca_path"):
            path = getattr(self, attr)
            if path:
                try:
                    unlink(path)
                except OSError as e:
                    _LOGGER.warning("Failed to delete temp TLS file %s: %s", path, e)
                setattr(self, attr, None)

    def _on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            _LOGGER.info("Connected to MQTT Broker!")
            if self._loop:
                self._loop.call_soon_threadsafe(self._connected_event.set)
            if self.device_id:
                self._pending_subscriptions.clear()
                for topic in (
                    f"cmd/eufy_home/{self.device_model}/{self.device_id}/res",
                    f"biz/eufy_home/{self.device_model}/{self.device_id}/res",
                ):
                    _LOGGER.debug("Subscribing to %s", topic)
                    _, mid = client.subscribe(topic)
                    self._pending_subscriptions[mid] = topic
        elif rc == 5 and self.app_name == "eufy_mega" and not self._use_thing_name_id and self.thing_name:
            _LOGGER.warning(
                "MQTT broker refused app-shaped client ID (rc=5); falling back to thing_name"
            )
            if self._loop:
                asyncio.run_coroutine_threadsafe(
                    self._reconnect_with_thing_name(), self._loop
                )
        else:
            _LOGGER.error("Failed to connect to MQTT, return code %d", rc)

    def _on_subscribe(self, client, userdata, mid, granted_qos):
        topic = self._pending_subscriptions.pop(mid, "an unknown topic")
        for qos in granted_qos:
            if qos >= MQTT_SUBACK_FAILURE:
                _LOGGER.warning(
                    "MQTT broker refused the subscription to %s (SUBACK %s); the "
                    "robot's updates on this topic will not reach Home Assistant",
                    topic,
                    qos,
                )
            else:
                _LOGGER.debug("Subscribed to %s (granted QoS %s)", topic, qos)

    def _on_disconnect(self, client, userdata, rc):
        if rc == 0:
            _LOGGER.debug("Disconnected from MQTT broker (clean)")
        else:
            _LOGGER.warning("Disconnected from MQTT broker unexpectedly, rc=%d", rc)
        if self._loop:
            self._loop.call_soon_threadsafe(self._connected_event.clear)

    def _on_message(self, client, userdata, msg):
        """Handle incoming MQTT messages."""
        try:
            payload = msg.payload
            _LOGGER.debug("Received MQTT message on %s", msg.topic)
            biz_topic = f"biz/eufy_home/{self.device_model}/{self.device_id}/res"
            if msg.topic == biz_topic:
                if self._on_biz_message_callback and self._loop:
                    self._loop.call_soon_threadsafe(
                        self._on_biz_message_callback, payload
                    )
            else:
                if self._on_message_callback and self._loop:
                    self._loop.call_soon_threadsafe(self._on_message_callback, payload)
        except Exception as e:  # noqa: BLE001
            _LOGGER.exception("Error handling MQTT message: %s", e)

    async def send_bytes(self, topic: str, payload: bytes):
        """Send raw bytes to the device."""
        if not self._mqtt_client or not self._loop:
            _LOGGER.error("Cannot send message: MQTT client not connected")
            return

        await self._loop.run_in_executor(
            None, partial(self._mqtt_client.publish, topic, payload)
        )
