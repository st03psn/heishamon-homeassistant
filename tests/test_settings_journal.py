"""Test the journal of setting changes against Home Assistant."""
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_capture_events,
    async_fire_mqtt_message,
)

from custom_components.aquarea.const import DOMAIN
from custom_components.aquarea.hub import EVENT_SETTING_CHANGED, get_hub

PREFIX = "panasonic_heat_pump/"
NUMBER = "number.panasonic_heat_pump_main_z1_heat_request_temp"
LAST = "sensor.panasonic_heat_pump_last_setting_change"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


async def publish(hass, name, payload):
    async_fire_mqtt_message(hass, f"{PREFIX}main/{name}", payload)
    await hass.async_block_till_done()


async def test_changes_are_recorded_with_their_origin(hass, mqtt_mock, hass_storage):
    entry = MockConfigEntry(domain=DOMAIN, data={"discovery_prefix": PREFIX}, version=2)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    events = async_capture_events(hass, EVENT_SETTING_CHANGED)
    hub = get_hub(hass, entry.entry_id)
    assert hub.journal.settings >= {"Z1_Heat_Request_Temp", "Quiet_Mode_Level"}

    # baseline, and a measurement that is no setting
    await publish(hass, "Z1_Heat_Request_Temp", "0")
    await publish(hass, "Main_Outlet_Temp", "30")
    await publish(hass, "Main_Outlet_Temp", "31")
    assert events == [] and hass.states.get(LAST).state == "unknown"

    # changed at the remote controller
    await publish(hass, "Z1_Heat_Request_Temp", "1")
    assert events[-1].data == {
        "setting": "Z1_Heat_Request_Temp",
        "old": "0",
        "new": "1",
        "origin": "other",
    }
    assert hass.states.get(LAST).state == "Z1_Heat_Request_Temp: 0 → 1"

    # changed from Home Assistant
    await hass.services.async_call(
        "number", "set_value", {"entity_id": NUMBER, "value": 2}, blocking=True
    )
    await publish(hass, "Z1_Heat_Request_Temp", "2")
    assert events[-1].data["origin"] == "home_assistant"
    changes = hass.states.get(LAST).attributes["changes"]
    assert [c["new"] for c in changes] == ["2", "1"]
    assert len(events) == 2

    # kept across a reload; the stored value is the baseline
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get(LAST).state == "Z1_Heat_Request_Temp: 1 → 2"
    await publish(hass, "Z1_Heat_Request_Temp", "2")
    assert len(get_hub(hass, entry.entry_id).journal.entries) == 2

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


async def test_every_setting_is_followed(hass, mqtt_mock):
    from custom_components.aquarea import _settings_of
    from custom_components.aquarea.definitions.numbers import build_numbers
    from custom_components.aquarea.definitions.selects import build_selects
    from custom_components.aquarea.definitions.switches import build_switches
    from custom_components.aquarea.logic.journal import TRANSIENT, SettingsJournal

    settings = _settings_of(PREFIX)
    followed = SettingsJournal(n for names in settings.values() for n in names).settings
    main = f"{PREFIX}main/"
    expected = {
        d.key.removeprefix(main)
        for build in (build_numbers, build_selects, build_switches)
        for d in build(PREFIX)
        if d.key.startswith(main) and getattr(d, "command_topic", None)
    }
    assert followed == expected - TRANSIENT
    # one command, all its readbacks: the curves
    assert len(settings["SetCurves"]) == 16


async def test_change_through_the_climate_entity_is_asked_for(hass, mqtt_mock):
    entry = MockConfigEntry(domain=DOMAIN, data={"discovery_prefix": PREFIX}, version=2)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    events = async_capture_events(hass, EVENT_SETTING_CHANGED)
    for name, payload in (
        ("Heatpump_State", "1"),
        ("Operating_Mode_State", "0"),
        ("Zones_State", "0"),
        ("Z1_Heat_Request_Temp", "30"),
    ):
        await publish(hass, name, payload)
    await hass.services.async_call(
        "climate",
        "set_temperature",
        {"entity_id": "climate.panasonic_heat_pump_main_z1_temp", "temperature": 32},
        blocking=True,
    )
    await publish(hass, "Z1_Heat_Request_Temp", "32")
    assert events[-1].data["setting"] == "Z1_Heat_Request_Temp"
    assert events[-1].data["origin"] == "home_assistant"
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
