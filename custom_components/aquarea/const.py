"""Constant values for HeishaMon integration."""

from enum import Enum

DOMAIN = "aquarea"


class DeviceType(Enum):
    HEATPUMP = 1
    HEISHAMON = 2

# API key of the optional HeishaMon web login (empty or missing: no login)
CONF_API_KEY = "api_key"

# talk HTTPS to the HeishaMon board (reboot, firmware upload)
CONF_USE_HTTPS = "use_https"
# SHA-256 fingerprint of the board's certificate, 64 lowercase hex characters
# (empty or missing: verify the certificate against the CAs Home Assistant trusts)
CONF_CERT_FINGERPRINT = "cert_fingerprint"
