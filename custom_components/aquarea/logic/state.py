"""What the heat pump is doing right now, derived from its topics."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Optional

from ..errors import is_fault

# TOP4 values in which the room side cools (MQTT-Topics.md of HeishaMon):
# 1 = Cool only, 5 = Cool+DHW, 7 = Auto(Cool), 8 = Auto(Cool)+DHW
COOLING_MODES = frozenset({1, 5, 7, 8})
# 3 = DHW only
DHW_ONLY_MODE = 3


class OperatingState(StrEnum):
    """Activity of the heat pump."""

    OFF = "off"
    IDLE = "idle"
    HEATING = "heating"
    COOLING = "cooling"
    DHW = "dhw"
    DEFROST = "defrost"
    FAULT = "fault"


def _number(value: Optional[str]) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _flag(value: Optional[str]) -> Optional[bool]:
    number = _number(value)
    return None if number is None else number != 0


@dataclass(frozen=True)
class Snapshot:
    """The values of the heat pump that the logic works with.

    A field is None until HeishaMon has published its topic.
    """

    heatpump_on: Optional[bool] = None
    compressor_freq: Optional[float] = None
    defrosting: Optional[bool] = None
    dhw_valve: Optional[bool] = None
    operating_mode: Optional[int] = None
    error: Optional[str] = None

    @classmethod
    def from_topics(cls, values: Mapping[str, str]) -> "Snapshot":
        """Build a snapshot from payloads keyed by topic name below main/."""
        mode = _number(values.get("Operating_Mode_State"))
        return cls(
            heatpump_on=_flag(values.get("Heatpump_State")),
            compressor_freq=_number(values.get("Compressor_Freq")),
            defrosting=_flag(values.get("Defrosting_State")),
            dhw_valve=_flag(values.get("ThreeWay_Valve_State")),
            operating_mode=None if mode is None else int(mode),
            error=values.get("Error"),
        )

    @property
    def compressor_running(self) -> Optional[bool]:
        """True while the compressor turns."""
        if self.compressor_freq is None:
            return None
        return self.compressor_freq > 0


def operating_state(snapshot: Snapshot) -> Optional[OperatingState]:
    """Return the activity of the heat pump, None while it cannot be told.

    Order: a fault wins, then the main switch, then defrosting. A running
    compressor heats the DHW tank when the 3-way valve points to it, else it
    cools or heats the rooms as the operating mode says.
    """
    if is_fault(snapshot.error):
        return OperatingState.FAULT
    if snapshot.heatpump_on is None:
        return None
    if not snapshot.heatpump_on:
        return OperatingState.OFF
    if snapshot.defrosting:
        return OperatingState.DEFROST
    running = snapshot.compressor_running
    if running is None:
        return None
    if not running:
        return OperatingState.IDLE
    if snapshot.dhw_valve or snapshot.operating_mode == DHW_ONLY_MODE:
        return OperatingState.DHW
    if snapshot.operating_mode in COOLING_MODES:
        return OperatingState.COOLING
    return OperatingState.HEATING
