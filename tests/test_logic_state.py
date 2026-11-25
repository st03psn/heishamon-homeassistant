"""Test the operating state derived from the topics."""
import pytest

from custom_components.aquarea.logic.state import (
    OperatingState,
    Snapshot,
    operating_state,
)

BASE = {
    "Heatpump_State": "1",
    "Compressor_Freq": "24",
    "Defrosting_State": "0",
    "ThreeWay_Valve_State": "0",
    "Operating_Mode_State": "0",
    "Error": "No error",
}


def state(**changes):
    return operating_state(Snapshot.from_topics({**BASE, **changes}))


def test_nothing_known():
    assert operating_state(Snapshot.from_topics({})) is None
    # switched on, but the compressor frequency has not arrived yet
    assert operating_state(Snapshot.from_topics({"Heatpump_State": "1"})) is None


def test_off_needs_no_other_value():
    assert operating_state(Snapshot.from_topics({"Heatpump_State": "0"})) is OperatingState.OFF


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({}, OperatingState.HEATING),
        ({"Compressor_Freq": "0"}, OperatingState.IDLE),
        ({"Heatpump_State": "0"}, OperatingState.OFF),
        ({"Defrosting_State": "1"}, OperatingState.DEFROST),
        ({"Defrosting_State": "1", "Compressor_Freq": "0"}, OperatingState.DEFROST),
        ({"ThreeWay_Valve_State": "1", "Operating_Mode_State": "4"}, OperatingState.DHW),
        ({"Operating_Mode_State": "3"}, OperatingState.DHW),
        ({"Operating_Mode_State": "1"}, OperatingState.COOLING),
        ({"Operating_Mode_State": "5"}, OperatingState.COOLING),
        ({"Operating_Mode_State": "7"}, OperatingState.COOLING),
        ({"Operating_Mode_State": "8"}, OperatingState.COOLING),
        ({"Operating_Mode_State": "5", "ThreeWay_Valve_State": "1"}, OperatingState.DHW),
        ({"Operating_Mode_State": "2"}, OperatingState.HEATING),
        ({"Operating_Mode_State": "6"}, OperatingState.HEATING),
        ({"Error": "H62"}, OperatingState.FAULT),
        ({"Error": "H62", "Heatpump_State": "0"}, OperatingState.FAULT),
        ({"Error": "H00"}, OperatingState.HEATING),
    ],
)
def test_states(changes, expected):
    assert state(**changes) is expected


def test_values_that_are_not_numbers():
    assert state(Compressor_Freq="nan?") is None
    assert state(Heatpump_State="") is None


@pytest.mark.parametrize("payload", ["nan", "inf", "-inf"])
def test_values_that_are_not_finite(payload):
    assert state(Operating_Mode_State=payload) is OperatingState.HEATING
    assert state(Compressor_Freq=payload) is None
