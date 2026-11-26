"""The HeishaMon component."""

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.storage import Store

from homeassistant.helpers import entity_registry as er

from .const import DOMAIN, OBSOLETE_SUB_DEVICES, SUB_DEVICES, DeviceType, Feature
from .definitions.arrange import SUB_DEVICE_OF_TOPIC
from .definitions.binary_sensors import build_binary_sensors
from .definitions.numbers import build_numbers
from .definitions.selects import build_selects
from .definitions.sensors import build_sensors
from .definitions.switches import build_switches
from .features import FeatureTracker, ManagedEntity, managed_entities
from .hub import HeatPumpHub, storage_key
from .model_catalog import ModelCatalog

PLATFORMS = [
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.SWITCH,
    Platform.SELECT,
    Platform.NUMBER,
    Platform.CLIMATE,
    Platform.WATER_HEATER,
    Platform.UPDATE,
    Platform.BUTTON,
    Platform.EVENT,
]
_LOGGER = logging.getLogger(__name__)

DEFAULT_MQTT_TOPIC = "panasonic_heat_pump/"


def _compute_identifiers(mqtt_topic: str) -> dict[DeviceType, tuple[str, str]]:
    if mqtt_topic == DEFAULT_MQTT_TOPIC:  # backward compatibility
        return {
            DeviceType.HEATPUMP: (DOMAIN, "panasonic_heat_pump"),
            DeviceType.HEISHAMON: (DOMAIN, "heishamon"),
        }
    return {
        DeviceType.HEATPUMP: (DOMAIN, mqtt_topic),
        DeviceType.HEISHAMON: (DOMAIN, f"heishamon-{mqtt_topic}"),
    }


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up the HeishaMon integration."""
    domain_data = hass.data.setdefault(DOMAIN, {})
    catalog = domain_data.get("model_catalog")
    if catalog is None:
        catalog = domain_data["model_catalog"] = ModelCatalog(hass)
    await catalog.async_load()

    mqtt_topic = entry.data["discovery_prefix"]
    identifiers = _compute_identifiers(mqtt_topic)

    device_registry = dr.async_get(hass)

    heishamon_device = device_registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={identifiers[DeviceType.HEISHAMON]},
        name="HeishaMon",
    )
    heatpump_device = device_registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={identifiers[DeviceType.HEATPUMP]},
        name="Aquarea HeatPump",
        manufacturer="Aquarea",
    )
    sub_device_ids: dict[DeviceType, str] = {}
    for device_type in SUB_DEVICES:
        sub_identifier = _sub_device_identifier(mqtt_topic, device_type)
        existing = _find_device(hass, entry, sub_identifier)
        sub_device = device_registry.async_get_or_create(
            config_entry_id=entry.entry_id,
            identifiers={sub_identifier},
            translation_key=SUB_DEVICES[device_type],
            manufacturer="Aquarea",
            via_device_id=heatpump_device.id,
        )
        sub_device_ids[device_type] = sub_device.id
        if existing is None and heatpump_device.area_id is not None:
            # new sub-devices start in the area of the heat pump
            device_registry.async_update_device(
                sub_device.id, area_id=heatpump_device.area_id
            )
    _remove_obsolete_sub_devices(hass, entry, mqtt_topic, heatpump_device.id, sub_device_ids)

    _remove_moved_entities(hass, entry)

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {
        "heishamon_device_id": heishamon_device.id,
        "heatpump_device_id": heatpump_device.id,
    }

    tracker = FeatureTracker(
        hass,
        entry,
        managed_entities(
            entry.entry_id,
            mqtt_topic,
            {
                Platform.SENSOR: build_sensors(mqtt_topic),
                Platform.BINARY_SENSOR: build_binary_sensors(mqtt_topic),
                Platform.SWITCH: build_switches(mqtt_topic),
                Platform.SELECT: build_selects(mqtt_topic),
                Platform.NUMBER: build_numbers(mqtt_topic),
            },
        )
        + [
            ManagedEntity(
                platform=Platform.WATER_HEATER,
                unique_id=f"{entry.entry_id}.water_heater",
                requires=(Feature.DHW,),
                topics=("main/DHW_Installed",),
            )
        ],
    )
    hass.data[DOMAIN][entry.entry_id]["features"] = tracker
    hub = HeatPumpHub(hass, entry, mqtt_topic, _settings_of(mqtt_topic))
    hass.data[DOMAIN][entry.entry_id]["hub"] = hub
    await hub.async_load()

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    await tracker.async_start()
    await hub.async_start()
    entry.async_on_unload(tracker.async_stop)
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    return True


async def _async_options_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Apply new options."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Remove what the integration stored for this entry."""
    await FeatureTracker(hass, entry, []).async_remove_storage()
    await Store(hass, 1, storage_key(entry.entry_id)).async_remove()


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload the HeishaMon integration."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        # only now: an entry that stays loaded keeps its hub running
        data = hass.data[DOMAIN].pop(entry.entry_id, {})
        if (hub := data.get("hub")) is not None:
            await hub.async_stop()
    return unloaded


def _sub_device_identifier(mqtt_topic: str, device_type: DeviceType) -> tuple[str, str]:
    return _sub_device_identifier_for(mqtt_topic, SUB_DEVICES[device_type])


