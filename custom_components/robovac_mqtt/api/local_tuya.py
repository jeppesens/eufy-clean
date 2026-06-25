"""Local Tuya transport for Eufy Clean devices.

Provides a push-based alternative to the Tuya Cloud polling path: the dock
publishes DPS updates over its LAN socket (port 6668) using the Tuya local
protocol. Same DPS payloads as the cloud path, just delivered instantly.

Built on the `tinytuya` library which handles v3.3 / v3.4 / v3.5 protocol
framing, encryption and session negotiation. All DPS values arrive in the
same {"dps": {key: value}} envelope used elsewhere in the integration, so
the existing parser/commands modules consume them unchanged.

Compared with the cloud transport this gives:
- ~immediate state updates instead of 30 s polling
- works while Eufy / Tuya cloud is unreachable
- requires LAN reachability between HA and the dock plus the device's
  16-character local key (auto-discovered from the user's Tuya Cloud login)
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable
from typing import Any

try:
    import tinytuya
except ImportError:  # pragma: no cover - tinytuya is declared in manifest.json
    tinytuya = None

_LOGGER = logging.getLogger(__name__)

# tinytuya's blocking receive() should return promptly so we can react to
# cancellation; values larger than ~5 s leave us blocked too long if the
# device goes silent.
_RECV_TIMEOUT = 5.0
_RECONNECT_BACKOFF_INITIAL = 5.0
_RECONNECT_BACKOFF_MAX = 60.0


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
        self._dev: Any | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._listen_task: asyncio.Task | None = None
        self._stop = False
        # tinytuya's Device (socket/seqno/AES state) is not thread-safe; every
        # access run in the executor must be serialized through this lock so the
        # listen loop's receive() never overlaps a send/status/open/close.
        self._dev_lock = asyncio.Lock()

    def set_on_message(self, callback: Callable[[bytes], None]) -> None:
        """Register the callback the coordinator listens on for DPS updates."""
        self._on_message = callback

    async def connect(self) -> None:
        """Open the socket and start the background listener."""
        self._loop = asyncio.get_running_loop()
        self._stop = False
        async with self._dev_lock:
            await self._loop.run_in_executor(None, self._open_device)
        # Initial status fetch — surfaces current DPS state to the coordinator
        # before the gratuitous-update stream takes over.
        try:
            async with self._dev_lock:
                initial = await self._loop.run_in_executor(None, self._dev.status)  # type: ignore[union-attr]
            self._dispatch(initial)
        except Exception as e:  # noqa: BLE001 - tinytuya raises broadly
            _LOGGER.debug(
                "Local Tuya %s: initial status fetch failed (%s); "
                "will rely on gratuitous updates",
                self.device_id, e,
            )
        self._listen_task = self._loop.create_task(self._listen_loop())

    def _open_device(self) -> None:
        """Construct the underlying tinytuya.Device (blocking).

        Callers must hold ``self._dev_lock`` so the close/reassign below cannot
        race the listen loop's receive(). Best-effort close any previous Device
        first to avoid leaking its socket on reconnect.
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
            connection_timeout=10,
            persist=True,
        )
        # Don't let tinytuya retry endlessly on missing replies — we manage
        # reconnect ourselves so we can surface failures to the coordinator.
        self._dev.set_socketRetryLimit(1)
        self._dev.set_socketRetryDelay(0)

    async def disconnect(self) -> None:
        """Cancel the listener task and close the socket."""
        # Set _stop first so the listen loop exits after its current receive()
        # cycle instead of starting another.
        self._stop = True

        # Close the device BEFORE cancelling the listener. Acquiring _dev_lock
        # here blocks until the listen loop's in-flight receive() executor thread
        # has actually finished (the loop only releases the lock once
        # run_in_executor resolves), so close() never runs concurrently with
        # receive() on the same non-thread-safe socket. Cancelling the task first
        # would instead inject CancelledError, unwind the loop's `async with`
        # immediately and free the lock while the executor thread keeps running —
        # letting close() race the still-active receive().
        if self._dev:
            async with self._dev_lock:
                try:
                    await self._loop.run_in_executor(None, self._dev.close)  # type: ignore[union-attr]
                except Exception:  # noqa: BLE001 - close is best-effort
                    pass
                self._dev = None

        if self._listen_task:
            self._listen_task.cancel()
            try:
                await self._listen_task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
            self._listen_task = None

    async def send_command(self, dps: dict[str, Any]) -> None:
        """Send a DPS write to the device.

        ``dps`` is a mapping of DPS index (string) to value matching the same
        format the MQTT and Cloud transports use. Values may be plain
        bool/int/string for legacy DPS or base64-encoded protobuf strings for
        novel DPS — the device handles both.
        """
        if not self._dev or not self._loop:
            raise LocalTuyaError(
                f"Local Tuya {self.device_id}: not connected"
            )
        _LOGGER.debug(
            "Local Tuya %s: sending DPS %s", self.device_id, list(dps.keys())
        )
        # tinytuya's set_multiple_values takes {dp_index: value} where dp_index
        # may be int or string. Returns a dict on success / error info dict on
        # failure; we only care about exceptions.
        try:
            async with self._dev_lock:
                await self._loop.run_in_executor(
                    None, self._dev.set_multiple_values, dps
                )
        except Exception as e:  # noqa: BLE001 - tinytuya raises broadly
            raise LocalTuyaError(
                f"Failed to send local Tuya command to {self.device_id}: {e}"
            ) from e

    async def _listen_loop(self) -> None:
        """Pump status() and receive() in the background, dispatching DPS pushes."""
        backoff = _RECONNECT_BACKOFF_INITIAL
        while not self._stop:
            try:
                # Hold the lock for one bounded receive() cycle then release it
                # between cycles so send_command() can acquire it promptly.
                async with self._dev_lock:
                    payload = await self._loop.run_in_executor(  # type: ignore[union-attr]
                        None, self._receive_with_timeout
                    )
                if payload is None:
                    continue
                # tinytuya may return error strings on socket failures
                if isinstance(payload, dict) and "Error" in payload:
                    err_msg = payload.get("Error")
                    if "timeout" in str(err_msg).lower():
                        continue
                    _LOGGER.debug(
                        "Local Tuya %s: device error '%s'; reconnecting in %.0fs",
                        self.device_id, err_msg, backoff,
                    )
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2, _RECONNECT_BACKOFF_MAX)
                    async with self._dev_lock:
                        await self._loop.run_in_executor(None, self._open_device)  # type: ignore[union-attr]
                    await self._refetch_status()
                    continue

                self._dispatch(payload)
                backoff = _RECONNECT_BACKOFF_INITIAL  # any successful packet resets
            except asyncio.CancelledError:
                break
            except Exception as e:  # noqa: BLE001 - tinytuya raises broadly
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
        """Re-fetch status() after a reconnect so state isn't stale until the
        next push (mirrors connect()'s initial fetch)."""
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
        """Blocking receive() with a bounded timeout so the loop stays responsive."""
        # tinytuya doesn't expose a per-call timeout, so we set the persistent
        # socket timeout once and rely on receive() returning Error/None on
        # timeout — the listen loop ignores those.
        if self._dev is None:
            return None
        self._dev.set_socketTimeout(_RECV_TIMEOUT)
        return self._dev.receive()

    def _dispatch(self, payload: Any) -> None:
        """Wrap a DPS payload into the MQTT envelope and fire the callback."""
        if not isinstance(payload, dict):
            return
        dps = payload.get("dps")
        if not isinstance(dps, dict) or not dps:
            return
        if not self._on_message:
            return
        # Match the wire format _handle_mqtt_message expects:
        #   {"payload": json.dumps({"data": <dps>})}
        # then the coordinator parses payload as JSON, extracts data.
        envelope = json.dumps(
            {"payload": json.dumps({"data": dps})}
        ).encode()
        self._on_message(envelope)
