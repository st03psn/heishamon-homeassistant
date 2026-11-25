"""Events of the heat pump."""
from __future__ import annotations

from homeassistant.components.event import EventEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import slugify

from . import build_device_info
from .const import DeviceType
from .hub import RunEvent, get_hub
from .logic.cycles import RunFinished

RUN_STARTED = "started"
RUN_FINISHED = "finished"


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the event entities."""
    async_add_entities([CompressorRunEvent(hass, config_entry)])


class CompressorRunEvent(EventEntity):
    """Fires when the compressor starts and when it stops.

    A stop carries the length of the run in minutes, its defrosts, whether
    it was a short run and what it was for.
    """

    _attr_has_entity_name = True
    _attr_translation_key = "compressor_run"
    _attr_event_types = [RUN_STARTED, RUN_FINISHED]

    def __init__(self, hass: HomeAssistant, config_entry: ConfigEntry) -> None:
        self.hass = hass
        self._hub = get_hub(hass, config_entry.entry_id)
        self._config_entry_id = config_entry.entry_id
        prefix = config_entry.data["discovery_prefix"]
        self.entity_id = f"event.{slugify(prefix.replace('/', '_'))}_compressor_run"
        self._attr_unique_id = f"{config_entry.entry_id}-hub-compressor_run"

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(self._hub.async_add_run_listener(self._run_event))

    @callback
    def _run_event(self, event: RunEvent) -> None:
        if isinstance(event, RunFinished):
            self._trigger_event(
                RUN_FINISHED,
                {
                    "duration": round(event.duration / 60, 1),
                    "defrosts": event.defrosts,
                    "short": event.short,
                    "purpose": event.purpose,
                },
            )
        else:
            pause = None if event.pause is None else round(event.pause / 60, 1)
            self._trigger_event(RUN_STARTED, {"pause": pause})
        self.async_write_ha_state()

    @property
    def device_info(self):
        return build_device_info(
            self.hass, DeviceType.HEATPUMP, self._hub.mqtt_prefix, self._config_entry_id
        )
