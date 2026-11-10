"""Test the command topics of the bivalent advanced temperatures."""
from custom_components.aquarea.definitions import build_numbers

PREFIX = "panasonic_heat_pump/"


def test_bivalent_advanced_temperature_commands():
    """HeishaMon names these commands SetBivalentAPStartTemp / SetBivalentAPStopTemp."""
    numbers = {n.heishamon_topic_id: n for n in build_numbers(PREFIX)}
    assert numbers["SET37"].command_topic == f"{PREFIX}commands/SetBivalentAPStartTemp"
    assert numbers["SET38"].command_topic == f"{PREFIX}commands/SetBivalentAPStopTemp"
