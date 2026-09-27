"""Unit tests for the MQTT client (api/client.py)."""

import asyncio
import datetime
import ssl
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID
from paho.mqtt import client as mqtt
from paho.mqtt.enums import CallbackAPIVersion
from paho.mqtt.packettypes import PacketTypes
from paho.mqtt.reasoncodes import ReasonCode

from custom_components.robovac_mqtt.api import client as client_mod
from custom_components.robovac_mqtt.api.client import (
    EufyCleanClient,
    get_blocking_mqtt_client,
)


def _make_client() -> EufyCleanClient:
    """Create a EufyCleanClient instance for testing (no real connection)."""
    return EufyCleanClient(
        device_id="TEST123",
        user_id="user1",
        app_name="eufy_home",
        thing_name="thing1",
        access_key="",
        ticket="",
        openudid="abc123",
        certificate_pem="cert",
        private_key="key",
        device_model="T2320",
        endpoint="mqtt.example.com",
    )


def _self_signed_pair() -> tuple[str, str]:
    """A synthetic client certificate and key, PEM encoded."""
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "thing.example.com")])
    now = datetime.datetime.now(datetime.UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(1)
        .not_valid_before(now)
        .not_valid_after(now + datetime.timedelta(days=1))
        .sign(key, hashes.SHA256())
    )
    cert_pem = cert.public_bytes(serialization.Encoding.PEM).decode()
    key_pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    return cert_pem, key_pem


def _connack(name: str) -> ReasonCode:
    return ReasonCode(PacketTypes.CONNACK, name)


def _disconnect(name: str) -> ReasonCode:
    return ReasonCode(PacketTypes.DISCONNECT, name)


# --- client construction / TLS ---


def test_blocking_client_leaves_no_key_file_behind(tmp_path, monkeypatch):
    """The key reaches the SSLContext once; no PEM file outlives the builder."""
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    cert_pem, key_pem = _self_signed_pair()

    client = get_blocking_mqtt_client("cid", "thing1", cert_pem, key_pem)

    assert not list(tmp_path.iterdir())
    assert client.callback_api_version == CallbackAPIVersion.VERSION2
    ctx = client._ssl_context
    assert ctx is not None
    assert ctx.verify_mode == ssl.CERT_REQUIRED
    assert ctx.check_hostname is True
    assert ctx.minimum_version >= ssl.TLSVersion.TLSv1_2
    assert client._tls_insecure is False


def test_blocking_client_bad_key_leaves_no_file_behind(tmp_path, monkeypatch):
    """A PEM the context rejects still leaves nothing on disk."""
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))

    with pytest.raises(ssl.SSLError):
        get_blocking_mqtt_client("cid", "thing1", "not a cert", "not a key")

    assert not list(tmp_path.iterdir())


@pytest.mark.asyncio
async def test_connect_failure_stops_the_client_and_reraises():
    """A failed broker connect stops paho and leaves no client behind."""
    client = _make_client()
    fake = MagicMock()
    fake.connect.side_effect = OSError("unreachable")

    with patch.object(client_mod, "get_blocking_mqtt_client", return_value=fake):
        with pytest.raises(OSError):
            await client.connect()

    fake.disconnect.assert_called_once()
    fake.loop_stop.assert_called_once()
    assert client._mqtt_client is None


@pytest.mark.asyncio
async def test_disconnect_runs_disconnect_and_loop_stop_in_executor():
    """disconnect() then loop_stop() (a thread join) happen off the event loop."""
    client = _make_client()
    fake = MagicMock()
    order: list[str] = []
    fake.disconnect.side_effect = lambda: order.append("disconnect")
    fake.loop_stop.side_effect = lambda: order.append("loop_stop")
    client._mqtt_client = fake
    loop = asyncio.get_running_loop()
    client._loop = loop

    with patch.object(loop, "run_in_executor", wraps=loop.run_in_executor) as rie:
        await client.disconnect()

    assert order == ["disconnect", "loop_stop"]
    rie.assert_called_once_with(None, client_mod._stop_blocking, fake)
    assert client._mqtt_client is None


@pytest.mark.asyncio
async def test_disconnect_no_loop_uses_running_loop():
    """disconnect() falls back to asyncio.get_running_loop() when _loop is None."""
    client = _make_client()
    assert client._loop is None
    client._mqtt_client = MagicMock()

    with patch("asyncio.get_running_loop") as mock_get_loop:
        mock_loop = MagicMock()
        mock_loop.run_in_executor = AsyncMock()
        mock_get_loop.return_value = mock_loop

        await client.disconnect()

        mock_get_loop.assert_called_once()
        mock_loop.run_in_executor.assert_called_once()


# --- paho v2 callbacks ---


def test_on_connect_success_sets_event_and_subscribes():
    """A successful CONNACK sets the event and subscribes to both topics."""
    client = _make_client()
    mock_loop = MagicMock()
    client._loop = mock_loop

    mock_mqtt = MagicMock()
    client._on_connect(mock_mqtt, None, MagicMock(), _connack("Success"), None)

    mock_loop.call_soon_threadsafe.assert_called_once_with(client._connected_event.set)
    assert mock_mqtt.subscribe.call_count == 2
    mock_mqtt.subscribe.assert_any_call("cmd/eufy_home/T2320/TEST123/res")
    mock_mqtt.subscribe.assert_any_call("biz/eufy_home/T2320/TEST123/res")


