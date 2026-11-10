"""Test the feature tracking with the integration set up on MQTT."""
import pytest
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_mqtt_message,
)

from custom_components.aquarea.const import (
    CONF_ENTITY_MANAGEMENT,
    DOMAIN,
    MODE_UNAVAILABLE,
)

PREFIX = "panasonic_heat_pump/"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


async def _setup(hass, options):
    entry = MockConfigEntry(
        domain=DOMAIN, data={"discovery_prefix": PREFIX}, options=options, version=2
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_entities_unavailable_while_feature_missing(hass, mqtt_mock):
    entry = await _setup(hass, {CONF_ENTITY_MANAGEMENT: MODE_UNAVAILABLE})
    registry = er.async_get(hass)
    dhw_target = registry.async_get_entity_id("number", DOMAIN, f"{entry.entry_id}-SET11")
    water_heater = registry.async_get_entity_id(
        "water_heater", DOMAIN, f"{entry.entry_id}.water_heater"
    )
    tank_switch = registry.async_get_entity_id("switch", DOMAIN, f"{entry.entry_id}-SET86")
    assert dhw_target and water_heater and tank_switch
    assert registry.async_get(tank_switch).disabled_by is not None  # opt-in

    async_fire_mqtt_message(hass, f"{PREFIX}main/DHW_Target_Temp", "50")
    async_fire_mqtt_message(hass, f"{PREFIX}main/DHW_Installed", "1")
    await hass.async_block_till_done()
    assert hass.states.get(dhw_target).state == "50"
    assert hass.states.get(water_heater).state != "unavailable"

    async_fire_mqtt_message(hass, f"{PREFIX}main/DHW_Installed", "0")
    await hass.async_block_till_done()
    assert hass.states.get(dhw_target).state == "unavailable"
    assert hass.states.get(water_heater).state == "unavailable"

    async_fire_mqtt_message(hass, f"{PREFIX}main/DHW_Installed", "1")
    await hass.async_block_till_done()
    assert hass.states.get(dhw_target).state == "50"

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


async def test_default_mode_keeps_entities_available(hass, mqtt_mock):
    entry = await _setup(hass, {})
    registry = er.async_get(hass)
    dhw_target = registry.async_get_entity_id("number", DOMAIN, f"{entry.entry_id}-SET11")
    async_fire_mqtt_message(hass, f"{PREFIX}main/DHW_Target_Temp", "50")
    async_fire_mqtt_message(hass, f"{PREFIX}main/DHW_Installed", "0")
    await hass.async_block_till_done()
    assert hass.states.get(dhw_target).state == "50"
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


async def test_options_flow(hass, mqtt_mock):
    entry = await _setup(hass, {})
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] == "form" and result["step_id"] == "init"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_ENTITY_MANAGEMENT: MODE_UNAVAILABLE}
    )
    assert result["type"] == "create_entry"
    await hass.async_block_till_done()
    assert entry.options == {CONF_ENTITY_MANAGEMENT: MODE_UNAVAILABLE}
    assert hass.data[DOMAIN][entry.entry_id]["features"].mode == MODE_UNAVAILABLE
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
