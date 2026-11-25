"""Test the hub, its entities and the climate action against Home Assistant."""
from datetime import timedelta

import pytest
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_mqtt_message,
    async_fire_time_changed,
)

from custom_components.aquarea.const import DOMAIN
from custom_components.aquarea.diagnostics import async_get_config_entry_diagnostics
from custom_components.aquarea.hub import get_hub, storage_key

PREFIX = "panasonic_heat_pump/"
STATE = "sensor.panasonic_heat_pump_operating_state"
STARTS = "sensor.panasonic_heat_pump_compressor_starts_today"
RUN_TIME = "sensor.panasonic_heat_pump_compressor_run_time_today"
LAST_RUN = "sensor.panasonic_heat_pump_last_run_time"
RUN_EVENT = "event.panasonic_heat_pump_compressor_run"
CLIMATE = "climate.panasonic_heat_pump_main_z1_temp"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


async def setup(hass):
    entry = MockConfigEntry(domain=DOMAIN, data={"discovery_prefix": PREFIX}, version=2)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def publish(hass, **topics):
    for name, payload in topics.items():
        async_fire_mqtt_message(hass, f"{PREFIX}main/{name}", payload)
    await hass.async_block_till_done()


async def advance(hass, freezer, seconds):
    """Let time pass in steps of the hub's tick."""
    for _ in range(seconds // 30):
        freezer.tick(timedelta(seconds=30))
        async_fire_time_changed(hass)
        await hass.async_block_till_done()


async def test_operating_state_sensor(hass, mqtt_mock):
    entry = await setup(hass)
    assert hass.states.get(STATE).state == "unknown"

    await publish(hass, Heatpump_State="1", Compressor_Freq="0", Operating_Mode_State="0")
    assert hass.states.get(STATE).state == "idle"
    await publish(hass, Compressor_Freq="24")
    assert hass.states.get(STATE).state == "heating"
    await publish(hass, Defrosting_State="1")
    assert hass.states.get(STATE).state == "defrost"
    await publish(hass, Defrosting_State="0", ThreeWay_Valve_State="1")
    assert hass.states.get(STATE).state == "dhw"
    await publish(hass, Error="H62")
    assert hass.states.get(STATE).state == "fault"
    await publish(hass, Error="No error", Heatpump_State="0")
    assert hass.states.get(STATE).state == "off"

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


async def test_state_is_unknown_while_heishamon_is_offline(hass, mqtt_mock):
    entry = await setup(hass)
    await publish(hass, Heatpump_State="1", Compressor_Freq="24", Operating_Mode_State="0")
    assert hass.states.get(STATE).state == "heating"
    async_fire_mqtt_message(hass, f"{PREFIX}LWT", "Offline")
    await hass.async_block_till_done()
    assert hass.states.get(STATE).state == "unknown"
    async_fire_mqtt_message(hass, f"{PREFIX}LWT", "Online")
    await hass.async_block_till_done()
    assert hass.states.get(STATE).state == "heating"
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


async def test_run_counters_and_event(hass, mqtt_mock, freezer):
    entry = await setup(hass)
    await publish(hass, Heatpump_State="1", Compressor_Freq="0", Operating_Mode_State="0")
    assert hass.states.get(STARTS).state == "0"
    assert hass.states.get(RUN_EVENT).state == "unknown"

    await publish(hass, Compressor_Freq="24")
    assert hass.states.get(STARTS).state == "1"
    event = hass.states.get(RUN_EVENT)
    assert event.attributes["event_type"] == "started"
    assert event.attributes["pause"] is None

    # no topic changes for 20 minutes: the tick keeps the run time going
    await advance(hass, freezer, 1200)
    assert float(hass.states.get(RUN_TIME).state) == 20.0

    await publish(hass, Compressor_Freq="0")
    event = hass.states.get(RUN_EVENT)
    assert event.attributes["event_type"] == "finished"
    assert event.attributes["duration"] == 20.0
    assert event.attributes["short"] is False
    assert event.attributes["purpose"] == "heating"
    assert float(hass.states.get(LAST_RUN).state) == 20.0

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


async def test_counters_survive_a_reload(hass, mqtt_mock, hass_storage, freezer):
    entry = await setup(hass)
    await publish(hass, Heatpump_State="1", Compressor_Freq="24", Operating_Mode_State="0")
    await advance(hass, freezer, 600)
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert hass_storage[storage_key(entry.entry_id)]["data"]["cycles"]["today"]["starts"] == 1

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get(STARTS).state == "1"
    assert float(hass.states.get(RUN_TIME).state) == 10.0
    # the run goes on after the reload: no second start
    await publish(hass, Heatpump_State="1", Compressor_Freq="24", Operating_Mode_State="0")
    assert hass.states.get(STARTS).state == "1"

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


async def test_climate_action(hass, mqtt_mock):
    entry = await setup(hass)
    await publish(
        hass,
        Heatpump_State="1",
        Operating_Mode_State="0",
        Zones_State="0",
        Compressor_Freq="0",
    )
    climate = hass.states.get(CLIMATE)
    assert climate.state == "heat"
    assert climate.attributes["hvac_action"] == "idle"
    await publish(hass, Compressor_Freq="30")
    assert hass.states.get(CLIMATE).attributes["hvac_action"] == "heating"
    await publish(hass, Defrosting_State="1")
    assert hass.states.get(CLIMATE).attributes["hvac_action"] == "defrosting"
    await publish(hass, Defrosting_State="0", ThreeWay_Valve_State="1")
    assert hass.states.get(CLIMATE).attributes["hvac_action"] == "idle"
    await publish(hass, Heatpump_State="0")
    assert hass.states.get(CLIMATE).attributes["hvac_action"] == "off"

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


async def test_diagnostics(hass, mqtt_mock):
    entry = await setup(hass)
    await publish(hass, Heatpump_State="1", Compressor_Freq="24", Operating_Mode_State="0")
    data = await async_get_config_entry_diagnostics(hass, entry)
    assert data["operating_state"] == "heating"
    assert data["topics"]["Compressor_Freq"] == "24"
    assert data["cycles"]["today"]["starts"] == 1
    assert get_hub(hass, entry.entry_id).online is None
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


async def test_counters_are_written_when_home_assistant_stops(hass, mqtt_mock, hass_storage):
    from homeassistant.const import EVENT_HOMEASSISTANT_STOP

    entry = await setup(hass)
    await publish(hass, Heatpump_State="1", Compressor_Freq="24", Operating_Mode_State="0")
    assert storage_key(entry.entry_id) not in hass_storage
    hass.bus.async_fire(EVENT_HOMEASSISTANT_STOP)
    await hass.async_block_till_done()
    stored = hass_storage[storage_key(entry.entry_id)]["data"]["cycles"]
    assert stored["running"] is True and stored["today"]["starts"] == 1
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


async def test_hub_keeps_running_when_the_unload_fails(hass, mqtt_mock):
    from unittest.mock import patch

    entry = await setup(hass)
    from custom_components.aquarea import async_unload_entry

    # called directly: Home Assistant itself leaves such an entry in a failed state
    with patch.object(hass.config_entries, "async_unload_platforms", return_value=False):
        assert not await async_unload_entry(hass, entry)
    await publish(hass, Heatpump_State="1", Compressor_Freq="24", Operating_Mode_State="0")
    assert get_hub(hass, entry.entry_id).state.value == "heating"
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
