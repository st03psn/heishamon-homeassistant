"""Test the settings sub-device of the heat pump."""
import pytest
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.aquarea import (
    _compute_identifiers,
    _sub_device_identifier,
    _sub_device_identifier_for,
)
from custom_components.aquarea.const import DOMAIN, DeviceType
from custom_components.aquarea.definitions import (
    SUB_DEVICE_OF_TOPIC,
    build_binary_sensors,
    build_numbers,
    build_selects,
    build_sensors,
    build_switches,
)

PREFIX = "panasonic_heat_pump/"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


def test_assignment():
    ids = [
        description.heishamon_topic_id
        for build in (build_sensors, build_binary_sensors, build_numbers, build_selects, build_switches)
        for description in build(PREFIX)
        if getattr(description, "heishamon_topic_id", None)
    ]
    assert [topic for topic in SUB_DEVICE_OF_TOPIC if topic not in ids] == []
    assert set(SUB_DEVICE_OF_TOPIC.values()) == {DeviceType.INSTALLER}
    numbers = {n.heishamon_topic_id: n for n in build_numbers(PREFIX)}
    assert numbers["SET67"].device == DeviceType.INSTALLER
    assert numbers["SET11"].device == DeviceType.HEATPUMP  # DHW target stays on the heat pump
    assert _sub_device_identifier(PREFIX, DeviceType.INSTALLER) == (DOMAIN, "panasonic_heat_pump-installer")


async def test_settings_device_and_cleanup(hass, mqtt_mock):
    entry = MockConfigEntry(domain=DOMAIN, data={"discovery_prefix": PREFIX}, version=2)
    entry.add_to_hass(hass)
    device_registry = dr.async_get(hass)
    entity_registry = er.async_get(hass)
    heatpump = device_registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={_compute_identifiers(PREFIX)[DeviceType.HEATPUMP]},
        name="Aquarea HeatPump",
    )
    device_registry.async_update_device(heatpump.id, area_id="boiler_room")
    # sub-device of an earlier version, holding a disabled installer entity and a DHW entity
    old = device_registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={_sub_device_identifier_for(PREFIX, "dhw")},
        name="Aquarea DHW",
    )
    offset = entity_registry.async_get_or_create(
        "number", DOMAIN, f"{entry.entry_id}-SET103", device_id=old.id,
        disabled_by=er.RegistryEntryDisabler.USER,
    )
    target = entity_registry.async_get_or_create(
        "number", DOMAIN, f"{entry.entry_id}-SET11", device_id=old.id
    )

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    settings = device_registry.async_get_device(
        identifiers={_sub_device_identifier(PREFIX, DeviceType.INSTALLER)}
    )
    assert settings is not None
    assert settings.name == "Aquarea Settings"
    assert settings.area_id == "boiler_room"
    assert device_registry.async_get(old.id) is None
    # entities survive the removal of the old device, with their settings
    assert entity_registry.async_get(offset.entity_id).device_id == settings.id
    assert entity_registry.async_get(offset.entity_id).disabled_by == er.RegistryEntryDisabler.USER
    assert entity_registry.async_get(target.entity_id).device_id == heatpump.id

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
