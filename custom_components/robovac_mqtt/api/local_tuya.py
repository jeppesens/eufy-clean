"""Local Tuya LAN transport (tinytuya, port 6668): push-based DPS updates in the same
{"dps": {key: value}} envelope as the MQTT and cloud transports."""

from __future__ import annotations

import asyncio
import json
import logging
import socket
import threading
from collections.abc import Callable
from typing import Any

try:
    import tinytuya
except ImportError:  # pragma: no cover - tinytuya is declared in manifest.json
    tinytuya = None

_LOGGER = logging.getLogger(__name__)

# bound tinytuya's blocking receive() so the loop can react to cancellation
_RECV_TIMEOUT = 5.0

# tinytuya's TCP connect/socket timeout for ordinary use.
_SOCKET_TIMEOUT = 10.0
_RECONNECT_BACKOFF_INITIAL = 5.0
_RECONNECT_BACKOFF_MAX = 60.0

# guard only: unload must never block on a wedged library
_DISCONNECT_TIMEOUT = 10.0

# Post-write status() re-read delay. The transport is push-only, so a write the
# device does not announce (a consumable reset) otherwise looks like a no-op.
_POST_WRITE_REFETCH_DELAY = 2.0

# The device closes an idle local socket after ~30 s; without a keepalive tinytuya
# silently re-dials and redoes session-key negotiation each time.
_HEARTBEAT_INTERVAL = 10.0

# receive() errors meaning one bad read, not a broken transport; ERR_PAYLOAD also
# covers EOF. Benign is per-read: the retry-immediately handling becomes a
# full-speed connect/EOF spin when every dial fails (rotated localKey, or the Eufy
# app holding the device's single local slot), so cap the run and fall back to the
# reconnect backoff.
_MAX_BENIGN_RECV_STREAK = 10
_BENIGN_RECV_ERRORS = frozenset(
    {
        tinytuya.ERR_TIMEOUT,  # 902 — idle, nothing to read
        tinytuya.ERR_PAYLOAD,  # 904 — frame we cannot parse
        tinytuya.ERR_JSON,     # 900 — frame with a non-JSON body
    }
    if tinytuya is not None
    else ()
)

# Versions tried when the configured one cannot talk to the device, ordered by
# prevalence across Eufy's Tuya models (older RoboVacs 3.3, newer ones 3.5).
_PROTOCOL_VERSIONS: tuple[float, ...] = (3.3, 3.5, 3.4, 3.1)

# probe only: the probe runs on the setup path, where three extra versions at the
# full connect timeout would block setup for ~40 s
_PROBE_SOCKET_TIMEOUT = 3.0

# tinytuya returns these only when the TCP socket never opened; a wrong protocol
# version fails differently, so probing other versions cannot help.
_UNREACHABLE_ERRORS = frozenset(
    {tinytuya.ERR_CONNECT, tinytuya.ERR_OFFLINE}
    if tinytuya is not None
    else ()
)


def _is_usable_status(result: Any) -> bool:
    """Did status() return real DPS rather than an error envelope?"""
    return isinstance(result, dict) and bool(result.get("dps"))


def _is_unreachable(result: Any) -> bool:
    """Does this error envelope say the socket itself never opened?"""
    if not isinstance(result, dict) or "Error" not in result:
        return False
    try:
        return int(result.get("Err", -1)) in _UNREACHABLE_ERRORS
    except (TypeError, ValueError):
        return False


class LocalTuyaError(Exception):
    """Raised for unrecoverable local Tuya transport errors."""