def test_on_connect_failure_does_not_subscribe():
    """A refused CONNACK neither sets the event nor subscribes."""
    client = _make_client()
    mock_loop = MagicMock()
    client._loop = mock_loop

    mock_mqtt = MagicMock()
    client._on_connect(mock_mqtt, None, MagicMock(), _connack("Server unavailable"), None)

    mock_loop.call_soon_threadsafe.assert_called_once_with(
        client._connected_event.clear
    )
    mock_mqtt.subscribe.assert_not_called()


def test_on_disconnect_clears_event():
    """A disconnect clears the connected event via call_soon_threadsafe."""
    client = _make_client()
    mock_loop = MagicMock()
    client._loop = mock_loop

    client._on_disconnect(MagicMock(), None, MagicMock(), _disconnect("Success"), None)

    mock_loop.call_soon_threadsafe.assert_called_once_with(
        client._connected_event.clear
    )


def _listener_calls(mock_loop: MagicMock, listener) -> list[tuple]:
    return [
        c.args[1:]
        for c in mock_loop.call_soon_threadsafe.call_args_list
        if c.args and c.args[0] is listener
    ]


def test_connection_listener_reports_connect_and_disconnect():
    """The listener gets (connected, auth_failed) on the loop for both edges."""
    client = _make_client()
    mock_loop = MagicMock()
    client._loop = mock_loop
    listener = MagicMock()
    client.set_connection_listener(listener)

    client._on_connect(MagicMock(), None, MagicMock(), _connack("Success"), None)
    client._on_disconnect(
        MagicMock(), None, MagicMock(), _disconnect("Unspecified error"), None
    )

    assert _listener_calls(mock_loop, listener) == [(True, False), (False, False)]
    listener.assert_not_called()  # only ever via the loop


@pytest.mark.parametrize("reason", ["Not authorized", "Bad user name or password"])
def test_connection_listener_flags_auth_rejection(reason):
    """A CONNACK that rejects the identity reports auth_failed=True, also on
    the disconnect that follows it."""
    client = _make_client()
    mock_loop = MagicMock()
    client._loop = mock_loop
    listener = MagicMock()
    client.set_connection_listener(listener)

    client._on_connect(MagicMock(), None, MagicMock(), _connack(reason), None)
    client._on_disconnect(
        MagicMock(), None, MagicMock(), _disconnect("Unspecified error"), None
    )

    assert _listener_calls(mock_loop, listener) == [(False, True), (False, True)]


def test_connection_listener_other_refusal_is_not_auth():
    """A broker outage refusal is not an auth failure."""
    client = _make_client()
    mock_loop = MagicMock()
    client._loop = mock_loop
    listener = MagicMock()
    client.set_connection_listener(listener)

    client._on_connect(MagicMock(), None, MagicMock(), _connack("Server unavailable"), None)

    assert _listener_calls(mock_loop, listener) == [(False, False)]


# --- sending ---


@pytest.mark.asyncio
async def test_send_command_raises_without_client():
    """send_command raises when there is no MQTT client, so the caller sees it."""
    client = _make_client()
    assert client._mqtt_client is None

    with pytest.raises(ConnectionError):
        await client.send_command({"test": "value"})


@pytest.mark.asyncio
async def test_send_command_raises_when_disconnected():
    """send_command raises and does not publish while the session is down."""
    client = _make_client()
    mock_mqtt = MagicMock()
    mock_mqtt.is_connected.return_value = False
    client._mqtt_client = mock_mqtt

    with pytest.raises(ConnectionError):
        await client.send_command({"test": "value"})

    mock_mqtt.publish.assert_not_called()


@pytest.mark.asyncio
async def test_send_command_raises_on_publish_error():
    """A publish paho refuses surfaces as ConnectionError."""
    client = _make_client()
    mock_mqtt = MagicMock()
    mock_mqtt.is_connected.return_value = True
    mock_mqtt.publish.return_value = MagicMock(rc=mqtt.MQTT_ERR_NO_CONN)
    client._mqtt_client = mock_mqtt
    client._loop = asyncio.get_running_loop()

    with pytest.raises(ConnectionError):
        await client.send_command({"test": "value"})


@pytest.mark.asyncio
async def test_send_command_publishes_when_connected():
    """A connected client publishes to the device's req topic."""
    client = _make_client()
    mock_mqtt = MagicMock()
    mock_mqtt.is_connected.return_value = True
    mock_mqtt.publish.return_value = MagicMock(rc=mqtt.MQTT_ERR_SUCCESS)
    client._mqtt_client = mock_mqtt
    client._loop = asyncio.get_running_loop()

    await client.send_command({"test": "value"})

    topic = mock_mqtt.publish.call_args.args[0]
    assert topic == "cmd/eufy_home/T2320/TEST123/req"
