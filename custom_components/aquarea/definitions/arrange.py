"""Display names, diagnostic categories and automatic enabling, applied to built descriptions."""
from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import replace
from functools import wraps
from typing import Any, Optional

from homeassistant.helpers.entity import EntityCategory

from ..const import DeviceType


# entities moved to a sub-device of the heat pump (none at the moment)
SUB_DEVICE_OF_TOPIC: dict[str, DeviceType] = {}


# "Emulated PCB ...": values HeishaMon sends to or receives from the heat pump
# in place of an optional PCB (only with the optional PCB emulation of HeishaMon
# switched on, not with a real optional PCB).
# Display names, so that the entities of one topic sort next to each other in
# the device page (Home Assistant sorts them by name). The prefix "Aquarea " is
# removed from all names: Home Assistant shows the device name in front.
ENTITY_NAMES: dict[str, str] = {
    "OPT6": "Emulated PCB alarm",
    "SET32": "External compressor control",
    "SET8": "Zone 2 cool shift",
    "SET7": "Zone 2 heat shift",
    "SET6": "Zone 1 cool shift",
    "SET5": "Zone 1 heat shift",
    "OPT3": "Emulated PCB Z2 mixing valve",
    "OPT1": "Emulated PCB Z1 mixing valve",
    "OPT2": "Emulated PCB Z2 pump",
    "OPT0": "Emulated PCB Z1 pump",
    "TOP152": "Dry concrete target",
    "SET73": "Bivalent adv. stop delay",
    "SET72": "Bivalent adv. start delay",
    "TOP138": "Bivalent adv. DHW delay",
    "TOP137": "Bivalent adv. stop delay",
    "TOP136": "Bivalent adv. start delay",
    "SET88": "Solar max temp",
    "TOP105": "Solar max temp",
    "SET79": "Solar frost protection",
    "TOP104": "Solar frost protection",
    "SET67": "Sensor offset remote Th1",
    "TOP177": "Sensor offset remote Th1",
    "SET83": "Cooling water mode",
    "SET82": "Heating water mode",
    "TOP43": "Zone 2 water target",
    "TOP42": "Zone 1 water target",
    "TOP37": "Zone 2 water outlet",
    "TOP36": "Zone 1 water outlet",
    "TOP12": "Compressor starts",
    "TOP11": "Compressor hours",
    "TOP33": "Remote control temp",
    # sensors
    "TOP1": "Pump flow",
    "TOP5": "Water inlet temperature",
    "TOP6": "Water outlet temperature",
    "TOP7": "Water outlet target",
    "TOP10": "DHW tank temperature",
    "TOP14": "Outdoor temperature",
    "TOP20": "Valve 3-way",
    "TOP125": "Valve 2-way",
    "TOP23": "Heating delta",
    "TOP24": "Cooling delta",
    "TOP25": "DHW holiday shift temperature",
    "TOP38": "Cooling power produced",
    "TOP39": "Cooling power consumed",
    "TOP40": "DHW power produced",
    "TOP41": "DHW power consumed",
    "TOP15": "Heat power produced",
    "TOP16": "Heat power consumed",
    "TOP44": "Error code",
    "TOP45": "Heating holiday shift",
    "TOP46": "Buffer temperature",
    "TOP47": "Solar temperature",
    "TOP48": "Pool temperature",
    "TOP56": "Zone 1 temperature",
    "TOP57": "Zone 2 temperature",
    "TOP64": "Pressure high",
    "TOP66": "Pressure low",
    "TOP70": "DHW sterilization temperature",
    "TOP71": "DHW sterilization maximum time",
    "TOP76": "Heating water mode",
    "TOP78": "Heater on outdoor temperature",
    "TOP79": "Auto to cool above",
    "TOP80": "Auto to heat below",
    "TOP81": "Cooling water mode",
    "TOP90": "Heater hours room",
    "TOP91": "Heater hours DHW",
    "TOP92": "Heat pump model",
    "TOP106": "Pump flow rate mode",
    "TOP113": "Buffer delta",
    "TOP116": "Water inlet 2 temperature",
    "TOP118": "Remote control 2 temp",
    "TOP131": "Bivalent start temp",
    "TOP140": "DHW smart mode",
    "TOP147": "Heater capacity",
    "TOP158": "DHW alternation room max",
    "TOP162": "External heat/cool switch",
    "TOP169": "Heating target with buffer",
    "TOP171": "Heating on outdoor temperature",
    "TOP174": "Heating efficiency stage 1",
    "TOP175": "Heating efficiency stage 2",
    "TOP176": "Heating efficiency stage 3",
    # binary sensors
    "TOP58": "DHW heater enabled",
    "TOP59": "Heater room enabled",
    "TOP60": "Heater internal state",
    "TOP61": "Heater external state",
    "TOP68": "Heater force state",
    "TOP100": "DHW installed",
    "TOP109": "Anti freeze mode",
    "TOP110": "Optional PCB enabled",
    "TOP167": "Heater backup enabled",
    "OPT4": "Emulated PCB pool pump",
    "OPT5": "Emulated PCB solar pump",
    # numbers
    "SET11": "DHW target temperature",
    "SET15": "Pump maximum duty",
    "SET18": "Heating delta",
    "SET19": "Cooling delta",
    "SET27": "Buffer delta",
    "SET29": "Heating off outdoor temperature",
    "SET46": "Heater on outdoor temperature",
    "SetDemandControl": "Emulated PCB demand control",
    "SET36": "Bivalent start temp",
    "SET37": "Bivalent adv. start temp",
    "SET38": "Bivalent adv. stop temp",
    "SET49": "DHW sterilization temperature",
    "SET50": "DHW sterilization maximum time",
    "SET51": "Auto to cool above",
    "SET52": "Auto to heat below",
    "SET53": "DHW alternation room max",
    "SET61": "Heating on outdoor temperature",
    "SET64": "Heating efficiency stage 1",
    "SET65": "Heating efficiency stage 2",
    "SET66": "Heating efficiency stage 3",
    "SET80": "Heating holiday shift",
    # selects
    "SET9": "Operating mode",
    "SET17": "Zones active",
    "SET40": "DHW smart mode",
    "SET42": "Pump flow rate mode",
    "SET44": "DHW heater release",
    "SET45": "Heater room release",
    "SET76": "Heater capacity",
    "SetSmartGridMode": "Emulated PCB SG ready signal",
    # switches
    "SET1": "Main power",
    "SET10": "DHW force",
    "SET13": "DHW sterilization force",
    "SET47": "Heater force",
    "SET25": "External outdoor sensor",
    "SET28": "Buffer tank installed",
    "SET30": "External control",
    "SET33": "External heat/cool control",
    "SetCompressorState": "Emulated PCB compressor",
    "SET86": "DHW tank installed",
}


