"""A journal of setting changes: what changed, when, and whether Home Assistant asked for it."""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import asdict, dataclass
from typing import Any, Optional

# a change counts as asked for by Home Assistant when it follows a command within this time
COMMAND_WINDOW = 60.0
MAX_ENTRIES = 200

# Readbacks of a switch or select that the heat pump sets back by itself when a
# run ends or a time is over. They are states, not settings, and would fill the
# journal: defrost, the forced runs, and the remaining time of the powerful mode.
TRANSIENT = frozenset(
    {
        "Defrosting_State",
        "Force_DHW_State",
        "Force_Heater_State",
        "Sterilization_State",
        "Powerful_Mode_Time",
    }
)

ORIGIN_HOME_ASSISTANT = "home_assistant"
# remote controller, Panasonic cloud, HeishaMon web page or rules, or the heat pump itself
ORIGIN_OTHER = "other"


@dataclass(frozen=True)
class Change:
    """One change of a setting."""

    at: float
    setting: str
    old: str
    new: str
    origin: str


class SettingsJournal:
    """Follows the readbacks of the settings and records their changes.

    The first value seen for a setting is the baseline and records nothing.
    """

    def __init__(self, settings: Iterable[str], max_entries: int = MAX_ENTRIES) -> None:
        self.settings = frozenset(settings) - TRANSIENT
        self.max_entries = max_entries
        self.values: dict[str, str] = {}
        self.entries: list[Change] = []
        self._commanded_at: dict[str, float] = {}

    def note_command(self, now: float, setting: str) -> None:
        """Home Assistant sent a command for this setting."""
        self._commanded_at[setting] = now

    def update(self, now: float, setting: str, value: str) -> Optional[Change]:
        """Take in a value; return the change it makes, if any."""
        if setting not in self.settings:
            return None
        old = self.values.get(setting)
        self.values[setting] = value
        if old is None or _same(old, value):
            return None
        # a command accounts for one change only
        commanded = self._commanded_at.pop(setting, None)
        asked = commanded is not None and 0 <= now - commanded <= COMMAND_WINDOW
        change = Change(
            at=now,
            setting=setting,
            old=old,
            new=value,
            origin=ORIGIN_HOME_ASSISTANT if asked else ORIGIN_OTHER,
        )
        self.entries.append(change)
        del self.entries[: -self.max_entries]
        return change

    def as_dict(self) -> dict[str, Any]:
        """Return values and entries as plain data, to store them."""
        return {"values": dict(self.values), "entries": [asdict(e) for e in self.entries]}

    def restore(self, data: Any) -> None:
        """Take over stored values and entries; settings that no longer exist are dropped.

        Raises ValueError when the data is not what as_dict returns; the
        journal is unchanged then.
        """
        try:
            values = {
                str(k): str(v) for k, v in data["values"].items() if k in self.settings
            }
            entries = [
                Change(
                    at=float(e["at"]),
                    setting=str(e["setting"]),
                    old=str(e["old"]),
                    new=str(e["new"]),
                    origin=str(e["origin"]),
                )
                for e in data["entries"]
            ]
        except (KeyError, TypeError, AttributeError, ValueError) as error:
            raise ValueError("stored journal is not readable") from error
        self.values = values
        self.entries = entries[-self.max_entries :]


def _same(old: str, new: str) -> bool:
    """Compare two payloads; "1" and "1.0" are the same value."""
    if old == new:
        return True
    try:
        return float(old) == float(new)
    except ValueError:
        return False
