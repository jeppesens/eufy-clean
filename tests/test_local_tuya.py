"""Unit tests for the LocalTuyaClient transport.

These tests don't reach the network — `tinytuya.Device` is fully mocked so we
verify the wrapping/dispatch behaviour in isolation.
"""

# pylint: disable=redefined-outer-name

import asyncio
import json
import time
from unittest.mock import MagicMock, patch

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


# ---------------------------------------------------------------------------
# Reconnect / backoff (S2)
# ---------------------------------------------------------------------------
#
# The listen loop runs as a background task and calls ``asyncio.sleep`` for its
# reconnect backoff. We patch that sleep (so tests don't wait real seconds) with
# a recorder that still yields control via the *real* sleep — patching the
# module attribute would otherwise also intercept the loop's own awaits. The
# test then drives completion off an Event that ``fake_receive`` sets once the
# scripted packets are exhausted, awaited via ``asyncio.wait_for`` (which does
# not route through ``asyncio.sleep``, so it is unaffected by the patch).

_REAL_SLEEP = asyncio.sleep


def _make_sleep_recorder(sleeps: list[float]):
    async def fake_sleep(delay):
        # Record real backoff sleeps only; a 0-delay is a cooperative yield
        # the listen loop uses to avoid busy-spinning, not a reconnect backoff.
        if delay:
            sleeps.append(delay)
        # Yield so the loop's executor work and other tasks make progress.
        await _REAL_SLEEP(0)

    return fake_sleep


async def _drive_until(done: asyncio.Event, client: LocalTuyaClient) -> None:
    """Wait for the scripted packets to drain, then tear the client down."""
    try:
        await asyncio.wait_for(done.wait(), timeout=2)
    finally:
        await client.disconnect()


def _scripted_receive(packets: list, done: asyncio.Event):
    """Build a fake ``tinytuya.Device.receive`` for the listen loop.

    Critically, this runs in the executor thread (the loop calls receive via
    run_in_executor), so it must behave like a real blocking socket: it sleeps
    a hair each call so ``await run_in_executor`` genuinely suspends and the
    event loop can make progress (a real receive() blocks on the socket timeout;
    an instant mock would busy-spin and, on Python 3.14, starve the loop). When
    the script is exhausted it signals ``done`` **thread-safely** — an
    asyncio.Event must not be set from off the loop thread — then returns None.
    """
    loop = asyncio.get_running_loop()
    it = iter(packets)

    def fake_receive():
        time.sleep(0.005)
        try:
            return next(it)
        except StopIteration:
            loop.call_soon_threadsafe(done.set)
            return None

    return fake_receive


@pytest.mark.asyncio
async def test_listener_ignores_timeout_error(patch_tinytuya, fake_dev):
    """An {"Error": "timeout"} packet is benign: continue, no reconnect."""
    done = asyncio.Event()
    fake_dev.receive.side_effect = _scripted_receive(
        [{"Error": "timeout while waiting"}], done
    )
    client = LocalTuyaClient(
        device_id="dev1", local_key="k" * 16, host="1.2.3.4"
    )
    client.set_on_message(lambda _b: None)

    sleeps: list[float] = []
    with patch(
        "custom_components.robovac_mqtt.api.local_tuya.asyncio.sleep",
        new=_make_sleep_recorder(sleeps),
    ):
        await client.connect()
        await _drive_until(done, client)

    # connect() builds the device once; a timeout error must NOT reopen it
    # and must NOT sleep for a reconnect backoff.
    assert patch_tinytuya.Device.call_count == 1
    assert not sleeps


@pytest.mark.asyncio
async def test_listener_reconnects_on_error_with_backoff(patch_tinytuya, fake_dev):
    """A real error dict triggers _open_device + exponential backoff sleeps."""
    done = asyncio.Event()
    fake_dev.receive.side_effect = _scripted_receive(
        [{"Error": "device offline"}, {"Error": "device offline"}], done
    )
    client = LocalTuyaClient(
        device_id="dev1", local_key="k" * 16, host="1.2.3.4"
    )
    client.set_on_message(lambda _b: None)

    sleeps: list[float] = []
    with patch(
        "custom_components.robovac_mqtt.api.local_tuya.asyncio.sleep",
        new=_make_sleep_recorder(sleeps),
    ):
        await client.connect()
        await _drive_until(done, client)

    # Two error packets -> two reconnects, each preceded by a backoff sleep
    # that grows exponentially from the initial value.
    assert sleeps[0] == 5.0
    assert sleeps[1] == 10.0
    # Device reconstructed: 1 (connect) + 2 (reconnects).
    assert patch_tinytuya.Device.call_count == 3


