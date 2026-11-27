"""Constant values for HeishaMon integration."""

from enum import Enum

DOMAIN = "aquarea"


class DeviceType(Enum):
    HEATPUMP = 1
    HEISHAMON = 2


# identifier suffix and translation key of the heat pump sub-devices (none at the moment)
SUB_DEVICES: dict[DeviceType, str] = {}
# identifier suffixes of sub-devices created by earlier versions of the fork
OBSOLETE_SUB_DEVICES = ["dhw", "cooling", "bivalent", "solar_buffer", "external_control", "installer"]


class Feature(Enum):
    """Optional parts of an installation, each reported by one topic."""

    DHW = "dhw"
    BUFFER = "buffer"
    SOLAR = "solar"
    BIVALENT = "bivalent"
    SG_READY = "sg_ready"
    OPTIONAL_PCB = "optional_pcb"
    COOLING = "cooling"
    # optional PCB emulated by HeishaMon (setting "Emulate optional PCB")
    EMULATED_PCB = "emulated_pcb"


CONF_ENTITY_MANAGEMENT = "entity_management"
# enable entities of a feature once the heat pump reports it (never disable)
MODE_ENABLE_ONLY = "enable_only"
# same, and report entities of a missing feature as unavailable
MODE_UNAVAILABLE = "unavailable"
# same, and disable entities of a missing feature in the entity registry
MODE_DISABLE = "disable"
ENTITY_MANAGEMENT_MODES = [MODE_ENABLE_ONLY, MODE_UNAVAILABLE, MODE_DISABLE]

# refuse to change a setting that has no effect while another setting is off
CONF_SETTINGS_GUARD = "settings_guard"

# hide the entities of settings that have no effect while the setting they depend on is off
CONF_HIDE_WITHOUT_EFFECT = "hide_without_effect"

# API key of the optional HeishaMon web login (empty or missing: no login)
CONF_API_KEY = "api_key"

# talk HTTPS to the HeishaMon board (reboot, firmware upload)
CONF_USE_HTTPS = "use_https"
# SHA-256 fingerprint of the board's certificate, 64 lowercase hex characters
# (empty or missing: verify the certificate against the CAs Home Assistant trusts)
CONF_CERT_FINGERPRINT = "cert_fingerprint"
