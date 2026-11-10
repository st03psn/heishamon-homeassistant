"""Test entities following the installation reported by the heat pump."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.aquarea import features
from custom_components.aquarea.const import (
    CONF_ENTITY_MANAGEMENT,
    DOMAIN,
    MODE_DISABLE,
    MODE_ENABLE_ONLY,
    MODE_UNAVAILABLE,
    Feature,
)
from custom_components.aquarea.definitions import (
    build_binary_sensors,
    build_numbers,
    build_selects,
    build_sensors,
    build_switches,
)
from custom_components.aquarea.features import (
    FeatureTracker,
    ManagedEntity,
    managed_entities,
)

PREFIX = "panasonic_heat_pump/"
INTEGRATION = er.RegistryEntryDisabler.INTEGRATION
USER = er.RegistryEntryDisabler.USER


def _descriptions():
    return {
        "sensor": build_sensors(PREFIX),
        "binary_sensor": build_binary_sensors(PREFIX),
        "switch": build_switches(PREFIX),
        "select": build_selects(PREFIX),
        "number": build_numbers(PREFIX),
    }


def _tracker(hass, mode, entities):
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"discovery_prefix": PREFIX},
        options={CONF_ENTITY_MANAGEMENT: mode},
    )
    entry.add_to_hass(hass)
    tracker = FeatureTracker(
        hass,
        entry,
        [
            ManagedEntity(platform, f"{entry.entry_id}-{topic_id}", requires, topics)
            for platform, topic_id, requires, topics in entities
        ],
    )
    return entry, tracker


@pytest.fixture
def no_side_effects(hass):
    """Avoid timers, storage and reloads: tests call async_evaluate themselves."""
    with patch.object(
        FeatureTracker, "_schedule_evaluation"
    ) as schedule, patch.object(
        features.Store, "async_delay_save"
    ) as save, patch.object(
        hass.config_entries, "async_reload", AsyncMock()
    ) as reload:
        yield SimpleNamespace(schedule=schedule, save=save, reload=reload)


def _publish(tracker, topic, payload):
    tracker._message_received(SimpleNamespace(topic=f"{PREFIX}{topic}", payload=payload))


def _register(hass, entry, platform, topic_id, disabled_by):
    return er.async_get(hass).async_get_or_create(
        platform, DOMAIN, f"{entry.entry_id}-{topic_id}", disabled_by=disabled_by
    )


def _disabled_by(hass, registry_entry):
    return er.async_get(hass).async_get(registry_entry.entity_id).disabled_by


DHW_NUMBER = ("number", "SET63", (Feature.DHW,), ("main/DHW_Booster_Delay", "main/Static_Pressure"))


def test_new_topics_and_commands_are_defined():
    ids = {
        description.heishamon_topic_id: description
        for descriptions in _descriptions().values()
        for description in descriptions
        if getattr(description, "heishamon_topic_id", None)
    }
    expected = [f"TOP{i}" for i in range(144, 197)]
    expected += [f"SET{i}" for i in range(49, 105) if i != 101]
    assert [i for i in expected if i not in ids] == []
    for topic_id in expected:
        assert ids[topic_id].entity_registry_enabled_default is False, topic_id


def test_number_ranges_and_payloads():
    numbers = {n.heishamon_topic_id: n for n in build_numbers(PREFIX)}
    for i in list(range(49, 55)) + [57, 99, 103, 104] + list(range(61, 69)):
        number = numbers[f"SET{i}"]
        assert number.native_min_value < number.native_max_value
        assert number.native_step > 0
    assert numbers["SET67"].state_to_mqtt(-1.5) == "-1.5"
    assert numbers["SET67"].state_to_mqtt(1) == "1.0"
    assert numbers["SET90"].state_to_mqtt(0.5) == "0.5"
    assert numbers["SET62"].state_to_mqtt(30.0) == "30"
    assert numbers["SET62"].state("30") == 30


def test_select_payloads():
    selects = {s.heishamon_topic_id: s for s in build_selects(PREFIX)}
    for topic_id in ["SET70", "SET74", "SET75", "SET82", "SET83", "SET84", "SET85", "SET87", "SET89", "SET100"]:
        select = selects[topic_id]
        for index, option in enumerate(select.options):
            assert select.state_to_mqtt(option) == str(index), topic_id
            assert select.state(str(index)) == option, topic_id
    heater = selects["SET76"]
    assert [heater.state_to_mqtt(o) for o in heater.options] == ["3", "6", "9"]
    assert heater.state("-1") is None
    zone = selects["SET81"]
    assert zone.state("21") == "Room" and zone.state("25") == "Pool"
    assert zone.state("22") is None
    assert zone.state_to_mqtt("Room") == "0" and zone.state_to_mqtt("Pool") == "1"


def test_switches_reporting_a_feature_do_not_depend_on_it():
    """The entity turning a feature on must stay reachable while it is off."""
    managed = {
        (e.platform, e.unique_id.split("-")[-1]): e
        for e in managed_entities("entry", PREFIX, _descriptions())
    }
    assert managed[("switch", "SET86")].requires == ()  # DHW tank: enabled, never disabled
    assert ("binary_sensor", "TOP100") not in managed
    assert ("switch", "SET28") not in managed  # buffer tank
    assert ("switch", "SET34") not in managed  # bivalent
    assert managed[("select", "SET87")].requires == (Feature.OPTIONAL_PCB,)
    assert managed[("select", "SET89")].requires == (Feature.OPTIONAL_PCB,)
    # topics proving the firmware knows the command
    assert managed[("number", "SET63")].topics == DHW_NUMBER[3]


async def test_entity_enabled_once_feature_and_topics_are_seen(hass, no_side_effects):
    entry, tracker = _tracker(hass, MODE_ENABLE_ONLY, [DHW_NUMBER])
    number = _register(hass, entry, "number", "SET63", INTEGRATION)

    _publish(tracker, "main/DHW_Installed", "1")
    tracker.async_evaluate()
    assert _disabled_by(hass, number) == INTEGRATION  # own topic not seen yet

    _publish(tracker, "main/DHW_Booster_Delay", "20")
    tracker.async_evaluate()
    assert _disabled_by(hass, number) == INTEGRATION  # firmware marker not seen yet

    _publish(tracker, "main/Static_Pressure", "0")
    tracker.async_evaluate()
    await hass.async_block_till_done()
    assert _disabled_by(hass, number) is None
    no_side_effects.reload.assert_called_once_with(entry.entry_id)


async def test_entity_disabled_by_user_is_left_alone(hass, no_side_effects):
    entry, tracker = _tracker(hass, MODE_DISABLE, [DHW_NUMBER])
    number = _register(hass, entry, "number", "SET63", USER)
    for topic, payload in [("main/DHW_Installed", "1"), ("main/DHW_Booster_Delay", "20"), ("main/Static_Pressure", "0")]:
        _publish(tracker, topic, payload)
    tracker.async_evaluate()
    assert _disabled_by(hass, number) == USER


async def test_feature_needing_optional_pcb(hass, no_side_effects):
    _, tracker = _tracker(hass, MODE_UNAVAILABLE, [])
    assert tracker.is_installed(Feature.SG_READY) is None
    _publish(tracker, "main/SG_Ready_Control", "2")
    assert tracker.is_installed(Feature.SG_READY) is True  # optional PCB unknown
    _publish(tracker, "main/Optional_PCB", "0")
    assert tracker.is_installed(Feature.SG_READY) is False
    _publish(tracker, "main/Optional_PCB", "1")
    assert tracker.is_installed(Feature.SG_READY) is True
    _publish(tracker, "main/Solar_Mode", "0")
    assert tracker.is_installed(Feature.SOLAR) is False


@pytest.mark.parametrize(
    "mode,expected", [(MODE_ENABLE_ONLY, True), (MODE_UNAVAILABLE, False), (MODE_DISABLE, False)]
)
async def test_availability(hass, no_side_effects, mode, expected):
    _, tracker = _tracker(hass, mode, [])
    assert tracker.is_available((Feature.DHW,)) is True  # unknown: do not hide
    listener_calls = []
    tracker.async_add_listener(lambda: listener_calls.append(1))
    _publish(tracker, "main/DHW_Installed", "0")
    assert tracker.is_available((Feature.DHW,)) is expected
    assert tracker.is_available((Feature.BIVALENT,)) is True
    assert listener_calls == [1]
    _publish(tracker, "main/DHW_Installed", "1")
    assert tracker.is_available((Feature.DHW,)) is True


async def test_enable_only_never_disables(hass, no_side_effects):
    entry, tracker = _tracker(hass, MODE_ENABLE_ONLY, [DHW_NUMBER])
    number = _register(hass, entry, "number", "SET63", None)
    _publish(tracker, "main/DHW_Installed", "0")
    tracker._missing_since[Feature.DHW] -= features.DISABLE_DELAY + 1
    tracker.async_evaluate()
    assert _disabled_by(hass, number) is None


async def test_disable_and_enable_again(hass, no_side_effects):
    entry, tracker = _tracker(hass, MODE_DISABLE, [DHW_NUMBER])
    number = _register(hass, entry, "number", "SET63", None)
    for topic, payload in [("main/DHW_Booster_Delay", "20"), ("main/Static_Pressure", "0")]:
        _publish(tracker, topic, payload)

    _publish(tracker, "main/DHW_Installed", "0")
    tracker.async_evaluate()
    assert _disabled_by(hass, number) == INTEGRATION  # no delay: the heat pump hides them at once
    assert tracker._auto_disabled == {number.unique_id}

    _publish(tracker, "main/DHW_Installed", "1")
    tracker.async_evaluate()
    await hass.async_block_till_done()
    assert _disabled_by(hass, number) is None
    assert tracker._auto_disabled == set()


async def test_short_absence_does_not_disable(hass, no_side_effects):
    entry, tracker = _tracker(hass, MODE_DISABLE, [DHW_NUMBER])
    number = _register(hass, entry, "number", "SET63", None)
    _publish(tracker, "main/DHW_Installed", "0")
    _publish(tracker, "main/DHW_Installed", "1")
    assert Feature.DHW not in tracker._missing_since
    tracker.async_evaluate()
    assert _disabled_by(hass, number) is None


async def test_entity_enabled_again_by_user_is_kept(hass, no_side_effects):
    entry, tracker = _tracker(hass, MODE_DISABLE, [DHW_NUMBER])
    number = _register(hass, entry, "number", "SET63", None)
    _publish(tracker, "main/DHW_Installed", "0")
    tracker._missing_since[Feature.DHW] -= features.DISABLE_DELAY + 1
    tracker.async_evaluate()
    assert _disabled_by(hass, number) == INTEGRATION

    er.async_get(hass).async_update_entity(number.entity_id, disabled_by=None)
    tracker.async_evaluate()
    tracker.async_evaluate()
    assert _disabled_by(hass, number) is None
    assert tracker._user_kept == {number.unique_id}


def test_bivalent_advanced_temperature_commands():
    """The firmware names these commands SetBivalentAPStartTemp / SetBivalentAPStopTemp."""
    numbers = {n.heishamon_topic_id: n for n in build_numbers(PREFIX)}
    assert numbers["SET37"].command_topic == f"{PREFIX}commands/SetBivalentAPStartTemp"
    assert numbers["SET38"].command_topic == f"{PREFIX}commands/SetBivalentAPStopTemp"


async def test_delay_survives_restart(hass, no_side_effects):
    """The delay before disabling counts from the first report, not from the last start."""
    entry, tracker = _tracker(hass, MODE_DISABLE, [DHW_NUMBER])
    number = _register(hass, entry, "number", "SET63", None)
    long_ago = features.time.time() - features.DISABLE_DELAY - 60
    tracker._stored_missing_since = {Feature.DHW: long_ago}  # as loaded from storage
    _publish(tracker, "main/DHW_Installed", "0")
    assert tracker._missing_since[Feature.DHW] == long_ago
    tracker.async_evaluate()
    assert _disabled_by(hass, number) == INTEGRATION

    # reported installed again: the stored time is forgotten
    _publish(tracker, "main/DHW_Installed", "1")
    assert Feature.DHW not in tracker._stored_missing_since


def test_new_entities_without_part_are_managed():
    managed = {
        (e.platform, e.unique_id.split("-")[-1]): e
        for e in managed_entities("entry", PREFIX, _descriptions())
    }
    heater = managed[("select", "SET76")]  # heater capacity: no optional part
    assert heater.requires == ()
    assert heater.topics == ("main/Internal_Heater_Capacity", "main/Static_Pressure")
    assert ("switch", "SET86") in managed  # DHW tank switch
    assert ("number", "SET5") not in managed  # existing entity, default unchanged


async def test_entity_without_part_enabled_once_published(hass, no_side_effects):
    entities = [("select", "SET76", (), ("main/Internal_Heater_Capacity", "main/Static_Pressure"))]
    entry, tracker = _tracker(hass, MODE_DISABLE, entities)
    heater = _register(hass, entry, "select", "SET76", INTEGRATION)
    _publish(tracker, "main/Internal_Heater_Capacity", "3")
    tracker.async_evaluate()
    assert _disabled_by(hass, heater) == INTEGRATION  # firmware marker missing
    _publish(tracker, "main/Static_Pressure", "0")
    tracker.async_evaluate()
    assert _disabled_by(hass, heater) is None
    # never disabled again: it needs no part
    _publish(tracker, "main/DHW_Installed", "0")
    tracker.async_evaluate()
    assert _disabled_by(hass, heater) is None
