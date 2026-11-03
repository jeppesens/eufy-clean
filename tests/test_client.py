"""Unit tests for the MQTT client (api/client.py)."""

import asyncio
import datetime
import logging
import socket
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
    Rejection,
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


def _suback(value: int) -> ReasonCode:
    return ReasonCode(PacketTypes.SUBACK, identifier=value)


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
    mock_mqtt.subscribe.return_value = (mqtt.MQTT_ERR_SUCCESS, 1)
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


def test_on_subscribe_warns_only_for_refused_topic(caplog):
    """A SUBACK of 128 logs a warning naming the refused topic; a grant doesn't."""
    client = _make_client()
    mids = {
        "cmd/eufy_home/T2320/TEST123/res": 1,
        "biz/eufy_home/T2320/TEST123/res": 2,
    }
    mock_mqtt = MagicMock()
    mock_mqtt.subscribe.side_effect = lambda topic: (mqtt.MQTT_ERR_SUCCESS, mids[topic])
    client._on_connect(mock_mqtt, None, MagicMock(), _connack("Success"), None)

    with caplog.at_level(logging.DEBUG):
        client._on_subscribe(mock_mqtt, None, 1, [_suback(128)], None)
        client._on_subscribe(mock_mqtt, None, 2, [_suback(0)], None)

    warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "refused the subscription to cmd/eufy_home/T2320/TEST123/res" in warnings[0]
    assert "Subscribed to biz/eufy_home/T2320/TEST123/res (granted QoS 0)" in caplog.text


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
    """The listener gets (connected, rejection) on the loop for both edges."""
    client = _make_client()
    mock_loop = MagicMock()
    client._loop = mock_loop
    listener = MagicMock()
    client.set_connection_listener(listener)
    paho = MagicMock()
    paho.subscribe.return_value = (mqtt.MQTT_ERR_SUCCESS, 1)

    client._on_connect(paho, None, MagicMock(), _connack("Success"), None)
    client._on_disconnect(
        MagicMock(), None, MagicMock(), _disconnect("Unspecified error"), None
    )

    assert _listener_calls(mock_loop, listener) == [(True, None), (False, None)]
    listener.assert_not_called()  # only ever via the loop


@pytest.mark.parametrize("reason", ["Not authorized", "Bad user name or password"])
def test_connection_listener_flags_auth_rejection(reason):
    """A CONNACK that rejects the identity reports an explicit rejection once;
    the disconnect paho reports after it does not count it again."""
    client = _make_client()
    mock_loop = MagicMock()
    client._loop = mock_loop
    listener = MagicMock()
    client.set_connection_listener(listener)

    client._on_socket_open(MagicMock(), None, MagicMock())
    client._on_connect(MagicMock(), None, MagicMock(), _connack(reason), None)
    client._on_disconnect(
        MagicMock(), None, MagicMock(), _disconnect("Unspecified error"), None
    )

    assert _listener_calls(mock_loop, listener) == [
        (False, Rejection.EXPLICIT), (False, None)
    ]


def test_connection_listener_other_refusal_is_not_auth():
    """A broker outage refusal is not an auth failure."""
    client = _make_client()
    mock_loop = MagicMock()
    client._loop = mock_loop
    listener = MagicMock()
    client.set_connection_listener(listener)

    client._on_connect(MagicMock(), None, MagicMock(), _connack("Server unavailable"), None)

    assert _listener_calls(mock_loop, listener) == [(False, None)]


def _ssl_error(reason: str, cls: type[ssl.SSLError] = ssl.SSLError) -> ssl.SSLError:
    """An SSLError as the ssl module raises it for an OpenSSL ``reason``."""
    err = cls(1, f"[SSL: {reason}] alert (_ssl.c:1081)")
    err.library = "SSL"
    err.reason = reason
    return err


