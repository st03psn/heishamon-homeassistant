"""Test that entities of settings without effect are hidden and shown again."""
from datetime import timedelta

import pytest
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_mqtt_message,
    async_fire_time_changed,
)

from custom_components.aquarea.const import CONF_HIDE_WITHOUT_EFFECT, DOMAIN

PREFIX = "panasonic_heat_pump/"
M_SERIES = "12 D7 0C 98 14 35 94 0D 83 10"
H_SERIES = "E2 CF 0B 13 33 32 D1 0C 16 33"
# SetFloorHeatDelta (SET18) and its readback TOP23 depend on Pump_Flowrate_Mode = 0
NUMBER = "number.panasonic_heat_pump_main_heat_delta"
READBACK = "sensor.panasonic_heat_pump_main_heat_delta"


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


async def publish(hass, freezer, **topics):
    for name, payload in topics.items():
        async_fire_mqtt_message(hass, f"{PREFIX}main/{name}", payload)
    await hass.async_block_till_done()
    freezer.tick(timedelta(seconds=11))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


def hidden(hass, entity_id):
    entry = er.async_get(hass).async_get(entity_id)
    return None if entry is None else entry.hidden_by


async def test_hidden_while_without_effect(hass, mqtt_mock, freezer):
    entry = await setup(hass)
    registry = er.async_get(hass)
    assert registry.async_get(NUMBER) is not None

    await publish(hass, freezer, Heat_Pump_Model=M_SERIES, Pump_Flowrate_Mode="1")
    assert hidden(hass, NUMBER) == er.RegistryEntryHider.INTEGRATION
    if registry.async_get(READBACK) is not None:
        assert hidden(hass, READBACK) == er.RegistryEntryHider.INTEGRATION

    await publish(hass, freezer, Pump_Flowrate_Mode="0")
    assert hidden(hass, NUMBER) is None

    # hidden by the user: never shown again by the integration
    registry.async_update_entity(NUMBER, hidden_by=er.RegistryEntryHider.USER)
    await publish(hass, freezer, Pump_Flowrate_Mode="1")
    await publish(hass, freezer, Pump_Flowrate_Mode="0")
    assert hidden(hass, NUMBER) == er.RegistryEntryHider.USER

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


async def test_nothing_hidden_for_other_models_offline_or_when_switched_off(
    hass, mqtt_mock, freezer
):
    entry = await setup(hass)
    await publish(hass, freezer, Heat_Pump_Model=H_SERIES, Pump_Flowrate_Mode="1")
    assert hidden(hass, NUMBER) is None

    async_fire_mqtt_message(hass, f"{PREFIX}LWT", "Offline")
    await publish(hass, freezer, Heat_Pump_Model=M_SERIES)
    assert hidden(hass, NUMBER) is None
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()

    hass.config_entries.async_update_entry(entry, options={CONF_HIDE_WITHOUT_EFFECT: False})
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    async_fire_mqtt_message(hass, f"{PREFIX}LWT", "Online")
    await publish(hass, freezer, Heat_Pump_Model=M_SERIES, Pump_Flowrate_Mode="1")
    assert hidden(hass, NUMBER) is None
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


async def test_shown_again_by_the_user_stays_shown(hass, mqtt_mock, freezer):
    entry = await setup(hass)
    registry = er.async_get(hass)
    await publish(hass, freezer, Heat_Pump_Model=M_SERIES, Pump_Flowrate_Mode="1")
    assert hidden(hass, NUMBER) == er.RegistryEntryHider.INTEGRATION
    registry.async_update_entity(NUMBER, hidden_by=None)
    await publish(hass, freezer, Main_Outlet_Temp="31")
    await publish(hass, freezer, Main_Outlet_Temp="32")
    assert hidden(hass, NUMBER) is None
    # once it has an effect and loses it again, it is hidden again
    await publish(hass, freezer, Pump_Flowrate_Mode="0")
    await publish(hass, freezer, Pump_Flowrate_Mode="1")
    assert hidden(hass, NUMBER) == er.RegistryEntryHider.INTEGRATION
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


async def test_switching_the_option_off_shows_them_even_offline(hass, mqtt_mock, freezer):
    entry = await setup(hass)
    await publish(hass, freezer, Heat_Pump_Model=M_SERIES, Pump_Flowrate_Mode="1")
    assert hidden(hass, NUMBER) == er.RegistryEntryHider.INTEGRATION
    # hidden through a blocked command as well (zone 2 settings with one zone);
    # sent twice: enabling new entities reloads the entry, and the mocked broker
    # does not deliver retained values again
    z2 = "number.panasonic_heat_pump_main_z2_heat_request_temp"
    for _ in range(2):
        await publish(
            hass, freezer, Heat_Pump_Model=M_SERIES, Pump_Flowrate_Mode="1", Zone_Configuration="21"
        )
    assert hidden(hass, z2) == er.RegistryEntryHider.INTEGRATION
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()

    hass.config_entries.async_update_entry(entry, options={CONF_HIDE_WITHOUT_EFFECT: False})
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    async_fire_mqtt_message(hass, f"{PREFIX}LWT", "Offline")
    freezer.tick(timedelta(seconds=11))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert hidden(hass, NUMBER) is None
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