class LocalTuyaClient:
    """Push-based local transport speaking the Tuya v3.x protocol."""

    def __init__(
        self,
        device_id: str,
        local_key: str,
        host: str,
        version: float = 3.3,
        port: int = 6668,
    ) -> None:
        if tinytuya is None:
            raise LocalTuyaError(
                "tinytuya is not installed; add it to manifest.json requirements"
            )
        self.device_id = device_id
        self.local_key = local_key
        self.host = host
        self.port = port
        self.version = version
        self._on_message: Callable[[bytes], None] | None = None
        self._on_dps: Callable[[dict[str, Any]], None] | None = None
        self._dev: Any | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._listen_task: asyncio.Task | None = None
        self._heartbeat_task: asyncio.Task | None = None
        self._refetch_task: asyncio.Task | None = None
        # threading.Event, not a bool: set on the loop, read in the executor thread
        self._stop = threading.Event()
        # tinytuya's Device is not thread-safe; serialize every executor access
        self._dev_lock = asyncio.Lock()

    def set_on_message(self, callback: Callable[[bytes], None]) -> None:
        """Register a callback for DPS updates wrapped in the MQTT JSON envelope."""
        self._on_message = callback

    def set_on_dps(self, callback: Callable[[dict[str, Any]], None]) -> None:
        """Register a callback for DPS updates as a plain dict; wins over set_on_message."""
        self._on_dps = callback

    async def connect(self) -> None:
        """Open the socket and start the background listener."""
        self._loop = asyncio.get_running_loop()
        self._stop.clear()
        async with self._dev_lock:
            await self._loop.run_in_executor(None, self._open_device)
        # seeds state before the push stream and confirms the protocol version
        try:
            async with self._dev_lock:
                initial = await self._loop.run_in_executor(
                    None, self._status_detecting_version
                )
            if _is_unreachable(initial):
                # tinytuya reports an unopened socket as a return value, not an
                # exception; raise so the coordinator falls back to cloud polling.
                raise LocalTuyaError(
                    f"device unreachable on port {self.port} ({initial.get('Error')})"
                )
            self._dispatch(initial)
        except LocalTuyaError:
            raise
        except Exception as e:  # noqa: BLE001 - tinytuya raises broadly
            _LOGGER.debug(
                "Local Tuya %s: initial status fetch failed (%s); "
                "will rely on gratuitous updates",
                self.device_id, e,
            )
        self._listen_task = self._loop.create_task(self._listen_loop())
        self._heartbeat_task = self._loop.create_task(self._heartbeat_loop())

    def _status_detecting_version(self) -> Any:
        """status(), falling back to the other Tuya protocol versions.

        A wrong ``version`` connects but fails to decrypt every frame, silently.
        Callers must hold ``self._dev_lock``.
        """
        result = self._dev.status()  # type: ignore[union-attr]
        if _is_usable_status(result) or _is_unreachable(result):
            return result

        try:
            self._dev.set_socketTimeout(_PROBE_SOCKET_TIMEOUT)  # type: ignore[union-attr]
            for version in _PROTOCOL_VERSIONS:
                if version == self.version:
                    continue
                self._dev.set_version(version)  # type: ignore[union-attr]
                candidate = self._dev.status()  # type: ignore[union-attr]
                if _is_usable_status(candidate):
                    _LOGGER.warning(
                        "Local Tuya %s: configured protocol %s did not work; "
                        "using %s instead",
                        self.device_id, self.version, version,
                    )
                    self.version = version
                    return candidate
                if _is_unreachable(candidate):
                    break
        finally:
            self._dev.set_socketTimeout(_SOCKET_TIMEOUT)  # type: ignore[union-attr]

        # nothing worked: restore the configured version so reconnects are predictable
        self._dev.set_version(self.version)  # type: ignore[union-attr]
        return result

    def _open_device(self) -> None:
        """Construct the underlying tinytuya.Device (blocking).

        Callers must hold ``self._dev_lock`` so the close/reassign cannot race the
        listen loop's receive().
        """
        if self._dev is not None:
            try:
                self._dev.close()
            except Exception:  # noqa: BLE001 - close is best-effort
                pass
        self._dev = tinytuya.Device(
            self.device_id,
            address=self.host,
            local_key=self.local_key,
            version=self.version,
            connection_timeout=_SOCKET_TIMEOUT,
            persist=True,
        )
        # we manage reconnect ourselves so failures reach the coordinator
        self._dev.set_socketRetryLimit(1)
        self._dev.set_socketRetryDelay(0)

    def _unblock_receive(self) -> None:
        """Wake a parked receive() from the event loop, best-effort.

        ``shutdown(SHUT_RDWR)`` is the safe cross-thread wakeup: recv() returns b''
        but the fd stays allocated, so the thread cannot read a recycled descriptor
        as a concurrent ``close()`` would allow. Retry limit 0 first stops tinytuya
        re-dialling inside that same receive().
        """
        dev = self._dev
        if dev is None:
            return
        try:
            dev.set_socketRetryLimit(0)
        except Exception:  # noqa: BLE001 - best-effort
            pass
        sock = getattr(dev, "socket", None)
        if sock is None:
            return
        try:
            sock.shutdown(socket.SHUT_RDWR)
        except (OSError, AttributeError):  # already closed / replaced
            pass

    async def disconnect(self) -> None:
        """Stop the listener and close the socket, promptly and idempotently."""
        # _stop first: no new receive cycle, and a queued executor job bails out
        self._stop.set()
        # a pending post-write re-read would take _dev_lock after teardown started
        if self._refetch_task is not None:
            self._refetch_task.cancel()
            self._refetch_task = None
        self._unblock_receive()

        # Close BEFORE cancelling the listener: _dev_lock here waits for the
        # in-flight receive() thread, whereas cancelling would free the lock while
        # that thread still runs and let close() race it.
        if self._dev:
            try:
                async with asyncio.timeout(_DISCONNECT_TIMEOUT):
                    async with self._dev_lock:
                        try:
                            await self._loop.run_in_executor(None, self._dev.close)  # type: ignore[union-attr]
                        except Exception:  # noqa: BLE001 - close is best-effort
                            pass
                        self._dev = None
            except TimeoutError:
                # closing would race the parked receive; drop the reference and let
                # the executor job release the socket when it returns
                _LOGGER.debug(
                    "Local Tuya %s: receive did not return within %.0fs of "
                    "disconnect; abandoning the device object",
                    self.device_id, _DISCONNECT_TIMEOUT,
                )
                self._dev = None

        if self._heartbeat_task:
            # safe to cancel unawaited: it holds _dev_lock for one datagram only
            self._heartbeat_task.cancel()
            self._heartbeat_task = None

        if self._listen_task:
            self._listen_task.cancel()
            try:
                async with asyncio.timeout(_DISCONNECT_TIMEOUT):
                    await self._listen_task
            except (asyncio.CancelledError, TimeoutError, Exception):  # noqa: BLE001
                pass
            self._listen_task = None

    async def send_command(self, dps: dict[str, Any]) -> None:
        """Send a DPS write to the device.

        ``dps`` maps DPS index to value, as for the MQTT and cloud transports:
        plain bool/int/str for legacy DPS, base64 protobuf for novel DPS.
        """
        if not self._dev or not self._loop:
            raise LocalTuyaError(
                f"Local Tuya {self.device_id}: not connected"
            )
        _LOGGER.debug(
            "Local Tuya %s: sending DPS %s", self.device_id, list(dps.keys())
        )
        # tinytuya does NOT raise when the device rejects a write — it returns
        # {"Error": ..., "Err": ...}, so the result must be inspected below.
        try:
            async with self._dev_lock:
                result = await self._loop.run_in_executor(
                    None, self._dev.set_multiple_values, dps
                )
        except Exception as e:  # noqa: BLE001 - tinytuya raises broadly
            raise LocalTuyaError(
                f"Failed to send local Tuya command to {self.device_id}: {e}"
            ) from e
        if isinstance(result, dict) and ("Error" in result or "Err" in result):
            raise LocalTuyaError(
                f"Local Tuya {self.device_id} rejected DPS {list(dps.keys())}: "
                f"{result.get('Err')} {result.get('Error')}"
            )
        # accepted, but what it changed may never be announced — ask
        self._schedule_status_refetch()

    def _schedule_status_refetch(self) -> None:
        """Re-read status() shortly after a write, coalescing a burst into one."""
        if self._stop.is_set() or self._loop is None:
            return
        if self._refetch_task is not None and not self._refetch_task.done():
            return
        self._refetch_task = self._loop.create_task(self._delayed_status_refetch())

    async def _delayed_status_refetch(self) -> None:
        try:
            await asyncio.sleep(_POST_WRITE_REFETCH_DELAY)
            if self._stop.is_set():
                return
            await self._refetch_status()
        except Exception:  # noqa: BLE001 - best-effort, never breaks a write
            _LOGGER.debug(
                "Local Tuya %s: post-write status re-read failed",
                self.device_id, exc_info=True,
            )

    async def _heartbeat_loop(self) -> None:
        """Keep the persistent socket alive (see ``_HEARTBEAT_INTERVAL``).

        ``nowait=True`` sends without reading; the reply reaches the listen loop's
        receive() as an empty payload.
        """
        while not self._stop.is_set():
            await asyncio.sleep(_HEARTBEAT_INTERVAL)
            if self._stop.is_set() or self._dev is None or self._loop is None:
                return
            try:
                async with self._dev_lock:
                    if self._stop.is_set() or self._dev is None:
                        return
                    await self._loop.run_in_executor(None, self._send_heartbeat)
            except Exception:  # noqa: BLE001 - tinytuya raises broadly
                _LOGGER.debug(
                    "Local Tuya %s: heartbeat failed", self.device_id, exc_info=True
                )

    def _send_heartbeat(self) -> None:
        """Blocking half of ``_heartbeat_loop``. Callers hold ``_dev_lock``."""
        dev = self._dev
        if dev is None or self._stop.is_set():
            return
        # tinytuya dials a new connection for any send without a socket;
        # reconnecting is the listen loop's job, on its backoff.
        if getattr(dev, "socket", None) is None:
            return
        result = dev.heartbeat(nowait=True)
        # a dead socket comes back as an error envelope, not an exception
        if isinstance(result, dict) and "Error" in result:
            _LOGGER.debug(
                "Local Tuya %s: heartbeat failed (%s)",
                self.device_id, result.get("Error"),
            )

    async def _listen_loop(self) -> None:
        """Pump status() and receive() in the background, dispatching DPS pushes."""
        backoff = _RECONNECT_BACKOFF_INITIAL
        benign_streak = 0
        while not self._stop.is_set():
            try:
                # one bounded receive() per lock hold, so send_command() gets a turn
                async with self._dev_lock:
                    payload = await self._loop.run_in_executor(  # type: ignore[union-attr]
                        None, self._receive_with_timeout
                    )
                if self._stop.is_set():
                    # disconnect() shut the socket down under us, not a device fault
                    break
                if payload is None:
                    # yield so a rapidly-returning receive() cannot busy-loop
                    await asyncio.sleep(0)
                    continue
                # tinytuya may return error envelopes instead of raising
                if isinstance(payload, dict) and "Error" in payload:
                    err_msg = payload.get("Error")
                    try:
                        err_code = int(payload.get("Err", -1))
                    except (TypeError, ValueError):
                        err_code = -1
                    # some envelopes carry no numeric code: match the message too
                    benign = err_code in _BENIGN_RECV_ERRORS or (
                        err_code == -1 and "timeout" in str(err_msg).lower()
                    )
                    if benign and benign_streak < _MAX_BENIGN_RECV_STREAK:
                        # one bad frame, not a dead socket: keep the session
                        benign_streak += 1
                        _LOGGER.debug(
                            "Local Tuya %s: ignoring transient receive error "
                            "%s ('%s') — one bad read, keeping the session",
                            self.device_id, err_code, err_msg,
                        )
                        await asyncio.sleep(0)
                        continue
                    if benign:
                        _LOGGER.debug(
                            "Local Tuya %s: %d consecutive transient receive "
                            "errors (%s '%s') — treating the session as dead "
                            "rather than re-reading at full speed",
                            self.device_id, benign_streak, err_code, err_msg,
                        )
                    else:
                        _LOGGER.debug(
                            "Local Tuya %s: device error '%s' (%s); reconnecting in %.0fs",
                            self.device_id, err_msg, err_code, backoff,
                        )
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2, _RECONNECT_BACKOFF_MAX)
                    benign_streak = 0
                    async with self._dev_lock:
                        await self._loop.run_in_executor(None, self._open_device)  # type: ignore[union-attr]
                    await self._refetch_status()
                    continue

                self._dispatch(payload)
                backoff = _RECONNECT_BACKOFF_INITIAL  # any successful packet resets
                benign_streak = 0
            except asyncio.CancelledError:
                break
            except Exception as e:  # noqa: BLE001 - tinytuya raises broadly
                if self._stop.is_set():
                    # teardown again, where tinytuya raises instead of returning
                    _LOGGER.debug(
                        "Local Tuya %s: listen loop ended during disconnect (%s)",
                        self.device_id, e,
                    )
                    break
                _LOGGER.warning(
                    "Local Tuya %s: listen loop error (%s); reconnecting in %.0fs",
                    self.device_id, e, backoff,
                )
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, _RECONNECT_BACKOFF_MAX)
                try:
                    async with self._dev_lock:
                        await self._loop.run_in_executor(None, self._open_device)  # type: ignore[union-attr]
                except Exception as reopen_err:  # noqa: BLE001
                    _LOGGER.debug(
                        "Local Tuya %s: reconnect failed: %s",
                        self.device_id, reopen_err,
                    )
                else:
                    await self._refetch_status()

    async def _refetch_status(self) -> None:
        """Re-fetch status() after a reconnect so state isn't stale until the next push."""
        try:
            async with self._dev_lock:
                status = await self._loop.run_in_executor(None, self._dev.status)  # type: ignore[union-attr]
            self._dispatch(status)
        except Exception as e:  # noqa: BLE001 - tinytuya raises broadly
            _LOGGER.debug(
                "Local Tuya %s: status re-fetch after reconnect failed (%s); "
                "will rely on gratuitous updates",
                self.device_id, e,
            )

    def _receive_with_timeout(self) -> Any:
        """Blocking receive() with a bounded timeout so the loop stays responsive.

        Runs in an executor thread; queued jobs cannot be cancelled, hence the
        threading.Event check before touching the socket.
        """
        # no per-call timeout in tinytuya; on expiry receive() returns Error/None
        dev = self._dev
        if dev is None or self._stop.is_set():
            return None
        dev.set_socketTimeout(_RECV_TIMEOUT)
        return dev.receive()

    def _dispatch(self, payload: Any) -> None:
        """Hand a DPS payload to the registered callback."""
        if not isinstance(payload, dict):
            return
        dps = payload.get("dps")
        if not isinstance(dps, dict) or not dps:
            return
        if self._on_dps is not None:
            self._on_dps(dps)
            return
        if not self._on_message:
            return
        # wire format _handle_mqtt_message expects: {"payload": json({"data": dps})}
        envelope = json.dumps(
            {"payload": json.dumps({"data": dps})}
        ).encode()
        self._on_message(envelope)