@pytest.mark.asyncio
async def test_listener_reconnects_on_exception_and_resets_backoff(
    patch_tinytuya, fake_dev
):
    """receive() raising triggers reconnect; a later good packet resets backoff."""
    done = asyncio.Event()
    loop = asyncio.get_running_loop()
    calls = {"n": 0}

    def fake_receive():
        time.sleep(0.005)  # behave like a blocking socket so the loop paces
        calls["n"] += 1
        if calls["n"] == 1:
            raise OSError("connection reset")
        if calls["n"] == 2:
            return {"dps": {"167": "AA=="}}
        loop.call_soon_threadsafe(done.set)  # signal off the executor thread
        return None

    fake_dev.receive.side_effect = fake_receive
    client = LocalTuyaClient(
        device_id="dev1", local_key="k" * 16, host="1.2.3.4"
    )
    seen: list[dict] = []

    def on_msg(payload: bytes) -> None:
        seen.append(json.loads(json.loads(payload.decode())["payload"]))

    client.set_on_message(on_msg)

    sleeps: list[float] = []
    with patch(
        "custom_components.robovac_mqtt.api.local_tuya.asyncio.sleep",
        new=_make_sleep_recorder(sleeps),
    ):
        await client.connect()
        await _drive_until(done, client)

    # The exception path slept once (initial backoff) then re-opened the device.
    assert sleeps and sleeps[0] == 5.0
    # Reconnect re-invoked tinytuya.Device: 1 (connect) + 1 (reopen).
    assert patch_tinytuya.Device.call_count >= 2
    # A successful packet after reconnect resets backoff to the initial value,
    # so no further (growing) sleeps occurred.
    assert all(s == 5.0 for s in sleeps)
    # The good packet was dispatched.
    assert any(d.get("data", {}).get("167") for d in seen)


@pytest.mark.asyncio
async def test_reconnect_refetches_status(patch_tinytuya, fake_dev):
    """After a reconnect the client re-runs status() (N3) so state isn't stale."""
    done = asyncio.Event()
    fake_dev.receive.side_effect = _scripted_receive(
        [{"Error": "device offline"}], done
    )
    # status() returns the initial fetch then a post-reconnect snapshot.
    fake_dev.status.side_effect = [
        {"dps": {"104": 87}},
        {"dps": {"104": 50}},
    ]
    client = LocalTuyaClient(
        device_id="dev1", local_key="k" * 16, host="1.2.3.4"
    )
    seen: list[dict] = []

    def on_msg(payload: bytes) -> None:
        seen.append(json.loads(json.loads(payload.decode())["payload"]))

    client.set_on_message(on_msg)

    sleeps: list[float] = []
    with patch(
        "custom_components.robovac_mqtt.api.local_tuya.asyncio.sleep",
        new=_make_sleep_recorder(sleeps),
    ):
        await client.connect()
        await _drive_until(done, client)

    # status() called twice: initial connect + post-reconnect refetch.
    assert fake_dev.status.call_count == 2
    # Both snapshots dispatched.
    assert any(d.get("data", {}).get("104") == 87 for d in seen)
    assert any(d.get("data", {}).get("104") == 50 for d in seen)


# ---------------------------------------------------------------------------
# _dispatch payload filtering + _dev guard (N4)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"dps": {}},
        "garbage",
        None,
        [1, 2, 3],
    ],
)
def test_dispatch_ignores_non_dps_payloads(payload, patch_tinytuya):
    """_dispatch must not fire the callback for empty/garbage payloads."""
    client = LocalTuyaClient(
        device_id="dev1", local_key="k" * 16, host="1.2.3.4"
    )
    fired: list[bytes] = []
    client.set_on_message(fired.append)
    client._dispatch(payload)
    assert not fired


def test_dispatch_without_callback_is_noop(patch_tinytuya):
    """_dispatch with a valid payload but no callback registered is a no-op."""
    client = LocalTuyaClient(
        device_id="dev1", local_key="k" * 16, host="1.2.3.4"
    )
    # No set_on_message() call. Should not raise.
    client._dispatch({"dps": {"104": 87}})


def test_receive_with_timeout_guards_none_dev(patch_tinytuya):
    """_receive_with_timeout returns None when _dev is None (no AttributeError)."""
    client = LocalTuyaClient(
        device_id="dev1", local_key="k" * 16, host="1.2.3.4"
    )
    assert client._dev is None
    assert client._receive_with_timeout() is None
