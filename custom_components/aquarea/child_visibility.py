"""Hide the entities of settings that have no effect, show them again once they do.

The remote controller hides a setting while the setting it depends on is off
(for example the solar deltas without a solar connection). This follows it:
entities whose readback or command has no effect with the current values of
the heat pump are hidden in the entity registry, and shown again as soon as
they have an effect. Only entities hidden by this integration are shown again;
an entity the user hid stays hidden. To see all of them, switch the option off.
Nothing is changed while HeishaMon is offline or for models the rules are not
known to hold for.
"""
from __future__ import annotations

import logging
from collections.abc import Iterable

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.event import async_call_later

from .const import CONF_HIDE_WITHOUT_EFFECT, DOMAIN
from .hub import HeatPumpHub

_LOGGER = logging.getLogger(__name__)

# wait for the burst of messages after a start before deciding
SETTLE_SECONDS = 10


class ChildVisibility:
    """Keeps the hidden state of the child entities in line with their parents."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        hub: HeatPumpHub,
        topic_ids_of_command: dict[str, list[str]],
    ) -> None:
        self.hass = hass
        self.entry = entry
        self.hub = hub
        self._topic_ids_of_command = topic_ids_of_command
        self._cancel_later: CALLBACK_TYPE | None = None
        self._unsubscribe: CALLBACK_TYPE | None = None

    def start(self) -> None:
        self._unsubscribe = self.hub.async_add_listener(self._hub_changed)

    @callback
    def stop(self) -> None:
        if self._unsubscribe is not None:
            self._unsubscribe()
            self._unsubscribe = None
        if self._cancel_later is not None:
            self._cancel_later()
            self._cancel_later = None

    @property
    def enabled(self) -> bool:
        return self.entry.options.get(CONF_HIDE_WITHOUT_EFFECT, True)

    def without_effect(self) -> set[str]:
        """Topic ids (TOP.., SET..) of the entities whose setting has no effect now."""
        topic_ids = set(self.hub.inactive_topics())
        for command in self.hub.blocked_commands():
            topic_ids.update(self._topic_ids_of_command.get(command, ()))
        return topic_ids

    @callback
    def _hub_changed(self) -> None:
        if self._cancel_later is None:
            self._cancel_later = async_call_later(self.hass, SETTLE_SECONDS, self._apply)

    @callback
    def _apply(self, _now=None) -> None:
        self._cancel_later = None
        # nothing is decided while HeishaMon is offline or the model is not covered
        if self.hub.online is False or not self.hub.rules_apply:
            return
        registry = er.async_get(self.hass)
        hide = self.without_effect() if self.enabled else set()
        prefix = f"{self.entry.entry_id}-"
        for entity in er.async_entries_for_config_entry(registry, self.entry.entry_id):
            if not entity.unique_id.startswith(prefix):
                continue
            topic_id = entity.unique_id.removeprefix(prefix)
            if topic_id in hide:
                if entity.hidden_by is None:
                    registry.async_update_entity(
                        entity.entity_id, hidden_by=er.RegistryEntryHider.INTEGRATION
                    )
                    _LOGGER.debug("Hiding %s: its setting has no effect", entity.entity_id)
            elif entity.hidden_by == er.RegistryEntryHider.INTEGRATION:
                registry.async_update_entity(entity.entity_id, hidden_by=None)
                _LOGGER.debug("Showing %s again", entity.entity_id)


def topic_ids_of_commands(descriptions: Iterable, mqtt_prefix: str) -> dict[str, list[str]]:
    """Map command names to the topic ids of the entities that send them."""
    result: dict[str, list[str]] = {}
    commands = f"{mqtt_prefix}commands/"
    for description in descriptions:
        command = getattr(description, "command_topic", None) or ""
        topic_id = getattr(description, "heishamon_topic_id", None)
        if topic_id and command.startswith(commands):
            result.setdefault(command.removeprefix(commands), []).append(topic_id)
    return result
