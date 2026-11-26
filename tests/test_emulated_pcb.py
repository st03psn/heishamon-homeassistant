"""Test that the emulated optional PCB is recognised from live optional/ topics."""
from datetime import timedelta
from unittest.mock import patch

import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_mqtt_message,
    async_fire_time_changed,
)

from custom_components.aquarea.const import DOMAIN, Feature
from custom_components.aquarea.definitions.binary_sensors import build_binary_sensors
from custom_components.aquarea.definitions.numbers import build_numbers
from custom_components.aquarea.definitions.selects import build_selects
from custom_components.aquarea.definitions.sensors import build_sensors
from custom_components.aquarea.definitions.switches import build_switches

PREFIX = "panasonic_heat_pump/"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


def test_emulated_pcb_entities_require_the_emulation():
    ids = {}
    for build in (build_sensors, build_binary_sensors, build_numbers, build_selects, build_switches):
        for d in build(PREFIX):
            ids[d.heishamon_topic_id] = d
    for topic_id in ("OPT0", "OPT6", "SetDemandControl", "SetSmartGridMode", "SetCompressorState"):
        assert Feature.EMULATED_PCB in ids[topic_id].requires, topic_id
    # the settings of a real optional PCB do not depend on the emulation
    for topic_id in ("TOP110", "TOP149", "TOP150"):
        assert Feature.EMULATED_PCB not in getattr(ids[topic_id], "requires", ()), topic_id


async def setup(hass):
    entry = MockConfigEntry(domain=DOMAIN, data={"discovery_prefix": PREFIX}, version=2)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry, hass.data[DOMAIN][entry.entry_id]["features"]


async def minutes(hass, freezer, count):
    for _ in range(count):
        freezer.tick(timedelta(minutes=1))
        async_fire_mqtt_message(hass, f"{PREFIX}main/Heatpump_State", "1")
        async_fire_time_changed(hass)
        await hass.async_block_till_done()


async def test_live_optional_topic_means_emulation_on(hass, mqtt_mock, freezer):
    entry, tracker = await setup(hass)
    assert tracker.is_installed(Feature.EMULATED_PCB) is None
    async_fire_mqtt_message(hass, f"{PREFIX}optional/Z1_Water_Pump", "0")
    await hass.async_block_till_done()
    assert tracker.is_installed(Feature.EMULATED_PCB) is True
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


async def test_only_retained_or_none_means_emulation_off(hass, mqtt_mock, freezer):
    entry, tracker = await setup(hass)
    # a retained value from an earlier emulation says nothing
    async_fire_mqtt_message(hass, f"{PREFIX}optional/Z1_Water_Pump", "0", retain=True)
    await hass.async_block_till_done()
    assert tracker.is_installed(Feature.EMULATED_PCB) is None
    await minutes(hass, freezer, 14)
    assert tracker.is_installed(Feature.EMULATED_PCB) is None
    await minutes(hass, freezer, 3)
    assert tracker.is_installed(Feature.EMULATED_PCB) is False
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


async def test_nothing_decided_while_heishamon_is_silent(hass, mqtt_mock, freezer):
    entry, tracker = await setup(hass)
    for _ in range(30):
        freezer.tick(timedelta(minutes=1))
        async_fire_time_changed(hass)
        await hass.async_block_till_done()
    assert tracker.is_installed(Feature.EMULATED_PCB) is None
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