_CERT_ALERTS = [
    "SSLV3_ALERT_BAD_CERTIFICATE",
    "SSLV3_ALERT_CERTIFICATE_REVOKED",
    "SSLV3_ALERT_CERTIFICATE_EXPIRED",
    "SSLV3_ALERT_CERTIFICATE_UNKNOWN",
    "TLSV1_ALERT_UNKNOWN_CA",
    "TLSV13_ALERT_CERTIFICATE_REQUIRED",
]

# How a broker closes the connection inside the handshake without an alert.
_SILENT_HANDSHAKE_ERRORS = [
    _ssl_error("UNEXPECTED_EOF_WHILE_READING", ssl.SSLEOFError),
    ConnectionResetError(104, "Connection reset by peer"),
]

_NOT_REJECTIONS = [
    _ssl_error("SSLV3_ALERT_HANDSHAKE_FAILURE"),
    _ssl_error("WRONG_VERSION_NUMBER"),
    # the client refusing the broker's certificate is not a verdict on ours
    _ssl_error("CERTIFICATE_VERIFY_FAILED", ssl.SSLCertVerificationError),
    ssl.SSLError(1, "no reason"),
    # plain TCP connect failures
    ConnectionRefusedError(111, "Connection refused"),
    TimeoutError("timed out"),
    socket.gaierror(-2, "Name or service not known"),
    OSError("no route"),
]


@pytest.mark.parametrize("reason", _CERT_ALERTS)
def test_a_certificate_alert_classifies_as_an_explicit_rejection(reason):
    assert client_mod.handshake_rejection(_ssl_error(reason)) is Rejection.EXPLICIT


@pytest.mark.parametrize("err", _SILENT_HANDSHAKE_ERRORS)
def test_a_handshake_the_broker_cut_off_classifies_as_a_silent_rejection(err):
    assert client_mod.handshake_rejection(err) is Rejection.SILENT


@pytest.mark.parametrize("err", _NOT_REJECTIONS)
def test_network_and_other_tls_errors_are_not_rejections(err):
    assert client_mod.handshake_rejection(err) is None


def _failed_reconnect(client: EufyCleanClient, err: BaseException) -> None:
    """What paho does when a reconnect raises: on_connect_fail inside the except."""
    try:
        raise err
    except OSError:
        client._on_connect_fail(MagicMock(), None)


@pytest.mark.parametrize(
    ("err", "rejection"),
    [
        (_ssl_error("SSLV3_ALERT_CERTIFICATE_REVOKED"), Rejection.EXPLICIT),
        *((err, Rejection.SILENT) for err in _SILENT_HANDSHAKE_ERRORS),
    ],
)
def test_a_reconnect_the_broker_turned_away_is_reported(err, rejection):
    client = _make_client()
    mock_loop = MagicMock()
    client._loop = mock_loop
    listener = MagicMock()
    client.set_connection_listener(listener)

    _failed_reconnect(client, err)

    assert _listener_calls(mock_loop, listener) == [(False, rejection)]


@pytest.mark.parametrize("err", _NOT_REJECTIONS)
def test_a_reconnect_failing_otherwise_is_not_counted(err):
    client = _make_client()
    mock_loop = MagicMock()
    client._loop = mock_loop
    listener = MagicMock()
    client.set_connection_listener(listener)

    _failed_reconnect(client, err)

    assert _listener_calls(mock_loop, listener) == []


def test_a_connection_closed_before_the_connack_is_a_silent_rejection():
    """TLS and CONNECT went through, then the broker closed without answering;
    a later disconnect without a new attempt is not counted again."""
    client = _make_client()
    mock_loop = MagicMock()
    client._loop = mock_loop
    listener = MagicMock()
    client.set_connection_listener(listener)
    dropped = _disconnect("Unspecified error")

    client._on_socket_open(MagicMock(), None, MagicMock())
    client._on_disconnect(MagicMock(), None, MagicMock(), dropped, None)
    client._on_disconnect(MagicMock(), None, MagicMock(), dropped, None)

    assert _listener_calls(mock_loop, listener) == [
        (False, Rejection.SILENT), (False, None)
    ]


