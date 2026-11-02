"""Live camera stream for the S1 Pro: robot -> P2P -> ffmpeg -> latest JPEG.

The robot only streams while a P2P session is open, and only after its
video-manager has been told to ``StreamOpen`` (DP 181). :class:`RobotVideo` ties
that lifecycle to whoever is looking: the first viewer opens the stream, a short
linger keeps it warm between requests, and the last one out closes it again so the
camera is never left running unattended.

The H.265 NAL units from the session are piped to ffmpeg, which decodes them to a
stream of JPEGs; the newest one is what the camera entity serves.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from typing import TYPE_CHECKING

from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.event import async_call_later

from .api.p2p import P2PError, P2PRefused
from .api.p2p.video import VideoSession
from .const import VIDEO_MGR_STATE_SET, VIDEO_MGR_STREAM_OPEN, WORK_STATE_REMOTE_CTRL

if TYPE_CHECKING:
    from .coordinator import EufyCleanCoordinator
    from .p2p_map import P2PMapFeed

_LOGGER = logging.getLogger(__name__)

LINGER_SECONDS = 20.0  # keep streaming this long after the last viewer leaves
FIRST_FRAME_TIMEOUT = 15.0
_OPEN_REPLY_TIMEOUT = 5.0
_STALL_SECONDS = 10.0  # no new frame for this long -> restart the session
# Each attempt fetches a cloud config that reserves a slot on the robot until used,
# so a refusing robot is retried rarely, not hammered.
_RETRY_BACKOFF = (5.0, 30.0, 300.0, 600.0)
_SLOT_WAIT = 45.0  # how long to wait for the map feed to finish its session
# A robot that refuses a session refuses for longer the more it is asked.
_REFUSAL_BACKOFF = 30 * 60
_JPEG_START, _JPEG_END = b"\xff\xd8", b"\xff\xd9"

# H.265 NAL units in on stdin, one JPEG per frame out on stdout.
# * Low latency comes from a small probe and `low_delay`, NOT `-fflags nobuffer`,
#   which makes ffmpeg emit nothing for a raw H.265 pipe.
# * The robot's video is limited-range YUV, which the MJPEG encoder only accepts as
#   full-range (`yuvj420p`); without the conversion it fails to open.
FFMPEG_ARGS: tuple[str, ...] = (
    "-loglevel", "error",
    "-probesize", "65536", "-analyzeduration", "0", "-flags", "low_delay",
    "-f", "hevc", "-i", "pipe:0",
    "-an", "-pix_fmt", "yuvj420p",
    "-f", "image2pipe", "-c:v", "mjpeg", "-q:v", "5", "pipe:1",
)


def retry_delay(*, refused: bool, attempt: int) -> float:
    """Seconds to wait before the next stream attempt (the nth in a row)."""
    if refused:
        return _REFUSAL_BACKOFF
    return _RETRY_BACKOFF[min(attempt, len(_RETRY_BACKOFF) - 1)]


def _ffmpeg_binary(hass: HomeAssistant) -> str:
    """The ffmpeg to run: the one Home Assistant's ffmpeg integration is configured
    with if it is loaded (it may be a custom path), otherwise ``ffmpeg`` on PATH."""
    try:
        from homeassistant.components.ffmpeg import (  # noqa: PLC0415  # pylint: disable=import-outside-toplevel
            get_ffmpeg_manager,
        )

        return get_ffmpeg_manager(hass).binary
    except (ImportError, ValueError):
        return "ffmpeg"


class RobotVideo:
    """Reference-counted live video for one robot."""

    def __init__(self, hass: HomeAssistant, coordinator: EufyCleanCoordinator) -> None:
        self._hass = hass
        self._coordinator = coordinator
        self._holders = 0
        self._linger_cancel: CALLBACK_TYPE | None = None
        self._task: asyncio.Task | None = None
        self._frame: bytes | None = None
        self._frame_at = 0.0
        self._frame_event = asyncio.Event()
        self.last_error: str | None = None
        self.sessions = 0
        self._kick = asyncio.Event()  # a new viewer wakes a stream that is backing off
        self._cooling_down = False  # ...unless the robot is refusing sessions

    # -- public ------------------------------------------------------------

    @property
    def streaming(self) -> bool:
        return self._task is not None and not self._task.done()

    @property
    def frame_age(self) -> float | None:
        return time.monotonic() - self._frame_at if self._frame is not None else None

    def _fresh_frame(self) -> bytes | None:
        if (
            self._coordinator.data.camera_enabled is True
            and self._coordinator.data.status_code == WORK_STATE_REMOTE_CTRL
            and self._frame is not None
            and time.monotonic() - self._frame_at < _STALL_SECONDS
        ):
            return self._frame
        return None

    @asynccontextmanager
    async def hold(self) -> AsyncIterator[RobotVideo]:
        """Keep the stream open for the duration of the ``async with`` block."""
        if self._coordinator.data.camera_enabled is not True:
            raise HomeAssistantError(
                "The robot's camera is switched off. Hold Start/Pause and Recharge on the "
                "robot for 10 seconds to turn it on."
            )
        if self._coordinator.data.status_code != WORK_STATE_REMOTE_CTRL:
            raise HomeAssistantError("Enable manual control before viewing the robot camera")
        self._holders += 1
        self._cancel_linger()
        self._ensure_running()
        if not self._cooling_down:
            self._kick.set()
        try:
            yield self
        finally:
            self._holders -= 1
            if self._holders == 0:
                self._linger_cancel = async_call_later(self._hass, LINGER_SECONDS, self._linger_over)

    async def wait_for_frame(self, timeout: float = FIRST_FRAME_TIMEOUT) -> bytes | None:
        """Return a fresh JPEG, waiting for the first one if the stream is starting."""
        deadline = time.monotonic() + timeout
        while True:
            if (
                self._coordinator.data.camera_enabled is not True
                or self._coordinator.data.status_code != WORK_STATE_REMOTE_CTRL
            ):
                return None
            if (frame := self._fresh_frame()) is not None:
                return frame
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not self.streaming:
                return None
            self._frame_event.clear()
            with suppress(TimeoutError):
                await asyncio.wait_for(self._frame_event.wait(), remaining)

    async def latest(self) -> bytes | None:
        return self._fresh_frame()

    async def stop(self) -> None:
        self._cancel_linger()
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await task

    # -- lifecycle ---------------------------------------------------------

    def _ensure_running(self) -> None:
        if not self.streaming:
            self._task = self._hass.async_create_background_task(
                self._run(), f"robovac_mqtt video {self._coordinator.device_name}"
            )

    def _cancel_linger(self) -> None:
        if self._linger_cancel is not None:
            self._linger_cancel()
            self._linger_cancel = None

    @callback
    def _linger_over(self, _now) -> None:
        self._linger_cancel = None
        if self._holders == 0 and self._task is not None:
            self._task.cancel()

    async def _run(self) -> None:
        attempt = 0
        try:
            while True:
                refused = False
                try:
                    await self._stream_once()
                    attempt = 0
                except (HomeAssistantError, P2PError, OSError) as err:
                    self.last_error = str(err)
                    refused = isinstance(err, P2PRefused)
                    if self._coordinator.data.status_code != WORK_STATE_REMOTE_CTRL:
                        break  # mode changed: close the camera, without changing the robot's mode
                    _LOGGER.debug("Video stream for %s ended: %s", self._coordinator.device_name, err)
                delay = retry_delay(refused=refused, attempt=attempt)
                attempt += 1
                self._cooling_down = refused
                self._kick.clear()
                with suppress(TimeoutError):
                    await asyncio.wait_for(self._kick.wait(), delay)
                self._cooling_down = False
        finally:
            self._cooling_down = False
            await self._close_robot_stream()
            self._frame = None
            self._frame_event.set()

    async def _stream_once(self) -> None:
        coordinator = self._coordinator
        feed = coordinator.p2p
        if feed is None:
            raise HomeAssistantError("No local P2P connection to the robot")
        if coordinator.data.status_code != WORK_STATE_REMOTE_CTRL:
            # HA maps remote control to activity="cleaning", so the raw mode is
            # authoritative here. Never reserve a session outside manual control.
            if coordinator.data.activity in ("cleaning", "returning"):
                raise HomeAssistantError("The robot is busy; enable manual control before viewing its camera")
            raise HomeAssistantError("Enable manual control before viewing the robot camera")
        try:
            await feed.acquire_slot(_SLOT_WAIT)
        except TimeoutError as err:
            raise HomeAssistantError("The robot is busy with the map; try again in a moment") from err
        try:
            await self._stream_in_slot(feed)
        finally:
            feed.release_slot()

    async def _stream_in_slot(self, feed: P2PMapFeed) -> None:
        self._frame = None  # a new session must not serve the previous session's image
        rtc = await feed.get_rtc()
        stdin: asyncio.StreamWriter | None = None

        def write_nal(nal: bytes) -> None:
            if stdin is not None and not stdin.is_closing():
                stdin.write(nal)

        # Validate the reserved session before launching a decoder process.
        session = VideoSession(
            host=feed.host,
            local_key=feed.local_key,
            device_id=feed.device_id,
            device_password=rtc["device_password"],
            ice_config=rtc.get("ice_config"),
            cloud_session=rtc.get("session") or {},
            open_stream=self._open_robot_stream,
            on_nal=write_nal,
        )
        ffmpeg = await asyncio.create_subprocess_exec(
            _ffmpeg_binary(self._hass),
            *FFMPEG_ARGS,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        assert ffmpeg.stdin is not None and ffmpeg.stdout is not None
        stdin = ffmpeg.stdin
        self.sessions += 1
        reader = asyncio.ensure_future(self._read_frames(ffmpeg.stdout))
        watchdog = asyncio.ensure_future(self._watch_stall(session.connect_timeout))
        runner = asyncio.ensure_future(session.run())
        try:
            done, _ = await asyncio.wait({runner, reader, watchdog}, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                task.result()  # re-raise the failure that ended the stream
        finally:
            for task in (runner, reader, watchdog):
                task.cancel()
            await session.close()
            await asyncio.gather(runner, reader, watchdog, return_exceptions=True)
            with suppress(Exception):
                stdin.close()
            with suppress(ProcessLookupError):
                ffmpeg.kill()
            with suppress(Exception):
                await ffmpeg.wait()

    async def _read_frames(self, stdout: asyncio.StreamReader) -> None:
        buffer = bytearray()
        while chunk := await stdout.read(65536):
            buffer += chunk
            while True:
                start = buffer.find(_JPEG_START)
                end = buffer.find(_JPEG_END, start + 2) if start >= 0 else -1
                if start < 0 or end < 0:
                    break
                self._frame = bytes(buffer[start : end + 2])
                self._frame_at = time.monotonic()
                self.last_error = None
                self._frame_event.set()
                del buffer[: end + 2]
        raise P2PError("the video decoder stopped")

    async def _watch_stall(self, first_frame_allowance: float) -> None:
        """Allow the session timeout for its first frame, then bound decoded-frame gaps."""
        started = time.monotonic()
        while True:
            await asyncio.sleep(1)
            if self._coordinator.data.status_code != WORK_STATE_REMOTE_CTRL:
                raise HomeAssistantError("Manual control ended; closing the robot camera")
            if self._coordinator.data.camera_enabled is not True:
                raise HomeAssistantError("The robot camera was switched off; closing its stream")
            idle = time.monotonic() - max(self._frame_at, started)
            allowance = first_frame_allowance if self._frame_at < started else _STALL_SECONDS
            if idle > allowance:
                raise P2PError(f"no video frames for {idle:.0f}s")

    # -- the robot's video manager (DP 181) --------------------------------

    async def _open_robot_stream(self) -> None:
        """Set ``passEn`` and open the stream while manual control is enabled."""
        await self._video_command("video_pass_enable", VIDEO_MGR_STATE_SET)
        await self._video_command("video_stream_open", VIDEO_MGR_STREAM_OPEN)

    async def _video_command(self, command: str, method: int) -> None:
        coordinator = self._coordinator
        sent = time.monotonic()
        # wait=False: the robot answers with a DP 181 push, which the coordinator
        # parses; waiting would swallow that reply as the write's return value.
        await coordinator.async_send_command(coordinator.build_device_command(command), wait=False)
        deadline = sent + _OPEN_REPLY_TIMEOUT
        while time.monotonic() < deadline:
            reply = coordinator.data.video_response
            if reply and reply[2] >= sent and reply[0] == method:
                if reply[1] != 0:
                    raise HomeAssistantError(
                        f"The robot refused to open its camera (result {reply[1]}). "
                        "It may be busy or the camera switch may be off."
                    )
                return
            await asyncio.sleep(0.1)
        raise HomeAssistantError("The robot did not answer the camera stream request")

    async def _close_robot_stream(self) -> None:
        coordinator = self._coordinator
        with suppress(Exception):
            await coordinator.async_send_command(
                coordinator.build_device_command("video_stream_close"), wait=False
            )