def _sub_device_identifier_for(mqtt_topic: str, suffix: str) -> tuple[str, str]:
    heatpump_identifier = _compute_identifiers(mqtt_topic)[DeviceType.HEATPUMP][1]
    return (DOMAIN, f"{heatpump_identifier}-{suffix}")


def _find_device(
    hass: HomeAssistant, entry: ConfigEntry, identifier: tuple[str, str]
) -> dr.DeviceEntry | None:
    """Return the device of this entry with the given identifier.

    device_registry.async_get_device is deprecated since identifiers are no
    longer unique across config entries; look among this entry's devices.
    """
    for device in dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id):
        if identifier in device.identifiers:
            return device
    return None


def _remove_obsolete_sub_devices(
    hass: HomeAssistant,
    entry: ConfigEntry,
    mqtt_topic: str,
    heatpump_device_id: str,
    sub_device_ids: dict[DeviceType, str],
) -> None:
    """Move the entities of sub-devices from earlier versions, then remove those devices.

    Entities are moved first: removing a device would remove its entities.
    """
    device_registry = dr.async_get(hass)
    entity_registry = er.async_get(hass)
    for suffix in OBSOLETE_SUB_DEVICES:
        device = _find_device(hass, entry, _sub_device_identifier_for(mqtt_topic, suffix))
        if device is None:
            continue
        for entity_entry in er.async_entries_for_device(
            entity_registry, device.id, include_disabled_entities=True
        ):
            topic_id = entity_entry.unique_id.removeprefix(f"{entry.entry_id}-")
            target = SUB_DEVICE_OF_TOPIC.get(topic_id)
            entity_registry.async_update_entity(
                entity_entry.entity_id,
                device_id=sub_device_ids.get(target, heatpump_device_id),
            )
        device_registry.async_remove_device(device.id)


def _settings_of(mqtt_topic: str) -> dict[str, list[str]]:
    """Map the command of every number, select and switch to the topic names of its readbacks.

    One command can have several readbacks: SetCurves carries all curve points.
    """
    settings: dict[str, list[str]] = {}
    main = f"{mqtt_topic}main/"
    commands = f"{mqtt_topic}commands/"
    for build in (build_numbers, build_selects, build_switches):
        for description in build(mqtt_topic):
            command = getattr(description, "command_topic", None) or ""
            if description.key.startswith(main) and command.startswith(commands):
                readbacks = settings.setdefault(command.removeprefix(commands), [])
                readback = description.key.removeprefix(main)
                if readback not in readbacks:
                    readbacks.append(readback)
    return settings


# topics that earlier versions of the fork had as sensors and that are binary sensors now
MOVED_TO_BINARY_SENSOR = ("TOP149", "TOP163")


def _remove_moved_entities(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Remove the sensor entries of topics that are binary sensors now.

    The binary sensor has the same unique id in another domain, so the old
    entry would stay behind as an entity that is no longer provided.
    """
    entity_registry = er.async_get(hass)
    for topic_id in MOVED_TO_BINARY_SENSOR:
        entity_id = entity_registry.async_get_entity_id(
            Platform.SENSOR, DOMAIN, f"{entry.entry_id}-{topic_id}"
        )
        if entity_id is not None:
            entity_registry.async_remove(entity_id)


def build_device_info(hass: HomeAssistant, device_type: DeviceType, mqtt_topic: str, config_entry_id: str) -> DeviceInfo:
    """Return device info for the given device type."""
    identifiers = _compute_identifiers(mqtt_topic)
    if device_type in SUB_DEVICES:
        device_info_fields = {
            "identifiers": {_sub_device_identifier(mqtt_topic, device_type)},
            "translation_key": SUB_DEVICES[device_type],
            "manufacturer": "Aquarea",
        }
        via_device_id = hass.data.get(DOMAIN, {}).get(config_entry_id, {}).get("heatpump_device_id")
        if via_device_id is not None:
            device_info_fields["via_device_id"] = via_device_id
        return DeviceInfo(**device_info_fields)
    if device_type == DeviceType.HEATPUMP:
        device_info_fields = {
            "identifiers": {identifiers[DeviceType.HEATPUMP]},
            "name": "Aquarea HeatPump",
            "manufacturer": "Aquarea",
        }
        via_device_id = hass.data.get(DOMAIN, {}).get(config_entry_id, {}).get("heishamon_device_id")
        if via_device_id is not None:
            device_info_fields["via_device_id"] = via_device_id
        return DeviceInfo(**device_info_fields)
    elif device_type == DeviceType.HEISHAMON:
        return DeviceInfo(
            identifiers={identifiers[DeviceType.HEISHAMON]},
            name="HeishaMon",
        )
    assert False, f"{device_type} management has not been implemented"


async def async_migrate_entry(hass, config_entry: ConfigEntry):
    if config_entry.version == 1:
        _LOGGER.warn(
            f"config_entry version is {config_entry.version}, migrating to version 2"
        )
        # we need to add the discovery prefix
        new = {**config_entry.data}
        new[
            "discovery_prefix"
        ] = DEFAULT_MQTT_TOPIC  # it was hardcoded in version 1 of the config_entry schema
        hass.config_entries.async_update_entry(config_entry, data=new, version=2)
        _LOGGER.info(f"Migration to version {config_entry.version} successful")
    return True
