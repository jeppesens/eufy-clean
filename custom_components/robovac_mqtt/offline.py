"""Local-only mode: keep a sensible state when the robot has no cloud connection.

When an S1 Pro on local Tuya cannot reach its cloud (blocked by the user's
firewall, or the internet is down), its Wi-Fi module stops relaying the Eufy
protobuf status: WorkStatus (153), errors and the station state no longer
arrive. It still accepts commands over the LAN, and it still reports the generic
Tuya robot-vacuum DPS:

* ``6``  cleaning time of the current task, minutes (keeps ticking while a task
  runs, including the trip home)
* ``7``  cleaned area, m2
* ``9``  suction (gentle / normal / strong / max)
* ``8``  battery %, the generic Tuya one: live. Eufy's own ``163`` is NOT; it
  freezes at its last value once the cloud is gone (seen: 163 stuck at 100 while
  8 counted 69, 68 on a robot stranded off the dock)

Without WorkStatus the coordinator would freeze on the last activity it saw.
:class:`LocalOnlyTracker` infers the activity from what is left: the
cleaning-time ticks, the battery trend, the live map pose and the command HA sent.
A robot on its dock charges, so off the dock shows as a battery that falls, or that
stays below full without rising for CHARGE_PROOF after the robot stopped.

Silence alone does not prove the robot is offline: an idle robot that is online
only pushes these DPS when something changes, and its ``status()`` reply never
includes them, online or not. So after a quiet spell the coordinator asks the
Tuya cloud (device list ``moduleMap.wifi.isOnline``), and any cloud-only DPS
that does arrive proves the robot is online straight away.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

# No cloud-only DPS for this long = quiet: poll status and ask the cloud.
LOCAL_ONLY_AFTER = 300.0
# Ask the cloud at connect, then (while quiet) after this long, doubling up to
# CLOUD_CHECK_MAX while it keeps saying "online" or can't tell.
CLOUD_CHECK_EVERY = 300.0
CLOUD_CHECK_MAX = 1800.0
# Status DPS the robot only pushes while it has its cloud connection. Command DPS
# (152 play/pause, 155 direction, 160 find, 162 language, 170 map edit) are left
# out: their replies could be echoes of a write. Seen offline on an S1 Pro:
# 6, 7, 8, 9, 10, 13, 40, 156, 158, 159, 161, 163.
CLOUD_ONLY_DPS = frozenset(
    {
        "153",
        "154",
        "157",
        "164",
        "165",
        "166",
        "167",
        "168",
        "169",
        "171",
        "172",
        "173",
        "176",
        "177",
        "178",
        "180",
        "181",
    }
)
# A cleaning-time tick within this window = a task is running.
TICK_WINDOW = 150.0
# After ticks stop (and the battery is not falling), assume the robot docked.
DOCK_AFTER_STOP = 120.0
# A start that has not left the dock after this long was ignored by the robot.
START_TIMEOUT = 150.0
# Stopped this long below FULL_ENOUGH % without the battery rising = not on the dock
# (a docked robot charges within a minute or two).
CHARGE_PROOF = 600.0
FULL_ENOUGH = 98
# Further than this from the dock (live map pose, cm) = not docked.
AWAY_FROM_DOCK_CM = 80.0
# How long an intent from a command is trusted before evidence takes over. A
# pause or stop holds until the robot ticks again (a resume), up to half a day.
INTENT_GRACE = {
    "cleaning": 240.0,
    "returning": 900.0,
    "paused": 43200.0,
    "idle": 43200.0,
}

STD_SUCTION = {"gentle": "Quiet", "normal": "Standard", "strong": "Turbo", "max": "Max"}


def _int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        return None
    try:
        return int(value)
    except ValueError:
        return None


@dataclass
class LocalOnlyTracker:
    """Track the evidence a local-only robot still gives and infer its activity."""

    connected_at: float = field(default_factory=time.monotonic)
    last_cloud_dps: float | None = None
    last_any: float | None = None
    cloud_online: bool | None = None
    cloud_checked_at: float | None = None
    cloud_check_every: float = CLOUD_CHECK_EVERY
    clean_minutes: int | None = None
    clean_area: int | None = None
    suction: str | None = None
    last_tick: float | None = None
    battery: int | None = None
    battery_live: bool = False  # seen the generic DPS 8, so ignore the frozen 163
    battery_rose_at: float | None = None
    battery_at_stop: int | None = None
    intent: str | None = None
    intent_at: float = 0.0

    def record(self, dps: dict, now: float | None = None) -> None:
        """Feed every DPS message in."""
        now = time.monotonic() if now is None else now
        self.last_any = now
        if CLOUD_ONLY_DPS.intersection(dps):
            self.last_cloud_dps = now
            self.cloud_online = True
        minutes = _int(dps.get("6"))
        if minutes is not None:
            if self.clean_minutes is not None and minutes > self.clean_minutes:
                self.last_tick = now
            self.clean_minutes = minutes
        area = _int(dps.get("7"))
        if area is not None:
            self.clean_area = area
        if dps.get("9") in STD_SUCTION:
            self.suction = STD_SUCTION[dps["9"]]
        battery = _int(dps.get("8"))
        if battery is not None:
            self.battery_live = True
        elif not self.battery_live:
            battery = _int(dps.get("163"))
        if battery is not None and 0 <= battery <= 100:
            if self.battery is not None and battery > self.battery:
                self.battery_rose_at = now
            self.battery = battery

    def note_intent(self, activity: str, now: float | None = None) -> None:
        """Remember what HA just asked the robot to do; check the cloud again soon."""
        self.intent = activity
        self.intent_at = time.monotonic() if now is None else now
        self.battery_at_stop = self.battery
        self.cloud_check_every = CLOUD_CHECK_EVERY

    def note_cloud_status(
        self,
        online: bool | None,
        now: float | None = None,
        asked_at: float | None = None,
    ) -> None:
        """Record the Tuya cloud's answer (None: it couldn't tell).

        A "not online" answer is dropped if a cloud-only DPS arrived after the
        question was asked: the robot is evidently online. None keeps what we knew.
        """
        now = time.monotonic() if now is None else now
        asked_at = now if asked_at is None else asked_at
        self.cloud_checked_at = now
        if online is False:
            if self.last_cloud_dps is None or self.last_cloud_dps < asked_at:
                self.cloud_online = False
            self.cloud_check_every = CLOUD_CHECK_EVERY
            return
        if online is True:
            self.cloud_online = True
        self.cloud_check_every = min(self.cloud_check_every * 2, CLOUD_CHECK_MAX)

    def quiet(self, now: float | None = None) -> bool:
        """True when no cloud-only DPS has arrived for LOCAL_ONLY_AFTER (or ever)."""
        now = time.monotonic() if now is None else now
        reference = (
            self.last_cloud_dps
            if self.last_cloud_dps is not None
            else self.connected_at
        )
        return now - reference > LOCAL_ONLY_AFTER

    def needs_cloud_check(self, now: float | None = None) -> bool:
        """Ask the cloud at connect (before any cloud DPS) and then while quiet."""
        now = time.monotonic() if now is None else now
        if self.cloud_checked_at is None:
            return self.last_cloud_dps is None or self.quiet(now)
        return self.quiet(now) and now - self.cloud_checked_at >= self.cloud_check_every

    def local_only(self, now: float | None = None) -> bool:
        """True while the cloud says the robot is offline and it still talks locally."""
        now = time.monotonic() if now is None else now
        if self.last_any is None or now - self.last_any > LOCAL_ONLY_AFTER:
            return False
        if self.cloud_online is not False:
            return False
        return self.last_cloud_dps is None or self.quiet(now)

    def stopped_at(self) -> float:
        """When the robot last did something: its last tick or HA's last command."""
        return max(self.last_tick or 0.0, self.intent_at or 0.0) or self.connected_at

    def charging(self) -> bool:
        """The battery has risen since the robot stopped: on the dock, charging."""
        return self.battery_rose_at is not None and self.battery_rose_at > self.stopped_at()

    def ticking(self, now: float) -> bool:
        return self.last_tick is not None and now - self.last_tick < TICK_WINDOW

    def infer(
        self, current: str, now: float | None = None, away: bool | None = None
    ) -> str:
        """Best guess of the activity from ticks, battery, position and the last intent.

        ``away`` is True when the live map pose is clearly off the dock, False when
        it is on it, None when there is no pose (no map feed).
        """
        now = time.monotonic() if now is None else now
        ticking = self.ticking(now)
        if ticking:
            self.battery_at_stop = None
        elif self.battery_at_stop is None:
            self.battery_at_stop = self.battery
        intent = self.intent
        if intent is not None and now - self.intent_at > INTENT_GRACE.get(
            intent, 600.0
        ):
            intent = None
        if intent in ("paused", "idle") and (
            self.last_tick is None or self.last_tick <= self.intent_at
        ):
            # Nothing has ticked since HA paused / stopped it. A stop on the dock
            # (or a pause the robot answered by going home) is still docked.
            return "docked" if away is False else intent
        if ticking:
            # Ticks continue on the way home, so a recent return intent wins.
            return "returning" if intent == "returning" else "cleaning"
        if intent == "cleaning" and not (
            away is False and now - self.intent_at > START_TIMEOUT
        ):
            return "cleaning"  # just started: the first tick takes up to two minutes
        if intent == "cleaning":
            intent = None  # never left the dock: the robot ignored the command
        stopped_for = now - self.stopped_at()
        charging = self.charging()
        falling = (
            self.battery is not None
            and self.battery_at_stop is not None
            and self.battery < self.battery_at_stop
        )
        uncharged = (
            self.battery is not None
            and self.battery < FULL_ENOUGH
            and stopped_for >= CHARGE_PROOF
            and not charging
        )
        if away is True:
            return "returning" if intent == "returning" else "idle"
        if charging:
            return "docked"
        if away is False and intent != "returning":
            return "docked"
        if falling or uncharged:
            # draining, or not charging: off the dock even with no pose to say so
            return "returning" if intent == "returning" else "idle"
        if stopped_for >= DOCK_AFTER_STOP:
            return "docked"
        if intent == "returning":
            return "returning"
        return current if current in ("docked", "idle", "paused") else "docked"
