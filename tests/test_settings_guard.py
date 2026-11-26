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
M_SERIES = "12 D7 0C 98 14 35 94 0D 83 10"  # WH-SDC0316M9E8
H_SERIES = "E2 CF 0B 13 33 32 D1 0C 16 33"  # WH-MDC05H3E5


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
    await publish(hass, "Heat_Pump_Model", M_SERIES)
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
    assert error.value.translation_placeholders["parent"] == "Pump Flowrate Mode"
    assert len(sent(mqtt_mock)) == 1

    await publish(hass, "Pump_Flowrate_Mode", "0")
    assert hass.states.get(COUNT).state == "0"
    await set_value(hass, 6)
    assert len(sent(mqtt_mock)) == 2

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


async def test_guard_can_be_switched_off(hass, mqtt_mock):
    entry = await setup(hass, {CONF_SETTINGS_GUARD: False})
    await publish(hass, "Heat_Pump_Model", M_SERIES)
    await publish(hass, "Pump_Flowrate_Mode", "1")
    await set_value(hass, 6)
    assert len(sent(mqtt_mock)) == 1
    # the sensor still shows what has no effect
    assert hass.states.get(COUNT).state == "2"
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


async def test_nothing_is_refused_for_other_models_or_while_offline(hass, mqtt_mock):
    from custom_components.aquarea.hub import get_hub

    entry = await setup(hass)
    hub = get_hub(hass, entry.entry_id)
    await publish(hass, "Pump_Flowrate_Mode", "1")
    # model not known yet
    assert hub.model is None and hub.blocked_commands() == {}
    await publish(hass, "Heat_Pump_Model", H_SERIES)
    assert "H3E5" in hub.model and hub.blocked_commands() == {}
    await set_value(hass, 6)
    assert len(sent(mqtt_mock)) == 1

    await publish(hass, "Heat_Pump_Model", M_SERIES)
    assert "SetFloorHeatDelta" in hub.blocked_commands()
    # the values may be out of date while HeishaMon is offline
    async_fire_mqtt_message(hass, f"{PREFIX}LWT", "Offline")
    await hass.async_block_till_done()
    assert hub.blocked_commands() == {}
    assert hass.states.get(COUNT).state == "0"

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


async def test_switching_off_and_the_first_option_are_never_refused(hass, mqtt_mock):
    from custom_components.aquarea.hub import get_hub

    entry = await setup(hass)
    hub = get_hub(hass, entry.entry_id)
    await publish(hass, "Heat_Pump_Model", M_SERIES)
    await publish(hass, "Optional_PCB", "0")
    topic = f"{PREFIX}commands/SetSolarMode"
    with pytest.raises(ServiceValidationError) as error:
        hub.check_command(topic, "1")
    assert error.value.translation_placeholders == {
        "command": "SetSolarMode",
        "parent": "Optional PCB",
        "needed": "1",
        "actual": "0",
    }
    # back to "disabled" stays possible, as text or as number
    hub.check_command(topic, "0")
    hub.check_command(topic, 0)

    # a switch only checks when it is switched on
    import inspect

    from custom_components.aquarea.switch import HeishaMonMQTTSwitch

    assert "check_command" in inspect.getsource(HeishaMonMQTTSwitch.async_turn_on)
    assert "check_command" not in inspect.getsource(HeishaMonMQTTSwitch.async_turn_off)

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