@pytest.mark.parametrize(
    ("connack", "disconnect", "calls"),
    [
        ("Success", "Unspecified error", [(True, None), (False, None)]),
        (None, "Keep alive timeout", [(False, None)]),
        (None, "Success", [(False, None)]),
    ],
    ids=["answered", "keepalive-timeout", "client-disconnect"],
)
def test_an_attempt_answered_timed_out_or_ended_by_the_client_is_not_a_rejection(
    connack, disconnect, calls
):
    client = _make_client()
    mock_loop = MagicMock()
    client._loop = mock_loop
    listener = MagicMock()
    client.set_connection_listener(listener)
    paho = MagicMock()
    paho.subscribe.return_value = (mqtt.MQTT_ERR_SUCCESS, 1)

    client._on_socket_open(paho, None, MagicMock())
    if connack:
        client._on_connect(paho, None, MagicMock(), _connack(connack), None)
    client._on_disconnect(paho, None, MagicMock(), _disconnect(disconnect), None)

    assert _listener_calls(mock_loop, listener) == calls


# paho's log line for a read that failed on a TLS 1.3 alert from the broker
_TLS13_READ_ALERT = (
    "failed to receive on socket: [SSL: TLSV13_ALERT_CERTIFICATE_REQUIRED] "
    "tlsv13 alert certificate required (_ssl.c:2710)"
)


def test_a_certificate_alert_on_a_read_counts_with_its_disconnect_once():
    """TLS 1.3: the alert reaches only paho's log, then the disconnect; it is
    an explicit rejection, not a connection closed without an answer."""
    client = _make_client()
    mock_loop = MagicMock()
    client._loop = mock_loop
    listener = MagicMock()
    client.set_connection_listener(listener)
    dropped = _disconnect("Unspecified error")

    client._on_socket_open(MagicMock(), None, MagicMock())
    client._on_log(MagicMock(), None, mqtt.MQTT_LOG_ERR, _TLS13_READ_ALERT)
    client._on_disconnect(MagicMock(), None, MagicMock(), dropped, None)
    client._on_disconnect(MagicMock(), None, MagicMock(), dropped, None)

    assert _listener_calls(mock_loop, listener) == [
        (False, Rejection.EXPLICIT), (False, None)
    ]


@pytest.mark.parametrize(
    ("level", "line"),
    [
        (mqtt.MQTT_LOG_ERR, "failed to receive on socket: [Errno 104] Connection reset by peer"),
        (mqtt.MQTT_LOG_ERR, "failed to receive on socket: [SSL: WRONG_VERSION_NUMBER] wrong version"),
        (mqtt.MQTT_LOG_DEBUG, _TLS13_READ_ALERT),
    ],
)
def test_other_read_failures_are_no_certificate_alert(level, line):
    client = _make_client()
    mock_loop = MagicMock()
    client._loop = mock_loop
    listener = MagicMock()
    client.set_connection_listener(listener)

    client._on_log(MagicMock(), None, level, line)
    client._on_disconnect(
        MagicMock(), None, MagicMock(), _disconnect("Unspecified error"), None
    )

    assert _listener_calls(mock_loop, listener) == [(False, None)]


@pytest.mark.asyncio
async def test_connect_hooks_the_attempt_the_failed_reconnect_the_log_and_the_suback():
    client = _make_client()
    fake = MagicMock()

    with patch.object(client_mod, "get_blocking_mqtt_client", return_value=fake):
        await client.connect()

    hooks = (fake.on_socket_open, fake.on_connect_fail, fake.on_log, fake.on_subscribe)
    assert hooks == (
        client._on_socket_open,
        client._on_connect_fail,
        client._on_log,
        client._on_subscribe,
    )


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
