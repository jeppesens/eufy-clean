"""Unit tests for the MQTT client (api/client.py)."""

import asyncio
import os
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.robovac_mqtt.api.client import (
    EufyCleanClient,
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


def test_on_connect_thread_safe_event():
    """Test _on_connect with rc=0 fires connected event via call_soon_threadsafe."""
    client = _make_client()
    mock_loop = MagicMock()
    client._loop = mock_loop

    mock_mqtt = MagicMock()
    client._on_connect(mock_mqtt, None, {}, 0)

    mock_loop.call_soon_threadsafe.assert_called_once_with(client._connected_event.set)
    assert mock_mqtt.subscribe.call_count == 2
    mock_mqtt.subscribe.assert_any_call("cmd/eufy_home/T2320/TEST123/res")
    mock_mqtt.subscribe.assert_any_call("biz/eufy_home/T2320/TEST123/res")


def test_on_disconnect_thread_safe_event():
    """Test _on_disconnect clears connected event via call_soon_threadsafe."""
    client = _make_client()
    mock_loop = MagicMock()
    client._loop = mock_loop

    client._on_disconnect(MagicMock(), None, 0)

    mock_loop.call_soon_threadsafe.assert_called_once_with(
        client._connected_event.clear
    )


def test_on_connect_failure_no_event():
    """Test _on_connect with rc != 0 does NOT fire the connected event."""
    client = _make_client()
    mock_loop = MagicMock()
    client._loop = mock_loop

    mock_mqtt = MagicMock()
    client._on_connect(mock_mqtt, None, {}, 1)

    mock_loop.call_soon_threadsafe.assert_not_called()
    mock_mqtt.subscribe.assert_not_called()


@pytest.mark.asyncio
async def test_send_command_not_connected():
    """Test send_command when _mqtt_client is None returns without error."""
    client = _make_client()
    assert client._mqtt_client is None

    # Should not raise
    await client.send_command({"test": "value"})


@pytest.mark.asyncio
async def test_send_command_disconnected_client():
    """Test send_command when client reports is_connected()=False skips publish."""
    client = _make_client()
    mock_mqtt = MagicMock()
    mock_mqtt.is_connected.return_value = False
    client._mqtt_client = mock_mqtt

    await client.send_command({"test": "value"})

    mock_mqtt.publish.assert_not_called()


@pytest.mark.asyncio
async def test_disconnect_cleans_temp_files():
    """Test disconnect() removes temporary certificate and key files."""
    client = _make_client()

    # Create real temp files to verify deletion
    cert_fd, cert_path = tempfile.mkstemp(suffix=".pem")
    key_fd, key_path = tempfile.mkstemp(suffix=".key")
    os.close(cert_fd)
    os.close(key_fd)

    client._cert_path = cert_path
    client._key_path = key_path

    mock_mqtt = MagicMock()
    client._mqtt_client = mock_mqtt
    client._loop = asyncio.get_running_loop()

    await client.disconnect()

    assert not os.path.exists(cert_path)
    assert not os.path.exists(key_path)
    assert client._cert_path is None
    assert client._key_path is None


@pytest.mark.asyncio
async def test_disconnect_no_loop_uses_running_loop():
    """Test disconnect() falls back to asyncio.get_running_loop() when _loop is None."""
    client = _make_client()
    assert client._loop is None

    mock_mqtt = MagicMock()
    client._mqtt_client = mock_mqtt

    with patch("asyncio.get_running_loop") as mock_get_loop:
        mock_loop = MagicMock()
        mock_loop.run_in_executor = AsyncMock()
        mock_get_loop.return_value = mock_loop

        await client.disconnect()

        mock_get_loop.assert_called_once()
        mock_loop.run_in_executor.assert_called_once()
