"""Test the grouping of entities on sub-devices of the heat pump."""
import pytest
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.aquarea import _compute_identifiers, _sub_device_identifier
from custom_components.aquarea.const import DOMAIN, SUB_DEVICES, DeviceType
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


def test_every_listed_topic_exists_once():
    ids = [
        description.heishamon_topic_id
        for build in (build_sensors, build_binary_sensors, build_numbers, build_selects, build_switches)
        for description in build(PREFIX)
        if getattr(description, "heishamon_topic_id", None)
    ]
    assert [topic for topic in SUB_DEVICE_OF_TOPIC if topic not in ids] == []
    numbers = {n.heishamon_topic_id: n for n in build_numbers(PREFIX)}
    assert numbers["SET11"].device == DeviceType.DHW
    assert numbers["SET5"].device == DeviceType.HEATPUMP


async def test_entities_move_to_sub_devices(hass, mqtt_mock):
    entry = MockConfigEntry(domain=DOMAIN, data={"discovery_prefix": PREFIX}, version=2)
    entry.add_to_hass(hass)
    device_registry = dr.async_get(hass)
    heatpump = device_registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={_compute_identifiers(PREFIX)[DeviceType.HEATPUMP]},
        name="Aquarea HeatPump",
    )
    device_registry.async_update_device(heatpump.id, area_id="boiler_room")
    # an existing entity created on the heat pump by an older version
    entity_registry = er.async_get(hass)
    old = entity_registry.async_get_or_create(
        "number", DOMAIN, f"{entry.entry_id}-SET11", device_id=heatpump.id
    )

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    dhw = device_registry.async_get_device(identifiers={_sub_device_identifier(PREFIX, DeviceType.DHW)})
    assert dhw is not None
    assert dhw.via_device_id == heatpump.id
    assert dhw.area_id == "boiler_room"
    assert dhw.name == "Aquarea DHW"
    assert len(SUB_DEVICES) == 6
    for device_type in SUB_DEVICES:
        assert device_registry.async_get_device(identifiers={_sub_device_identifier(PREFIX, device_type)})
    assert _sub_device_identifier(PREFIX, DeviceType.DHW) == (DOMAIN, "panasonic_heat_pump-dhw")
    assert entity_registry.async_get(old.entity_id).device_id == dhw.id
    main_power = entity_registry.async_get_entity_id("switch", DOMAIN, f"{entry.entry_id}-SET1")
    assert entity_registry.async_get(main_power).device_id == heatpump.id

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
