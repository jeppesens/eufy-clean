from __future__ import annotations

import asyncio
import json
import logging
import os
import ssl
import tempfile
import time
from collections.abc import Callable
from functools import partial
from typing import Any

from paho.mqtt import client as mqtt
from paho.mqtt.enums import CallbackAPIVersion
from paho.mqtt.reasoncodes import ReasonCode

_LOGGER = logging.getLogger(__name__)

# CONNACK reasons that reject the client identity: retrying cannot help.
_AUTH_REJECTED_REASONS = frozenset({"Bad user name or password", "Not authorized"})

ConnectionListener = Callable[[bool, bool], None]


def _build_tls_context(certificate_pem: str, private_key: str) -> ssl.SSLContext:
    """A verifying TLS >= 1.2 client context holding the client certificate.

    ``load_cert_chain`` reads only from paths, so the PEMs pass through a
    private temp directory that is removed before this returns.
    """
    context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    with tempfile.TemporaryDirectory(prefix="robovac_mqtt_") as tmp:
        cert_path = os.path.join(tmp, "client.pem")
        key_path = os.path.join(tmp, "client.key")
        for path, text in ((cert_path, certificate_pem), (key_path, private_key)):
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w") as fh:
                fh.write(text)
        context.load_cert_chain(cert_path, key_path)
    return context


def get_blocking_mqtt_client(
    client_id: str,
    username: str,
    certificate_pem: str,
    private_key: str,
) -> mqtt.Client:
    """Create a blocking Paho MQTT client with mutual TLS; no file outlives it."""
    client = mqtt.Client(
        CallbackAPIVersion.VERSION2,
        client_id=client_id,
        transport="tcp",
    )
    client.username_pw_set(username)
    # Sets check_hostname and CERT_REQUIRED from the context.
    client.tls_set_context(_build_tls_context(certificate_pem, private_key))
    return client


def _stop_blocking(client: mqtt.Client) -> None:
    """Disconnect, then join the network thread (it may sit in a reconnect wait)."""
    client.disconnect()
    client.loop_stop()


