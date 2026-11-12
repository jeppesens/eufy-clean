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

from custom_components.robovac_mqtt.api import local_tuya
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
        {"154": "BgoEIgIIAg=="}, nowait=False
    )


@pytest.mark.asyncio
async def test_send_command_can_skip_the_reply_wait(patch_tinytuya, fake_dev):
    """Drive commands get no reply; waiting on one stalls the next by the socket timeout."""
    client = LocalTuyaClient(device_id="dev1", local_key="k" * 16, host="1.2.3.4")
    client.set_on_message(lambda _b: None)
    await client.connect()
    try:
        await client.send_command({"155": "AggB"}, wait=False)
    finally:
        await client.disconnect()
    fake_dev.set_multiple_values.assert_called_once_with({"155": "AggB"}, nowait=True)


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


def _silence_keepalive(client: LocalTuyaClient) -> None:
    """Drop the keepalive task for tests about the LISTEN loop.

    The heartbeat sleeps on the same patched ``asyncio.sleep`` the backoff
    assertions read, and its interval collides with a legitimate backoff value
    (both 10 s), so filtering by duration would hide a real regression. These
    tests are about reconnect behaviour; the keepalive has its own test.
    """

    async def _no_keepalive() -> None:
        return

    client._heartbeat_loop = _no_keepalive  # type: ignore[method-assign]  # noqa: SLF001


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

    _silence_keepalive(client)

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

    _silence_keepalive(client)

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

    _silence_keepalive(client)

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

    _silence_keepalive(client)

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


def test_dispatch_hands_a_dps_callback_the_plain_dict(patch_tinytuya):
    """A DPS callback gets the dict itself; no JSON envelope is built."""
    client = LocalTuyaClient(device_id="dev1", local_key="k" * 16, host="1.2.3.4")
    enveloped: list[bytes] = []
    plain: list[dict] = []
    client.set_on_message(enveloped.append)
    client.set_on_dps(plain.append)
    with patch(
        "custom_components.robovac_mqtt.api.local_tuya.json.dumps"
    ) as dumps:
        client._dispatch({"dps": {"104": 87}})
    dumps.assert_not_called()
    assert plain == [{"104": 87}]
    assert not enveloped


def test_unreachable_error_omits_the_address(patch_tinytuya):
    """The message reaches a WARNING in the coordinator; the LAN host stays out."""
    client = LocalTuyaClient(device_id="dev1", local_key="k" * 16, host="192.168.1.77")
    client._dev = MagicMock()
    client._dev.status.return_value = {"Error": "Network Error: Unable to Connect", "Err": "901"}
    with patch.object(client, "_open_device"), pytest.raises(LocalTuyaError) as err:
        asyncio.run(client.connect())
    assert "192.168.1.77" not in str(err.value)


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


@pytest.mark.asyncio
async def test_write_is_followed_by_a_status_re_read(patch_tinytuya, fake_dev):
    """A write must be followed by a fresh status(), or its effect can go unseen.

    The transport is push-only, and the device announces what it chooses to
    announce. A consumable reset (DPS 116) applies on the device and is never
    pushed, so without this the counter kept its old value in Home Assistant
    until the next reconnect — indistinguishable, from the dashboard, from a
    reset that did nothing at all.
    """
    client = LocalTuyaClient(device_id="dev1", local_key="k" * 16, host="1.2.3.4")
    received: list[bytes] = []
    client.set_on_message(received.append)
    await client.connect()
    try:
        fake_dev.status.return_value = {"dps": {"116": "eyJyZXNldCI6MH0="}}
        with patch.object(local_tuya, "_POST_WRITE_REFETCH_DELAY", 0):
            await client.send_command({"116": "eyJjb25zdW1hYmxlIjp7fX0="})
            await asyncio.sleep(0.05)
    finally:
        await client.disconnect()

    payloads = [json.loads(json.loads(b.decode())["payload"])["data"] for b in received]
    assert {"116": "eyJyZXNldCI6MH0="} in payloads


@pytest.mark.asyncio
async def test_a_burst_of_writes_costs_one_re_read(patch_tinytuya, fake_dev):
    """Several writes in a row coalesce into a single status() call."""
    client = LocalTuyaClient(device_id="dev1", local_key="k" * 16, host="1.2.3.4")
    client.set_on_message(lambda _b: None)
    await client.connect()
    fake_dev.status.reset_mock()
    try:
        with patch.object(local_tuya, "_POST_WRITE_REFETCH_DELAY", 0.02):
            await client.send_command({"102": "Quiet"})
            await client.send_command({"103": True})
            await client.send_command({"105": "Mid"})
            await asyncio.sleep(0.08)
    finally:
        await client.disconnect()
    assert fake_dev.status.call_count == 1


