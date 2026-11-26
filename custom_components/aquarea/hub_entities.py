"""Entities that show what the hub derives from the topics."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Optional

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory, UnitOfTime
from homeassistant.core import HomeAssistant, callback
from homeassistant.util import dt as dt_util
from homeassistant.util import slugify

from . import build_device_info
from .const import DeviceType
from .hub import HeatPumpHub, get_hub
from .logic.state import OperatingState


@dataclass(frozen=True, kw_only=True)
class HubSensorDescription(SensorEntityDescription):
    """A sensor whose value is read from the hub."""

    value: Callable[[HeatPumpHub], Any]
    attributes: Callable[[HeatPumpHub], dict[str, Any]] | None = None


def _blocked_settings(hub: HeatPumpHub) -> dict[str, Any]:
    """Blocked commands with the parent setting in the way, for the state attributes."""
    return {
        "settings": {
            command: [
                {
                    "parent": reason.parent_name,
                    "needed": list(reason.needed),
                    "actual": reason.actual,
                }
                for reason in reasons
            ]
            for command, reasons in sorted(hub.blocked_commands().items())
        }
    }


def _text(hub: HeatPumpHub, change: Any) -> dict[str, str]:
    """The change as Home Assistant shows the setting; raw values without labels."""
    labels = hub.labels
    if labels is None:
        return {"name": change.setting, "old": change.old, "new": change.new, "origin": change.origin}
    return {
        "name": labels.name(change.setting),
        "old": labels.value(change.setting, change.old),
        "new": labels.value(change.setting, change.new),
        "origin": labels.origin(change.origin),
    }


def _last_change(hub: HeatPumpHub) -> Optional[str]:
    if not hub.journal.entries:
        return None
    text = _text(hub, hub.journal.entries[-1])
    # a state holds at most 255 characters
    return f"{text['name'][:100]}: {text['old'][:60]} → {text['new'][:60]}"


def _recent_changes(hub: HeatPumpHub) -> dict[str, Any]:
    """The newest changes first, for the state attributes."""
    changes = []
    for change in reversed(hub.journal.entries[-20:]):
        text = _text(hub, change)
        changes.append(
            {
                "at": dt_util.utc_from_timestamp(change.at).isoformat(),
                "setting": change.setting,
                "old": change.old,
                "new": change.new,
                "origin": change.origin,
                "name": text["name"],
                "old_text": text["old"],
                "new_text": text["new"],
                "origin_text": text["origin"],
            }
        )
    return {"changes": changes}


def _minutes(seconds: Optional[float]) -> Optional[float]:
    return None if seconds is None else round(seconds / 60, 1)


HUB_SENSORS: tuple[HubSensorDescription, ...] = (
    HubSensorDescription(
        key="operating_state",
        translation_key="operating_state",
        device_class=SensorDeviceClass.ENUM,
        options=[state.value for state in OperatingState],
        value=lambda hub: None if hub.known_state is None else hub.known_state.value,
    ),
    HubSensorDescription(
        key="compressor_starts_today",
        translation_key="compressor_starts_today",
        state_class=SensorStateClass.TOTAL_INCREASING,
        value=lambda hub: hub.cycles.today.starts,
    ),
    HubSensorDescription(
        key="compressor_run_time_today",
        translation_key="compressor_run_time_today",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value=lambda hub: _minutes(hub.cycles.today.run_seconds),
    ),
    HubSensorDescription(
        key="short_runs_today",
        translation_key="short_runs_today",
        state_class=SensorStateClass.TOTAL_INCREASING,
        value=lambda hub: hub.cycles.today.short_runs,
    ),
    HubSensorDescription(
        key="defrosts_today",
        translation_key="defrosts_today",
        state_class=SensorStateClass.TOTAL_INCREASING,
        value=lambda hub: hub.cycles.today.defrosts,
    ),
    HubSensorDescription(
        key="current_run_time",
        translation_key="current_run_time",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        value=lambda hub: _minutes(hub.cycles.run_seconds) if hub.cycles.running else 0,
    ),
    HubSensorDescription(
        key="last_run_time",
        translation_key="last_run_time",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        value=lambda hub: _minutes(hub.cycles.last_run_seconds),
    ),
    HubSensorDescription(
        key="last_pause",
        translation_key="last_pause",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        value=lambda hub: _minutes(hub.cycles.last_pause_seconds),
    ),
    HubSensorDescription(
        key="last_setting_change",
        translation_key="last_setting_change",
        entity_category=EntityCategory.DIAGNOSTIC,
        value=_last_change,
        attributes=_recent_changes,
    ),
    HubSensorDescription(
        key="settings_without_effect",
        translation_key="settings_without_effect",
        entity_category=EntityCategory.DIAGNOSTIC,
        value=lambda hub: len(hub.blocked_commands()),
        attributes=_blocked_settings,
    ),
)


class HubSensor(SensorEntity):
    """A sensor that follows the hub."""

    entity_description: HubSensorDescription
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: ConfigEntry,
        description: HubSensorDescription,
    ) -> None:
        self.hass = hass
        self.entity_description = description
        self._hub = get_hub(hass, config_entry.entry_id)
        self._config_entry_id = config_entry.entry_id
        prefix = config_entry.data["discovery_prefix"]
        self.entity_id = f"sensor.{slugify(prefix.replace('/', '_'))}_{description.key}"
        self._attr_unique_id = f"{config_entry.entry_id}-hub-{description.key}"
        self._attr_native_value = description.value(self._hub)
        self._update_attributes()

    def _update_attributes(self) -> None:
        if self.entity_description.attributes is not None:
            self._attr_extra_state_attributes = self.entity_description.attributes(self._hub)

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self._hub.async_add_listener(self._hub_changed))

    @callback
    def _hub_changed(self) -> None:
        value = self.entity_description.value(self._hub)
        previous = getattr(self, "_attr_extra_state_attributes", None)
        self._update_attributes()
        changed = previous != getattr(self, "_attr_extra_state_attributes", None)
        if value != self._attr_native_value or changed:
            self._attr_native_value = value
            self.async_write_ha_state()

    @property
    def device_info(self):
        return build_device_info(
            self.hass, DeviceType.HEATPUMP, self._hub.mqtt_prefix, self._config_entry_id
        )


def build_hub_sensors(hass: HomeAssistant, config_entry: ConfigEntry) -> list[HubSensor]:
    """Return the sensors of the hub."""
    return [HubSensor(hass, config_entry, description) for description in HUB_SENSORS]
