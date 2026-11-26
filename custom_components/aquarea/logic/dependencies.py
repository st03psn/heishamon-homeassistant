"""Which settings have no effect right now, and why.

Evaluates the parent/child rules of dependency_data against the current
values of the heat pump. A rule is only applied when every parent value is
known; an unknown parent never blocks anything.
"""
from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass

from .dependency_data import REQUIREMENTS, Condition, Requirement

# Commands that also serve settings outside the rule that names them: the
# operating mode has heat modes next to the cool and auto modes, the curves
# command carries zone 1 next to zone 2, the schedule switch is a plain on/off.
# Judging them needs the value that is sent, which the rules do not describe.
SHARED_COMMANDS = frozenset({"SetOperationMode", "SetCurves", "SetMainSchedule"})


@dataclass(frozen=True)
class Reason:
    """A parent setting that keeps a child setting from having an effect."""

    parent_topic: str
    parent_name: str
    # values of the parent with which the child would work; empty for a rule
    # that blocks while the parent has `actual`
    needed: tuple[str, ...]
    actual: str


def _unmet(requirement: Requirement, values: Mapping[str, str]) -> list[Reason] | None:
    """Return the parents that keep the children of a rule from working.

    None: the rule cannot be judged (a parent value is unknown, or the rule
    has parts the data does not express). Empty list: the children work.
    """
    if requirement.any_of or not requirement.when:
        return None
    conditions: tuple[Condition, ...] = requirement.when
    actual = {condition.name: values.get(condition.name) for condition in conditions}
    if any(value is None for value in actual.values()):
        return None
    if requirement.blocks:
        if all(actual[c.name] in c.values for c in conditions):
            return [Reason(c.topic, c.name, (), actual[c.name]) for c in conditions]
        return []
    return [
        Reason(c.topic, c.name, c.values, actual[c.name])
        for c in conditions
        if actual[c.name] not in c.values
    ]


def rules_apply_to(model: str | None) -> bool:
    """Return True when the rules are known to hold for this heat pump model.

    The rules come from the manuals of the M series and from an M-series
    unit. `model` is the name of the model as the integration shows it,
    e.g. "WH-SDC0316M9E8 9 3ph T-CAP - M-series".
    """
    if not model:
        return False
    if "M-series" in model:
        return True
    return re.match(r"WH-[A-Z]+\d+M\d?E\d", model) is not None


def _is_single_command(command: str) -> bool:
    return " " not in command and command not in SHARED_COMMANDS


def blocked_commands(values: Mapping[str, str]) -> dict[str, list[Reason]]:
    """Return the commands that have no effect now, with the parents in the way.

    `values` are payloads keyed by topic name below main/.
    """
    blocked: dict[str, list[Reason]] = {}
    for requirement in REQUIREMENTS:
        reasons = _unmet(requirement, values)
        if not reasons:
            continue
        for command in requirement.child_commands:
            if _is_single_command(command):
                blocked.setdefault(command, []).extend(reasons)
    return blocked


def inactive_topics(values: Mapping[str, str]) -> dict[str, list[Reason]]:
    """Return the topic ids of readbacks whose setting has no effect now."""
    inactive: dict[str, list[Reason]] = {}
    for requirement in REQUIREMENTS:
        reasons = _unmet(requirement, values)
        if not reasons:
            continue
        for topic in requirement.child_topics:
            inactive.setdefault(topic, []).extend(reasons)
    return inactive