@pytest.mark.asyncio
async def test_teardown_cancels_a_pending_re_read(patch_tinytuya, fake_dev):
    """A queued re-read must not reach for the socket after disconnect()."""
    client = LocalTuyaClient(device_id="dev1", local_key="k" * 16, host="1.2.3.4")
    client.set_on_message(lambda _b: None)
    await client.connect()
    fake_dev.status.reset_mock()
    with patch.object(local_tuya, "_POST_WRITE_REFETCH_DELAY", 5):
        await client.send_command({"102": "Quiet"})
    await client.disconnect()
    await asyncio.sleep(0.05)
    assert fake_dev.status.call_count == 0


@pytest.mark.asyncio
async def test_the_keepalive_holds_the_session_open(patch_tinytuya, fake_dev):
    """Without it the device closes the idle socket every ~30 s.

    tinytuya then reports the EOF as ERR_PAYLOAD 904 ("Unexpected Payload from
    Device", which describes something else entirely) and silently re-dials,
    redoing the whole 3.5 session-key negotiation — measured 124 times in one
    hour on a T2266, none of which refreshed any state.
    """
    done = asyncio.Event()
    fake_dev.receive.side_effect = _scripted_receive([None, None, None], done)
    client = LocalTuyaClient(device_id="dev1", local_key="k" * 16, host="1.2.3.4")
    client.set_on_message(lambda _b: None)

    # Fire the keepalive immediately instead of waiting out its real interval.
    with patch(
        "custom_components.robovac_mqtt.api.local_tuya._HEARTBEAT_INTERVAL", 0.01
    ):
        await client.connect()
        await _drive_until(done, client)

    assert fake_dev.heartbeat.called, "the socket is never kept alive"
    # nowait: the reply is an empty payload the listen loop already ignores, and
    # waiting for it here would read from the socket the listener owns.
    assert all(c.kwargs.get("nowait") is True for c in fake_dev.heartbeat.call_args_list)
    # ...and it stops with the client, rather than poking a closed socket.
    assert client._heartbeat_task is None


@pytest.mark.parametrize("connected", [True, False])
def test_the_keepalive_never_dials_a_closed_socket(connected):
    """tinytuya opens a socket for any send when none is open; reconnecting
    belongs to the listen loop's backoff."""
    client = LocalTuyaClient(device_id="dev1", local_key="k" * 16, host="1.2.3.4")
    dev = MagicMock()
    dev.socket = MagicMock() if connected else None
    client._dev = dev
    client._send_heartbeat()
    assert dev.heartbeat.called is connected


@pytest.mark.asyncio
async def test_a_failing_keepalive_is_not_fatal(patch_tinytuya, fake_dev):
    """A heartbeat that cannot be sent is the listen loop's problem to notice."""
    done = asyncio.Event()
    fake_dev.heartbeat.side_effect = OSError("broken pipe")
    fake_dev.receive.side_effect = _scripted_receive([{"dps": {"1": True}}], done)
    client = LocalTuyaClient(device_id="dev1", local_key="k" * 16, host="1.2.3.4")
    seen: list[bytes] = []
    client.set_on_message(seen.append)

    with patch(
        "custom_components.robovac_mqtt.api.local_tuya._HEARTBEAT_INTERVAL", 0.01
    ):
        await client.connect()
        await _drive_until(done, client)

    assert seen, "the listener kept working through the failing keepalive"


# ---------------------------------------------------------------------------
# "Benign" is per-read, not per-session
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_one_benign_payload_error_keeps_the_session(patch_tinytuya, fake_dev):
    """904 on a single read is an empty/unparsable frame, not a dead socket."""
    done = asyncio.Event()
    fake_dev.receive.side_effect = _scripted_receive(
        [{"Error": "Unexpected Payload from Device", "Err": 904}], done
    )
    client = LocalTuyaClient(device_id="dev1", local_key="k" * 16, host="1.2.3.4")
    client.set_on_message(lambda _b: None)
    _silence_keepalive(client)

    sleeps: list[float] = []
    with patch(
        "custom_components.robovac_mqtt.api.local_tuya.asyncio.sleep",
        new=_make_sleep_recorder(sleeps),
    ):
        await client.connect()
        await _drive_until(done, client)

    assert patch_tinytuya.Device.call_count == 1
    assert not sleeps


