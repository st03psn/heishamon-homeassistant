"""Test the compressor run tracker."""
from custom_components.aquarea.logic.cycles import (
    CycleTracker,
    RunFinished,
    RunStarted,
)
from custom_components.aquarea.logic.state import OperatingState as S

DAY = "2026-11-25"


def feed(tracker, start, end, state, day=DAY, step=30):
    """Call the tracker every `step` seconds from start up to and including end."""
    events = []
    now = start
    while now <= end:
        events += tracker.update(now, day, state)
        now += step
    return events


def test_one_run():
    tracker = CycleTracker()
    assert feed(tracker, 0, 300, S.IDLE) == []
    events = feed(tracker, 330, 1500, S.HEATING)
    assert events == [RunStarted(at=330, pause=None)]
    assert tracker.running and tracker.today.starts == 1
    events = feed(tracker, 1530, 1600, S.IDLE)
    assert events == [
        RunFinished(at=1530, duration=1200, defrosts=0, short=False, purpose="heating")
    ]
    assert not tracker.running
    assert tracker.last_run_seconds == 1200
    assert tracker.today.run_seconds == 1200
    assert tracker.today.short_runs == 0


def test_pause_and_short_run():
    tracker = CycleTracker()
    feed(tracker, 0, 300, S.HEATING)
    feed(tracker, 330, 900, S.IDLE)
    events = feed(tracker, 930, 1000, S.HEATING)
    assert events == [RunStarted(at=930, pause=600)]
    assert tracker.last_pause_seconds == 600
    assert tracker.today.short_runs == 1
    assert tracker.today.starts == 2


def test_defrost_belongs_to_the_run():
    tracker = CycleTracker()
    feed(tracker, 0, 600, S.HEATING)
    feed(tracker, 630, 900, S.DEFROST)
    feed(tracker, 930, 1200, S.HEATING)
    feed(tracker, 1230, 1500, S.DEFROST)
    events = feed(tracker, 1530, 1530, S.IDLE)
    assert events == [
        RunFinished(at=1530, duration=1530, defrosts=2, short=False, purpose="heating")
    ]
    assert tracker.today.defrosts == 2
    assert tracker.today.starts == 1


def test_purpose_is_what_took_longest():
    tracker = CycleTracker()
    feed(tracker, 0, 300, S.HEATING)
    feed(tracker, 330, 1500, S.DHW)
    (finished,) = feed(tracker, 1530, 1530, S.OFF)
    assert finished.purpose == "dhw"


def test_switching_off_or_a_fault_ends_the_run():
    for end_state in (S.OFF, S.FAULT):
        tracker = CycleTracker()
        feed(tracker, 0, 900, S.HEATING)
        (finished,) = feed(tracker, 930, 930, end_state)
        assert isinstance(finished, RunFinished) and finished.duration == 930


def test_gap_is_not_counted_as_run_time():
    tracker = CycleTracker()
    feed(tracker, 0, 300, S.HEATING)
    # nothing for an hour, then still running: only MAX_STEP is added
    tracker.update(3900, DAY, S.HEATING)
    assert tracker.run_seconds == 300 + 120


def test_unknown_state_keeps_the_run_open_and_counts_nothing():
    tracker = CycleTracker()
    feed(tracker, 0, 300, S.HEATING)
    assert feed(tracker, 330, 900, None) == []
    assert tracker.running
    feed(tracker, 930, 1200, S.HEATING)
    # 0-300 and 930-1200; the step into 930 follows an unknown state
    assert tracker.run_seconds == 300 + 270


def test_new_day_resets_the_counters_but_not_the_run():
    tracker = CycleTracker()
    feed(tracker, 0, 600, S.HEATING, day="2026-11-25")
    feed(tracker, 630, 1200, S.HEATING, day="2026-11-26")
    assert tracker.today.day == "2026-11-26"
    assert tracker.today.starts == 0
    assert tracker.today.run_seconds == 600
    (finished,) = feed(tracker, 1230, 1230, S.IDLE, day="2026-11-26")
    assert finished.duration == 1230


def test_store_and_restore():
    tracker = CycleTracker()
    feed(tracker, 0, 600, S.HEATING)
    feed(tracker, 630, 900, S.DEFROST)
    restored = CycleTracker.from_dict(tracker.as_dict())
    assert restored.running and restored.run_seconds == 900
    assert restored.today.starts == 1 and restored.today.defrosts == 1
    assert restored.last_update is None
    # the time while it was stored does not count
    restored.update(5000, DAY, S.HEATING)
    assert restored.run_seconds == 900
    (finished,) = restored.update(5030, DAY, S.IDLE)
    assert finished.duration == 930 and finished.defrosts == 1


def test_run_seen_only_in_part_is_not_a_short_run():
    # HeishaMon offline during the run
    tracker = CycleTracker()
    feed(tracker, 0, 120, S.HEATING)
    feed(tracker, 150, 3000, None)
    (finished,) = tracker.update(3030, DAY, S.IDLE)
    assert finished.short is False and finished.duration == 120
    assert tracker.today.short_runs == 0

    # Home Assistant restarted during the run
    tracker = CycleTracker()
    feed(tracker, 0, 120, S.HEATING)
    restored = CycleTracker.from_dict(tracker.as_dict())
    (finished,) = restored.update(9000, DAY, S.IDLE)
    assert finished.short is False

    # a run seen from start to end still is
    tracker = CycleTracker()
    feed(tracker, 0, 120, S.HEATING)
    (finished,) = tracker.update(150, DAY, S.IDLE)
    assert finished.short is True
