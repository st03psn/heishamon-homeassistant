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

# GitHub repository the firmware update entity takes HeishaMon releases from
CONF_FIRMWARE_SOURCE = "firmware_source"
# owner/repo, only used with FIRMWARE_SOURCE_CUSTOM
CONF_FIRMWARE_REPOSITORY = "firmware_repository"
FIRMWARE_SOURCE_FORK = "fork"
FIRMWARE_SOURCE_ORIGINAL = "original"
FIRMWARE_SOURCE_CUSTOM = "custom"
FIRMWARE_SOURCES = [FIRMWARE_SOURCE_FORK, FIRMWARE_SOURCE_ORIGINAL, FIRMWARE_SOURCE_CUSTOM]
# also the default of entries created before the option existed: offering the
# original firmware would replace the hardened one of this fork
DEFAULT_FIRMWARE_SOURCE = FIRMWARE_SOURCE_FORK
FORK_FIRMWARE_REPOSITORY = "st03psn/HeishaMon"
ORIGINAL_FIRMWARE_REPOSITORY = "heishamon/HeishaMon"
# the repository name must not consist of dots only ("." and ".." are paths)
FIRMWARE_REPOSITORY_PATTERN = r"^[A-Za-z0-9-]+/(?!\.+$)[A-Za-z0-9._-]+$"