class EufyCleanClient:
    """Handles low-level MQTT connectivity and protocol transport."""

    def __init__(
        self,
        device_id: str,
        user_id: str,
        app_name: str,
        thing_name: str,
        access_key: str,  # unused for MQTT, part of the credential set
        ticket: str,  # unused for MQTT
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
        self._client_id: str | None = None
        self._on_message_callback: Callable[[bytes], None] | None = None
        self._on_biz_message_callback: Callable[[bytes], None] | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._connected_event = asyncio.Event()
        self._connection_listener: ConnectionListener | None = None
        # Last CONNACK rejected the identity; reported with the disconnect
        # that follows it.
        self._auth_rejected = False

    def set_connection_listener(self, callback: ConnectionListener | None) -> None:
        """Call ``callback(connected, auth_failed)`` on the event loop on every
        broker connect, refused connect and disconnect.

        ``auth_failed`` is True when the broker rejected the client identity
        (bad credentials or not authorised).
        """
        self._connection_listener = callback

    @property
    def is_connected(self) -> bool:
        """True while the broker session is up."""
        return bool(self._mqtt_client and self._mqtt_client.is_connected())

    def _notify_connection(self, connected: bool, auth_failed: bool) -> None:
        """Hand a connection change to the event loop (called from paho's thread)."""
        if self._loop is None:
            return
        if connected:
            self._loop.call_soon_threadsafe(self._connected_event.set)
        else:
            self._loop.call_soon_threadsafe(self._connected_event.clear)
        if self._connection_listener is not None:
            self._loop.call_soon_threadsafe(
                self._connection_listener, connected, auth_failed
            )

    def set_on_message(self, callback: Callable[[bytes], None]):
        """Set callback for incoming raw MQTT payloads."""
        self._on_message_callback = callback

    def set_on_biz_message(self, callback: Callable[[bytes], None]):
        """Set callback for biz/ MQTT topic payloads (map stream data)."""
        self._on_biz_message_callback = callback

    async def send_command(self, data_payload: dict[str, Any]) -> None:
        """Send a formatted command to the device.

        Raises ConnectionError when the broker session is down, and whatever
        the publish raises; the coordinator reports both to the caller.
        """
        if not self.is_connected:
            raise ConnectionError("MQTT client not connected")

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

        client_id = (
            self._client_id
            or f"android-{self.app_name}-eufy_android_{self.openudid}_{self.user_id}"
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

    async def connect(self):
        """Connect to MQTT broker."""
        self._loop = asyncio.get_running_loop()

        client_id = (
            f"android-{self.app_name}-eufy_android_{self.openudid}_{self.user_id}"
            f"-{int(time.time() * 1000)}"
        )
        self._client_id = client_id

        # The client id embeds the openudid and the user id; never log it in full.
        _LOGGER.debug("Initializing MQTT client for %s", self.app_name)

        if self._mqtt_client:
            await self.disconnect()

        mqtt_client = await self._loop.run_in_executor(
            None,
            partial(
                get_blocking_mqtt_client,
                client_id=client_id,
                username=self.thing_name,
                certificate_pem=self.certificate_pem,
                private_key=self.private_key,
            ),
        )
        mqtt_client.on_connect = self._on_connect
        mqtt_client.on_message = self._on_message
        mqtt_client.on_disconnect = self._on_disconnect

        _LOGGER.debug("Connecting to MQTT broker at %s...", self.endpoint)
        try:
            await self._loop.run_in_executor(
                None, partial(mqtt_client.connect, self.endpoint, 8883, 60)
            )
            mqtt_client.loop_start()
        except BaseException:
            await self._loop.run_in_executor(None, _stop_blocking, mqtt_client)
            raise
        self._mqtt_client = mqtt_client

    async def disconnect(self):
        """Disconnect from MQTT and join paho's network thread off the loop."""
        mqtt_client = self._mqtt_client
        if mqtt_client is None:
            return
        self._mqtt_client = None
        _LOGGER.debug("Disconnecting MQTT client...")
        loop = self._loop or asyncio.get_running_loop()
        await loop.run_in_executor(None, _stop_blocking, mqtt_client)

    def _on_connect(
        self,
        client: mqtt.Client,
        userdata: Any,
        flags: Any,
        reason_code: ReasonCode,
        properties: Any = None,
    ) -> None:
        if reason_code.is_failure:
            self._auth_rejected = str(reason_code) in _AUTH_REJECTED_REASONS
            _LOGGER.error("MQTT broker refused the connection: %s", reason_code)
            self._notify_connection(False, self._auth_rejected)
            return
        self._auth_rejected = False
        _LOGGER.info("Connected to MQTT Broker!")
        self._notify_connection(True, False)
        if self.device_id:
            cmd_topic = f"cmd/eufy_home/{self.device_model}/{self.device_id}/res"
            _LOGGER.debug("Subscribing to %s", cmd_topic)
            client.subscribe(cmd_topic)
            biz_topic = f"biz/eufy_home/{self.device_model}/{self.device_id}/res"
            _LOGGER.debug("Subscribing to %s", biz_topic)
            client.subscribe(biz_topic)

    def _on_disconnect(
        self,
        client: mqtt.Client,
        userdata: Any,
        flags: Any,
        reason_code: ReasonCode,
        properties: Any = None,
    ) -> None:
        if reason_code.is_failure:
            _LOGGER.warning("Disconnected from MQTT broker unexpectedly: %s", reason_code)
        else:
            _LOGGER.debug("Disconnected from MQTT broker (clean)")
        self._notify_connection(False, self._auth_rejected)

    def _on_message(self, client, userdata, msg):
        """Handle incoming MQTT messages."""
        try:
            payload = msg.payload
            _LOGGER.debug("Received MQTT message on %s", msg.topic)
            biz_topic = f"biz/eufy_home/{self.device_model}/{self.device_id}/res"
            if msg.topic == biz_topic:
                if self._on_biz_message_callback and self._loop:
                    self._loop.call_soon_threadsafe(self._on_biz_message_callback, payload)
            else:
                if self._on_message_callback and self._loop:
                    self._loop.call_soon_threadsafe(self._on_message_callback, payload)
        except Exception as e:
            _LOGGER.exception("Error handling MQTT message: %s", e)

    async def send_bytes(self, topic: str, payload: bytes):
        """Send raw bytes to the device."""
        if not self._mqtt_client or not self._loop:
            raise ConnectionError("MQTT client not connected")

        info = await self._loop.run_in_executor(
            None, partial(self._mqtt_client.publish, topic, payload)
        )
        if info.rc != mqtt.MQTT_ERR_SUCCESS:
            raise ConnectionError(f"MQTT publish failed: {mqtt.error_string(info.rc)}")
