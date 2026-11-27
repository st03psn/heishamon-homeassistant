"""Access to the HTTP endpoints of HeishaMon: web login and HTTPS."""
from __future__ import annotations

import re

import aiohttp

from homeassistant.config_entries import ConfigEntry
from homeassistant.exceptions import HomeAssistantError

from .const import CONF_API_KEY, CONF_CERT_FINGERPRINT, CONF_USE_HTTPS, DOMAIN

_API_KEY_RE = re.compile(r"[0-9a-fA-F]{32}")
_FINGERPRINT_RE = re.compile(r"[0-9a-f]{64}")
_FINGERPRINT_SEPARATORS = re.compile(r"[\s:]")


def normalize_api_key(value: str | None) -> str | None:
    """Return the key in lowercase, "" for no key, None if it is not valid."""
    value = (value or "").strip()
    if not value:
        return ""
    if _API_KEY_RE.fullmatch(value):
        return value.lower()
    return None


def normalize_fingerprint(value: str | None) -> str | None:
    """Return the SHA-256 fingerprint as 64 lowercase hex characters.

    Colons and whitespace are dropped, so "AB:CD:..." as shown by browsers
    and OpenSSL works. "" means no fingerprint, None that it is not valid.
    """
    value = _FINGERPRINT_SEPARATORS.sub("", value or "").lower()
    if not value:
        return ""
    if _FINGERPRINT_RE.fullmatch(value):
        return value
    return None


def api_key_headers(entry: ConfigEntry) -> dict[str, str]:
    """Authorization header for the HeishaMon HTTP endpoints, if a key is set."""
    key = entry.options.get(CONF_API_KEY)
    return {"Authorization": f"Bearer {key}"} if key else {}


def board_connection(
    entry: ConfigEntry, host: str
) -> tuple[str, bool | aiohttp.Fingerprint]:
    """Base URL of the board and the ``ssl`` argument for aiohttp requests.

    - HTTPS off: ``http://<host>``; ``ssl`` is the default (True), which aiohttp
      ignores for plain HTTP.
    - HTTPS on with a fingerprint: ``https://<host>`` and an
      ``aiohttp.Fingerprint``. aiohttp then skips CA and hostname checks and
      instead requires the SHA-256 of the board's (leaf) certificate to match,
      which is what makes the self-signed certificate of HeishaMon usable.
    - HTTPS on without a fingerprint: ``https://<host>`` and True, i.e. the
      verifying SSL context of the Home Assistant session (certifi CA bundle
      and hostname check), for a certificate uploaded to the board.

    There is no unverified mode and no fallback to HTTP once HTTPS is on.
    """
    if not entry.options.get(CONF_USE_HTTPS):
        return f"http://{host}", True
    fingerprint = entry.options.get(CONF_CERT_FINGERPRINT)
    if fingerprint:
        return f"https://{host}", aiohttp.Fingerprint(bytes.fromhex(fingerprint))
    return f"https://{host}", True


def tls_error(err: Exception, host: str) -> HomeAssistantError | None:
    """Translated error for a certificate problem, None for other errors."""
    if isinstance(err, aiohttp.ServerFingerprintMismatch):
        key = "certificate_fingerprint_mismatch"
    elif isinstance(err, aiohttp.ClientConnectorCertificateError):
        key = "certificate_verification_failed"
    else:
        return None
    return HomeAssistantError(
        translation_domain=DOMAIN,
        translation_key=key,
        translation_placeholders={"host": str(host)},
    )
