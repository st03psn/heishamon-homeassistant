"""Diagnostics download of a HeishaMon config entry."""
from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from .const import CONF_API_KEY
from .hub import get_hub

TO_REDACT = {CONF_API_KEY}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return what the integration knows about the heat pump.

    Topic payloads are values of the heat pump (temperatures, states,
    settings); they hold no credentials and no addresses. The API key in the options
    is redacted; the certificate fingerprint is public (shown on the access page
    of HeishaMon) and stays readable.
    """
    hub = get_hub(hass, entry.entry_id)
    return {
        "entry": {
            "data": async_redact_data(entry.data, TO_REDACT),
            "options": async_redact_data(entry.options, TO_REDACT),
        },
        "online": hub.online,
        "operating_state": None if hub.state is None else hub.state.value,
        "cycles": hub.cycles.as_dict(),
        "journal": hub.journal.as_dict()["entries"],
        "topics": dict(sorted(hub.topics.items())),
    }
