"""Unit tests for the LocalTuyaClient transport.

These tests don't reach the network — `tinytuya.Device` is fully mocked so we
verify the wrapping/dispatch behaviour in isolation.
"""

# pylint: disable=redefined-outer-name

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.robovac_mqtt.api.local_tuya import (
    LocalTuyaClient,
    LocalTuyaError,
)


@pytest.fixture
def fake_dev():
    """Replacement for tinytuya.Device — captures call history."""
    dev = MagicMock()
    dev.status.return_value = {"dps": {"104": 87}}
    dev.receive.return_value = None
    dev.set_multiple_values.return_value = {"dps": {"154": "BgoEIgIIAg=="}}
    return dev


@pytest.fixture
def patch_tinytuya(fake_dev):
    """Patch tinytuya.Device so LocalTuyaClient builds without a real socket."""
    with patch(
        "custom_components.robovac_mqtt.api.local_tuya.tinytuya"
    ) as fake_module:
        fake_module.Device.return_value = fake_dev
        yield fake_module


def test_construct_requires_tinytuya():
    """Importing without tinytuya should fail at construct time, not import."""
    with patch(
        "custom_components.robovac_mqtt.api.local_tuya.tinytuya", new=None
    ):
        with pytest.raises(LocalTuyaError):
            LocalTuyaClient(device_id="x", local_key="k" * 16, host="1.2.3.4")


@pytest.mark.asyncio
async def test_connect_dispatches_initial_status(patch_tinytuya, fake_dev):
    """First status() should be wrapped in the MQTT envelope and delivered."""
    client = LocalTuyaClient(
        device_id="dev1", local_key="k" * 16, host="1.2.3.4"
    )

    received: list[bytes] = []
    client.set_on_message(received.append)

    await client.connect()
    # Stop the listener immediately so it doesn't keep polling
    await client.disconnect()

    assert len(received) == 1
    parsed = json.loads(received[0].decode())
    inner = json.loads(parsed["payload"])
    assert inner == {"data": {"104": 87}}


@pytest.mark.asyncio
async def test_send_command_calls_set_multiple(patch_tinytuya, fake_dev):
    """send_command should hand the dps dict to tinytuya unchanged."""
    client = LocalTuyaClient(
        device_id="dev1", local_key="k" * 16, host="1.2.3.4"
    )
    client.set_on_message(lambda _b: None)
    await client.connect()
    try:
        await client.send_command({"154": "BgoEIgIIAg=="})
    finally:
        await client.disconnect()
    fake_dev.set_multiple_values.assert_called_once_with(
        {"154": "BgoEIgIIAg=="}
    )


@pytest.mark.asyncio
async def test_send_command_when_disconnected_raises(patch_tinytuya):
    """Sending without connect() must error so callers see the failure."""
    client = LocalTuyaClient(
        device_id="dev1", local_key="k" * 16, host="1.2.3.4"
    )
    with pytest.raises(LocalTuyaError):
        await client.send_command({"152": "AA=="})


@pytest.mark.asyncio
async def test_send_command_propagates_underlying_failure(
    patch_tinytuya, fake_dev
):
    """tinytuya can raise on send (e.g., socket dead) — surface as LocalTuyaError."""
    fake_dev.set_multiple_values.side_effect = OSError("broken pipe")
    client = LocalTuyaClient(
        device_id="dev1", local_key="k" * 16, host="1.2.3.4"
    )
    client.set_on_message(lambda _b: None)
    await client.connect()
    try:
        with pytest.raises(LocalTuyaError):
            await client.send_command({"152": "AA=="})
    finally:
        await client.disconnect()


@pytest.mark.asyncio
async def test_listener_dispatches_pushed_dps(patch_tinytuya, fake_dev):
    """Gratuitous DPS pushes from the device should reach the callback."""
    pushes = iter([
        {"dps": {"167": "FAoFCKYPEBoSCwjg70UQrYkBGMYC"}},
        # Subsequent calls return None to mimic timeouts
    ])

    def fake_receive():
        try:
            return next(pushes)
        except StopIteration:
            return None

    fake_dev.receive.side_effect = fake_receive
    client = LocalTuyaClient(
        device_id="dev1", local_key="k" * 16, host="1.2.3.4"
    )
    seen: list[dict] = []

    def on_msg(payload: bytes) -> None:
        seen.append(json.loads(json.loads(payload.decode())["payload"]))

    client.set_on_message(on_msg)
    await client.connect()
    # Give the listener loop a chance to run once
    await asyncio.sleep(0.05)
    await client.disconnect()

    # First push is the initial status() call (DPS 104=87), second is the
    # gratuitous receive() push (DPS 167).
    assert any(d.get("data", {}).get("167") for d in seen)
