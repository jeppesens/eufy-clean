"""Tests for local-only mode: an S1 Pro cut off from its cloud."""

from custom_components.robovac_mqtt.offline import (
    CHARGE_PROOF,
    CLOUD_CHECK_EVERY,
    CLOUD_CHECK_MAX,
    DOCK_AFTER_STOP,
    LOCAL_ONLY_AFTER,
    TICK_WINDOW,
    LocalOnlyTracker,
)


def _tracker() -> LocalOnlyTracker:
    return LocalOnlyTracker(connected_at=0.0)


def test_not_local_only_while_cloud_dps_arrive():
    t = _tracker()
    for now in range(0, 1000, 60):
        t.record({"173": "x", "6": 0}, now=now)
    t.note_cloud_status(False, now=1000)  # even a stale "offline" answer
    assert not t.quiet(now=1000)
    assert not t.local_only(now=1000)


def test_quiet_alone_is_not_local_only():
    """An idle robot that is online goes quiet too: wait for the cloud's word."""
    t = _tracker()
    t.record({"6": 0, "163": 80}, now=LOCAL_ONLY_AFTER + 1)
    assert t.quiet(now=LOCAL_ONLY_AFTER + 1)
    assert not t.local_only(now=LOCAL_ONLY_AFTER + 1)
    t.note_cloud_status(True, now=LOCAL_ONLY_AFTER + 1)
    assert not t.local_only(now=LOCAL_ONLY_AFTER + 2)


def test_local_only_when_quiet_and_cloud_says_offline():
    t = _tracker()
    t.record({"6": 0}, now=LOCAL_ONLY_AFTER + 1)
    t.note_cloud_status(False, now=LOCAL_ONLY_AFTER + 1)
    assert t.local_only(now=LOCAL_ONLY_AFTER + 2)


def test_a_cloud_dps_ends_local_only_at_once():
    t = _tracker()
    t.record({"6": 0}, now=LOCAL_ONLY_AFTER + 1)
    t.note_cloud_status(False, now=LOCAL_ONLY_AFTER + 1)
    t.record({"153": "x"}, now=LOCAL_ONLY_AFTER + 30)
    assert t.cloud_online is True
    assert not t.local_only(now=LOCAL_ONLY_AFTER + 31)


def test_not_local_only_when_robot_silent_altogether():
    t = _tracker()
    t.record({"6": 0}, now=10)
    t.note_cloud_status(False, now=10)
    assert not t.local_only(now=10 + LOCAL_ONLY_AFTER + 1)


def test_cloud_check_cadence():
    t = _tracker()
    assert t.needs_cloud_check(now=10)  # at connect, before any cloud DPS
    t.record({"173": "x"}, now=5)
    t2 = _tracker()
    t2.record({"173": "x"}, now=5)
    assert not t2.needs_cloud_check(now=10)  # it is talking to its cloud
    t.note_cloud_status(True, now=LOCAL_ONLY_AFTER + 10)
    assert not t.needs_cloud_check(now=LOCAL_ONLY_AFTER + 60)
    # "online" answers back off: 600 s after the first, then 1200 s, capped
    first = LOCAL_ONLY_AFTER + 10
    assert not t.needs_cloud_check(now=first + CLOUD_CHECK_EVERY)
    assert t.needs_cloud_check(now=first + 2 * CLOUD_CHECK_EVERY)
    t.note_cloud_status(None, now=first + 2 * CLOUD_CHECK_EVERY)
    assert t.cloud_online is True  # "can't tell" keeps what we knew
    assert t.cloud_check_every == 4 * CLOUD_CHECK_EVERY
    for _ in range(5):
        t.note_cloud_status(True, now=first)
    assert t.cloud_check_every == CLOUD_CHECK_MAX
    t.note_intent("cleaning", now=first)  # a command: check again soon
    assert t.cloud_check_every == CLOUD_CHECK_EVERY


def test_offline_from_connect_needs_no_quiet_spell():
    t = _tracker()
    t.record({"6": 0, "163": 80}, now=10)
    t.note_cloud_status(False, now=10)
    assert t.local_only(now=11)


def test_a_late_offline_answer_loses_to_a_fresh_cloud_dps():
    t = _tracker()
    t.record({"6": 0}, now=LOCAL_ONLY_AFTER + 1)
    t.record({"173": "x"}, now=LOCAL_ONLY_AFTER + 20)  # arrives while asking
    t.note_cloud_status(False, now=LOCAL_ONLY_AFTER + 30, asked_at=LOCAL_ONLY_AFTER + 5)
    assert t.cloud_online is True
    assert not t.local_only(now=LOCAL_ONLY_AFTER + 31)


def test_command_dps_do_not_count_as_cloud_traffic():
    t = _tracker()
    t.record({"152": "AA==", "170": "AggB", "6": 0}, now=10)
    assert t.last_cloud_dps is None


def test_generic_area_and_suction_recorded():
    t = _tracker()
    t.record({"7": 12, "9": "strong"}, now=10)
    t.record({"7": True, "9": "bogus"}, now=11)
    assert (t.clean_area, t.suction) == (12, "Turbo")


def test_ticks_mean_cleaning():
    t = _tracker()
    t.record({"6": 1}, now=400)
    t.record({"6": 2}, now=460)
    assert t.infer("docked", now=470) == "cleaning"


def test_ticks_after_return_intent_mean_returning():
    t = _tracker()
    t.record({"6": 1}, now=400)
    t.note_intent("returning", now=450)
    t.record({"6": 2}, now=460)
    assert t.infer("cleaning", now=470) == "returning"


