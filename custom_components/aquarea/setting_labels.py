"""Readable names and values for the settings in the journal.

The journal records the MQTT name of a setting and its raw payload. This turns
them into what the user sees in Home Assistant: the name of the entity that
changes the setting and its value with unit or option text.
"""
from __future__ import annotations

from collections.abc import Iterable
from typing import Any, Optional

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .const import DOMAIN
from .definitions.descriptions import (
    HeishaMonNumberEntityDescription,
    HeishaMonSelectEntityDescription,
    HeishaMonSwitchEntityDescription,
)

_DOMAINS = (
    (HeishaMonNumberEntityDescription, "number"),
    (HeishaMonSelectEntityDescription, "select"),
    (HeishaMonSwitchEntityDescription, "switch"),
)

_WORDS = {
    "de": {"on": "an", "off": "aus", "home_assistant": "Home Assistant", "other": "extern"},
    "en": {"on": "on", "off": "off", "home_assistant": "Home Assistant", "other": "external"},
}


def _domain_of(description: Any) -> Optional[str]:
    for kind, domain in _DOMAINS:
        if isinstance(description, kind):
            return domain
    return None


def _number_text(value: float) -> str:
    text = f"{value:.2f}".rstrip("0").rstrip(".")
    return "0" if text == "-0" else text


class SettingLabels:
    """Names and values of settings as Home Assistant shows them."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry_id: str,
        descriptions: Iterable[Any],
        mqtt_prefix: str,
    ) -> None:
        self.hass = hass
        self.entry_id = entry_id
        self._by_setting: dict[str, tuple[str, Any]] = {}
        main = f"{mqtt_prefix}main/"
        for description in descriptions:
            domain = _domain_of(description)
            key = getattr(description, "key", "") or ""
            if domain is None or not key.startswith(main):
                continue
            # the first description of a setting wins (the order of the build lists)
            self._by_setting.setdefault(key.removeprefix(main), (domain, description))

    @property
    def _words(self) -> dict[str, str]:
        language = (self.hass.config.language or "en").split("-")[0]
        return _WORDS.get(language, _WORDS["en"])

    def name(self, setting: str) -> str:
        """The name of the entity that changes the setting, else the MQTT name."""
        found = self._by_setting.get(setting)
        if found is None:
            return setting
        domain, description = found
        registry = er.async_get(self.hass)
        topic_id = getattr(description, "heishamon_topic_id", None)
        entity_id = registry.async_get_entity_id(domain, DOMAIN, f"{self.entry_id}-{topic_id}")
        entry = registry.async_get(entity_id) if entity_id else None
        if entry is not None and (entry.name or entry.original_name):
            return entry.name or entry.original_name
        return setting

    def value(self, setting: str, raw: str) -> str:
        """The value as the entity shows it, with unit; the raw payload when unknown."""
        found = self._by_setting.get(setting)
        if found is None:
            return raw
        domain, description = found
        reader = getattr(description, "state", None)
        try:
            value = reader(raw) if reader is not None else raw
        except Exception:  # noqa: BLE001 - some readers raise a bare Exception on unknown values
            if domain != "number":
                return raw
            value = raw  # int("-2.0") fails; the number text below reads it
        if value is None:
            return raw
        if isinstance(value, bool):
            return self._words["on" if value else "off"]
        if domain == "number":
            try:
                text = _number_text(float(value))
            except (ValueError, TypeError):
                return raw
            unit = getattr(description, "native_unit_of_measurement", None)
            return f"{text} {unit}" if unit else text
        return str(value)

    def origin(self, origin: str) -> str:
        return self._words.get(origin, origin)
