"""Compressor runs: starts, run time, pauses, short runs and defrosts.

The tracker is fed with the current time and what the heat pump is doing.
It has to be fed at a steady pace, also while nothing changes, because run
time is added up from one call to the next. A gap longer than MAX_STEP (the
caller was not running, HeishaMon was offline) is not counted as run time.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Optional

from .state import OperatingState

# a run shorter than this counts as a short run
SHORT_RUN_SECONDS = 600
# longest time between two calls that still counts as run time
MAX_STEP = 120.0

RUNNING_STATES = frozenset(
    {
        OperatingState.HEATING,
        OperatingState.COOLING,
        OperatingState.DHW,
        OperatingState.DEFROST,
    }
)
PURPOSES = frozenset(
    {OperatingState.HEATING.value, OperatingState.COOLING.value, OperatingState.DHW.value}
)


@dataclass(frozen=True)
class RunStarted:
    """The compressor started."""

    at: float
    # seconds since the previous run ended, None when that is not known
    pause: Optional[float]


@dataclass(frozen=True)
class RunFinished:
    """The compressor stopped."""

    at: float
    # seconds of run time that were seen, without gaps
    duration: float
    defrosts: int
    short: bool
    # what the run did for most of its time: heating, cooling or dhw
    purpose: Optional[str]


@dataclass
class DayCounters:
    """Counters of one calendar day."""

    day: Optional[str] = None
    starts: int = 0
    run_seconds: float = 0.0
    short_runs: int = 0
    defrosts: int = 0


@dataclass
class CycleTracker:
    """Follows the compressor from run to run."""

    short_run_seconds: float = SHORT_RUN_SECONDS
    today: DayCounters = field(default_factory=DayCounters)
    running: bool = False
    defrosting: bool = False
    run_seconds: float = 0.0
    run_defrosts: int = 0
    run_purpose_seconds: dict[str, float] = field(default_factory=dict)
    last_run_seconds: Optional[float] = None
    last_pause_seconds: Optional[float] = None
    last_stop: Optional[float] = None
    last_update: Optional[float] = None
    last_state: Optional[str] = None

    def update(
        self, now: float, day: str, state: Optional[OperatingState]
    ) -> list[RunStarted | RunFinished]:
        """Take in the state at time `now` on calendar day `day`.

        `state` is None while the state is not known; nothing is counted then
        and an open run stays open.
        """
        events: list[RunStarted | RunFinished] = []
        if self.today.day != day:
            self.today = DayCounters(day=day)
        if state is None:
            self.last_update = None
            self.last_state = None
            return events

        step = 0.0
        if self.last_update is not None:
            step = max(0.0, min(now - self.last_update, MAX_STEP))
        self.last_update = now

        if self.running:
            # the time since the last call belongs to the state seen then
            self.run_seconds += step
            self.today.run_seconds += step
            if self.last_state in PURPOSES:
                seconds = self.run_purpose_seconds.get(self.last_state, 0.0)
                self.run_purpose_seconds[self.last_state] = seconds + step
        self.last_state = state.value

        running = state in RUNNING_STATES
        if running and not self.running:
            pause = None if self.last_stop is None else max(0.0, now - self.last_stop)
            self.last_pause_seconds = pause
            self.running = True
            self.run_seconds = 0.0
            self.run_defrosts = 0
            self.run_purpose_seconds = {}
            self.defrosting = False
            self.today.starts += 1
            events.append(RunStarted(at=now, pause=pause))

        if self.running and running:
            defrosting = state is OperatingState.DEFROST
            if defrosting and not self.defrosting:
                self.run_defrosts += 1
                self.today.defrosts += 1
            self.defrosting = defrosting

        if self.running and not running:
            short = self.run_seconds < self.short_run_seconds
            if short:
                self.today.short_runs += 1
            purpose = None
            if self.run_purpose_seconds:
                purpose = max(self.run_purpose_seconds, key=self.run_purpose_seconds.get)
            events.append(
                RunFinished(
                    at=now,
                    duration=self.run_seconds,
                    defrosts=self.run_defrosts,
                    short=short,
                    purpose=purpose,
                )
            )
            self.last_run_seconds = self.run_seconds
            self.last_stop = now
            self.running = False
            self.defrosting = False
        return events

    def as_dict(self) -> dict[str, Any]:
        """Return the tracker as plain data, to store it."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CycleTracker":
        """Restore a tracker; the time of the last call is not kept."""
        data = dict(data)
        today = DayCounters(**data.pop("today", {}))
        data.pop("last_update", None)
        data.pop("last_state", None)
        return cls(today=today, **data)
