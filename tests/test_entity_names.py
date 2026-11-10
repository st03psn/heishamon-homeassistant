"""Test the display names of the entities."""
import re

from custom_components.aquarea.const import DeviceType
from custom_components.aquarea.definitions import (
    ENTITY_NAMES,
    build_binary_sensors,
    build_numbers,
    build_selects,
    build_sensors,
    build_switches,
)

PREFIX = "panasonic_heat_pump/"
BUILDS = (build_sensors, build_binary_sensors, build_numbers, build_selects, build_switches)


def _descriptions():
    return [
        d
        for build in BUILDS
        for d in build(PREFIX)
        if getattr(d, "device", None) != DeviceType.HEISHAMON
    ]


def test_names_are_short_and_without_prefix():
    names = [d.name for d in _descriptions()]
    assert [n for n in names if n.startswith("Aquarea")] == []
    assert max(len(n) for n in names) <= 30
    # sentence case: no capitalized word after the first one, abbreviations allowed
    assert [n for n in names if re.search(r"\s[A-Z][a-z]+\b", n) and "Th1" not in n] == []


def test_explicit_names_refer_to_existing_entities():
    ids = {d.heishamon_topic_id for d in _descriptions() if getattr(d, "heishamon_topic_id", None)}
    assert [topic for topic in ENTITY_NAMES if topic not in ids] == []


def test_examples():
    by_id = {d.heishamon_topic_id: d for d in _descriptions() if getattr(d, "heishamon_topic_id", None)}
    assert by_id["TOP10"].name == "DHW tank temp"
    assert by_id["SET5"].name == "Zone 1 heat shift"
    assert by_id["TOP29"].name == "Zone 1 heat curve target high"
    assert by_id["SET39"].name == "Heating control"
    assert by_id["SET1"].name == "Main power"
