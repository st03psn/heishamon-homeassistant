"""A journal of setting changes: what changed, when, and whether Home Assistant asked for it."""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import asdict, dataclass
from typing import Any, Optional

# a change counts as asked for by Home Assistant when it follows a command within this time
COMMAND_WINDOW = 60.0
MAX_ENTRIES = 200

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
        self.settings = frozenset(settings)
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
        if old is None or old == value:
            return None
        commanded = self._commanded_at.get(setting)
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

    def restore(self, data: dict[str, Any]) -> None:
        """Take over stored values and entries; settings that no longer exist are dropped."""
        self.values = {k: v for k, v in data.get("values", {}).items() if k in self.settings}
        self.entries = [Change(**entry) for entry in data.get("entries", [])][-self.max_entries :]
