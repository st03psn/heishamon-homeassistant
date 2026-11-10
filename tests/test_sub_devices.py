"""Test entity names and the removal of sub-devices of earlier versions."""
import pytest
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity import EntityCategory
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.aquarea import _compute_identifiers, _sub_device_identifier_for
from custom_components.aquarea.const import DOMAIN, OBSOLETE_SUB_DEVICES, DeviceType
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


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


def test_names_and_categories():
    descriptions = [d for build in BUILDS for d in build(PREFIX)]
    ids = {d.heishamon_topic_id for d in descriptions if getattr(d, "heishamon_topic_id", None)}
    assert [topic for topic in ENTITY_NAMES if topic not in ids] == []
    heatpump = [d for d in descriptions if getattr(d, "device", None) != DeviceType.HEISHAMON]
    assert [d.name for d in heatpump if d.name.startswith("Aquarea")] == []
    by_id = {d.heishamon_topic_id: d for d in descriptions if getattr(d, "heishamon_topic_id", None)}
    assert by_id["TOP10"].name == "DHW tank temp"
    assert by_id["SET67"].name == "Sensor offset remote Th1"
    assert by_id["TOP29"].name == "Zone 1 heat curve target high"
    assert by_id["SET39"].name == "Heating control"
    assert by_id["TOP177"].entity_category == EntityCategory.DIAGNOSTIC
    assert by_id["TOP5"].entity_category is None


async def test_old_sub_devices_are_removed(hass, mqtt_mock):
    entry = MockConfigEntry(domain=DOMAIN, data={"discovery_prefix": PREFIX}, version=2)
    entry.add_to_hass(hass)
    device_registry = dr.async_get(hass)
    entity_registry = er.async_get(hass)
    heatpump = device_registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={_compute_identifiers(PREFIX)[DeviceType.HEATPUMP]},
        name="Aquarea HeatPump",
    )
    old_devices = [
        device_registry.async_get_or_create(
            config_entry_id=entry.entry_id,
            identifiers={_sub_device_identifier_for(PREFIX, suffix)},
            name=suffix,
        )
        for suffix in ("installer", "dhw")
    ]
    assert set(("installer", "dhw")) <= set(OBSOLETE_SUB_DEVICES)
    offset = entity_registry.async_get_or_create(
        "number", DOMAIN, f"{entry.entry_id}-SET103", device_id=old_devices[0].id,
        disabled_by=er.RegistryEntryDisabler.USER,
    )
    target = entity_registry.async_get_or_create(
        "number", DOMAIN, f"{entry.entry_id}-SET11", device_id=old_devices[1].id
    )

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    for device in old_devices:
        assert device_registry.async_get(device.id) is None
    assert entity_registry.async_get(offset.entity_id).device_id == heatpump.id
    assert entity_registry.async_get(offset.entity_id).disabled_by == er.RegistryEntryDisabler.USER
    assert entity_registry.async_get(target.entity_id).device_id == heatpump.id

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