def test_docked_once_ticks_stop_and_battery_holds():
    t = _tracker()
    t.record({"6": 1, "163": 60}, now=400)
    t.record({"6": 2, "163": 59}, now=460)
    t.infer("cleaning", now=470)
    later = 460 + TICK_WINDOW + DOCK_AFTER_STOP
    t.record({"6": 2, "163": 60}, now=later)
    assert t.infer("returning", now=later) == "docked"


def test_idle_when_stopped_off_dock_and_battery_falls():
    t = _tracker()
    t.record({"6": 1, "163": 60}, now=400)
    t.record({"6": 2, "163": 60}, now=460)
    t.note_intent("idle", now=470)
    t.record({"163": 55}, now=900)
    assert t.infer("cleaning", now=900) == "idle"


def test_start_intent_shows_cleaning_before_first_tick():
    t = _tracker()
    t.record({"6": 0}, now=400)
    t.note_intent("cleaning", now=410)
    assert t.infer("docked", now=420) == "cleaning"


def test_pause_intent_holds_without_ticks():
    t = _tracker()
    t.note_intent("paused", now=400)
    assert t.infer("cleaning", now=500) == "paused"


def test_pause_wins_over_a_recent_tick_until_the_robot_ticks_again():
    t = _tracker()
    t.record({"6": 1}, now=400)
    t.record({"6": 2}, now=460)
    t.note_intent("paused", now=470)
    assert t.infer("cleaning", now=480) == "paused"
    t.note_intent("cleaning", now=500)  # resume
    t.record({"6": 3}, now=520)
    assert t.infer("paused", now=525) == "cleaning"


def test_pose_off_the_dock_means_idle_not_docked():
    t = _tracker()
    t.record({"6": 1, "163": 70}, now=400)
    assert t.infer("docked", now=2000, away=True) == "idle"
    assert t.infer("idle", now=2000, away=False) == "docked"


def test_pose_off_the_dock_while_returning_stays_returning():
    t = _tracker()
    t.note_intent("returning", now=400)
    assert t.infer("cleaning", now=500, away=True) == "returning"


def test_ignored_start_falls_back_to_docked():
    t = _tracker()
    t.note_intent("cleaning", now=400)
    assert t.infer("docked", now=450, away=False) == "cleaning"
    assert t.infer("cleaning", now=600, away=False) == "docked"


def test_garbage_dps_values_are_ignored():
    t = _tracker()
    t.record({"6": "x", "163": None}, now=10)
    assert t.clean_minutes is None and t.battery is None


def test_stale_intent_expires():
    t = _tracker()
    t.note_intent("returning", now=0)
    assert t.infer("returning", now=5000) == "docked"


def test_falling_battery_off_the_dock_means_idle_without_a_pose():
    t = _tracker()
    t.record({"163": 60}, now=400)
    t.infer("cleaning", now=400)
    t.record({"163": 55}, now=450)
    assert t.infer("cleaning", now=450) == "idle"


def test_return_intent_holds_until_docked():
    t = _tracker()
    t.record({"163": 60}, now=400)
    t.note_intent("returning", now=400)
    assert t.infer("cleaning", now=450) == "returning"


def test_stop_or_pause_on_the_dock_shows_docked():
    t = _tracker()
    t.note_intent("idle", now=400)
    assert t.infer("idle", now=500, away=False) == "docked"
    t.note_intent("paused", now=600)
    assert t.infer("paused", now=700, away=False) == "docked"
    assert t.infer("paused", now=700, away=True) == "paused"
    assert t.infer("paused", now=700) == "paused"  # no pose: trust the intent


def test_live_dps8_battery_wins_over_the_frozen_163():
    """Offline, 163 sticks at its last value; the generic DPS 8 keeps counting."""
    t = _tracker()
    t.record({"8": 69, "163": 100}, now=400)
    assert t.battery == 69
    t.record({"163": 100}, now=460)  # 163 alone: still frozen, ignored
    assert t.battery == 69
    t.record({"8": 68}, now=520)
    assert t.battery == 68


def test_stranded_below_full_without_charging_is_idle_not_docked():
    """24 Nov: stopped off the dock with no pose, DPS 8 at 69 and never rising."""
    t = _tracker()
    t.record({"6": 1, "8": 70}, now=400)
    t.record({"6": 2, "8": 69}, now=460)
    t.infer("cleaning", now=470)
    later = 460 + TICK_WINDOW + DOCK_AFTER_STOP
    assert t.infer("cleaning", now=later) == "docked"  # too early to tell
    assert t.infer("docked", now=460 + CHARGE_PROOF + 1) == "idle"


def test_a_rising_battery_means_docked_and_charging():
    t = _tracker()
    t.record({"6": 1, "8": 60}, now=400)
    t.record({"6": 2, "8": 59}, now=460)
    t.infer("cleaning", now=470)
    t.record({"8": 60}, now=700)
    assert t.infer("returning", now=700) == "docked"
    assert t.infer("docked", now=460 + CHARGE_PROOF + 1) == "docked"


def test_full_battery_on_the_dock_stays_docked():
    t = _tracker()
    t.record({"6": 1, "8": 100}, now=400)
    t.record({"6": 2, "8": 100}, now=460)
    t.infer("cleaning", now=470)
    assert t.infer("docked", now=460 + CHARGE_PROOF * 3) == "docked"


def test_a_return_that_never_charges_stays_returning_then_goes_idle():
    """The dock retry automation catches 'returning' for 6 min, or 'idle' for 10."""
    t = _tracker()
    t.record({"8": 68}, now=400)
    t.note_intent("returning", now=400)
    assert t.infer("returning", now=400 + CHARGE_PROOF + 1) == "returning"
    assert t.infer("returning", now=400 + 900 + 1) == "idle"