# readbacks of settings, shown under "Diagnostic" instead of "Sensors"
DIAGNOSTIC_READBACKS = set(
    "TOP23 TOP24 TOP25 TOP45 TOP70 TOP71 TOP76 TOP78 TOP79 TOP80 TOP81 TOP92 TOP101 TOP102 TOP103 "
    "TOP104 TOP105 TOP106 TOP107 TOP111 TOP112 TOP113 TOP131 TOP136 TOP137 TOP138 TOP139 TOP140 TOP141 "
    "TOP145 TOP146 TOP147 TOP148 TOP149 TOP153 TOP154 TOP155 TOP156 TOP157 TOP158 TOP159 TOP171 TOP172 "
    "TOP173 TOP174 TOP175 TOP176 TOP177 TOP178 TOP180 TOP182 TOP183 TOP184 TOP185 TOP186 TOP187 TOP188 "
    "TOP189 TOP190 TOP191 TOP192 TOP193 TOP195 TOP196 "
    "TOP100 TOP109 TOP110 TOP132 TOP133 TOP150 TOP151 TOP167 TOP168 TOP170 TOP179 TOP181 TOP194".split()
)


# applied to all names: shorter words, consistent case
_SHORTER_WORDS = [
    (re.compile(r"\btemperature\b", re.IGNORECASE), "temp"),
    (re.compile(r"\bmaximum\b", re.IGNORECASE), "max"),
    # sentence case: capitalized words after the first one are written in lower case,
    # abbreviations (DHW, SG, PCB, HEX, Th1, ...) are kept
    (re.compile(r"(?<=\s)([A-Z][a-z]+)\b"), lambda m: m.group(1).lower()),
]


def _display_name(topic_id: Optional[str], name) -> Any:
    if not isinstance(name, str):
        return name
    name = ENTITY_NAMES.get(topic_id) or name.removeprefix("Aquarea ")
    for pattern, replacement in _SHORTER_WORDS:
        name = pattern.sub(replacement, name)
    return name[:1].upper() + name[1:]


def _is_new_topic(topic_id: Optional[str]) -> bool:
    """TOP144-TOP196 and SET49-SET104: enabled once the firmware publishes them."""
    match = re.fullmatch(r"(TOP|SET)(\d+)", topic_id or "")
    if match is None:
        return False
    number = int(match.group(2))
    return 144 <= number <= 196 if match.group(1) == "TOP" else 49 <= number <= 104


def arranged(build: Callable) -> Callable:
    """Apply display names, sub-devices and diagnostic categories to built descriptions."""

    @wraps(build)
    def wrapper(*args, **kwargs):
        result = []
        for description in build(*args, **kwargs):
            topic_id = getattr(description, "heishamon_topic_id", None)
            changes = {}
            if getattr(description, "device", None) != DeviceType.HEISHAMON:
                name = _display_name(topic_id, description.name)
                if name != description.name:
                    changes["name"] = name
            device = SUB_DEVICE_OF_TOPIC.get(topic_id)
            if device is not None and getattr(description, "device", None) == DeviceType.HEATPUMP:
                changes["device"] = device
            if topic_id in DIAGNOSTIC_READBACKS and description.entity_category is None:
                changes["entity_category"] = EntityCategory.DIAGNOSTIC
            if _is_new_topic(topic_id) and not getattr(description, "requires", ()):
                changes["auto_enable"] = True
            result.append(replace(description, **changes) if changes else description)
        return result

    return wrapper