@pytest.mark.asyncio
async def test_a_run_of_benign_errors_backs_off_instead_of_spinning(
    patch_tinytuya, fake_dev
):
    """Back-to-back 904s are a dead transport, and must not be re-read at full speed.

    tinytuya reports EOF as ERR_PAYLOAD after closing the socket, so a rotated
    localKey — or the eufy app holding the device's single local slot — gives one
    on every dial. Handled as "one bad read" that is a connect/EOF/reconnect spin
    with `sleep(0)` between attempts, pegging an executor thread indefinitely.
    """
    done = asyncio.Event()
    payload_err = {"Error": "Unexpected Payload from Device", "Err": 904}
    fake_dev.receive.side_effect = _scripted_receive([payload_err] * 12, done)
    client = LocalTuyaClient(device_id="dev1", local_key="k" * 16, host="1.2.3.4")
    client.set_on_message(lambda _b: None)
    _silence_keepalive(client)

    sleeps: list[float] = []
    with patch(
        "custom_components.robovac_mqtt.api.local_tuya.asyncio.sleep",
        new=_make_sleep_recorder(sleeps),
    ):
        await client.connect()
        await _drive_until(done, client)

    # 10 free reads, then the 11th is treated as a broken session: one real
    # backoff and one reconnect, not twelve immediate re-dials.
    assert sleeps == [5.0]
    assert patch_tinytuya.Device.call_count == 2


# ---------------------------------------------------------------------------
# Version probing / unreachable devices
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unreachable_device_raises_instead_of_pretending_to_connect(
    patch_tinytuya, fake_dev
):
    """The socket never opened, so connect() must fail and let cloud take over.

    tinytuya returns that as a value, not an exception; swallowing it left the
    coordinator holding a local client that could never deliver anything.
    """
    fake_dev.status.return_value = {"Error": "Device Unreachable", "Err": 905}
    client = LocalTuyaClient(device_id="dev1", local_key="k" * 16, host="1.2.3.4")
    client.set_on_message(lambda _b: None)

    with pytest.raises(LocalTuyaError):
        await client.connect()
    await client.disconnect()

    # ...and no protocol version was probed: no version can open a socket, and
    # at the full timeout a try per version turned one dead device into ~20 s of
    # blocked setup.
    assert fake_dev.status.call_count == 1
    assert fake_dev.set_version.call_count == 0


@pytest.mark.asyncio
async def test_a_wrong_protocol_version_is_still_probed(patch_tinytuya, fake_dev):
    """A socket that opens but cannot decrypt IS the case the probe exists for."""
    results = [
        {"Error": "Check device key or version", "Err": 914},  # configured 3.3
        {"dps": {"104": 87}},                                   # 3.5 answers
    ]
    fake_dev.status.side_effect = results
    client = LocalTuyaClient(
        device_id="dev1", local_key="k" * 16, host="1.2.3.4", version=3.3
    )
    client.set_on_message(lambda _b: None)
    _silence_keepalive(client)

    await client.connect()
    await client.disconnect()

    assert client.version == 3.5
    # Probed with the short timeout, and the ordinary one restored afterwards.
    assert [c.args[0] for c in fake_dev.set_socketTimeout.call_args_list] == [
        local_tuya._COMMAND_TIMEOUT,  # set when the device is opened
        local_tuya._PROBE_SOCKET_TIMEOUT,
        local_tuya._COMMAND_TIMEOUT,
    ]


@pytest.mark.asyncio
async def test_cancelled_write_holds_socket_lock_until_executor_finishes(patch_tinytuya, fake_dev):
    client = LocalTuyaClient(device_id="dev1", local_key="k" * 16, host="1.2.3.4")
    client._dev = fake_dev
    pending = asyncio.get_running_loop().create_future()
    client._loop = MagicMock()
    client._loop.run_in_executor.return_value = pending
    write = asyncio.create_task(client.send_command({"155": "brake"}, wait=False))
    await asyncio.sleep(0)
    write.cancel()
    await asyncio.sleep(0)
    assert client._dev_lock.locked() and not pending.cancelled()
    pending.set_result(None)
    with pytest.raises(asyncio.CancelledError):
        await write
    assert not client._dev_lock.locked()


@pytest.mark.asyncio
async def test_only_the_listen_receive_uses_the_short_socket_timeout(patch_tinytuya, fake_dev):
    """A short timeout elsewhere makes tinytuya reconnect and re-send slow robots' writes."""
    client = LocalTuyaClient(device_id="dev1", local_key="k" * 16, host="1.2.3.4")
    await client.connect()
    fake_dev.receive.side_effect = lambda: fake_dev.set_socketTimeout.call_args_list[-1].args[0]
    assert client._receive_with_timeout() == local_tuya._RECV_TIMEOUT
    assert fake_dev.set_socketTimeout.call_args_list[-1].args[0] == local_tuya._COMMAND_TIMEOUT
    assert local_tuya._COMMAND_TIMEOUT > local_tuya._RECV_TIMEOUT
    await client.disconnect()
