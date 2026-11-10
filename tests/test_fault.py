"""Test the fault sensor and its Repairs issue."""
import pytest
from homeassistant.helpers import issue_registry as ir
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_mqtt_message,
)

from custom_components.aquarea.const import DOMAIN
from custom_components.aquarea.errors import ERROR_CODES, describe, is_fault

PREFIX = "panasonic_heat_pump/"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


def test_descriptions():
    assert describe("H28") == "Abnormal solar sensor"
    assert describe("H28", "de") == "Solarfühler gestört"
    assert describe("F99").startswith("Unknown code")
    assert not is_fault("No error") and not is_fault("H00") and is_fault("F12")
    assert all(len(texts) == 2 and all(texts) for texts in ERROR_CODES.values())


async def test_fault_sensor_and_issue(hass, mqtt_mock):
    entry = MockConfigEntry(domain=DOMAIN, data={"discovery_prefix": PREFIX}, version=2)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    entity_id = "binary_sensor.panasonic_heat_pump_main_error"
    issue_id = f"heat_pump_fault_{entry.entry_id}"
    registry = ir.async_get(hass)

    async_fire_mqtt_message(hass, f"{PREFIX}main/Error", "H28")
    await hass.async_block_till_done()
    state = hass.states.get(entity_id)
    assert state.state == "on"
    assert state.attributes["code"] == "H28"
    assert state.attributes["description"] == "Abnormal solar sensor"
    issue = registry.async_get_issue(DOMAIN, issue_id)
    assert issue is not None and issue.translation_placeholders["code"] == "H28"

    async_fire_mqtt_message(hass, f"{PREFIX}main/Error", "No error")
    await hass.async_block_till_done()
    assert hass.states.get(entity_id).state == "off"
    assert registry.async_get_issue(DOMAIN, issue_id) is None

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
