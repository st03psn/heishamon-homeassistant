"""Entity names come from the translation files, in the language of Home Assistant."""
import json
from pathlib import Path

import pytest
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.aquarea.const import DOMAIN

PREFIX = "panasonic_heat_pump/"
COMPONENT = Path(__file__).parent.parent / "custom_components" / "aquarea"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


def _load(name):
    return json.loads((COMPONENT / name).read_text(encoding="utf-8"))


async def _setup(hass, language):
    hass.config.language = language
    entry = MockConfigEntry(domain=DOMAIN, data={"discovery_prefix": PREFIX}, version=2)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def test_strings_equal_english_translations():
    assert _load("strings.json") == _load("translations/en.json")


def test_translation_files_have_the_same_entities():
    en = _load("translations/en.json")["entity"]
    de = _load("translations/de.json")["entity"]
    assert {p: set(v) for p, v in en.items()} == {p: set(v) for p, v in de.items()}


async def test_every_entity_has_a_translated_name(hass, mqtt_mock):
    entry = await _setup(hass, "en")
    en = _load("translations/en.json")["entity"]
    de = _load("translations/de.json")["entity"]
    registry = er.async_get(hass)
    entries = [
        e for e in er.async_entries_for_config_entry(registry, entry.entry_id)
        if e.platform == DOMAIN
    ]
    assert len(entries) > 300
    missing = []
    for e in entries:
        key = e.translation_key
        for translations in (en, de):
            if not key or key not in translations.get(e.domain, {}):
                missing.append((e.domain, e.unique_id, key))
    assert missing == []
    # keys are unique per platform
    keys = [(e.domain, e.translation_key) for e in entries]
    assert len(keys) == len(set(keys))


@pytest.mark.parametrize(
    ("language", "name"),
    [
        ("en", "Aquarea HeatPump Compressor frequency"),
        ("de", "Aquarea HeatPump Verdichter Frequenz"),
    ],
)
async def test_name_follows_language_and_entity_id_is_stable(hass, mqtt_mock, language, name):
    entry = await _setup(hass, language)
    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id("sensor", DOMAIN, f"{entry.entry_id}-TOP8")
    assert entity_id == "sensor.panasonic_heat_pump_main_compressor_freq"
    state = hass.states.get(entity_id)
    assert state is not None
    # Home Assistant puts the name of the device in front of the entity name
    assert state.attributes["friendly_name"] == name
