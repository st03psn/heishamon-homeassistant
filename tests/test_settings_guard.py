"""Test that a setting without effect is refused, with the reason."""
import pytest
from homeassistant.exceptions import ServiceValidationError
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_mqtt_message,
)

from custom_components.aquarea.const import CONF_SETTINGS_GUARD, DOMAIN

PREFIX = "panasonic_heat_pump/"
NUMBER = "number.panasonic_heat_pump_main_heat_delta"
COUNT = "sensor.panasonic_heat_pump_settings_without_effect"
TOPIC = f"{PREFIX}commands/SetFloorHeatDelta"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


async def setup(hass, options=None):
    entry = MockConfigEntry(
        domain=DOMAIN, data={"discovery_prefix": PREFIX}, options=options or {}, version=2
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def publish(hass, name, payload):
    async_fire_mqtt_message(hass, f"{PREFIX}main/{name}", payload)
    await hass.async_block_till_done()


async def set_value(hass, value):
    await hass.services.async_call(
        "number", "set_value", {"entity_id": NUMBER, "value": value}, blocking=True
    )


def sent(mqtt_mock):
    return [c for c in mqtt_mock.async_publish.mock_calls if c.args[0] == TOPIC]


async def test_refused_while_the_parent_is_off(hass, mqtt_mock):
    entry = await setup(hass)
    # parent unknown: allowed
    await set_value(hass, 5)
    assert len(sent(mqtt_mock)) == 1
    assert hass.states.get(COUNT).state == "0"

    await publish(hass, "Pump_Flowrate_Mode", "1")
    assert hass.states.get(COUNT).state == "2"
    settings = hass.states.get(COUNT).attributes["settings"]
    assert settings["SetFloorHeatDelta"] == [
        {"parent": "Pump_Flowrate_Mode", "needed": ["0"], "actual": "1"}
    ]
    with pytest.raises(ServiceValidationError) as error:
        await set_value(hass, 6)
    assert error.value.translation_key == "setting_needs_parent"
    assert error.value.translation_placeholders["parent"] == "Pump_Flowrate_Mode"
    assert len(sent(mqtt_mock)) == 1

    await publish(hass, "Pump_Flowrate_Mode", "0")
    assert hass.states.get(COUNT).state == "0"
    await set_value(hass, 6)
    assert len(sent(mqtt_mock)) == 2

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


async def test_guard_can_be_switched_off(hass, mqtt_mock):
    entry = await setup(hass, {CONF_SETTINGS_GUARD: False})
    await publish(hass, "Pump_Flowrate_Mode", "1")
    await set_value(hass, 6)
    assert len(sent(mqtt_mock)) == 1
    # the sensor still shows what has no effect
    assert hass.states.get(COUNT).state == "2"
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
