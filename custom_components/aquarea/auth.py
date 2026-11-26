"""API key of the optional HeishaMon web login."""
from __future__ import annotations

import re

from homeassistant.config_entries import ConfigEntry

from .const import CONF_API_KEY

_API_KEY_RE = re.compile(r"[0-9a-fA-F]{32}")


def normalize_api_key(value: str | None) -> str | None:
    """Return the key in lowercase, "" for no key, None if it is not valid."""
    value = (value or "").strip()
    if not value:
        return ""
    if _API_KEY_RE.fullmatch(value):
        return value.lower()
    return None


def api_key_headers(entry: ConfigEntry) -> dict[str, str]:
    """Authorization header for the HeishaMon HTTP endpoints, if a key is set."""
    key = entry.options.get(CONF_API_KEY)
    return {"Authorization": f"Bearer {key}"} if key else {}
