"""Support for HeishaMon controlled heatpumps through MQTT."""

from __future__ import annotations
import logging

from homeassistant.components import mqtt
from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import slugify

from .definitions import (
    build_switches,
    build_binary_sensors,
    HeishaMonBinarySensorEntityDescription,
)
from . import build_device_info
from .const import DOMAIN, DeviceType
from .errors import describe, is_fault
from .features import FeatureGatedEntity

_LOGGER = logging.getLogger(__name__)

# async_setup_platform should be defined if one wants to support config via configuration.yaml


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up HeishaMon binary sensors from config entry."""
    discovery_prefix = config_entry.data[
        "discovery_prefix"
    ]  # TODO: handle migration of entities
    _LOGGER.debug(
        f"Starting bootstrap of binary sensors with prefix '{discovery_prefix}'"
    )
    binary_sensors = build_binary_sensors(discovery_prefix)
    async_add_entities(
        HeishaMonBinarySensor(description, config_entry)
        for description in binary_sensors
    )
    # those entities are added for people who want to have "safe" entities visible in their dashboard
    # instead of exposing entities whose state can be modified by mistake. See #151
    # A switch whose topic already has a binary sensor gets no read-only copy: the
    # copy would show the same value twice (and get an entity ID ending in _2).
    shown_topics = {description.key for description in binary_sensors}
    entity_registry = er.async_get(hass)
    readonly_switches = []
    for switch_description in build_switches(discovery_prefix):
        if switch_description.key in shown_topics:
            duplicate = entity_registry.async_get_entity_id(
                "binary_sensor",
                DOMAIN,
                f"{config_entry.entry_id}-{switch_description.heishamon_topic_id}",
            )
            if duplicate is not None:
                entity_registry.async_remove(duplicate)
            continue
        category = switch_description.entity_category
        if category == EntityCategory.CONFIG:
            category = EntityCategory.DIAGNOSTIC
        readonly_switches.append(
            HeishaMonBinarySensor(
                HeishaMonBinarySensorEntityDescription(
                    heishamon_topic_id=switch_description.heishamon_topic_id,
                    key=switch_description.key,
                    name=f"{switch_description.name} (readonly)",
                    entity_category=category,
                    device=switch_description.device,
                    state=switch_description.state,
                    device_class=switch_description.binary_sensor_device_class,
                    entity_registry_enabled_default=False,
                ),
                config_entry,
            )
        )
    async_add_entities(readonly_switches)
    async_add_entities([HeishaMonFaultSensor(config_entry)])


class HeishaMonBinarySensor(FeatureGatedEntity, BinarySensorEntity):
    """Representation of a HeishaMon binary sensor that is updated via MQTT."""

    entity_description: HeishaMonBinarySensorEntityDescription

    def __init__(
        self,
        description: HeishaMonBinarySensorEntityDescription,
        config_entry: ConfigEntry,
    ) -> None:
        """Initialize the binary sensor."""
        self.entity_description = description
        self.config_entry_entry_id = config_entry.entry_id
        self.discovery_prefix = config_entry.data[
            "discovery_prefix"
        ]  # TODO: handle migration of entities

        slug = slugify(description.key.replace("/", "_"))
        self.entity_id = f"binary_sensor.{slug}"
        self._attr_unique_id = (
            f"{config_entry.entry_id}-{description.heishamon_topic_id}"
        )

    async def async_added_to_hass(self) -> None:
        """Subscribe to MQTT events."""
        self._setup_feature_gating()

        @callback
        def message_received(message):
            """Handle new MQTT messages."""
            if self.entity_description.state is not None:
                self._attr_is_on = self.entity_description.state(message.payload)
            else:
                self._attr_is_on = message.payload

            self.async_write_ha_state()
            if self.entity_description.on_receive is not None:
                self.entity_description.on_receive(
                    self.hass, self, self.config_entry_entry_id, self._attr_is_on
                )

        await mqtt.async_subscribe(
            self.hass, self.entity_description.key, message_received, 1
        )

    @property
    def device_info(self):
        return build_device_info(self.hass, self.entity_description.device, self.discovery_prefix, self.config_entry_entry_id)


class HeishaMonFaultSensor(BinarySensorEntity):
    """On while the heat pump reports a fault (TOP44), with a Repairs issue."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_name = "Fault"

    def __init__(self, config_entry: ConfigEntry) -> None:
        self.config_entry_entry_id = config_entry.entry_id
        self.discovery_prefix = config_entry.data["discovery_prefix"]
        self._topic = f"{self.discovery_prefix}main/Error"
        self.entity_id = f"binary_sensor.{slugify(self._topic.replace('/', '_'))}"
        self._attr_unique_id = f"{config_entry.entry_id}-TOP44-fault"
        self._issue_id = f"heat_pump_fault_{config_entry.entry_id}"
        self._attr_extra_state_attributes = {}

    async def async_added_to_hass(self) -> None:
        @callback
        def message_received(message):
            code = message.payload
            if isinstance(code, bytes):
                code = code.decode("utf-8", errors="replace")
            code = str(code).strip()
            fault = is_fault(code)
            self._attr_is_on = fault
            language = self.hass.config.language or "en"
            self._attr_extra_state_attributes = (
                {"code": code, "description": describe(code, language)} if fault else {}
            )
            self.async_write_ha_state()
            if fault:
                ir.async_create_issue(
                    self.hass,
                    DOMAIN,
                    self._issue_id,
                    is_fixable=False,
                    is_persistent=False,
                    severity=ir.IssueSeverity.ERROR,
                    translation_key="heat_pump_fault",
                    translation_placeholders={
                        "code": code,
                        "description": describe(code, language),
                    },
                )
            else:
                ir.async_delete_issue(self.hass, DOMAIN, self._issue_id)

        await mqtt.async_subscribe(self.hass, self._topic, message_received, 1)

    @property
    def device_info(self):
        return build_device_info(
            self.hass, DeviceType.HEATPUMP, self.discovery_prefix, self.config_entry_entry_id
        )
