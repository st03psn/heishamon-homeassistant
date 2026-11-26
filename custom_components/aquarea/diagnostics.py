"""Diagnostics download of a HeishaMon config entry."""
from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .hub import get_hub


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return what the integration knows about the heat pump.

    Topic payloads are values of the heat pump (temperatures, states,
    settings); they hold no credentials and no addresses.
    """
    hub = get_hub(hass, entry.entry_id)
    return {
        "entry": {"data": dict(entry.data), "options": dict(entry.options)},
        "online": hub.online,
        "operating_state": None if hub.state is None else hub.state.value,
        "cycles": hub.cycles.as_dict(),
        "topics": dict(sorted(hub.topics.items())),
    }
