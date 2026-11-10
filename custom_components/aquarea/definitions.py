"""Definitions for HeishaMon sensors added to MQTT."""

from __future__ import annotations
from functools import partial, wraps
import json
import re
from enum import Flag, auto

from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Optional, TypeVar, Any
import logging

from homeassistant.const import MAJOR_VERSION
from homeassistant.helpers.entity import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.components.button import ButtonEntityDescription, ButtonDeviceClass
from homeassistant.components.switch import SwitchEntityDescription
from homeassistant.components.select import SelectEntityDescription
from homeassistant.components.number import NumberEntityDescription, NumberDeviceClass

from homeassistant.components.sensor import (
    SensorEntity,
    SensorDeviceClass,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntityDescription,
)

from .models import HEATPUMP_MODELS, HEATPUMP_MODELS_39
from .const import DeviceType, Feature
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


class OperatingMode(Flag):
    HEAT = auto()
    COOL = auto()
    DHW = auto()
    AUTO = auto()

    @staticmethod
    def modes_to_str():
        return {
            OperatingMode.HEAT: "Heat only",
            OperatingMode.COOL: "Cool only",
            (OperatingMode.HEAT | OperatingMode.AUTO): "Auto(Heat)",
            OperatingMode.DHW: "DHW only",
            (OperatingMode.HEAT | OperatingMode.DHW): "Heat+DHW",
            (OperatingMode.COOL | OperatingMode.DHW): "Cool+DHW",
            (
                OperatingMode.HEAT | OperatingMode.AUTO | OperatingMode.DHW
            ): "Auto(Heat)+DHW",
            (OperatingMode.COOL | OperatingMode.AUTO): "Auto(Cool)",
            (
                OperatingMode.COOL | OperatingMode.AUTO | OperatingMode.DHW
            ): "Auto(Cool)+DHW",
        }

    def __str__(self) -> str:
        return self.modes_to_str().get(self, f"Unknown mode")

    @staticmethod
    def modes_to_int():
        return {
            OperatingMode.HEAT: 0,
            OperatingMode.COOL: 1,
            (OperatingMode.HEAT | OperatingMode.AUTO): 2,
            OperatingMode.DHW: 3,
            (OperatingMode.HEAT | OperatingMode.DHW): 4,
            (OperatingMode.COOL | OperatingMode.DHW): 5,
            (OperatingMode.HEAT | OperatingMode.AUTO | OperatingMode.DHW): 6,
            (OperatingMode.COOL | OperatingMode.AUTO): 7,
            (OperatingMode.COOL | OperatingMode.AUTO | OperatingMode.DHW): 8,
        }

    def __int__(self) -> int:
        mode_mapping = self.modes_to_int()
        if self not in mode_mapping:
            raise ValueError(
                f"Invalid operating mode {self} (value: {self.value}). "
                f"Cannot convert to MQTT value. This may indicate an empty/uninitialized mode."
            )
        return mode_mapping[self]

    @staticmethod
    def from_str(str_repr: str) -> OperatingMode:
        operating_mode = lookup_by_value(OperatingMode.modes_to_str(), str_repr)
        if operating_mode is None:
            raise Exception(
                f"Unable to find the operating mode corresponding to {str_repr}"
            )
        return operating_mode

    @staticmethod
    def from_mqtt(value: str) -> OperatingMode:
        operating_mode = lookup_by_value(OperatingMode.modes_to_int(), int(value))
        if operating_mode is None:
            raise Exception(
                f"Unable to find the operating mode corresponding to {value}"
            )
        return operating_mode

    def to_mqtt(self) -> str:
        # heishamon reports Auto as 7/8 (TOP4) while cooling but only accepts 0-6
        # to set it (SET9): Auto is 2 and Auto+DHW is 6 whatever the current state
        value = int(self)
        return str({7: 2, 8: 6}.get(value, value))


def convert_pressure_to_kPa(str_repr: str) -> float:
    return float(str_repr) * 98.0665


def operating_mode_to_state(str_repr: str):
    return OperatingMode.from_str(str_repr).to_mqtt()


def read_enabled_disabled(value: str) -> Optional[bool]:
    if value == "1":
        return True
    if value == "0":
        return False
    return None


def read_bivalent_mode(value: str) -> Optional[str]:
    return BIVALENT_MODES.get(value, None)


BIVALENT_MODES = {
    "0": "Alternative",
    "1": "Parallel",
    "2": "Advanced Parallel",
}


def bivalent_mode_to_mqtt(value: str) -> Optional[str]:
    return lookup_by_value(BIVALENT_MODES, value)


def read_operating_mode_state(value: str) -> str:
    mode = OperatingMode.from_mqtt(value)
    return str(mode)


PUMP_FLOWRATE_MODE = {
    "0": "DeltaT",
    "1": "Maximum flow",
}


def read_pump_flowrate_mode(value: str) -> Optional[str]:
    return PUMP_FLOWRATE_MODE.get(value, None)

def pump_flowrate_mode_to_mqtt(value: str) -> Optional[str]:
    return lookup_by_value(PUMP_FLOWRATE_MODE, value)


def read_liquid_type(value: str) -> Optional[str]:
    if value == "0":
        return "Water"
    if value == "1":
        return "Glycol"
    if value == "-1":
        return None
    _LOGGER.warning(f"Unknown liquid type '{value}', open ticket to maintainer")
    return None


def read_zone_sensor_type(value: str) -> Optional[str]:
    if value == "0":
        return "Water Temperature"
    if value == "1":
        return "External Thermostat"
    if value == "2":
        return "Internal Thermostat"
    if value == "3":
        return "Thermistor"
    if value == "-1":
        return None
    _LOGGER.warning(
        f"Unknown zone sensor type '{value}', please open ticket to maintainer"
    )
    return None


EXTERNAL_PAD_HEATER_TYPE = {
    "0": "Disabled",
    "1": "type-A",
    "2": "type-B",
}


def read_external_pad_heater_enabled(value: str) -> Optional[str]:
    return EXTERNAL_PAD_HEATER_TYPE.get(
        value, f"Unknown pad heater type value: {value}"
    )


def external_pad_heater_type_to_mqtt(value: str) -> Optional[str]:
    return lookup_by_value(EXTERNAL_PAD_HEATER_TYPE, value)


def read_mixing_valve_request(value: str) -> Optional[str]:
    if value == "0":
        return "Off"
    if value == "1":
        return "Decrease"
    if value == "2":
        return "Increase"
    if value == "-1":
        return None
    _LOGGER.warning(
        f"Unknown mixing valve request '{value}', please open ticket to maintainer"
    )
    return None


ZONE_STATES_STRING = {
    "0": "Zone 1",
    "1": "Zone 2",
    "2": "Zones 1 + 2",
}


SMART_GRID_MODES_STRING = {
    "0": "Normal",
    "1": "Capacity 1",
    "2": "HP/DHW off",
    "3": "Capacity 2",
}


def read_zones_state(value):
    return ZONE_STATES_STRING.get(value, f"Unknown zone state value: {value}")


def zone_state_to_mqtt(value: str) -> Optional[str]:
    return lookup_by_value(ZONE_STATES_STRING, value)


POWERFUL_MODE_TIMES = {"0": "Off", "1": "30 min", "2": "60 min", "3": "90 min"}


def read_power_mode_time(value):
    return POWERFUL_MODE_TIMES.get(value, f"Unknown powerful mode: {value}")


def set_power_mode_time(value: str):
    return lookup_by_value(POWERFUL_MODE_TIMES, value)


Key = TypeVar("Key")
Value = TypeVar("Value")


def lookup_by_value(hash: dict[Key, Value], value: Value) -> Optional[Key]:
    options = [key for (key, v) in hash.items() if v == value]
    if len(options) == 0:
        return None
    return options[0]


def read_threeway_valve(value: str) -> Optional[str]:
    if value == "0":
        return "Room"
    elif value == "1":
        return "Tank"
    else:
        _LOGGER.info(f"Reading unhandled value for ThreeWay Valve state: '{value}'")
        return None


def read_twoway_valve(value: str) -> Optional[str]:
    if value == "0":
        return "Cooling"
    elif value == "1":
        return "Heating"
    else:
        _LOGGER.info(f"Reading unhandled value for TwoWay Valve state: '{value}'")
        return None


def first_positive(values) -> Optional[int]:
    for v in values:
        if v is not None and v >= 0:
            return int(v)
    return None


# TODO(kamaradclimber): this decorator can be simply replaced by @dataclass(frozen=True, kw_only=True) when we stop supporting HA < 2024.1
def frozendataclass(cls):
    def wrapper_dataclass(cls):
        if MAJOR_VERSION > 2023:
            return dataclass(cls, frozen=True, kw_only=True)
        else:
            return dataclass(cls)

    if cls is None:
        # we are called with parens
        return wrapper_dataclass

    # we are called without parens
    return wrapper_dataclass(cls)


@frozendataclass
class HeishaMonEntityDescription:
    heishamon_topic_id: str | None = None

    # a method called when receiving a new value
    state: Callable | None = None

    # device sensor belong to
    device: DeviceType = DeviceType.HEATPUMP

    # a method called when receiving a new value. With a lot of context. Used to update device info for instance
    on_receive: Callable | None = None

    # installation features this entity belongs to. Such an entity is enabled once
    # the heat pump reports all of them, see features.py
    requires: tuple[Feature, ...] = ()

    # topic (without prefix) only published by firmwares knowing this entity,
    # when its own topic is older than the entity
    firmware_marker: str | None = None

    # entity created disabled, enabled once HeishaMon has published its topic
    # (and firmware_marker), so that it stays hidden on firmwares without it
    auto_enable: bool = False


@frozendataclass
class HeishaMonSensorEntityDescription(
    HeishaMonEntityDescription, SensorEntityDescription
):
    """Sensor entity description for HeishaMon."""

    pass


@frozendataclass
class MultiMQTTSensorEntityDescription(SensorEntityDescription):
    topics: list[str] | None = None
    # this callable will receive a list with as many entries as topics
    # values in that list will be in the same order as the topics key.
    # For instance, if topics are ["a", "b", "c"], state will receive a list with
    # 3 items, whose values will be the last received value from the topics a, b and c.
    # values will be None when we have not received any value for the corresponding topic yet.
    compute_state: Callable | None = None

    # one of unique_id and heishamon_topic_id must be defined
    unique_id: Optional[str] = None
    heishamon_topic_id: Optional[str] = None


@frozendataclass
class HeishaMonSwitchEntityDescription(
    HeishaMonEntityDescription, SwitchEntityDescription
):
    """Switch entity description for HeishaMon."""

    command_topic: str = "void/topic"
    qos: int = 0
    payload_on: str = "1"
    payload_off: str = "0"
    retain: bool = False
    encoding: str = "utf-8"
    # device class used by the readonly binary sensor mirroring this switch.
    # SwitchEntityDescription.device_class only supports SwitchDeviceClass.
    binary_sensor_device_class: Optional[BinarySensorDeviceClass] = None


@frozendataclass
class HeishaMonButtonEntityDescription(
    HeishaMonEntityDescription, ButtonEntityDescription
):
    """Button entity description for HeishaMon."""

    command_topic: str = "void/topic"
    qos: int = 0
    retain: bool = False
    encoding: str = "utf-8"
    payload: str = "1"


@frozendataclass
class HeishaMonBinarySensorEntityDescription(
    HeishaMonEntityDescription, BinarySensorEntityDescription
):
    """Binary sensor entity description for HeishaMon."""

    pass


@frozendataclass
class HeishaMonSelectEntityDescription(
    HeishaMonEntityDescription, SelectEntityDescription
):
    """Select entity description for HeishaMon"""

    command_topic: str = "void/topic"
    retain: bool = False
    encoding: str = "utf-8"
    qos: int = 0
    # function to transform selected option in value sent via mqtt
    state_to_mqtt: Optional[Callable] = None


@frozendataclass
class HeishaMonNumberEntityDescription(
    HeishaMonEntityDescription, NumberEntityDescription
):
    """Number entity description for HeishaMon"""

    command_topic: str = "void/topic"
    retain: bool = False
    encoding: str = "utf-8"
    qos: int = 0
    # function to transform selected option in value sent via mqtt
    state_to_mqtt: Optional[Callable] = None

    # Initial value to set waiting for the first message from MQTT
    # if let empty, no value will be set until first message
    initial_value: Optional[Any] = None


def positive_to_bool(value: str) -> bool:
    return int(value) > 0


def bit_to_bool(value: str) -> Optional[bool]:
    if value == "1":
        return True
    elif value == "0":
        return False
    else:
        return None

def relay_to_bool(value: str) -> Optional[bool]:
    if value in ["1", "on", "enable", "true"]:
        return True
    elif value in ["0", "off", "disable", "false"]:
        return False
    return None


def read_demandcontrol(value: str) -> Optional[int]:
    i = float(value)
    if i >= 43 and i <= 234:
        i = (i - 43) / (234 - 43)
        return round(i * 95) + 5
    return None


def write_demandcontrol(value: int) -> str:
    value = (value - 5) / 95  # 5% -> 100% to 0% -> 95% for remapping
    return str(int(value * (234 - 43) + 43))


def read_smart_grid_mode(value: str) -> str:
    return SMART_GRID_MODES_STRING.get(value, f"Unknown smart grid mode: {value}")


def write_smart_grid_mode(value: str) -> str:
    return lookup_by_value(SMART_GRID_MODES_STRING, value)


def read_quiet_mode(value: str) -> str:
    # values range from 0 to 4
    if value == "4":
        return "Scheduled"
    elif value == "0":
        return "Off"
    return value


def read_heatpump_model(value: str) -> str:
    if len(value) < 8:
        # heishamon < 3.9
        return HEATPUMP_MODELS.get(value, "Unknown model for HeishaMon")
    return HEATPUMP_MODELS_39.get(value, "Unknown model for HeishaMon")


def read_solar_mode(value: str) -> str:
    return {"0": "Disabled", "1": "Buffer", "2": "DHW"}.get(
        value, f"Unknown solar mode: {value}"
    )


def write_quiet_mode(selected_value: str):
    if selected_value == "Off":
        return 0
    elif selected_value == "Scheduled":
        return 4
    else:
        return int(selected_value)


def guess_shift_or_direct_and_clamp_min_max_values(
    range1,
    range2,
    hass: HomeAssistant,
    entity: SensorEntity,
    config_entry_id: str,
    native_value: int,
):
    """
    This method clamp min/max values based on the current value.
    It relies on the fact that range1 and range2 are not intersecting.
    ^^^ is false because Cool mode value '5' can mean +5 or 5°.
    """
    # FIXME: we assume entity is of type HeishMonNumberEntity. We should find a way to properly use the type system
    if native_value in range1:  # we always favor range1
        entity.set_range(min(range1), max(range1))
    elif native_value in range2:
        entity.set_range(min(range2), max(range2))
    else:
        _LOGGER.warn(
            f"Received value {native_value} for {entity.entity_description.name}. Impossible to know if we are using 'shift' mode or 'direct' mode, ignoring"
        )


PARITY_DHW_CAPACITY_MODE = {
    "0": "Standard",
    "1": "Variable",
}


def read_parity_dhw_capacity_mode(value: str) -> Optional[str]:
    return PARITY_DHW_CAPACITY_MODE.get(value, None)


def parity_dhw_capacity_mode_to_mqtt(value: str) -> Optional[str]:
    return lookup_by_value(PARITY_DHW_CAPACITY_MODE, value)


PARITY_ZONE_CONFIGURATION = {
    "21": "One zone, zone 1 room",
    "25": "One zone, zone 1 pool",
    "22": "Two zones, zone 2 room",
    "38": "Two zones, zone 2 pool",
}


def read_parity_zone_configuration(value: str) -> Optional[str]:
    return PARITY_ZONE_CONFIGURATION.get(value, None)


def parity_zone_configuration_to_mqtt(value: str) -> Optional[str]:
    return lookup_by_value(PARITY_ZONE_CONFIGURATION, value)


PARITY_DHW_HEATER_TYPE = {
    "0": "Internal",
    "1": "External",
}


def read_parity_dhw_heater_type(value: str) -> Optional[str]:
    return PARITY_DHW_HEATER_TYPE.get(value, None)


def parity_dhw_heater_type_to_mqtt(value: str) -> Optional[str]:
    return lookup_by_value(PARITY_DHW_HEATER_TYPE, value)


PARITY_SG_READY_CONTROL = {
    "0": "Disabled",
    "1": "Capacity",
    "2": "Power consumption",
}


def read_parity_sg_ready_control(value: str) -> Optional[str]:
    return PARITY_SG_READY_CONTROL.get(value, None)


def parity_sg_ready_control_to_mqtt(value: str) -> Optional[str]:
    return lookup_by_value(PARITY_SG_READY_CONTROL, value)


PARITY_HEAT_COOL_SWITCH = {
    "0": "Heat",
    "1": "Cool",
}


def read_parity_heat_cool_switch(value: str) -> Optional[str]:
    return PARITY_HEAT_COOL_SWITCH.get(value, None)


def parity_heat_cool_switch_to_mqtt(value: str) -> Optional[str]:
    return lookup_by_value(PARITY_HEAT_COOL_SWITCH, value)


PARITY_EXTERNAL_SWITCH = {
    "0": "Closed",
    "1": "Open",
}


def read_parity_external_switch(value: str) -> Optional[str]:
    return PARITY_EXTERNAL_SWITCH.get(value, None)


def parity_external_switch_to_mqtt(value: str) -> Optional[str]:
    return lookup_by_value(PARITY_EXTERNAL_SWITCH, value)


PARITY_BIVALENT_OPERATING_MODE = {
    "0": "Auto",
    "1": "SG ready",
    "2": "Intelligent",
}


def read_parity_bivalent_operating_mode(value: str) -> Optional[str]:
    return PARITY_BIVALENT_OPERATING_MODE.get(value, None)


def parity_bivalent_operating_mode_to_mqtt(value: str) -> Optional[str]:
    return lookup_by_value(PARITY_BIVALENT_OPERATING_MODE, value)


PARITY_EXTRA_PUMP_USE = {
    "0": "Not used",
    "1": "Heating",
    "2": "DHW",
}


def read_parity_extra_pump_use(value: str) -> Optional[str]:
    return PARITY_EXTRA_PUMP_USE.get(value, None)


def parity_extra_pump_use_to_mqtt(value: str) -> Optional[str]:
    return lookup_by_value(PARITY_EXTRA_PUMP_USE, value)


PARITY_EXTRA_PUMP_MODE = {
    "0": "Comfort",
    "1": "Efficiency",
}


def read_parity_extra_pump_mode(value: str) -> Optional[str]:
    return PARITY_EXTRA_PUMP_MODE.get(value, None)


def parity_extra_pump_mode_to_mqtt(value: str) -> Optional[str]:
    return lookup_by_value(PARITY_EXTRA_PUMP_MODE, value)


PARITY_INTERNAL_HEATER_CAPACITY = {
    "3": "3 kW",
    "6": "6 kW",
    "9": "9 kW",
}


def read_parity_internal_heater_capacity(value: str) -> Optional[str]:
    return PARITY_INTERNAL_HEATER_CAPACITY.get(value, None)


def parity_internal_heater_capacity_to_mqtt(value: str) -> Optional[str]:
    return lookup_by_value(PARITY_INTERNAL_HEATER_CAPACITY, value)


PARITY_ZONE_TYPE = {
    "21": "Room",
    "25": "Pool",
}


def read_parity_zone_type(value: str) -> Optional[str]:
    return PARITY_ZONE_TYPE.get(value, None)


def parity_zone_type_to_mqtt(value: str) -> Optional[str]:
    return lookup_by_value(PARITY_ZONE_TYPE, value)


PARITY_WATER_TEMPERATURE_MODE = {
    "0": "Compensation curve",
    "1": "Direct",
}


def read_parity_water_temperature_mode(value: str) -> Optional[str]:
    return PARITY_WATER_TEMPERATURE_MODE.get(value, None)


def parity_water_temperature_mode_to_mqtt(value: str) -> Optional[str]:
    return lookup_by_value(PARITY_WATER_TEMPERATURE_MODE, value)


PARITY_LIQUID_TYPE = {
    "0": "Water",
    "1": "Glycol",
}


def read_parity_liquid_type(value: str) -> Optional[str]:
    return PARITY_LIQUID_TYPE.get(value, None)


def parity_liquid_type_to_mqtt(value: str) -> Optional[str]:
    return lookup_by_value(PARITY_LIQUID_TYPE, value)


PARITY_SOLAR_MODE = {
    "0": "Disabled",
    "1": "Buffer",
    "2": "DHW",
}


def read_parity_solar_mode(value: str) -> Optional[str]:
    return PARITY_SOLAR_MODE.get(value, None)


def parity_solar_mode_to_mqtt(value: str) -> Optional[str]:
    return lookup_by_value(PARITY_SOLAR_MODE, value)


PARITY_ZONE_SENSOR_TYPE = {
    "0": "Water Temperature",
    "1": "External Thermostat",
    "2": "Internal Thermostat",
    "3": "Thermistor",
}


def read_parity_zone_sensor_type(value: str) -> Optional[str]:
    return PARITY_ZONE_SENSOR_TYPE.get(value, None)


def parity_zone_sensor_type_to_mqtt(value: str) -> Optional[str]:
    return lookup_by_value(PARITY_ZONE_SENSOR_TYPE, value)


def zone_type_to_mqtt(value: str) -> Optional[str]:
    """SetZoneType takes 0 (room) or 1 (pool), Zone_Configuration reports 21 or 25."""
    return {"Room": "0", "Pool": "1"}.get(value, None)


def read_optional_int(value: str) -> Optional[int]:
    """Read an integer topic reporting -1 when the heat pump has no value."""
    number = int(float(value))
    return None if number == -1 else number


def one_decimal_to_mqtt(value: float) -> str:
    return f"{float(value):.1f}"


def integer_to_mqtt(value: float) -> str:
    return str(int(round(float(value))))


def build_numbers(mqtt_prefix: str) -> list[HeishaMonNumberEntityDescription]:
    numbers = [
        HeishaMonNumberEntityDescription(
            heishamon_topic_id="SET5",  # also TOP27
            key=f"{mqtt_prefix}main/Z1_Heat_Request_Temp",
            command_topic=f"{mqtt_prefix}commands/SetZ1HeatRequestTemperature",
            # it can be relative (-5 -> +5, or absolute [20, ..[)
            name="Aquarea Zone 1 Heat Requested shift",
            entity_category=EntityCategory.CONFIG,
            device_class=NumberDeviceClass.TEMPERATURE,
            native_unit_of_measurement="°C",
            native_min_value=-5,
            native_max_value=20,
            state=int,
            state_to_mqtt=int,
            on_receive=partial(
                guess_shift_or_direct_and_clamp_min_max_values,
                range(-5, 6),
                range(7, 61),
            ),
        ),
        HeishaMonNumberEntityDescription(
            heishamon_topic_id="SET6",  # also TOP28
            requires=(Feature.COOLING,),
            key=f"{mqtt_prefix}main/Z1_Cool_Request_Temp",
            command_topic=f"{mqtt_prefix}commands/SetZ1CoolRequestTemperature",
            # it can be relative (-5 -> +5, or absolute [20, ..[)
            name="Aquarea Zone 1 Cool Requested shift",
            entity_category=EntityCategory.CONFIG,
            device_class=NumberDeviceClass.TEMPERATURE,
            native_unit_of_measurement="°C",
            native_min_value=-5,
            native_max_value=25,
            state=int,
            state_to_mqtt=int,
            on_receive=partial(
                guess_shift_or_direct_and_clamp_min_max_values,
                range(-5, 6),
                range(5, 36),
            ),
            entity_registry_enabled_default=False,  # by default we hide all options related to less common setup (cooling, buffer, solar and pool)
        ),
        HeishaMonNumberEntityDescription(
            heishamon_topic_id="SET7",  # also TOP34
            key=f"{mqtt_prefix}main/Z2_Heat_Request_Temp",
            command_topic=f"{mqtt_prefix}commands/SetZ2HeatRequestTemperature",
            # it can be relative (-5 -> +5, or absolute [20, ..[)
            name="Aquarea Zone 2 Heat Requested shift",
            entity_category=EntityCategory.CONFIG,
            device_class=NumberDeviceClass.TEMPERATURE,
            native_unit_of_measurement="°C",
            native_min_value=-5,
            native_max_value=20,
            state=int,
            state_to_mqtt=int,
            on_receive=partial(
                guess_shift_or_direct_and_clamp_min_max_values,
                range(-5, 6),
                range(7, 45),
            ),
        ),
        HeishaMonNumberEntityDescription(
            heishamon_topic_id="SET8",  # also TOP35
            key=f"{mqtt_prefix}main/Z2_Cool_Request_Temp",
            command_topic=f"{mqtt_prefix}commands/SetZ2CoolRequestTemperature",
            # it can be relative (-5 -> +5, or absolute [20, ..[)
            name="Aquarea Zone 2 Cool Requested shift",
            entity_category=EntityCategory.CONFIG,
            device_class=NumberDeviceClass.TEMPERATURE,
            native_unit_of_measurement="°C",
            native_min_value=-5,
            native_max_value=25,
            state=int,
            state_to_mqtt=int,
            on_receive=partial(
                guess_shift_or_direct_and_clamp_min_max_values,
                range(-5, 6),
                range(5, 36),
            ),
            entity_registry_enabled_default=False,  # by default we hide all options related to less common setup (cooling, buffer, solar and pool)
        ),
        HeishaMonNumberEntityDescription(
            heishamon_topic_id="SET11",  # TOP9
            requires=(Feature.DHW,),
            key=f"{mqtt_prefix}main/DHW_Target_Temp",
            command_topic=f"{mqtt_prefix}commands/SetDHWTemp",
            name="DHW Target Temperature",
            entity_category=EntityCategory.CONFIG,
            device_class=NumberDeviceClass.TEMPERATURE,
            native_unit_of_measurement="°C",
            native_min_value=40,
            native_max_value=65,
            state=int,
            state_to_mqtt=int,
        ),
        HeishaMonNumberEntityDescription(
            heishamon_topic_id="SET15",  # also TOP95
            key=f"{mqtt_prefix}main/Max_Pump_Duty",
            command_topic=f"{mqtt_prefix}commands/SetMaxPumpDuty",
            name="Aquarea Max pump duty configured",
            entity_category=EntityCategory.CONFIG,
            native_unit_of_measurement="Count",
            native_min_value=64,
            native_max_value=254,
            state=int,
            state_to_mqtt=int,
        ),
        HeishaMonNumberEntityDescription(
            heishamon_topic_id="SET18",  # also corresponds to TOP23
            key=f"{mqtt_prefix}main/Heat_Delta",
            command_topic=f"{mqtt_prefix}commands/SetFloorHeatDelta",
            name="Aquarea Room heating delta",
            entity_category=EntityCategory.CONFIG,
            device_class=NumberDeviceClass.TEMPERATURE_DELTA,
            native_unit_of_measurement="K",
            native_min_value=1,
            native_max_value=15,
            state=int,
            state_to_mqtt=int,
        ),
        HeishaMonNumberEntityDescription(
            heishamon_topic_id="SET19",  # also corresponds to TOP24
            requires=(Feature.COOLING,),
            key=f"{mqtt_prefix}main/Cool_Delta",
            command_topic=f"{mqtt_prefix}commands/SetFloorCoolDelta",
            name="Aquarea Room Cooling delta",
            entity_category=EntityCategory.CONFIG,
            device_class=NumberDeviceClass.TEMPERATURE_DELTA,
            native_unit_of_measurement="K",
            native_min_value=1,
            native_max_value=15,
            state=int,
            state_to_mqtt=int,
            entity_registry_enabled_default=False,  # by default we hide all options related to less common setup (cooling, buffer, solar and pool)
        ),
        HeishaMonNumberEntityDescription(
            heishamon_topic_id="SET20",  # also corresponds to TOP22
            requires=(Feature.DHW,),
            key=f"{mqtt_prefix}main/DHW_Heat_Delta",
            command_topic=f"{mqtt_prefix}commands/SetDHWHeatDelta",
            name="Aquarea DHW heating delta",
            entity_category=EntityCategory.CONFIG,
            device_class=NumberDeviceClass.TEMPERATURE_DELTA,
            native_unit_of_measurement="K",
            native_min_value=-12,
            native_max_value=-2,
            state=int,
            state_to_mqtt=int,
        ),
        HeishaMonNumberEntityDescription(
            heishamon_topic_id="SET21",  # also corresponds to TOP96
            key=f"{mqtt_prefix}main/Heater_Delay_Time",
            command_topic=f"{mqtt_prefix}commands/SetHeaterDelayTime",
            name="Aquarea Heater delay time",
            entity_category=EntityCategory.CONFIG,
            device_class=NumberDeviceClass.DURATION,
            native_unit_of_measurement="min",
            native_min_value=10,
            native_max_value=60,
            state=int,
            state_to_mqtt=int,
            entity_registry_enabled_default=False,  # by default we hide all options related to less common setup (cooling, buffer, solar and pool)
        ),
        HeishaMonNumberEntityDescription(
            heishamon_topic_id="SET22",  # also corresponds to TOP97
            key=f"{mqtt_prefix}main/Heater_Start_Delta",
            command_topic=f"{mqtt_prefix}commands/SetHeaterStartDelta",
            name="Aquarea Heater start delta",
            entity_category=EntityCategory.CONFIG,
            device_class=NumberDeviceClass.TEMPERATURE_DELTA,
            native_unit_of_measurement="K",
            native_min_value=-10,
            native_max_value=-2,
            state=int,
            state_to_mqtt=int,
            entity_registry_enabled_default=False,  # by default we hide all options related to less common setup (cooling, buffer, solar and pool)
        ),
        HeishaMonNumberEntityDescription(
            heishamon_topic_id="SET23",  # also corresponds to TOP98
            key=f"{mqtt_prefix}main/Heater_Stop_Delta",
            command_topic=f"{mqtt_prefix}commands/SetHeaterStopDelta",
            name="Aquarea Heater stop delta",
            entity_category=EntityCategory.CONFIG,
            device_class=NumberDeviceClass.TEMPERATURE_DELTA,
            native_unit_of_measurement="K",
            native_min_value=-8,
            native_max_value=0,
            state=int,
            state_to_mqtt=int,
            entity_registry_enabled_default=False,  # by default we hide all options related to less common setup (cooling, buffer, solar and pool)
        ),
        HeishaMonNumberEntityDescription(
            heishamon_topic_id="SET27",  # also corresponds to TOP113
            requires=(Feature.BUFFER,),
            key=f"{mqtt_prefix}main/Buffer_Tank_Delta",
            command_topic=f"{mqtt_prefix}commands/SetBufferDelta",
            name="Aquarea Buffer tank delta",
            entity_category=EntityCategory.CONFIG,
            device_class=NumberDeviceClass.TEMPERATURE_DELTA,
            native_unit_of_measurement="K",
            native_min_value=0,
            native_max_value=10,
            state=int,
            state_to_mqtt=int,
            entity_registry_enabled_default=False,  # by default we hide all options related to less common setup (cooling, buffer, solar and pool)
        ),
        HeishaMonNumberEntityDescription(
            heishamon_topic_id="SET29",  # also corresponds to TOP77
            key=f"{mqtt_prefix}main/Heating_Off_Outdoor_Temp",
            command_topic=f"{mqtt_prefix}commands/SetHeatingOffOutdoorTemp",
            name="Aquarea Outdoor temperature heating cutoff",
            entity_category=EntityCategory.CONFIG,
            device_class=NumberDeviceClass.TEMPERATURE,
            native_unit_of_measurement="°C",
            native_min_value=5,
            native_max_value=35,
            state=int,
            state_to_mqtt=int,
        ),
        HeishaMonNumberEntityDescription(
            heishamon_topic_id="SET46",  # corresponds to TOP78
            key=f"{mqtt_prefix}main/Heater_On_Outdoor_Temp",
            command_topic=f"{mqtt_prefix}commands/SetHeaterOnOutdoorTemp",
            name="Aquarea Outdoor temperature backup heater power on",
            entity_category=EntityCategory.CONFIG,
            device_class=NumberDeviceClass.TEMPERATURE,
            native_unit_of_measurement="°C",
            native_min_value=-15,
            native_max_value=20,
            native_step=1,
            state=int,
            state_to_mqtt=int,
        ),
        HeishaMonNumberEntityDescription(
            heishamon_topic_id="SetDemandControl",
            key=f"{mqtt_prefix}commands/SetDemandControl",
            command_topic=f"{mqtt_prefix}commands/SetDemandControl",
            retain=True,
            name="Demand Control",
            entity_category=EntityCategory.CONFIG,
            native_unit_of_measurement="%",
            native_min_value=5,
            native_max_value=100,
            native_step=5,
            state=read_demandcontrol,
            state_to_mqtt=write_demandcontrol,
            entity_registry_enabled_default=False,  # comes from the optional PCB: disabled by default
            initial_value=100,
        ),
        HeishaMonNumberEntityDescription(
            heishamon_topic_id="SET36",  # corresponds to TOP131
            requires=(Feature.BIVALENT,),
            key=f"{mqtt_prefix}main/Bivalent_Start_Temp",
            command_topic=f"{mqtt_prefix}commands/SetBivalentStartTemp",
            retain=True,
            name="Aquarea Bivalent Start Temp",
            entity_category=EntityCategory.CONFIG,
            device_class=NumberDeviceClass.TEMPERATURE,
            native_unit_of_measurement="°C",
            native_min_value=-15,
            native_max_value=35,
            native_step=1,
            state=int,
            state_to_mqtt=int,
            entity_registry_enabled_default=True,
            initial_value=0,
        ),
        HeishaMonNumberEntityDescription(
            heishamon_topic_id="SET37",  # corresponds to TOP134
            requires=(Feature.BIVALENT,),
            key=f"{mqtt_prefix}main/Bivalent_Advanced_Start_Temp",
            command_topic=f"{mqtt_prefix}commands/SetBivalentAPStartTemp",
            name="Aquarea Bivalent Advanced Start Temp",
            entity_category=EntityCategory.CONFIG,
            device_class=NumberDeviceClass.TEMPERATURE,
            native_unit_of_measurement="°C",
            native_min_value=-15,
            native_max_value=35,
            native_step=1,
            state=int,
            state_to_mqtt=int,
            entity_registry_enabled_default=True,
            initial_value=0,
        ),
        HeishaMonNumberEntityDescription(
            heishamon_topic_id="SET38",  # corresponds to TOP135
            requires=(Feature.BIVALENT,),
            key=f"{mqtt_prefix}main/Bivalent_Advanced_Stop_Temp",
            command_topic=f"{mqtt_prefix}commands/SetBivalentAPStopTemp",
            name="Aquarea Bivalent Advanced Stop Temp",
            entity_category=EntityCategory.CONFIG,
            device_class=NumberDeviceClass.TEMPERATURE,
            native_unit_of_measurement="°C",
            native_min_value=-15,
            native_max_value=35,
            native_step=1,
            state=int,
            state_to_mqtt=int,
            entity_registry_enabled_default=True,
            initial_value=0,
        ),
        HeishaMonNumberEntityDescription(
            heishamon_topic_id="SET49",
            key=f"{mqtt_prefix}main/Sterilization_Temp",
            command_topic=f"{mqtt_prefix}commands/SetSterilizationTemp",
            name="Aquarea Sterilization temperature",
            entity_category=EntityCategory.CONFIG,
            device_class=NumberDeviceClass.TEMPERATURE,
            native_unit_of_measurement="°C",
            native_min_value=55,
            native_max_value=75,
            native_step=1,
            state=float,
            state_to_mqtt=integer_to_mqtt,
            requires=(Feature.DHW,),
            firmware_marker="main/DHW_Heatup_Max_Time",
            entity_registry_enabled_default=False,
        ),
        HeishaMonNumberEntityDescription(
            heishamon_topic_id="SET50",
            key=f"{mqtt_prefix}main/Sterilization_Max_Time",
            command_topic=f"{mqtt_prefix}commands/SetSterilizationMaxTime",
            name="Aquarea Sterilization maximum time",
            entity_category=EntityCategory.CONFIG,
            device_class=NumberDeviceClass.DURATION,
            native_unit_of_measurement="min",
            native_min_value=5,
            native_max_value=60,
            native_step=5,
            state=float,
            state_to_mqtt=integer_to_mqtt,
            requires=(Feature.DHW,),
            firmware_marker="main/DHW_Heatup_Max_Time",
            entity_registry_enabled_default=False,
        ),
        HeishaMonNumberEntityDescription(
            heishamon_topic_id="SET51",
            key=f"{mqtt_prefix}main/Heat_To_Cool_Temp",
            command_topic=f"{mqtt_prefix}commands/SetHeatToCoolTemp",
            name="Aquarea Outdoor temperature heat to cool",
            entity_category=EntityCategory.CONFIG,
            device_class=NumberDeviceClass.TEMPERATURE,
            native_unit_of_measurement="°C",
            native_min_value=-127,
            native_max_value=127,
            native_step=1,
            state=float,
            state_to_mqtt=integer_to_mqtt,
            requires=(Feature.COOLING,),
            firmware_marker="main/DHW_Heatup_Max_Time",
            entity_registry_enabled_default=False,
        ),
        HeishaMonNumberEntityDescription(
            heishamon_topic_id="SET52",
            key=f"{mqtt_prefix}main/Cool_To_Heat_Temp",
            command_topic=f"{mqtt_prefix}commands/SetCoolToHeatTemp",
            name="Aquarea Outdoor temperature cool to heat",
            entity_category=EntityCategory.CONFIG,
            device_class=NumberDeviceClass.TEMPERATURE,
            native_unit_of_measurement="°C",
            native_min_value=-127,
            native_max_value=127,
            native_step=1,
            state=float,
            state_to_mqtt=integer_to_mqtt,
            requires=(Feature.COOLING,),
            firmware_marker="main/DHW_Heatup_Max_Time",
            entity_registry_enabled_default=False,
        ),
        HeishaMonNumberEntityDescription(
            heishamon_topic_id="SET53",
            key=f"{mqtt_prefix}main/Room_Operation_Max_Time",
            command_topic=f"{mqtt_prefix}commands/SetRoomOperationMaxTime",
            name="Aquarea Room operation maximum time",
            entity_category=EntityCategory.CONFIG,
            device_class=NumberDeviceClass.DURATION,
            native_unit_of_measurement="min",
            native_min_value=30,
            native_max_value=7620,
            native_step=30,
            state=float,
            state_to_mqtt=integer_to_mqtt,
            requires=(Feature.DHW,),
            entity_registry_enabled_default=False,
        ),
        HeishaMonNumberEntityDescription(
            heishamon_topic_id="SET54",
            key=f"{mqtt_prefix}main/DHW_Heatup_Max_Time",
            command_topic=f"{mqtt_prefix}commands/SetDHWHeatupMaxTime",
            name="Aquarea DHW heat-up maximum time",
            entity_category=EntityCategory.CONFIG,
            device_class=NumberDeviceClass.DURATION,
            native_unit_of_measurement="min",
            native_min_value=1,
            native_max_value=254,
            native_step=1,
            state=float,
            state_to_mqtt=integer_to_mqtt,
            requires=(Feature.DHW,),
            entity_registry_enabled_default=False,
        ),
        HeishaMonNumberEntityDescription(
            heishamon_topic_id="SET57",
            key=f"{mqtt_prefix}main/Pool_Delta",
            command_topic=f"{mqtt_prefix}commands/SetPoolDelta",
            name="Aquarea Pool delta",
            entity_category=EntityCategory.CONFIG,
            native_unit_of_measurement="K",
            native_min_value=0,
            native_max_value=10,
            native_step=1,
            state=float,
            state_to_mqtt=integer_to_mqtt,
            firmware_marker="main/Static_Pressure",
            entity_registry_enabled_default=False,
        ),
        HeishaMonNumberEntityDescription(
            heishamon_topic_id="SET61",
            key=f"{mqtt_prefix}main/Heating_On_Outdoor_Temp",
            command_topic=f"{mqtt_prefix}commands/SetHeatingOnOutdoorTemp",
            name="Aquarea Outdoor temperature heating on",
            entity_category=EntityCategory.CONFIG,
            device_class=NumberDeviceClass.TEMPERATURE,
            native_unit_of_measurement="°C",
            native_min_value=5,
            native_max_value=34,
            native_step=1,
            state=float,
            state_to_mqtt=integer_to_mqtt,
            firmware_marker="main/Static_Pressure",
            entity_registry_enabled_default=False,
        ),
        HeishaMonNumberEntityDescription(
            heishamon_topic_id="SET62",
            key=f"{mqtt_prefix}main/Heating_On_Delay",
            command_topic=f"{mqtt_prefix}commands/SetHeatingOnDelay",
            name="Aquarea Heating on delay",
            entity_category=EntityCategory.CONFIG,
            device_class=NumberDeviceClass.DURATION,
            native_unit_of_measurement="min",
            native_min_value=30,
            native_max_value=1440,
            native_step=30,
            state=float,
            state_to_mqtt=integer_to_mqtt,
            firmware_marker="main/Static_Pressure",
            entity_registry_enabled_default=False,
        ),
        HeishaMonNumberEntityDescription(
            heishamon_topic_id="SET63",
            key=f"{mqtt_prefix}main/DHW_Booster_Delay",
            command_topic=f"{mqtt_prefix}commands/SetDHWBoosterDelay",
            name="Aquarea DHW booster heater delay",
            entity_category=EntityCategory.CONFIG,
            device_class=NumberDeviceClass.DURATION,
            native_unit_of_measurement="min",
            native_min_value=20,
            native_max_value=180,
            native_step=5,
            state=float,
            state_to_mqtt=integer_to_mqtt,
            requires=(Feature.DHW,),
            firmware_marker="main/Static_Pressure",
            entity_registry_enabled_default=False,
        ),
        HeishaMonNumberEntityDescription(
            heishamon_topic_id="SET64",
            key=f"{mqtt_prefix}main/Efficiency_Stage1_Time",
            command_topic=f"{mqtt_prefix}commands/SetEfficiencyStage1Time",
            name="Aquarea Efficiency stage 1 time",
            entity_category=EntityCategory.CONFIG,
            device_class=NumberDeviceClass.DURATION,
            native_unit_of_measurement="min",
            native_min_value=0,
            native_max_value=60,
            native_step=5,
            state=float,
            state_to_mqtt=integer_to_mqtt,
            firmware_marker="main/Static_Pressure",
            entity_registry_enabled_default=False,
        ),
        HeishaMonNumberEntityDescription(
            heishamon_topic_id="SET65",
            key=f"{mqtt_prefix}main/Efficiency_Stage2_Time",
            command_topic=f"{mqtt_prefix}commands/SetEfficiencyStage2Time",
            name="Aquarea Efficiency stage 2 time",
            entity_category=EntityCategory.CONFIG,
            device_class=NumberDeviceClass.DURATION,
            native_unit_of_measurement="min",
            native_min_value=0,
            native_max_value=60,
            native_step=5,
            state=float,
            state_to_mqtt=integer_to_mqtt,
            firmware_marker="main/Static_Pressure",
            entity_registry_enabled_default=False,
        ),
        HeishaMonNumberEntityDescription(
            heishamon_topic_id="SET66",
            key=f"{mqtt_prefix}main/Efficiency_Stage3_Time",
            command_topic=f"{mqtt_prefix}commands/SetEfficiencyStage3Time",
            name="Aquarea Efficiency stage 3 time",
            entity_category=EntityCategory.CONFIG,
            device_class=NumberDeviceClass.DURATION,
            native_unit_of_measurement="min",
            native_min_value=0,
            native_max_value=30,
            native_step=5,
            state=float,
            state_to_mqtt=integer_to_mqtt,
            firmware_marker="main/Static_Pressure",
            entity_registry_enabled_default=False,
        ),
        HeishaMonNumberEntityDescription(
            heishamon_topic_id="SET67",
            key=f"{mqtt_prefix}main/Sensor_Offset_Remote_Th1",
            command_topic=f"{mqtt_prefix}commands/SetSensorOffsetRemoteTh1",
            name="Aquarea Sensor offset remote thermistor 1",
            entity_category=EntityCategory.CONFIG,
            native_unit_of_measurement="K",
            native_min_value=-3,
            native_max_value=3,
            native_step=0.5,
            state=float,
            state_to_mqtt=one_decimal_to_mqtt,
            firmware_marker="main/Static_Pressure",
            entity_registry_enabled_default=False,
        ),
        HeishaMonNumberEntityDescription(
            heishamon_topic_id="SET68",
            key=f"{mqtt_prefix}main/Sensor_Offset_Outdoor",
            command_topic=f"{mqtt_prefix}commands/SetSensorOffsetOutdoor",
            name="Aquarea Sensor offset outdoor",
            entity_category=EntityCategory.CONFIG,
            native_unit_of_measurement="K",
            native_min_value=-3,
            native_max_value=3,
            native_step=0.5,
            state=float,
            state_to_mqtt=one_decimal_to_mqtt,
            firmware_marker="main/Static_Pressure",
            entity_registry_enabled_default=False,
        ),
        HeishaMonNumberEntityDescription(
            heishamon_topic_id="SET72",
            key=f"{mqtt_prefix}main/Bivalent_Advanced_Start_Delay",
            command_topic=f"{mqtt_prefix}commands/SetBivalentAPStartDelay",
            name="Aquarea Bivalent advanced start delay",
            entity_category=EntityCategory.CONFIG,
            device_class=NumberDeviceClass.DURATION,
            native_unit_of_measurement="min",
            native_min_value=5,
            native_max_value=250,
            native_step=5,
            state=float,
            state_to_mqtt=integer_to_mqtt,
            requires=(Feature.BIVALENT,),
            firmware_marker="main/Static_Pressure",
            entity_registry_enabled_default=False,
        ),
        HeishaMonNumberEntityDescription(
            heishamon_topic_id="SET73",
            key=f"{mqtt_prefix}main/Bivalent_Advanced_Stop_Delay",
            command_topic=f"{mqtt_prefix}commands/SetBivalentAPStopDelay",
            name="Aquarea Bivalent advanced stop delay",
            entity_category=EntityCategory.CONFIG,
            device_class=NumberDeviceClass.DURATION,
            native_unit_of_measurement="min",
            native_min_value=5,
            native_max_value=250,
            native_step=5,
            state=float,
            state_to_mqtt=integer_to_mqtt,
            requires=(Feature.BIVALENT,),
            firmware_marker="main/Static_Pressure",
            entity_registry_enabled_default=False,
        ),
        HeishaMonNumberEntityDescription(
            heishamon_topic_id="SET77",
            key=f"{mqtt_prefix}main/Solar_On_Delta",
            command_topic=f"{mqtt_prefix}commands/SetSolarOnDelta",
            name="Aquarea Solar delta on",
            entity_category=EntityCategory.CONFIG,
            native_unit_of_measurement="K",
            native_min_value=5,
            native_max_value=15,
            native_step=1,
            state=float,
            state_to_mqtt=integer_to_mqtt,
            requires=(Feature.SOLAR,),
            firmware_marker="main/Static_Pressure",
            entity_registry_enabled_default=False,
        ),
        HeishaMonNumberEntityDescription(
            heishamon_topic_id="SET78",
            key=f"{mqtt_prefix}main/Solar_Off_Delta",
            command_topic=f"{mqtt_prefix}commands/SetSolarOffDelta",
            name="Aquarea Solar delta off",
            entity_category=EntityCategory.CONFIG,
            native_unit_of_measurement="K",
            native_min_value=2,
            native_max_value=10,
            native_step=1,
            state=float,
            state_to_mqtt=integer_to_mqtt,
            requires=(Feature.SOLAR,),
            firmware_marker="main/Static_Pressure",
            entity_registry_enabled_default=False,
        ),
        HeishaMonNumberEntityDescription(
            heishamon_topic_id="SET79",
            key=f"{mqtt_prefix}main/Solar_Frost_Protection",
            command_topic=f"{mqtt_prefix}commands/SetSolarFrostProtection",
            name="Aquarea Solar frost protection temperature",
            entity_category=EntityCategory.CONFIG,
            device_class=NumberDeviceClass.TEMPERATURE,
            native_unit_of_measurement="°C",
            native_min_value=-20,
            native_max_value=10,
            native_step=1,
            state=float,
            state_to_mqtt=integer_to_mqtt,
            requires=(Feature.SOLAR,),
            firmware_marker="main/Static_Pressure",
            entity_registry_enabled_default=False,
        ),
        HeishaMonNumberEntityDescription(
            heishamon_topic_id="SET80",
            key=f"{mqtt_prefix}main/Room_Holiday_Shift_Temp",
            command_topic=f"{mqtt_prefix}commands/SetRoomHolidayShiftTemp",
            name="Aquarea Room heating holiday shift temperature",
            entity_category=EntityCategory.CONFIG,
            native_unit_of_measurement="K",
            native_min_value=-15,
            native_max_value=15,
            native_step=1,
            state=float,
            state_to_mqtt=integer_to_mqtt,
            firmware_marker="main/Static_Pressure",
            entity_registry_enabled_default=False,
        ),
        HeishaMonNumberEntityDescription(
            heishamon_topic_id="SET88",
            key=f"{mqtt_prefix}main/Solar_High_Limit",
            command_topic=f"{mqtt_prefix}commands/SetSolarHighLimit",
            name="Aquarea Solar max temperature limit",
            entity_category=EntityCategory.CONFIG,
            device_class=NumberDeviceClass.TEMPERATURE,
            native_unit_of_measurement="°C",
            native_min_value=70,
            native_max_value=90,
            native_step=1,
            state=float,
            state_to_mqtt=integer_to_mqtt,
            requires=(Feature.SOLAR,),
            firmware_marker="main/Static_Pressure",
            entity_registry_enabled_default=False,
        ),
        HeishaMonNumberEntityDescription(
            heishamon_topic_id="SET90",
            key=f"{mqtt_prefix}main/SG_Ready_1_DHW_Power",
            command_topic=f"{mqtt_prefix}commands/SetSGReadyDHWPower1",
            name="Aquarea SG ready 1 DHW power",
            entity_category=EntityCategory.CONFIG,
            device_class=NumberDeviceClass.POWER,
            native_unit_of_measurement="kW",
            native_min_value=0.5,
            native_max_value=10,
            native_step=0.1,
            state=float,
            state_to_mqtt=one_decimal_to_mqtt,
            requires=(Feature.SG_READY, Feature.DHW,),
            firmware_marker="main/Static_Pressure",
            entity_registry_enabled_default=False,
        ),
        HeishaMonNumberEntityDescription(
            heishamon_topic_id="SET91",
            key=f"{mqtt_prefix}main/SG_Ready_1_Heat_Power",
            command_topic=f"{mqtt_prefix}commands/SetSGReadyHeatPower1",
            name="Aquarea SG ready 1 heating power",
            entity_category=EntityCategory.CONFIG,
            device_class=NumberDeviceClass.POWER,
            native_unit_of_measurement="kW",
            native_min_value=0.5,
            native_max_value=10,
            native_step=0.1,
            state=float,
            state_to_mqtt=one_decimal_to_mqtt,
            requires=(Feature.SG_READY,),
            firmware_marker="main/Static_Pressure",
            entity_registry_enabled_default=False,
        ),
        HeishaMonNumberEntityDescription(
            heishamon_topic_id="SET92",
            key=f"{mqtt_prefix}main/SG_Ready_1_Cool_Power",
            command_topic=f"{mqtt_prefix}commands/SetSGReadyCoolPower1",
            name="Aquarea SG ready 1 cooling power",
            entity_category=EntityCategory.CONFIG,
            device_class=NumberDeviceClass.POWER,
            native_unit_of_measurement="kW",
            native_min_value=0.5,
            native_max_value=10,
            native_step=0.1,
            state=float,
            state_to_mqtt=one_decimal_to_mqtt,
            requires=(Feature.SG_READY, Feature.COOLING,),
            firmware_marker="main/Static_Pressure",
            entity_registry_enabled_default=False,
        ),
        HeishaMonNumberEntityDescription(
            heishamon_topic_id="SET93",
            key=f"{mqtt_prefix}main/SG_Ready_2_DHW_Power",
            command_topic=f"{mqtt_prefix}commands/SetSGReadyDHWPower2",
            name="Aquarea SG ready 2 DHW power",
            entity_category=EntityCategory.CONFIG,
            device_class=NumberDeviceClass.POWER,
            native_unit_of_measurement="kW",
            native_min_value=0.5,
            native_max_value=10,
            native_step=0.1,
            state=float,
            state_to_mqtt=one_decimal_to_mqtt,
            requires=(Feature.SG_READY, Feature.DHW,),
            firmware_marker="main/Static_Pressure",
            entity_registry_enabled_default=False,
        ),
        HeishaMonNumberEntityDescription(
            heishamon_topic_id="SET94",
            key=f"{mqtt_prefix}main/SG_Ready_2_Heat_Power",
            command_topic=f"{mqtt_prefix}commands/SetSGReadyHeatPower2",
            name="Aquarea SG ready 2 heating power",
            entity_category=EntityCategory.CONFIG,
            device_class=NumberDeviceClass.POWER,
            native_unit_of_measurement="kW",
            native_min_value=0.5,
            native_max_value=10,
            native_step=0.1,
            state=float,
            state_to_mqtt=one_decimal_to_mqtt,
            requires=(Feature.SG_READY,),
            firmware_marker="main/Static_Pressure",
            entity_registry_enabled_default=False,
        ),
        HeishaMonNumberEntityDescription(
            heishamon_topic_id="SET95",
            key=f"{mqtt_prefix}main/SG_Ready_2_Cool_Power",
            command_topic=f"{mqtt_prefix}commands/SetSGReadyCoolPower2",
            name="Aquarea SG ready 2 cooling power",
            entity_category=EntityCategory.CONFIG,
            device_class=NumberDeviceClass.POWER,
            native_unit_of_measurement="kW",
            native_min_value=0.5,
            native_max_value=10,
            native_step=0.1,
            state=float,
            state_to_mqtt=one_decimal_to_mqtt,
            requires=(Feature.SG_READY, Feature.COOLING,),
            firmware_marker="main/Static_Pressure",
            entity_registry_enabled_default=False,
        ),
        HeishaMonNumberEntityDescription(
            heishamon_topic_id="SET96",
            key=f"{mqtt_prefix}main/SG_Ready_Stop_Power",
            command_topic=f"{mqtt_prefix}commands/SetSGReadyStopPower",
            name="Aquarea SG ready stop power",
            entity_category=EntityCategory.CONFIG,
            device_class=NumberDeviceClass.POWER,
            native_unit_of_measurement="kW",
            native_min_value=0.5,
            native_max_value=10,
            native_step=0.1,
            state=float,
            state_to_mqtt=one_decimal_to_mqtt,
            requires=(Feature.SG_READY,),
            firmware_marker="main/Static_Pressure",
            entity_registry_enabled_default=False,
        ),
        HeishaMonNumberEntityDescription(
            heishamon_topic_id="SET97",
            key=f"{mqtt_prefix}main/SG_Ready_1_Cool_Capacity",
            command_topic=f"{mqtt_prefix}commands/SetSGReadyCoolCapacity1",
            name="Aquarea SG ready 1 cooling offset",
            entity_category=EntityCategory.CONFIG,
            device_class=NumberDeviceClass.TEMPERATURE,
            native_unit_of_measurement="°C",
            native_min_value=-15,
            native_max_value=0,
            native_step=1,
            state=float,
            state_to_mqtt=integer_to_mqtt,
            requires=(Feature.SG_READY, Feature.COOLING,),
            firmware_marker="main/Static_Pressure",
            entity_registry_enabled_default=False,
        ),
        HeishaMonNumberEntityDescription(
            heishamon_topic_id="SET98",
            key=f"{mqtt_prefix}main/SG_Ready_2_Cool_Capacity",
            command_topic=f"{mqtt_prefix}commands/SetSGReadyCoolCapacity2",
            name="Aquarea SG ready 2 cooling offset",
            entity_category=EntityCategory.CONFIG,
            device_class=NumberDeviceClass.TEMPERATURE,
            native_unit_of_measurement="°C",
            native_min_value=-15,
            native_max_value=0,
            native_step=1,
            state=float,
            state_to_mqtt=integer_to_mqtt,
            requires=(Feature.SG_READY, Feature.COOLING,),
            firmware_marker="main/Static_Pressure",
            entity_registry_enabled_default=False,
        ),
        HeishaMonNumberEntityDescription(
            heishamon_topic_id="SET99",
            key=f"{mqtt_prefix}main/Sensor_Offset_Return",
            command_topic=f"{mqtt_prefix}commands/SetSensorOffsetReturn",
            name="Aquarea Sensor offset return",
            entity_category=EntityCategory.CONFIG,
            native_unit_of_measurement="K",
            native_min_value=-3,
            native_max_value=3,
            native_step=0.5,
            state=float,
            state_to_mqtt=one_decimal_to_mqtt,
            firmware_marker="main/Static_Pressure",
            entity_registry_enabled_default=False,
        ),
        HeishaMonNumberEntityDescription(
            heishamon_topic_id="SET103",
            key=f"{mqtt_prefix}main/Sensor_Offset_DHW_Tank",
            command_topic=f"{mqtt_prefix}commands/SetSensorOffsetDhwTank",
            name="Aquarea Sensor offset DHW tank",
            entity_category=EntityCategory.CONFIG,
            native_unit_of_measurement="K",
            native_min_value=-3,
            native_max_value=3,
            native_step=0.5,
            state=float,
            state_to_mqtt=one_decimal_to_mqtt,
            requires=(Feature.DHW,),
            firmware_marker="main/Static_Pressure",
            entity_registry_enabled_default=False,
        ),
        HeishaMonNumberEntityDescription(
            heishamon_topic_id="SET104",
            key=f"{mqtt_prefix}main/Sensor_Offset_Flow",
            command_topic=f"{mqtt_prefix}commands/SetSensorOffsetFlow",
            name="Aquarea Sensor offset flow",
            entity_category=EntityCategory.CONFIG,
            native_unit_of_measurement="K",
            native_min_value=-3,
            native_max_value=3,
            native_step=0.5,
            state=float,
            state_to_mqtt=one_decimal_to_mqtt,
            firmware_marker="main/Static_Pressure",
            entity_registry_enabled_default=False,
        ),
    ]
    topic_ids = {
        "1 Heat Target High": "TOP29",
        "1 Heat Target Low": "TOP30",
        "1 Heat Outside High": "TOP31",
        "1 Heat Outside Low": "TOP32",
        "1 Cool Target High": "TOP72",
        "1 Cool Target Low": "TOP73",
        "1 Cool Outside High": "TOP74",
        "1 Cool Outside Low": "TOP75",
        "2 Heat Target High": "TOP82",
        "2 Heat Target Low": "TOP83",
        "2 Heat Outside High": "TOP84",
        "2 Heat Outside Low": "TOP85",
        "2 Cool Target High": "TOP86",
        "2 Cool Target Low": "TOP87",
        "2 Cool Outside High": "TOP88",
        "2 Cool Outside Low": "TOP89",
    }
    ranges = {
        "Heat": {
            "Outside": [-20, 30],
            "Target": [15, 75],
        },
        "Cool": {
            "Outside": [15, 30],
            "Target": [5, 20],
        },
    }

    def dual_location(loc):
        if loc == "Target":
            return "Outside"
        return "Target"

    for zone_id in [1, 2]:
        for action in ["Cool", "Heat"]:
            for point in ["High", "Low"]:
                for loc in ["Target", "Outside"]:
                    numbers.append(
                        HeishaMonNumberEntityDescription(
                            heishamon_topic_id=topic_ids[
                                f"{zone_id} {action} {loc} {point}"
                            ],
                            key=f"{mqtt_prefix}main/Z{zone_id}_{action}_Curve_{loc}_{point}_Temp",
                            command_topic=f"{mqtt_prefix}commands/SetCurves",
                            entity_category=EntityCategory.CONFIG,
                            native_min_value=ranges[action][loc][0],
                            native_max_value=ranges[action][loc][1],
                            name=f"Aquarea Zone {zone_id} {action.lower()} curve {loc.lower()} {point.lower()}",
                            device_class=NumberDeviceClass.TEMPERATURE,
                            native_unit_of_measurement="°C",
                            # by default we hide all options related to less common setup (cooling, buffer, solar and pool)
                            entity_registry_enabled_default=(action == "Heat"),
                            state=float,
                            state_to_mqtt=write_curves_gen(zone_id, action, loc, point),
                        )
                    )
    return numbers


def write_curves_gen(zone_id: int, action: str, loc: str, point: str):
    def write_curves(value: int) -> str:
        json_doc = {
            f"zone{zone_id}": {
                action.lower(): {loc.lower(): {point.lower(): int(value)}}
            }
        }
        return json.dumps(json_doc)

    return write_curves


def build_selects(mqtt_prefix: str) -> list[HeishaMonSelectEntityDescription]:
    return [
        HeishaMonSelectEntityDescription(
            heishamon_topic_id="SET3",  # also corresponds to TOP18
            key=f"{mqtt_prefix}main/Quiet_Mode_Level",
            command_topic=f"{mqtt_prefix}commands/SetQuietMode",
            name="Aquarea Quiet Mode",
            entity_category=EntityCategory.CONFIG,
            state=read_quiet_mode,
            state_to_mqtt=write_quiet_mode,
            options=["Off", "1", "2", "3", "Scheduled"],
        ),
        HeishaMonSelectEntityDescription(
            heishamon_topic_id="SET4",  # also corresponds to TOP17
            key=f"{mqtt_prefix}main/Powerful_Mode_Time",
            command_topic=f"{mqtt_prefix}commands/SetPowerfulMode",
            name="Aquarea Powerful Mode",
            state=read_power_mode_time,
            state_to_mqtt=set_power_mode_time,
            options=list(POWERFUL_MODE_TIMES.values()),
        ),
        HeishaMonSelectEntityDescription(
            heishamon_topic_id="SET9",  # also corresponds to TOP4
            key=f"{mqtt_prefix}main/Operating_Mode_State",
            command_topic=f"{mqtt_prefix}commands/SetOperationMode",
            name="Aquarea Mode",
            state=read_operating_mode_state,
            state_to_mqtt=operating_mode_to_state,
            options=list(OperatingMode.modes_to_str().values()),
        ),
        HeishaMonSelectEntityDescription(
            heishamon_topic_id="SET17",  # also TOP94
            key=f"{mqtt_prefix}main/Zones_State",
            command_topic=f"{mqtt_prefix}commands/SetZones",
            name="Active zones",
            state=read_zones_state,
            state_to_mqtt=zone_state_to_mqtt,
            options=list(ZONE_STATES_STRING.values()),
        ),
        HeishaMonSelectEntityDescription(
            heishamon_topic_id="SET26",  # also TOP114
            key=f"{mqtt_prefix}main/External_Pad_Heater",
            command_topic=f"{mqtt_prefix}commands/SetExternalPadHeater",
            name="Aquarea External Pad Heater type",
            state=read_external_pad_heater_enabled,
            state_to_mqtt=external_pad_heater_type_to_mqtt,
            options=list(EXTERNAL_PAD_HEATER_TYPE.values()),
        ),
        HeishaMonSelectEntityDescription(
            heishamon_topic_id="SET35",  # also TOP130
            requires=(Feature.BIVALENT,),
            key=f"{mqtt_prefix}main/Bivalent_Mode",
            command_topic=f"{mqtt_prefix}commands/SetBivalentMode",
            name="Aquarea Bivalent Mode",
            state=read_bivalent_mode,
            state_to_mqtt=bivalent_mode_to_mqtt,
            options=list(BIVALENT_MODES.values()),
        ),
        HeishaMonSelectEntityDescription(
            heishamon_topic_id="SET39",  # corresponds to TOP139
            key=f"{mqtt_prefix}main/Heating_Control",
            command_topic=f"{mqtt_prefix}commands/SetHeatingControl",
            name="Aquarea Heating Control",
            entity_category=EntityCategory.CONFIG,
            state=read_heating_control,
            state_to_mqtt=heating_control_to_mqtt,
            options=list(HEATING_CONTROL.values()),
        ),
        HeishaMonSelectEntityDescription(
            heishamon_topic_id="SET40",  # corresponds to TOP140
            requires=(Feature.DHW,),
            key=f"{mqtt_prefix}main/Smart_DHW",
            command_topic=f"{mqtt_prefix}commands/SetSmartDHW",
            name="Aquarea Smart DHW",
            entity_category=EntityCategory.CONFIG,
            state=read_smart_dhw,
            state_to_mqtt=smart_dhw_to_mqtt,
            options=list(SMART_DHW.values()),
        ),
        HeishaMonSelectEntityDescription(
            heishamon_topic_id="SET41",  # corresponds to TOP141
            key=f"{mqtt_prefix}main/Quiet_Mode_Priority",
            command_topic=f"{mqtt_prefix}commands/SetQuietModePriority",
            name="Aquarea Quiet Mode Priority",
            entity_category=EntityCategory.CONFIG,
            state=read_quiet_mode_priority,
            state_to_mqtt=quiet_mode_priority_to_mqtt,
            options=list(QUIET_MODE_PRIORITY.values()),
        ),
        HeishaMonSelectEntityDescription(
            heishamon_topic_id="SET42",  # corresponds to TOP106
            key=f"{mqtt_prefix}main/Pump_Flowrate_Mode",
            command_topic=f"{mqtt_prefix}commands/SetPumpFlowrateMode",
            name="Aquarea Pump Flowrate Mode",
            entity_category=EntityCategory.CONFIG,
            state=read_pump_flowrate_mode,
            state_to_mqtt=pump_flowrate_mode_to_mqtt,
            options=list(PUMP_FLOWRATE_MODE.values()),
        ),
        HeishaMonSelectEntityDescription(
            heishamon_topic_id="SetSmartGridMode",
            key=f"{mqtt_prefix}commands/SetSmartGridMode",
            command_topic=f"{mqtt_prefix}commands/SetSmartGridMode",
            retain=True,
            name="Smart Grid Mode",
            entity_category=EntityCategory.CONFIG,
            state=read_smart_grid_mode,
            state_to_mqtt=write_smart_grid_mode,
            options=list(SMART_GRID_MODES_STRING.values()),
            entity_registry_enabled_default=False,  # comes from the optional PCB: disabled by default
        ),
        HeishaMonSelectEntityDescription(
            heishamon_topic_id="SET43",  # corresponds to TOP143
            key=f"{mqtt_prefix}main/DHW_Sensor_Selection",
            command_topic=f"{mqtt_prefix}commands/SetDHWSensorSelection",
            name="Aquarea DHW Sensor Selection",
            entity_category=EntityCategory.CONFIG,
            icon="mdi:thermometer-water",
            state=read_dhw_sensor_selection,
            state_to_mqtt=dhw_sensor_selection_to_mqtt,
            options=list(DHW_SENSOR_SELECTION.values()),
            entity_registry_enabled_default=False,  # only applicable to K/L series All-In-One units
        ),
        HeishaMonSelectEntityDescription(
            heishamon_topic_id="SET44", # corresponds to TOP58
            requires=(Feature.DHW,),
            key=f"{mqtt_prefix}main/DHW_Heater_State",
            command_topic=f"{mqtt_prefix}commands/SetDHWHeaterState",
            name="Aquarea DHW Heater State",
            entity_category=EntityCategory.CONFIG,
            icon="mdi:thermometer-water",
            state=read_heater_state,
            state_to_mqtt=heater_state_to_mqtt,
            options=list(HEATER_STATE.values()),
        ),
        HeishaMonSelectEntityDescription(
            heishamon_topic_id="SET45", # corresponds to TOP59
            key=f"{mqtt_prefix}main/Room_Heater_State",
            command_topic=f"{mqtt_prefix}commands/SetRoomHeaterState",
            name="Aquarea Room Heater State",
            entity_category=EntityCategory.CONFIG,
            icon="mdi:thermometer-water",
            state=read_heater_state,
            state_to_mqtt=heater_state_to_mqtt,
            options=list(HEATER_STATE.values()),
        ),
        HeishaMonSelectEntityDescription(
            heishamon_topic_id="SET70",
            key=f"{mqtt_prefix}main/Bivalent_Operating_Mode",
            command_topic=f"{mqtt_prefix}commands/SetBivalentOperatingMode",
            name="Aquarea Bivalent operating mode",
            entity_category=EntityCategory.CONFIG,
            state=read_parity_bivalent_operating_mode,
            state_to_mqtt=parity_bivalent_operating_mode_to_mqtt,
            options=list(PARITY_BIVALENT_OPERATING_MODE.values()),
            requires=(Feature.BIVALENT,),
            firmware_marker="main/Static_Pressure",
            entity_registry_enabled_default=False,
        ),
        HeishaMonSelectEntityDescription(
            heishamon_topic_id="SET74",
            key=f"{mqtt_prefix}main/Extra_Pump_Use",
            command_topic=f"{mqtt_prefix}commands/SetExtraPump",
            name="Aquarea Extra pump use",
            entity_category=EntityCategory.CONFIG,
            state=read_parity_extra_pump_use,
            state_to_mqtt=parity_extra_pump_use_to_mqtt,
            options=list(PARITY_EXTRA_PUMP_USE.values()),
            requires=(Feature.OPTIONAL_PCB,),
            firmware_marker="main/Static_Pressure",
            entity_registry_enabled_default=False,
        ),
        HeishaMonSelectEntityDescription(
            heishamon_topic_id="SET75",
            key=f"{mqtt_prefix}main/Extra_Pump_Mode",
            command_topic=f"{mqtt_prefix}commands/SetExtraPumpMode",
            name="Aquarea Extra pump mode",
            entity_category=EntityCategory.CONFIG,
            state=read_parity_extra_pump_mode,
            state_to_mqtt=parity_extra_pump_mode_to_mqtt,
            options=list(PARITY_EXTRA_PUMP_MODE.values()),
            requires=(Feature.OPTIONAL_PCB,),
            firmware_marker="main/Static_Pressure",
            entity_registry_enabled_default=False,
        ),
        HeishaMonSelectEntityDescription(
            heishamon_topic_id="SET76",
            key=f"{mqtt_prefix}main/Internal_Heater_Capacity",
            command_topic=f"{mqtt_prefix}commands/SetInternalHeaterCapacity",
            name="Aquarea Internal heater capacity",
            entity_category=EntityCategory.CONFIG,
            state=read_parity_internal_heater_capacity,
            state_to_mqtt=parity_internal_heater_capacity_to_mqtt,
            options=list(PARITY_INTERNAL_HEATER_CAPACITY.values()),
            firmware_marker="main/Static_Pressure",
            entity_registry_enabled_default=False,
        ),
        HeishaMonSelectEntityDescription(
            heishamon_topic_id="SET81",
            key=f"{mqtt_prefix}main/Zone_Configuration",
            command_topic=f"{mqtt_prefix}commands/SetZoneType",
            name="Aquarea Zone 1 type",
            entity_category=EntityCategory.CONFIG,
            state=read_parity_zone_type,
            state_to_mqtt=zone_type_to_mqtt,
            options=list(PARITY_ZONE_TYPE.values()),
            firmware_marker="main/Static_Pressure",
            entity_registry_enabled_default=False,
        ),
        HeishaMonSelectEntityDescription(
            heishamon_topic_id="SET82",
            key=f"{mqtt_prefix}main/Heating_Mode",
            command_topic=f"{mqtt_prefix}commands/SetHeatingWaterMode",
            name="Aquarea Heating water temperature mode",
            entity_category=EntityCategory.CONFIG,
            state=read_parity_water_temperature_mode,
            state_to_mqtt=parity_water_temperature_mode_to_mqtt,
            options=list(PARITY_WATER_TEMPERATURE_MODE.values()),
            firmware_marker="main/Static_Pressure",
            entity_registry_enabled_default=False,
        ),
        HeishaMonSelectEntityDescription(
            heishamon_topic_id="SET83",
            key=f"{mqtt_prefix}main/Cooling_Mode",
            command_topic=f"{mqtt_prefix}commands/SetCoolingWaterMode",
            name="Aquarea Cooling water temperature mode",
            entity_category=EntityCategory.CONFIG,
            state=read_parity_water_temperature_mode,
            state_to_mqtt=parity_water_temperature_mode_to_mqtt,
            options=list(PARITY_WATER_TEMPERATURE_MODE.values()),
            firmware_marker="main/Static_Pressure",
            entity_registry_enabled_default=False,
        ),
        HeishaMonSelectEntityDescription(
            heishamon_topic_id="SET84",
            key=f"{mqtt_prefix}main/Liquid_Type",
            command_topic=f"{mqtt_prefix}commands/SetLiquidType",
            name="Aquarea Liquid type",
            entity_category=EntityCategory.CONFIG,
            state=read_parity_liquid_type,
            state_to_mqtt=parity_liquid_type_to_mqtt,
            options=list(PARITY_LIQUID_TYPE.values()),
            firmware_marker="main/Static_Pressure",
            entity_registry_enabled_default=False,
        ),
        HeishaMonSelectEntityDescription(
            heishamon_topic_id="SET85",
            key=f"{mqtt_prefix}main/DHW_Heater_Type",
            command_topic=f"{mqtt_prefix}commands/SetDHWHeaterType",
            name="Aquarea DHW heater type",
            entity_category=EntityCategory.CONFIG,
            state=read_parity_dhw_heater_type,
            state_to_mqtt=parity_dhw_heater_type_to_mqtt,
            options=list(PARITY_DHW_HEATER_TYPE.values()),
            requires=(Feature.DHW,),
            firmware_marker="main/Static_Pressure",
            entity_registry_enabled_default=False,
        ),
        HeishaMonSelectEntityDescription(
            heishamon_topic_id="SET87",
            key=f"{mqtt_prefix}main/Solar_Mode",
            command_topic=f"{mqtt_prefix}commands/SetSolarMode",
            name="Aquarea Solar mode",
            entity_category=EntityCategory.CONFIG,
            state=read_parity_solar_mode,
            state_to_mqtt=parity_solar_mode_to_mqtt,
            options=list(PARITY_SOLAR_MODE.values()),
            requires=(Feature.OPTIONAL_PCB,),
            firmware_marker="main/Static_Pressure",
            entity_registry_enabled_default=False,
        ),
        HeishaMonSelectEntityDescription(
            heishamon_topic_id="SET89",
            key=f"{mqtt_prefix}main/SG_Ready_Control",
            command_topic=f"{mqtt_prefix}commands/SetSGReadyMode",
            name="Aquarea SG ready mode",
            entity_category=EntityCategory.CONFIG,
            state=read_parity_sg_ready_control,
            state_to_mqtt=parity_sg_ready_control_to_mqtt,
            options=list(PARITY_SG_READY_CONTROL.values()),
            requires=(Feature.OPTIONAL_PCB,),
            firmware_marker="main/Static_Pressure",
            entity_registry_enabled_default=False,
        ),
        HeishaMonSelectEntityDescription(
            heishamon_topic_id="SET100",
            key=f"{mqtt_prefix}main/Z1_Sensor_Settings",
            command_topic=f"{mqtt_prefix}commands/SetZ1SensorSettings",
            name="Aquarea Zone 1 sensor type",
            entity_category=EntityCategory.CONFIG,
            state=read_parity_zone_sensor_type,
            state_to_mqtt=parity_zone_sensor_type_to_mqtt,
            options=list(PARITY_ZONE_SENSOR_TYPE.values()),
            firmware_marker="main/Static_Pressure",
            entity_registry_enabled_default=False,
        ),
    ]


def read_holiday_status(value: str) -> str:
    if value == "0":
        return "Off"
    elif value == "1":
        return "Scheduled"
    else:
        return "Active"


def read_holiday_status_to_bool(value: str) -> bool:
    return value != "0"


def build_switches(mqtt_prefix: str) -> list[HeishaMonSwitchEntityDescription]:
    return [
        HeishaMonSwitchEntityDescription(
            heishamon_topic_id="SET1",  # also corresponds to TOP0
            key=f"{mqtt_prefix}main/Heatpump_State",
            command_topic=f"{mqtt_prefix}commands/SetHeatpump",
            name="Aquarea Main Power",
            state=bit_to_bool,
            binary_sensor_device_class=BinarySensorDeviceClass.RUNNING,
        ),
        HeishaMonSwitchEntityDescription(
            heishamon_topic_id="SET2",  # TOP19
            key=f"{mqtt_prefix}main/Holiday_Mode_State",
            command_topic=f"{mqtt_prefix}commands/SetHolidayMode",
            name="Aquarea Holiday Mode",
            entity_category=EntityCategory.CONFIG,
            state=read_holiday_status_to_bool,
        ),
        HeishaMonSwitchEntityDescription(
            heishamon_topic_id="SET10",  # also corresponds to TOP2
            requires=(Feature.DHW,),
            key=f"{mqtt_prefix}main/Force_DHW_State",
            command_topic=f"{mqtt_prefix}commands/SetForceDHW",
            name="Aquarea Force DHW Mode",
            entity_category=EntityCategory.CONFIG,
            state=bit_to_bool,
        ),
        HeishaMonSwitchEntityDescription(
            heishamon_topic_id="SET12",  # corresponds to TOP26
            key=f"{mqtt_prefix}main/Defrosting_State",
            command_topic=f"{mqtt_prefix}commands/SetForceDefrost",
            name="Aquarea Defrost routine",
            entity_category=EntityCategory.CONFIG,
            state=bit_to_bool,
        ),
        HeishaMonSwitchEntityDescription(
            heishamon_topic_id="SET13",  # corresponds to TOP69
            requires=(Feature.DHW,),
            key=f"{mqtt_prefix}main/Sterilization_State",
            command_topic=f"{mqtt_prefix}commands/SetForceSterilization",
            name="Aquarea Force Sterilization",
            entity_category=EntityCategory.CONFIG,
            binary_sensor_device_class=BinarySensorDeviceClass.RUNNING,
            state=bit_to_bool,
        ),
        HeishaMonSwitchEntityDescription(
            heishamon_topic_id="SET47",  # corresponds to TOP68
            key=f"{mqtt_prefix}main/Force_Heater_State",
            command_topic=f"{mqtt_prefix}commands/SetForceHeater",
            name="Aquarea Force Heater",
            entity_category=EntityCategory.CONFIG,
            state=bit_to_bool,
        ),
        HeishaMonSwitchEntityDescription(
            heishamon_topic_id="SET24",  # corresponds to "TOP13"
            key=f"{mqtt_prefix}main/Main_Schedule_State",
            command_topic=f"{mqtt_prefix}commands/SetMainSchedule",
            name="Aquarea Main thermostat schedule",
            entity_category=EntityCategory.CONFIG,
            state=bit_to_bool,
        ),
        HeishaMonSwitchEntityDescription(
            heishamon_topic_id="SET25",  # corresponds to TOP108
            key=f"{mqtt_prefix}main/Alt_External_Sensor",
            command_topic=f"{mqtt_prefix}commands/SetAltExternalSensor",
            name="Aquarea use external outdoor sensor",
            entity_category=EntityCategory.CONFIG,
            state=bit_to_bool,
        ),
        HeishaMonSwitchEntityDescription(
            heishamon_topic_id="SET28",  # corresponds to TOP99
            key=f"{mqtt_prefix}main/Buffer_Installed",
            command_topic=f"{mqtt_prefix}commands/SetBuffer",
            name="Aquarea Buffer tank",
            entity_category=EntityCategory.CONFIG,
            state=bit_to_bool,
        ),
        HeishaMonSwitchEntityDescription(
            heishamon_topic_id="SET30",  # corresponds to TOP119
            key=f"{mqtt_prefix}main/External_Control",
            command_topic=f"{mqtt_prefix}commands/SetExternalControl",
            name="Aquarea External Control Enabled",
            entity_category=EntityCategory.CONFIG,
            state=bit_to_bool,
            entity_registry_enabled_default=False,
        ),
        HeishaMonSwitchEntityDescription(
            heishamon_topic_id="SET31",  # corresponds to TOP121
            requires=(Feature.OPTIONAL_PCB,),
            key=f"{mqtt_prefix}main/External_Error_Signal",
            command_topic=f"{mqtt_prefix}commands/SetExternalError",
            name="Aquarea External Error Signal",
            entity_category=EntityCategory.CONFIG,
            state=bit_to_bool,
            entity_registry_enabled_default=False,
        ),
        HeishaMonSwitchEntityDescription(
            heishamon_topic_id="SET32",  # corresponds to TOP122
            requires=(Feature.OPTIONAL_PCB,),
            key=f"{mqtt_prefix}main/External_Compressor_Control",
            command_topic=f"{mqtt_prefix}commands/SetExternalCompressorControl",
            name="Aquarea External Compressor control",
            entity_category=EntityCategory.CONFIG,
            state=bit_to_bool,
            entity_registry_enabled_default=False,
        ),
        HeishaMonSwitchEntityDescription(
            heishamon_topic_id="SetCompressorState",  # depends on SET32 TOP122
            key=f"{mqtt_prefix}commands/SetCompressorState",
            command_topic=f"{mqtt_prefix}commands/SetCompressorState",
            name="Aquarea Set Compressor state",
            retain=True,  # should be retained since the value is not provided by heat pump data
            entity_category=EntityCategory.CONFIG,
            state=bit_to_bool,
            entity_registry_enabled_default=False,  # hide by default since actual action depends on state of SET32=External_Compressor_Control (only if "ON", this switch has any effect) and on state of Pin3 of SW2 on Main PCB (Pin3=1 Switch Backup Heater OFF; Pin3=0 Switch Compressor OFF)
        ),
        HeishaMonSwitchEntityDescription(
            heishamon_topic_id="SET33",  # corresponds to TOP120
            requires=(Feature.OPTIONAL_PCB,),
            key=f"{mqtt_prefix}main/External_Heat_Cool_Control",
            command_topic=f"{mqtt_prefix}commands/SetExternalHeatCoolControl",
            name="Aquarea External Heat Cool control",
            entity_category=EntityCategory.CONFIG,
            state=bit_to_bool,
            entity_registry_enabled_default=False,
        ),
        HeishaMonSwitchEntityDescription(
            heishamon_topic_id="SET34",  # corresponds to TOP129
            key=f"{mqtt_prefix}main/Bivalent_Control",
            command_topic=f"{mqtt_prefix}commands/SetBivalentControl",
            name="Aquarea Bivalent Control",
            state=bit_to_bool,
            entity_registry_enabled_default=True,
        ),
        HeishaMonSwitchEntityDescription(
            heishamon_topic_id="RELAY01",
            key=f"{mqtt_prefix}gpio/relay/one",
            command_topic=f"{mqtt_prefix}gpio/relay/one",
            name="Relay 1",
            entity_category=EntityCategory.CONFIG,
            device=DeviceType.HEISHAMON,
            state=relay_to_bool,
            retain=True,
            payload_on="on",
            payload_off="off",
            entity_registry_enabled_default=False,  # by default we hide all options related to less common setup (cooling, buffer, solar and pool)
        ),
        HeishaMonSwitchEntityDescription(
            heishamon_topic_id="RELAY02",
            key=f"{mqtt_prefix}gpio/relay/two",
            command_topic=f"{mqtt_prefix}gpio/relay/two",
            name="Relay 2",
            entity_category=EntityCategory.CONFIG,
            device=DeviceType.HEISHAMON,
            state=relay_to_bool,
            retain=True,
            payload_on="on",
            payload_off="off",
            entity_registry_enabled_default=False,  # by default we hide all options related to less common setup (cooling, buffer, solar and pool)
        ),
        HeishaMonSwitchEntityDescription(
            heishamon_topic_id="SET55",
            key=f"{mqtt_prefix}main/Quiet_Mode_Schedule",
            command_topic=f"{mqtt_prefix}commands/SetQuietModeSchedule",
            name="Aquarea Quiet mode schedule",
            entity_category=EntityCategory.CONFIG,
            state=bit_to_bool,
            firmware_marker="main/DHW_Heatup_Max_Time",
            entity_registry_enabled_default=False,
        ),
        HeishaMonSwitchEntityDescription(
            heishamon_topic_id="SET56",
            key=f"{mqtt_prefix}main/Anti_Freeze_Mode",
            command_topic=f"{mqtt_prefix}commands/SetAntiFreezeMode",
            name="Aquarea Anti freeze mode",
            entity_category=EntityCategory.CONFIG,
            state=bit_to_bool,
            firmware_marker="main/Static_Pressure",
            entity_registry_enabled_default=False,
        ),
        HeishaMonSwitchEntityDescription(
            heishamon_topic_id="SET58",
            key=f"{mqtt_prefix}main/Demand_Control",
            command_topic=f"{mqtt_prefix}commands/SetDemandControlEnable",
            name="Aquarea Demand control",
            entity_category=EntityCategory.CONFIG,
            state=bit_to_bool,
            requires=(Feature.OPTIONAL_PCB,),
            firmware_marker="main/Static_Pressure",
            entity_registry_enabled_default=False,
        ),
        HeishaMonSwitchEntityDescription(
            heishamon_topic_id="SET59",
            key=f"{mqtt_prefix}main/DHW_Defrost",
            command_topic=f"{mqtt_prefix}commands/SetDHWDefrost",
            name="Aquarea DHW defrost",
            entity_category=EntityCategory.CONFIG,
            state=bit_to_bool,
            requires=(Feature.DHW,),
            firmware_marker="main/Static_Pressure",
            entity_registry_enabled_default=False,
        ),
        HeishaMonSwitchEntityDescription(
            heishamon_topic_id="SET60",
            key=f"{mqtt_prefix}main/Static_Pressure",
            command_topic=f"{mqtt_prefix}commands/SetStaticPressure",
            name="Aquarea Static pressure",
            entity_category=EntityCategory.CONFIG,
            state=bit_to_bool,
            entity_registry_enabled_default=False,
        ),
        HeishaMonSwitchEntityDescription(
            heishamon_topic_id="SET69",
            key=f"{mqtt_prefix}main/Bivalent_Advanced_Heat",
            command_topic=f"{mqtt_prefix}commands/SetBivalentAPHeat",
            name="Aquarea Bivalent advanced heat",
            entity_category=EntityCategory.CONFIG,
            state=bit_to_bool,
            requires=(Feature.BIVALENT,),
            firmware_marker="main/Static_Pressure",
            entity_registry_enabled_default=False,
        ),
        HeishaMonSwitchEntityDescription(
            heishamon_topic_id="SET71",
            key=f"{mqtt_prefix}main/Bivalent_External_Pump",
            command_topic=f"{mqtt_prefix}commands/SetBivalentExternalPump",
            name="Aquarea Bivalent external pump",
            entity_category=EntityCategory.CONFIG,
            state=bit_to_bool,
            requires=(Feature.BIVALENT,),
            entity_registry_enabled_default=False,
        ),
        HeishaMonSwitchEntityDescription(
            heishamon_topic_id="SET86",
            key=f"{mqtt_prefix}main/DHW_Installed",
            command_topic=f"{mqtt_prefix}commands/SetDHWInstalled",
            name="Aquarea DHW tank",
            entity_category=EntityCategory.CONFIG,
            state=bit_to_bool,
            firmware_marker="main/Static_Pressure",
            entity_registry_enabled_default=False,
        ),
        HeishaMonSwitchEntityDescription(
            heishamon_topic_id="SET102",
            key=f"{mqtt_prefix}main/Defrost_Signal",
            command_topic=f"{mqtt_prefix}commands/SetDefrostSignal",
            name="Aquarea Defrost signal",
            entity_category=EntityCategory.CONFIG,
            state=bit_to_bool,
            entity_registry_enabled_default=False,
        ),
    ]


def online_to_bool(value: str) -> Optional[bool]:
    if value == "Online":
        return True
    elif value == "Offline":
        return False
    else:
        return None


def build_binary_sensors(
    mqtt_prefix: str,
) -> list[HeishaMonBinarySensorEntityDescription]:
    return [
        HeishaMonBinarySensorEntityDescription(
            heishamon_topic_id="LWT",
            key=f"{mqtt_prefix}LWT",
            name="HeatPump online",
            entity_category=EntityCategory.DIAGNOSTIC,
            device=DeviceType.HEISHAMON,
            state=online_to_bool,
        ),
        HeishaMonBinarySensorEntityDescription(
            heishamon_topic_id="TOP3",
            key=f"{mqtt_prefix}main/Quiet_Mode_Schedule",
            name="Aquarea Quiet Mode Schedule",
            state=bit_to_bool,
        ),
        # deprecated since we have a switch now
        HeishaMonBinarySensorEntityDescription(
            heishamon_topic_id="TOP58",
            requires=(Feature.DHW,),
            key=f"{mqtt_prefix}main/DHW_Heater_State",
            name="Aquarea Tank Heater Enabled",
            state=bit_to_bool,
        ),
        # deprecated since we have a switch now
        HeishaMonBinarySensorEntityDescription(
            heishamon_topic_id="TOP59",
            key=f"{mqtt_prefix}main/Room_Heater_State",
            name="Aquarea Room Heater Enabled",
            state=bit_to_bool,
        ),
        HeishaMonBinarySensorEntityDescription(
            heishamon_topic_id="TOP60",
            key=f"{mqtt_prefix}main/Internal_Heater_State",
            name="Aquarea Internal Heater State",
            state=bit_to_bool,
            device_class=BinarySensorDeviceClass.RUNNING,
        ),
        HeishaMonBinarySensorEntityDescription(
            heishamon_topic_id="TOP61",
            key=f"{mqtt_prefix}main/External_Heater_State",
            name="Aquarea External Heater State",
            state=bit_to_bool,
            device_class=BinarySensorDeviceClass.RUNNING,
        ),
        HeishaMonBinarySensorEntityDescription(
            heishamon_topic_id="TOP68",
            key=f"{mqtt_prefix}main/Force_Heater_State",
            name="Aquarea Force heater status",
            state=bit_to_bool,
        ),
        HeishaMonBinarySensorEntityDescription(
            heishamon_topic_id="TOP93",
            key=f"{mqtt_prefix}main/Pump_Duty",
            name="Aquarea Pump Running",
            # TODO(kamaradclimber): it seems value is showing something more than just "on/off". Tests show value of 120 when running and slowly decreasing to 100
            state=positive_to_bool,
            device_class=BinarySensorDeviceClass.RUNNING,
        ),
        HeishaMonBinarySensorEntityDescription(
            heishamon_topic_id="TOP100",
            key=f"{mqtt_prefix}main/DHW_Installed",
            name="Aquarea DHW Installed",
            state=bit_to_bool,
        ),
        HeishaMonBinarySensorEntityDescription(
            heishamon_topic_id="TOP109",
            key=f"{mqtt_prefix}main/Anti_Freeze_Mode",
            name="Aquarea anti freeze mode",
            state=bit_to_bool,
            device_class=BinarySensorDeviceClass.RUNNING,
        ),
        HeishaMonBinarySensorEntityDescription(
            heishamon_topic_id="TOP110",
            key=f"{mqtt_prefix}main/Optional_PCB",
            name="Aquarea optional PCB enabled",
            state=bit_to_bool,
        ),
        HeishaMonBinarySensorEntityDescription(
            heishamon_topic_id="TOP132",
            requires=(Feature.BIVALENT,),
            key=f"{mqtt_prefix}main/Bivalent_Advanced_Heat",
            name="Aquarea Bivalent Advanced Heat",
            state=read_enabled_disabled,
            entity_registry_enabled_default=True,
        ),
        HeishaMonBinarySensorEntityDescription(
            heishamon_topic_id="TOP133",
            requires=(Feature.BIVALENT, Feature.DHW,),
            key=f"{mqtt_prefix}main/Bivalent_Advanced_DHW",
            name="Aquarea Bivalent Advanced DHW",
            state=read_enabled_disabled,
            entity_registry_enabled_default=True,
        ),
        HeishaMonBinarySensorEntityDescription(
            heishamon_topic_id="TOP123",
            key=f"{mqtt_prefix}main/Z1_Pump_State",
            name="Aquarea Zone 1 Pump State",
            state=bit_to_bool,
            device_class=BinarySensorDeviceClass.RUNNING,
        ),
        HeishaMonBinarySensorEntityDescription(
            heishamon_topic_id="TOP124",
            key=f"{mqtt_prefix}main/Z2_Pump_State",
            name="Aquarea Zone 2 Pump State",
            state=bit_to_bool,
            device_class=BinarySensorDeviceClass.RUNNING,
        ),
        HeishaMonBinarySensorEntityDescription(
            heishamon_topic_id="OPT0",
            key=f"{mqtt_prefix}optional/Z1_Water_Pump",
            name="Aquarea Zone 1 water pump action request",
            state=bit_to_bool,
            device_class=BinarySensorDeviceClass.RUNNING,
            entity_registry_enabled_default=False,  # by default we hide all options related to less common setup (cooling, buffer, solar and pool)
        ),
        HeishaMonBinarySensorEntityDescription(
            heishamon_topic_id="OPT2",
            key=f"{mqtt_prefix}optional/Z2_Water_Pump",
            name="Aquarea Zone 2 water pump action request",
            state=bit_to_bool,
            device_class=BinarySensorDeviceClass.RUNNING,
            entity_registry_enabled_default=False,  # by default we hide all options related to less common setup (cooling, buffer, solar and pool)
        ),
        HeishaMonBinarySensorEntityDescription(
            heishamon_topic_id="OPT4",
            key=f"{mqtt_prefix}optional/Pool_Water_Pump",
            name="Aquarea pool water pump action request",
            state=bit_to_bool,
            device_class=BinarySensorDeviceClass.RUNNING,
            entity_registry_enabled_default=False,  # by default we hide all options related to less common setup (cooling, buffer, solar and pool)
        ),
        HeishaMonBinarySensorEntityDescription(
            heishamon_topic_id="OPT5",
            key=f"{mqtt_prefix}optional/Solar_Water_Pump",
            name="Aquarea solar water pump action request",
            state=bit_to_bool,
            device_class=BinarySensorDeviceClass.RUNNING,
            entity_registry_enabled_default=False,  # by default we hide all options related to less common setup (cooling, buffer, solar and pool)
        ),
        HeishaMonBinarySensorEntityDescription(
            heishamon_topic_id="OPT6",
            key=f"{mqtt_prefix}optional/Alarm_State",
            name="Aquarea Alarm State",
            state=bit_to_bool,
            device_class=BinarySensorDeviceClass.PROBLEM,
            entity_registry_enabled_default=False,  # by default we hide all options related to less common setup (cooling, buffer, solar and pool)
        ),
        HeishaMonBinarySensorEntityDescription(
            heishamon_topic_id="TOP144",
            key=f"{mqtt_prefix}main/Dry_Concrete_State",
            name="Aquarea Dry concrete",
            state=bit_to_bool,
            entity_registry_enabled_default=False,
        ),
        HeishaMonBinarySensorEntityDescription(
            heishamon_topic_id="TOP150",
            key=f"{mqtt_prefix}main/Demand_Control",
            name="Aquarea Demand control enabled",
            state=bit_to_bool,
            requires=(Feature.OPTIONAL_PCB,),
            entity_registry_enabled_default=False,
        ),
        HeishaMonBinarySensorEntityDescription(
            heishamon_topic_id="TOP151",
            key=f"{mqtt_prefix}main/DHW_Defrost",
            name="Aquarea DHW defrost",
            state=bit_to_bool,
            requires=(Feature.DHW,),
            entity_registry_enabled_default=False,
        ),
        HeishaMonBinarySensorEntityDescription(
            heishamon_topic_id="TOP160",
            key=f"{mqtt_prefix}main/Quiet_Mode_Actual_State",
            name="Aquarea Quiet mode active",
            state=bit_to_bool,
            entity_registry_enabled_default=False,
        ),
        HeishaMonBinarySensorEntityDescription(
            heishamon_topic_id="TOP161",
            key=f"{mqtt_prefix}main/Powerful_Mode_Actual_State",
            name="Aquarea Powerful mode active",
            state=bit_to_bool,
            entity_registry_enabled_default=False,
        ),
        HeishaMonBinarySensorEntityDescription(
            heishamon_topic_id="TOP164",
            key=f"{mqtt_prefix}main/Bivalent_Boiler_Contact_State",
            name="Aquarea Bivalent boiler contact",
            state=bit_to_bool,
            requires=(Feature.BIVALENT,),
            entity_registry_enabled_default=False,
        ),
        HeishaMonBinarySensorEntityDescription(
            heishamon_topic_id="TOP165",
            key=f"{mqtt_prefix}main/Z2_Active",
            name="Aquarea Zone 2 active",
            state=bit_to_bool,
            entity_registry_enabled_default=False,
        ),
        HeishaMonBinarySensorEntityDescription(
            heishamon_topic_id="TOP166",
            key=f"{mqtt_prefix}main/Z1_Active",
            name="Aquarea Zone 1 active",
            state=bit_to_bool,
            entity_registry_enabled_default=False,
        ),
        HeishaMonBinarySensorEntityDescription(
            heishamon_topic_id="TOP167",
            key=f"{mqtt_prefix}main/Backup_Heater_Enable",
            name="Aquarea Backup heater enabled",
            state=bit_to_bool,
            entity_registry_enabled_default=False,
        ),
        HeishaMonBinarySensorEntityDescription(
            heishamon_topic_id="TOP168",
            key=f"{mqtt_prefix}main/Cooling_Enable",
            name="Aquarea Cooling enabled",
            state=bit_to_bool,
            entity_registry_enabled_default=False,
        ),
        HeishaMonBinarySensorEntityDescription(
            heishamon_topic_id="TOP170",
            key=f"{mqtt_prefix}main/Static_Pressure",
            name="Aquarea Static pressure",
            state=bit_to_bool,
            entity_registry_enabled_default=False,
        ),
        HeishaMonBinarySensorEntityDescription(
            heishamon_topic_id="TOP179",
            key=f"{mqtt_prefix}main/Anti_Stick_Mode",
            name="Aquarea Anti-stick mode",
            state=bit_to_bool,
            entity_registry_enabled_default=False,
        ),
        HeishaMonBinarySensorEntityDescription(
            heishamon_topic_id="TOP181",
            key=f"{mqtt_prefix}main/Bivalent_External_Pump",
            name="Aquarea Bivalent external pump",
            state=bit_to_bool,
            requires=(Feature.BIVALENT,),
            entity_registry_enabled_default=False,
        ),
        HeishaMonBinarySensorEntityDescription(
            heishamon_topic_id="TOP194",
            key=f"{mqtt_prefix}main/Defrost_Signal",
            name="Aquarea Defrost signal",
            state=bit_to_bool,
            entity_registry_enabled_default=False,
        ),
    ]


def _get_device_identifiers(device_info):
    """Return device identifiers, supporting old and new Home Assistant versions."""
    if device_info is None:
        return None
    if isinstance(device_info, dict):
        # Home Assistant < 2026.11 represented DeviceInfo as a TypedDict.
        return device_info.get("identifiers")
    return device_info.identifiers


def update_device_ip(
    hass: HomeAssistant, entity: SensorEntity, config_entry_id: str, ip: str
):
    _LOGGER.debug(f"Received ip address: {ip}")
    device_registry = dr.async_get(hass)
    identifiers = _get_device_identifiers(entity.device_info)
    device_registry.async_get_or_create(
        config_entry_id=config_entry_id,
        identifiers=identifiers,
        configuration_url=f"http://{ip}",
    )


K_L_SERIES_ENTITY_TOPIC_IDS = ["TOP115", "TOP116", "TOP117", "TOP118", "SET43"]


def is_kl_series(model: str) -> bool:
    """Return True if heatpump model belongs to K or L series."""
    return "K-series" in model or "L-series" in model


def update_device_model(
    hass: HomeAssistant, entity: SensorEntity, config_entry_id: str, model: str
):
    _LOGGER.debug("Set model")

    device_registry = dr.async_get(hass)
    identifiers = _get_device_identifiers(entity.device_info)
    device_registry.async_get_or_create(
        config_entry_id=config_entry_id, identifiers=identifiers, model=model
    )

    if is_kl_series(model):
        enable_kl_entities(hass, config_entry_id)


def enable_kl_entities(hass: HomeAssistant, config_entry_id: str):
    """Enable by default K/L-series entities still disabled by the integration.

    Entities the user disabled explicitly (disabled_by=USER) are left alone.
    """
    entity_registry = er.async_get(hass)
    reload_entry = False
    for topic_id in K_L_SERIES_ENTITY_TOPIC_IDS:
        unique_id = f"{config_entry_id}-{topic_id}"
        entry = entity_registry.async_get_entity_id("sensor", DOMAIN, unique_id) or \
            entity_registry.async_get_entity_id("select", DOMAIN, unique_id)
        if entry is None:
            continue
        registry_entry = entity_registry.async_get(entry)
        if registry_entry.disabled_by == er.RegistryEntryDisabler.INTEGRATION:
            entity_registry.async_update_entity(entry, disabled_by=None)
            reload_entry = True
            _LOGGER.info(
                "Detected K/L-series heatpump model, enabling entity %s", entry
            )
    if reload_entry:
        hass.async_create_task(hass.config_entries.async_reload(config_entry_id))


def read_heating_mode(value: str) -> Optional[str]:
    if value == "0":
        return "compensation curve"
    elif value == "1":
        return "direct"
    return None


HEATING_CONTROL = {
    "0": "Comfort",
    "1": "Efficiency",
}


def read_heating_control(value: str) -> Optional[str]:
    return HEATING_CONTROL.get(value, None)


def heating_control_to_mqtt(value: str) -> Optional[str]:
    return lookup_by_value(HEATING_CONTROL, value)


SMART_DHW = {
    "0": "Variable",
    "1": "Standard",
}


def read_smart_dhw(value: str) -> Optional[str]:
    return SMART_DHW.get(value, None)


def smart_dhw_to_mqtt(value: str) -> Optional[str]:
    return lookup_by_value(SMART_DHW, value)


QUIET_MODE_PRIORITY = {
    "0": "Sound",
    "1": "Capacity",
}


def read_quiet_mode_priority(value: str) -> Optional[str]:
    return QUIET_MODE_PRIORITY.get(value, None)


def quiet_mode_priority_to_mqtt(value: str) -> Optional[str]:
    return lookup_by_value(QUIET_MODE_PRIORITY, value)


DHW_SENSOR_SELECTION = {
    "0": "Top",
    "1": "Center",
}


def read_dhw_sensor_selection(value: str) -> Optional[str]:
    return DHW_SENSOR_SELECTION.get(value, None)


def dhw_sensor_selection_to_mqtt(value: str) -> Optional[str]:
    return lookup_by_value(DHW_SENSOR_SELECTION, value)

HEATER_STATE = {
    "0": "blocked",
    "1": "free",
}
def read_heater_state(value: str) -> Optional[str]:
    return HEATER_STATE.get(value, None)
def heater_state_to_mqtt(value: str) -> Optional[str]:
    return lookup_by_value(HEATER_STATE, value)

def read_temp(value: str) -> Optional[Any]:
    v = int(value)
    if v == -128:
        return None
    return value


def read_stats_json(field_name: str, json_doc: str) -> Optional[float]:
    field_value = json.loads(json_doc).get(field_name, None)
    if field_value:
        return float(field_value)
    return None


def read_board_type(json_doc: str) -> Optional[str]:
    j = json.loads(json_doc)
    if "board" in j:
        return j["board"]
    if "voltage" in j:
        # ESP32 has a static 3.3V and more than 64k free heap
        if j["voltage"] != 3.3:
            return "ESP8266"
        if "free heap" in j:
            if float(j["free heap"]) > 65535:
                return "ESP32"
    return None


def ms_to_secs(value: Optional[float]) -> Optional[float]:
    if value:
        return value / 1000
    return None


def build_sensors(mqtt_prefix: str) -> list[HeishaMonSensorEntityDescription]:
    return [
        HeishaMonSensorEntityDescription(
            heishamon_topic_id="TOP1",
            key=f"{mqtt_prefix}main/Pump_Flow",
            name="Aquarea Pump Flow",
            native_unit_of_measurement="L/min",
            device_class=SensorDeviceClass.VOLUME_FLOW_RATE,
            state_class=SensorStateClass.MEASUREMENT,
            suggested_display_precision=1,
        ),
        HeishaMonSensorEntityDescription(
            heishamon_topic_id="TOP5",
            key=f"{mqtt_prefix}main/Main_Inlet_Temp",
            state_class=SensorStateClass.MEASUREMENT,
            name="Aquarea Inlet Temperature",
            device_class=SensorDeviceClass.TEMPERATURE,
            native_unit_of_measurement="°C",
            suggested_display_precision=1,
        ),
        HeishaMonSensorEntityDescription(
            heishamon_topic_id="TOP6",
            key=f"{mqtt_prefix}main/Main_Outlet_Temp",
            state_class=SensorStateClass.MEASUREMENT,
            name="Aquarea Outlet Temperature",
            device_class=SensorDeviceClass.TEMPERATURE,
            native_unit_of_measurement="°C",
            suggested_display_precision=1,
        ),
        HeishaMonSensorEntityDescription(
            heishamon_topic_id="TOP7",
            key=f"{mqtt_prefix}main/Main_Target_Temp",
            state_class=SensorStateClass.MEASUREMENT,
            name="Aquarea Outlet Target Temperature",
            device_class=SensorDeviceClass.TEMPERATURE,
            native_unit_of_measurement="°C",
            suggested_display_precision=1,
        ),
        HeishaMonSensorEntityDescription(
            heishamon_topic_id="TOP8",
            key=f"{mqtt_prefix}main/Compressor_Freq",
            state_class=SensorStateClass.MEASUREMENT,
            name="Aquarea Compressor Frequency",
            device_class=SensorDeviceClass.FREQUENCY,
            native_unit_of_measurement="Hz",
            entity_category=EntityCategory.DIAGNOSTIC,
            suggested_display_precision=0,
        ),
        HeishaMonSensorEntityDescription(
            heishamon_topic_id="TOP10",
            requires=(Feature.DHW,),
            key=f"{mqtt_prefix}main/DHW_Temp",
            name="Aquarea Tank Actual Tank Temperature",
            device_class=SensorDeviceClass.TEMPERATURE,
            native_unit_of_measurement="°C",
            state_class=SensorStateClass.MEASUREMENT,
            suggested_display_precision=1,
        ),
        HeishaMonSensorEntityDescription(
            heishamon_topic_id="TOP11",
            key=f"{mqtt_prefix}main/Operations_Hours",
            name="Aquarea Compressor Operating Hours",
            device_class=SensorDeviceClass.DURATION,
            native_unit_of_measurement="h",
            state_class=SensorStateClass.TOTAL_INCREASING,
            entity_category=EntityCategory.DIAGNOSTIC,
            suggested_display_precision=0,
        ),
        HeishaMonSensorEntityDescription(
            heishamon_topic_id="TOP12",
            key=f"{mqtt_prefix}main/Operations_Counter",
            name="Aquarea Compressor Start/Stop Counter",
            state_class=SensorStateClass.TOTAL_INCREASING,
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
        HeishaMonSensorEntityDescription(
            heishamon_topic_id="TOP14",
            key=f"{mqtt_prefix}main/Outside_Temp",
            name="Aquarea Outdoor Ambient",
            device_class=SensorDeviceClass.TEMPERATURE,
            native_unit_of_measurement="°C",
            state_class=SensorStateClass.MEASUREMENT,
            suggested_display_precision=1,
        ),
        MultiMQTTSensorEntityDescription(
            heishamon_topic_id="TOP15",
            key=f"{mqtt_prefix}main/Heat_Power_Production",
            topics=[
                f"{mqtt_prefix}extra/Heat_Power_Production_Extra",  # XTOP3, fw >= 3.2.3
                f"{mqtt_prefix}extra/Heat_Power_Production",  # XTOP3
                f"{mqtt_prefix}main/Heat_Power_Production",
                f"{mqtt_prefix}main/Heat_Energy_Production",
            ],
            compute_state=first_positive,
            name="Aquarea Heat Power Produced",
            device_class=SensorDeviceClass.POWER,
            native_unit_of_measurement="W",
            state_class=SensorStateClass.MEASUREMENT,
            suggested_display_precision=0,
        ),
        MultiMQTTSensorEntityDescription(
            heishamon_topic_id="TOP16",
            key=f"{mqtt_prefix}main/Heat_Power_Consumption",
            topics=[
                f"{mqtt_prefix}extra/Heat_Power_Consumption_Extra",  # XTOP3, fw >= 3.2.3
                f"{mqtt_prefix}extra/Heat_Power_Consumption",  # XTOP0
                f"{mqtt_prefix}main/Heat_Power_Consumption",
                f"{mqtt_prefix}main/Heat_Energy_Consumption",
            ],
            compute_state=first_positive,
            name="Aquarea Heat Power Consumed",
            device_class=SensorDeviceClass.POWER,
            native_unit_of_measurement="W",
            state_class=SensorStateClass.MEASUREMENT,
            suggested_display_precision=0,
        ),
        HeishaMonSensorEntityDescription(
            heishamon_topic_id="TOP20",
            key=f"{mqtt_prefix}main/ThreeWay_Valve_State",
            name="Aquarea 3-way Valve",
            state=read_threeway_valve,
            options=["Room", "Tank"],
            device_class=SensorDeviceClass.ENUM,
        ),
        HeishaMonSensorEntityDescription(
            heishamon_topic_id="TOP125",
            key=f"{mqtt_prefix}main/TwoWay_Valve_State",
            name="Aquarea 2-way Valve",
            state=read_twoway_valve,
            options=["Cooling", "Heating"],
            device_class=SensorDeviceClass.ENUM,
        ),
        HeishaMonSensorEntityDescription(
            heishamon_topic_id="TOP21",
            key=f"{mqtt_prefix}main/Outside_Pipe_Temp",
            state_class=SensorStateClass.MEASUREMENT,
            name="Aquarea Outdoor Pipe Temperature",
            device_class=SensorDeviceClass.TEMPERATURE,
            native_unit_of_measurement="°C",
            suggested_display_precision=1,
        ),
        HeishaMonSensorEntityDescription(
            heishamon_topic_id="TOP23",
            key=f"{mqtt_prefix}main/Heat_Delta",
            state_class=SensorStateClass.MEASUREMENT,
            name="Aquarea Heat delta",
            device_class=SensorDeviceClass.TEMPERATURE_DELTA,
            native_unit_of_measurement="K",
            suggested_display_precision=1,
        ),
        HeishaMonSensorEntityDescription(
            heishamon_topic_id="TOP24",
            requires=(Feature.COOLING,),
            key=f"{mqtt_prefix}main/Cool_Delta",
            state_class=SensorStateClass.MEASUREMENT,
            name="Aquarea Cool delta",
            device_class=SensorDeviceClass.TEMPERATURE_DELTA,
            native_unit_of_measurement="K",
            entity_registry_enabled_default=False,  # by default we hide all options related to less common setup (cooling, buffer, solar and pool)
            suggested_display_precision=1,
        ),
        HeishaMonSensorEntityDescription(
            heishamon_topic_id="TOP25",
            requires=(Feature.DHW,),
            key=f"{mqtt_prefix}main/DHW_Holiday_Shift_Temp",
            state_class=SensorStateClass.MEASUREMENT,
            name="Aquarea DHW Holiday shift temperature",
            device_class=SensorDeviceClass.TEMPERATURE_DELTA,
            native_unit_of_measurement="K",
            suggested_display_precision=1,
        ),
        HeishaMonSensorEntityDescription(
            heishamon_topic_id="TOP33",
            key=f"{mqtt_prefix}main/Room_Thermostat_Temp",
            state_class=SensorStateClass.MEASUREMENT,
            name="Aquarea Remote control thermostat temperature",
            device_class=SensorDeviceClass.TEMPERATURE,
            native_unit_of_measurement="°C",
            suggested_display_precision=1,
        ),
        HeishaMonSensorEntityDescription(
            heishamon_topic_id="TOP36",
            key=f"{mqtt_prefix}main/Z1_Water_Temp",
            state_class=SensorStateClass.MEASUREMENT,
            name="Aquarea Zone 1 water outlet temperature",
            device_class=SensorDeviceClass.TEMPERATURE,
            native_unit_of_measurement="°C",
            state=read_temp,
            suggested_display_precision=1,
        ),
        HeishaMonSensorEntityDescription(
            heishamon_topic_id="TOP37",
            key=f"{mqtt_prefix}main/Z2_Water_Temp",
            state_class=SensorStateClass.MEASUREMENT,
            name="Aquarea Zone 2 water outlet temperature",
            device_class=SensorDeviceClass.TEMPERATURE,
            native_unit_of_measurement="°C",
            state=read_temp,
            suggested_display_precision=1,
        ),
        MultiMQTTSensorEntityDescription(
            heishamon_topic_id="TOP38",
            key=f"{mqtt_prefix}main/Cool_Power_Production",
            topics=[
                f"{mqtt_prefix}extra/Cool_Power_Production_Extra",  # XTOP4, fw >= 3.2.3
                f"{mqtt_prefix}extra/Cool_Power_Production",  # XTOP4
                f"{mqtt_prefix}main/Cool_Power_Production",
                f"{mqtt_prefix}main/Cool_Energy_Production",
            ],
            compute_state=first_positive,
            state_class=SensorStateClass.MEASUREMENT,
            name="Aquarea Thermal Cooling power production",
            device_class=SensorDeviceClass.POWER,
            native_unit_of_measurement="W",
            entity_registry_enabled_default=False,  # by default we hide all options related to less common setup (cooling, buffer, solar and pool)
            suggested_display_precision=0,
        ),
        MultiMQTTSensorEntityDescription(
            heishamon_topic_id="TOP39",
            key=f"{mqtt_prefix}main/Cool_Power_Consumption",
            topics=[
                f"{mqtt_prefix}extra/Cool_Power_Consumption_Extra",  # XTOP1, fw >= 3.2.3
                f"{mqtt_prefix}extra/Cool_Power_Consumption",  # XTOP1
                f"{mqtt_prefix}main/Cool_Power_Consumption",
                f"{mqtt_prefix}main/Cool_Energy_Consumption",
            ],
            compute_state=first_positive,
            state_class=SensorStateClass.MEASUREMENT,
            name="Aquarea Thermal Cooling power consumption",
            device_class=SensorDeviceClass.POWER,
            native_unit_of_measurement="W",
            entity_registry_enabled_default=False,  # by default we hide all options related to less common setup (cooling, buffer, solar and pool)
            suggested_display_precision=0,
        ),
        MultiMQTTSensorEntityDescription(
            heishamon_topic_id="TOP40",
            key=f"{mqtt_prefix}main/DHW_Power_Production",
            topics=[
                f"{mqtt_prefix}extra/DHW_Power_Production_Extra",  # XTOP5, fw >= 3.2.3
                f"{mqtt_prefix}extra/DHW_Power_Production",  # XTOP5
                f"{mqtt_prefix}main/DHW_Power_Production",
                f"{mqtt_prefix}main/DHW_Energy_Production",
            ],
            compute_state=first_positive,
            name="Aquarea DHW Power Produced",
            device_class=SensorDeviceClass.POWER,
            native_unit_of_measurement="W",
            state_class=SensorStateClass.MEASUREMENT,
            suggested_display_precision=0,
        ),
        MultiMQTTSensorEntityDescription(
            heishamon_topic_id="TOP41",
            key=f"{mqtt_prefix}main/DHW_Power_Consumption",
            topics=[
                f"{mqtt_prefix}extra/DHW_Power_Consumption_Extra",  # XTOP2, fw >= 3.2.3
                f"{mqtt_prefix}extra/DHW_Power_Consumption",  # XTOP2
                f"{mqtt_prefix}main/DHW_Power_Consumption",
                f"{mqtt_prefix}main/DHW_Energy_Consumption",
            ],
            compute_state=first_positive,
            name="Aquarea DHW Power Consumed",
            device_class=SensorDeviceClass.POWER,
            native_unit_of_measurement="W",
            state_class=SensorStateClass.MEASUREMENT,
            suggested_display_precision=0,
        ),
        HeishaMonSensorEntityDescription(
            heishamon_topic_id="TOP42",
            key=f"{mqtt_prefix}main/Z1_Water_Target_Temp",
            name="Aquarea Zone 1 water target temperature",
            device_class=SensorDeviceClass.TEMPERATURE,
            native_unit_of_measurement="°C",
            state_class=SensorStateClass.MEASUREMENT,
            suggested_display_precision=1,
        ),
        HeishaMonSensorEntityDescription(
            heishamon_topic_id="TOP43",
            key=f"{mqtt_prefix}main/Z2_Water_Target_Temp",
            name="Aquarea Zone 2 water target temperature",
            device_class=SensorDeviceClass.TEMPERATURE,
            native_unit_of_measurement="°C",
            state_class=SensorStateClass.MEASUREMENT,
            suggested_display_precision=1,
        ),
        HeishaMonSensorEntityDescription(
            heishamon_topic_id="TOP44",
            key=f"{mqtt_prefix}main/Error",
            name="Aquarea Last Error",
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
        HeishaMonSensorEntityDescription(
            heishamon_topic_id="TOP45",
            key=f"{mqtt_prefix}main/Room_Holiday_Shift_Temp",
            name="Aquarea Room heating Holiday shift temperature",
            device_class=SensorDeviceClass.TEMPERATURE_DELTA,
            native_unit_of_measurement="K",
            state_class=SensorStateClass.MEASUREMENT,
            suggested_display_precision=1,
        ),
        HeishaMonSensorEntityDescription(
            heishamon_topic_id="TOP46",
            requires=(Feature.BUFFER,),
            key=f"{mqtt_prefix}main/Buffer_Temp",
            name="Aquarea Actual Buffer temperature",
            device_class=SensorDeviceClass.TEMPERATURE,
            native_unit_of_measurement="°C",
            state_class=SensorStateClass.MEASUREMENT,
            entity_registry_enabled_default=False,  # by default we hide all options related to less common setup (cooling, buffer, solar and pool)
            suggested_display_precision=1,
        ),
        HeishaMonSensorEntityDescription(
            heishamon_topic_id="TOP47",
            requires=(Feature.SOLAR,),
            key=f"{mqtt_prefix}main/Solar_Temp",
            name="Aquarea Actual Solar temperature",
            device_class=SensorDeviceClass.TEMPERATURE,
            native_unit_of_measurement="°C",
            state_class=SensorStateClass.MEASUREMENT,
            entity_registry_enabled_default=False,  # by default we hide all options related to less common setup (cooling, buffer, solar and pool)
            suggested_display_precision=1,
        ),
        HeishaMonSensorEntityDescription(
            heishamon_topic_id="TOP48",
            key=f"{mqtt_prefix}main/Pool_Temp",
            name="Aquarea Actual Pool temperature",
            device_class=SensorDeviceClass.TEMPERATURE,
            native_unit_of_measurement="°C",
            state_class=SensorStateClass.MEASUREMENT,
            entity_registry_enabled_default=False,  # by default we hide all options related to less common setup (cooling, buffer, solar and pool)
            suggested_display_precision=1,
        ),
        HeishaMonSensorEntityDescription(
            heishamon_topic_id="TOP49",
            key=f"{mqtt_prefix}main/Main_Hex_Outlet_Temp",
            name="Aquarea Main HEX Outlet Temperature",
            device_class=SensorDeviceClass.TEMPERATURE,
            native_unit_of_measurement="°C",
            state_class=SensorStateClass.MEASUREMENT,
            suggested_display_precision=1,
        ),
        HeishaMonSensorEntityDescription(
            heishamon_topic_id="TOP50",
            key=f"{mqtt_prefix}main/Discharge_Temp",
            name="Aquarea Discharge Temperature",
            device_class=SensorDeviceClass.TEMPERATURE,
            native_unit_of_measurement="°C",
            state_class=SensorStateClass.MEASUREMENT,
            suggested_display_precision=1,
        ),
        HeishaMonSensorEntityDescription(
            heishamon_topic_id="TOP51",
            key=f"{mqtt_prefix}main/Inside_Pipe_Temp",
            name="Aquarea Inside Pipe Temperature",
            device_class=SensorDeviceClass.TEMPERATURE,
            native_unit_of_measurement="°C",
            state_class=SensorStateClass.MEASUREMENT,
            suggested_display_precision=1,
        ),
        HeishaMonSensorEntityDescription(
            heishamon_topic_id="TOP52",
            key=f"{mqtt_prefix}main/Defrost_Temp",
            name="Aquarea Defrost Temperature",
            device_class=SensorDeviceClass.TEMPERATURE,
            native_unit_of_measurement="°C",
            state_class=SensorStateClass.MEASUREMENT,
            suggested_display_precision=1,
        ),
        HeishaMonSensorEntityDescription(
            heishamon_topic_id="TOP53",
            key=f"{mqtt_prefix}main/Eva_Outlet_Temp",
            name="Aquarea Eva Outlet Temperature",
            device_class=SensorDeviceClass.TEMPERATURE,
            native_unit_of_measurement="°C",
            state_class=SensorStateClass.MEASUREMENT,
            suggested_display_precision=1,
        ),
        HeishaMonSensorEntityDescription(
            heishamon_topic_id="TOP54",
            key=f"{mqtt_prefix}main/Bypass_Outlet_Temp",
            name="Aquarea Bypass Outlet Temperature",
            device_class=SensorDeviceClass.TEMPERATURE,
            native_unit_of_measurement="°C",
            state_class=SensorStateClass.MEASUREMENT,
            suggested_display_precision=1,
        ),
        HeishaMonSensorEntityDescription(
            heishamon_topic_id="TOP55",
            key=f"{mqtt_prefix}main/Ipm_Temp",
            name="Aquarea Ipm Temperature",
            device_class=SensorDeviceClass.TEMPERATURE,
            native_unit_of_measurement="°C",
            state_class=SensorStateClass.MEASUREMENT,
            suggested_display_precision=1,
        ),
        HeishaMonSensorEntityDescription(
            heishamon_topic_id="TOP56",
            key=f"{mqtt_prefix}main/Z1_Temp",
            name="Aquarea Zone1: Actual Temperature",
            device_class=SensorDeviceClass.TEMPERATURE,
            native_unit_of_measurement="°C",
            state_class=SensorStateClass.MEASUREMENT,
            suggested_display_precision=1,
        ),
        HeishaMonSensorEntityDescription(
            heishamon_topic_id="TOP57",
            key=f"{mqtt_prefix}main/Z2_Temp",
            name="Aquarea Zone2: Actual Temperature",
            device_class=SensorDeviceClass.TEMPERATURE,
            native_unit_of_measurement="°C",
            state_class=SensorStateClass.MEASUREMENT,
            suggested_display_precision=1,
        ),
        HeishaMonSensorEntityDescription(
            heishamon_topic_id="TOP62",
            key=f"{mqtt_prefix}main/Fan1_Motor_Speed",
            name="Aquarea Fan 1 Speed",
            native_unit_of_measurement="R/min",
            state_class=SensorStateClass.MEASUREMENT,
            suggested_display_precision=0,
        ),
        HeishaMonSensorEntityDescription(
            heishamon_topic_id="TOP63",
            key=f"{mqtt_prefix}main/Fan2_Motor_Speed",
            name="Aquarea Fan 2 Speed",
            native_unit_of_measurement="R/min",
            state_class=SensorStateClass.MEASUREMENT,
            suggested_display_precision=0,
        ),
        HeishaMonSensorEntityDescription(
            heishamon_topic_id="TOP64",
            key=f"{mqtt_prefix}main/High_Pressure",
            name="Aquarea High pressure",
            native_unit_of_measurement="kPa",
            device_class=SensorDeviceClass.PRESSURE,
            state_class=SensorStateClass.MEASUREMENT,
            state=convert_pressure_to_kPa,
            suggested_display_precision=1,
        ),
        HeishaMonSensorEntityDescription(
            heishamon_topic_id="TOP65",
            key=f"{mqtt_prefix}main/Pump_Speed",
            name="Aquarea Pump Speed",
            native_unit_of_measurement="R/min",
            state_class=SensorStateClass.MEASUREMENT,
            suggested_display_precision=0,
        ),
        HeishaMonSensorEntityDescription(
            heishamon_topic_id="TOP66",
            key=f"{mqtt_prefix}main/Low_Pressure",
            name="Aquarea Low Pressure",
            native_unit_of_measurement="kPa",
            device_class=SensorDeviceClass.PRESSURE,
            state_class=SensorStateClass.MEASUREMENT,
            state=convert_pressure_to_kPa,
            suggested_display_precision=1,
        ),
        HeishaMonSensorEntityDescription(
            heishamon_topic_id="TOP67",
            key=f"{mqtt_prefix}main/Compressor_Current",
            name="Aquarea Compressor Current",
            device_class=SensorDeviceClass.CURRENT,
            native_unit_of_measurement="A",
            state_class=SensorStateClass.MEASUREMENT,
            entity_category=EntityCategory.DIAGNOSTIC,
            suggested_display_precision=2,
        ),
        HeishaMonSensorEntityDescription(
            heishamon_topic_id="TOP70",
            requires=(Feature.DHW,),
            key=f"{mqtt_prefix}main/Sterilization_Temp",
            name="Aquarea Sterilization Temperature",
            device_class=SensorDeviceClass.TEMPERATURE,
            native_unit_of_measurement="°C",
            state_class=SensorStateClass.MEASUREMENT,
            suggested_display_precision=1,
        ),
        HeishaMonSensorEntityDescription(
            heishamon_topic_id="TOP71",
            requires=(Feature.DHW,),
            key=f"{mqtt_prefix}main/Sterilization_Max_Time",
            name="Aquarea Sterilization maximum time",
            device_class=SensorDeviceClass.DURATION,
            native_unit_of_measurement="min",
            state_class=SensorStateClass.MEASUREMENT,
            suggested_display_precision=0,
        ),
        HeishaMonSensorEntityDescription(
            heishamon_topic_id="TOP76",
            key=f"{mqtt_prefix}main/Heating_Mode",
            name="Aquarea Heating Mode",
            state=read_heating_mode,
            device_class=SensorDeviceClass.ENUM,
            options=["compensation curve", "direct"],
        ),
        HeishaMonSensorEntityDescription(
            heishamon_topic_id="TOP78",
            key=f"{mqtt_prefix}main/Heater_On_Outdoor_Temp",
            name="Aquarea Outdoor temperature backup heater power on",
            device_class=SensorDeviceClass.TEMPERATURE,
            native_unit_of_measurement="°C",
            state_class=SensorStateClass.MEASUREMENT,
            suggested_display_precision=1,
        ),
        HeishaMonSensorEntityDescription(
            heishamon_topic_id="TOP79",
            requires=(Feature.COOLING,),
            key=f"{mqtt_prefix}main/Heat_To_Cool_Temp",
            name="Aquarea Outdoor temperature heat->cool threshold",  # when in "auto" mode
            device_class=SensorDeviceClass.TEMPERATURE,
            native_unit_of_measurement="°C",
            state_class=SensorStateClass.MEASUREMENT,
            entity_registry_enabled_default=False,  # by default we hide all options related to less common setup (cooling, buffer, solar and pool)
            suggested_display_precision=1,
        ),
        HeishaMonSensorEntityDescription(
            heishamon_topic_id="TOP80",
            requires=(Feature.COOLING,),
            key=f"{mqtt_prefix}main/Cool_To_Heat_Temp",
            name="Aquarea Outdoor temperature cool->heat threshold",  # when in "auto" mode
            device_class=SensorDeviceClass.TEMPERATURE,
            native_unit_of_measurement="°C",
            state_class=SensorStateClass.MEASUREMENT,
            entity_registry_enabled_default=False,  # by default we hide all options related to less common setup (cooling, buffer, solar and pool)
            suggested_display_precision=1,
        ),
        HeishaMonSensorEntityDescription(
            heishamon_topic_id="TOP81",
            requires=(Feature.COOLING,),
            key=f"{mqtt_prefix}main/Cooling_Mode",
            name="Aquarea Cooling Mode",
            state=read_heating_mode,
            device_class=SensorDeviceClass.ENUM,
            options=["compensation curve", "direct"],
            entity_registry_enabled_default=False,  # by default we hide all options related to less common setup (cooling, buffer, solar and pool)
        ),
        HeishaMonSensorEntityDescription(
            heishamon_topic_id="TOP90",
            key=f"{mqtt_prefix}main/Room_Heater_Operations_Hours",
            name="Aquarea Electric heater operating time for Room",
            device_class=SensorDeviceClass.DURATION,
            native_unit_of_measurement="h",
            state_class=SensorStateClass.MEASUREMENT,
            suggested_display_precision=0,
        ),
        HeishaMonSensorEntityDescription(
            heishamon_topic_id="TOP91",
            requires=(Feature.DHW,),
            key=f"{mqtt_prefix}main/DHW_Heater_Operations_Hours",
            name="Aquarea Electric heater operating time for DHW",
            device_class=SensorDeviceClass.DURATION,
            native_unit_of_measurement="h",
            state_class=SensorStateClass.MEASUREMENT,
            suggested_display_precision=0,
        ),
        HeishaMonSensorEntityDescription(
            heishamon_topic_id="TOP92",
            key=f"{mqtt_prefix}main/Heat_Pump_Model",
            name="Aquarea Heatpump model",
            state=read_heatpump_model,
            on_receive=update_device_model,
        ),
        HeishaMonSensorEntityDescription(
            heishamon_topic_id="TOP93",
            key=f"{mqtt_prefix}main/Pump_Duty",
            name="Aquarea Pump Duty",
            native_unit_of_measurement="Count",
        ),
        HeishaMonSensorEntityDescription(
            heishamon_topic_id="TOP101",
            requires=(Feature.OPTIONAL_PCB,),
            key=f"{mqtt_prefix}main/Solar_Mode",
            name="Aquarea Solar Mode",
            state=read_solar_mode,
            entity_registry_enabled_default=False,  # by default we hide all options related to less common setup (cooling, buffer, solar and pool)
        ),
        HeishaMonSensorEntityDescription(
            heishamon_topic_id="TOP102",
            requires=(Feature.SOLAR,),
            key=f"{mqtt_prefix}main/Solar_On_Delta",
            name="Aquarea Solar delta on",
            device_class=SensorDeviceClass.TEMPERATURE_DELTA,
            native_unit_of_measurement="K",
            state=int,
            entity_registry_enabled_default=False,  # by default we hide all options related to less common setup (cooling, buffer, solar and pool)
            suggested_display_precision=1,
        ),
        HeishaMonSensorEntityDescription(
            heishamon_topic_id="TOP103",
            requires=(Feature.SOLAR,),
            key=f"{mqtt_prefix}main/Solar_Off_Delta",
            name="Aquarea Solar delta off",
            device_class=SensorDeviceClass.TEMPERATURE_DELTA,
            native_unit_of_measurement="K",
            state=int,
            entity_registry_enabled_default=False,  # by default we hide all options related to less common setup (cooling, buffer, solar and pool)
            suggested_display_precision=1,
        ),
        HeishaMonSensorEntityDescription(
            heishamon_topic_id="TOP104",
            requires=(Feature.SOLAR,),
            key=f"{mqtt_prefix}main/Solar_Frost_Protection",
            name="Aquarea Solar frost protection temperature",
            device_class=SensorDeviceClass.TEMPERATURE,
            native_unit_of_measurement="°C",
            state=int,
            entity_registry_enabled_default=False,  # by default we hide all options related to less common setup (cooling, buffer, solar and pool)
            suggested_display_precision=1,
        ),
        HeishaMonSensorEntityDescription(
            heishamon_topic_id="TOP105",
            requires=(Feature.SOLAR,),
            key=f"{mqtt_prefix}main/Solar_High_Limit",
            name="Aquarea Solar max temperature limit",
            device_class=SensorDeviceClass.TEMPERATURE,
            native_unit_of_measurement="°C",
            state=int,
            entity_registry_enabled_default=False,  # by default we hide all options related to less common setup (cooling, buffer, solar and pool)
            suggested_display_precision=1,
        ),
        HeishaMonSensorEntityDescription(
            heishamon_topic_id="TOP106",
            key=f"{mqtt_prefix}main/Pump_Flowrate_Mode",
            name="Aquarea Pump flowrate mode",
            state=read_pump_flowrate_mode,
            device_class=SensorDeviceClass.ENUM,
            options=list(PUMP_FLOWRATE_MODE.values()),
            entity_registry_enabled_default=False,  # deprecated, use SET42 select entity instead
        ),
        HeishaMonSensorEntityDescription(
            heishamon_topic_id="TOP107",
            key=f"{mqtt_prefix}main/Liquid_Type",
            name="Aquarea Liquid Type",
            state=read_liquid_type,
        ),
        HeishaMonSensorEntityDescription(
            heishamon_topic_id="TOP111",
            key=f"{mqtt_prefix}main/Z2_Sensor_Settings",
            name="Aquarea Zone 2 sensor setting",
            state=read_zone_sensor_type,
        ),
        HeishaMonSensorEntityDescription(
            heishamon_topic_id="TOP112",
            key=f"{mqtt_prefix}main/Z1_Sensor_Settings",
            name="Aquarea Zone 1 sensor setting",
            state=read_zone_sensor_type,
        ),
        HeishaMonSensorEntityDescription(
            heishamon_topic_id="TOP113",
            requires=(Feature.BUFFER,),
            key=f"{mqtt_prefix}main/Buffer_Tank_Delta",
            state_class=SensorStateClass.MEASUREMENT,
            name="Aquarea Buffer tank delta",
            device_class=SensorDeviceClass.TEMPERATURE_DELTA,
            native_unit_of_measurement="K",
            entity_registry_enabled_default=False,  # by default we hide all options related to less common setup (cooling, buffer, solar and pool)
            suggested_display_precision=1,
        ),
        HeishaMonSensorEntityDescription(
            heishamon_topic_id="TOP115",
            key=f"{mqtt_prefix}main/Water_Pressure",
            state_class=SensorStateClass.MEASUREMENT,
            name="Aquarea Water Pressure",
            device_class=SensorDeviceClass.PRESSURE,
            native_unit_of_measurement="bar",
            entity_registry_enabled_default=False,  # K/L Series
            suggested_display_precision=1,
        ),
        HeishaMonSensorEntityDescription(
            heishamon_topic_id="TOP116",
            key=f"{mqtt_prefix}main/Second_Inlet_Temp",
            state_class=SensorStateClass.MEASUREMENT,
            name="Aquarea Inlet 2 Temperature",
            device_class=SensorDeviceClass.TEMPERATURE,
            native_unit_of_measurement="°C",
            entity_registry_enabled_default=False,  # K/L Series
            suggested_display_precision=1,
        ),
        HeishaMonSensorEntityDescription(
            heishamon_topic_id="TOP117",
            key=f"{mqtt_prefix}main/Economizer_Outlet_Temp",
            state_class=SensorStateClass.MEASUREMENT,
            name="Aquarea Economizer Outlet Temperature",
            device_class=SensorDeviceClass.TEMPERATURE,
            native_unit_of_measurement="°C",
            entity_registry_enabled_default=False,  # K/L Series
            suggested_display_precision=1,
        ),
        HeishaMonSensorEntityDescription(
            heishamon_topic_id="TOP118",
            key=f"{mqtt_prefix}main/Second_Room_Thermostat_Temp",
            state_class=SensorStateClass.MEASUREMENT,
            name="Aquarea Remote control 2 thermostat temp",
            device_class=SensorDeviceClass.TEMPERATURE,
            native_unit_of_measurement="°C",
            entity_registry_enabled_default=False,  # K/L Series
            suggested_display_precision=1,
        ),
        HeishaMonSensorEntityDescription(
            heishamon_topic_id="TOP127",
            key=f"{mqtt_prefix}main/Z1_Valve_PID",
            state_class=SensorStateClass.MEASUREMENT,
            name="Aquarea Zone 1 valve PID",
            native_unit_of_measurement="%",
            entity_registry_enabled_default=True,
            suggested_display_precision=0,
        ),
        HeishaMonSensorEntityDescription(
            heishamon_topic_id="TOP128",
            key=f"{mqtt_prefix}main/Z2_Valve_PID",
            state_class=SensorStateClass.MEASUREMENT,
            name="Aquarea Zone 2 valve PID",
            native_unit_of_measurement="%",
            entity_registry_enabled_default=True,
            suggested_display_precision=0,
        ),
        HeishaMonSensorEntityDescription(
            heishamon_topic_id="TOP131",
            requires=(Feature.BIVALENT,),
            key=f"{mqtt_prefix}main/Bivalent_Start_Temp",
            state_class=SensorStateClass.MEASUREMENT,
            device_class=SensorDeviceClass.TEMPERATURE,
            name="Aquarea Bivalent start Temperature",
            state=int,
            native_unit_of_measurement="°C",
            entity_registry_enabled_default=True,
            suggested_display_precision=1,
        ),
        HeishaMonSensorEntityDescription(
            heishamon_topic_id="TOP136",
            requires=(Feature.BIVALENT,),
            key=f"{mqtt_prefix}main/Bivalent_Advanced_Start_Delay",
            state_class=SensorStateClass.MEASUREMENT,
            device_class=SensorDeviceClass.DURATION,
            name="Aquarea Bivalent advanced start Delay",
            state=int,
            native_unit_of_measurement="min",
            entity_registry_enabled_default=True,
            suggested_display_precision=0,
        ),
        HeishaMonSensorEntityDescription(
            heishamon_topic_id="TOP137",
            requires=(Feature.BIVALENT,),
            key=f"{mqtt_prefix}main/Bivalent_Advanced_Stop_Delay",
            state_class=SensorStateClass.MEASUREMENT,
            device_class=SensorDeviceClass.DURATION,
            name="Aquarea Bivalent advanced stop Delay",
            state=int,
            native_unit_of_measurement="min",
            entity_registry_enabled_default=True,
            suggested_display_precision=0,
        ),
        HeishaMonSensorEntityDescription(
            heishamon_topic_id="TOP138",
            requires=(Feature.BIVALENT, Feature.DHW,),
            key=f"{mqtt_prefix}main/Bivalent_Advanced_DHW_Delay",
            state_class=SensorStateClass.MEASUREMENT,
            device_class=SensorDeviceClass.DURATION,
            name="Aquarea Bivalent advanced DHW Delay",
            state=int,
            native_unit_of_measurement="min",
            entity_registry_enabled_default=True,
            suggested_display_precision=0,
        ),
        HeishaMonSensorEntityDescription(
            heishamon_topic_id="TOP139",
            key=f"{mqtt_prefix}main/Heating_Control",
            name="Aquarea Heating Control",
            state=read_heating_control,
            device_class=SensorDeviceClass.ENUM,
            options=list(HEATING_CONTROL.values()),
            entity_registry_enabled_default=False,  # deprecated, use SET39 select entity instead
        ),
        HeishaMonSensorEntityDescription(
            heishamon_topic_id="TOP140",
            requires=(Feature.DHW,),
            key=f"{mqtt_prefix}main/Smart_DHW",
            name="Aquarea Smart DHW",
            state=read_smart_dhw,
            device_class=SensorDeviceClass.ENUM,
            options=list(SMART_DHW.values()),
            entity_registry_enabled_default=False,  # deprecated, use SET40 select entity instead
        ),
        HeishaMonSensorEntityDescription(
            heishamon_topic_id="TOP141",
            key=f"{mqtt_prefix}main/Quiet_Mode_Priority",
            name="Aquarea Quiet Mode Priority",
            state=read_quiet_mode_priority,
            device_class=SensorDeviceClass.ENUM,
            options=list(QUIET_MODE_PRIORITY.values()),
            entity_registry_enabled_default=False,  # deprecated, use SET41 select entity instead
        ),
        HeishaMonSensorEntityDescription(
            heishamon_topic_id="TOP142",
            key=f"{mqtt_prefix}main/Expansion_Valve",
            name="Aquarea Expansion Valve",
            native_unit_of_measurement="Steps",
            state_class=SensorStateClass.MEASUREMENT,
            state=int,
            suggested_display_precision=0,
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
        HeishaMonSensorEntityDescription(
            heishamon_topic_id="STAT1_rssi",
            key=f"{mqtt_prefix}stats",
            name="HeishaMon RSSI",
            state=partial(read_stats_json, "wifi"),
            device=DeviceType.HEISHAMON,
            native_unit_of_measurement="%",
            state_class=SensorStateClass.MEASUREMENT,
            entity_category=EntityCategory.DIAGNOSTIC,
            suggested_display_precision=0,
        ),
        HeishaMonSensorEntityDescription(
            heishamon_topic_id="STAT1_uptime",
            key=f"{mqtt_prefix}stats",
            name="HeishaMon Uptime",
            state=lambda json_doc: ms_to_secs(read_stats_json("uptime", json_doc)),
            device=DeviceType.HEISHAMON,
            device_class=SensorDeviceClass.DURATION,
            native_unit_of_measurement="s",
            state_class=SensorStateClass.MEASUREMENT,
            entity_category=EntityCategory.DIAGNOSTIC,
            suggested_display_precision=0,
        ),
        HeishaMonSensorEntityDescription(
            heishamon_topic_id="STAT1_total_reads",
            key=f"{mqtt_prefix}stats",
            name="HeishaMon Total reads",
            state=partial(read_stats_json, "total reads"),
            device=DeviceType.HEISHAMON,
            entity_category=EntityCategory.DIAGNOSTIC,
            state_class=SensorStateClass.TOTAL_INCREASING,
        ),
        HeishaMonSensorEntityDescription(
            heishamon_topic_id="STAT1_good_reads",
            key=f"{mqtt_prefix}stats",
            name="HeishaMon Good reads",
            state=partial(read_stats_json, "good reads"),
            device=DeviceType.HEISHAMON,
            entity_category=EntityCategory.DIAGNOSTIC,
            state_class=SensorStateClass.TOTAL_INCREASING,
        ),
        HeishaMonSensorEntityDescription(
            heishamon_topic_id="STAT1_badcrc_reads",
            key=f"{mqtt_prefix}stats",
            name="HeishaMon bad CRC reads",
            state=partial(read_stats_json, "bad crc reads"),
            device=DeviceType.HEISHAMON,
            entity_category=EntityCategory.DIAGNOSTIC,
            state_class=SensorStateClass.TOTAL_INCREASING,
        ),
        HeishaMonSensorEntityDescription(
            heishamon_topic_id="STAT1_badheader_reads",
            key=f"{mqtt_prefix}stats",
            name="HeishaMon bad header reads",
            state=partial(read_stats_json, "bad header reads"),
            device=DeviceType.HEISHAMON,
            entity_category=EntityCategory.DIAGNOSTIC,
            state_class=SensorStateClass.TOTAL_INCREASING,
        ),
        HeishaMonSensorEntityDescription(
            heishamon_topic_id="STAT1_tooshort_reads",
            key=f"{mqtt_prefix}stats",
            name="HeishaMon too short reads",
            state=partial(read_stats_json, "too short reads"),
            device=DeviceType.HEISHAMON,
            entity_category=EntityCategory.DIAGNOSTIC,
            state_class=SensorStateClass.TOTAL_INCREASING,
        ),
        HeishaMonSensorEntityDescription(
            heishamon_topic_id="STAT1_toolong_reads",
            key=f"{mqtt_prefix}stats",
            name="HeishaMon too long reads",
            state=partial(read_stats_json, "too long reads"),
            device=DeviceType.HEISHAMON,
            entity_category=EntityCategory.DIAGNOSTIC,
            state_class=SensorStateClass.TOTAL_INCREASING,
        ),
        HeishaMonSensorEntityDescription(
            heishamon_topic_id="STAT1_timeout_reads",
            key=f"{mqtt_prefix}stats",
            name="HeishaMon timeout reads",
            state=partial(read_stats_json, "timeout reads"),
            device=DeviceType.HEISHAMON,
            entity_category=EntityCategory.DIAGNOSTIC,
            state_class=SensorStateClass.TOTAL_INCREASING,
        ),
        HeishaMonSensorEntityDescription(
            heishamon_topic_id="STAT1_voltage",
            key=f"{mqtt_prefix}stats",
            name="HeishaMon voltage",
            state=partial(read_stats_json, "voltage"),
            device=DeviceType.HEISHAMON,
            native_unit_of_measurement="V",
            device_class=SensorDeviceClass.VOLTAGE,
            state_class=SensorStateClass.MEASUREMENT,
            entity_category=EntityCategory.DIAGNOSTIC,
            suggested_display_precision=2,
        ),
        HeishaMonSensorEntityDescription(
            heishamon_topic_id="STAT1_freememory",
            key=f"{mqtt_prefix}stats",
            name="HeishaMon free memory",
            state=partial(read_stats_json, "free memory"),
            device=DeviceType.HEISHAMON,
            native_unit_of_measurement="%",
            state_class=SensorStateClass.MEASUREMENT,
            entity_category=EntityCategory.DIAGNOSTIC,
            suggested_display_precision=0,
        ),
        HeishaMonSensorEntityDescription(
            heishamon_topic_id="STAT1_freeheap",
            key=f"{mqtt_prefix}stats",
            name="HeishaMon free heap",
            state=partial(read_stats_json, "free heap"),
            device=DeviceType.HEISHAMON,
            state_class=SensorStateClass.MEASUREMENT,
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
        HeishaMonSensorEntityDescription(
            heishamon_topic_id="STAT1-mqttreconnects",
            key=f"{mqtt_prefix}stats",
            name="HeishaMon mqtt reconnects",
            state=partial(read_stats_json, "mqtt reconnects"),
            device=DeviceType.HEISHAMON,
            entity_category=EntityCategory.DIAGNOSTIC,
            state_class=SensorStateClass.TOTAL_INCREASING,
        ),
        HeishaMonSensorEntityDescription(
            heishamon_topic_id="STAT1-active-rules",
            key=f"{mqtt_prefix}stats",
            name="HeishaMon Active rules",
            state=partial(read_stats_json, "rules active"),
            device=DeviceType.HEISHAMON,
            entity_category=EntityCategory.DIAGNOSTIC,
            state_class=SensorStateClass.MEASUREMENT,
        ),
        HeishaMonSensorEntityDescription(
            heishamon_topic_id="STAT1-board",
            key=f"{mqtt_prefix}stats",
            name="HeishaMon Board type",
            state=read_board_type,
            device=DeviceType.HEISHAMON,
            device_class=SensorDeviceClass.ENUM,
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
        HeishaMonSensorEntityDescription(
            heishamon_topic_id="INFO_ip",
            key=f"{mqtt_prefix}ip",
            name="HeishaMon IP Address",
            device=DeviceType.HEISHAMON,
            entity_category=EntityCategory.DIAGNOSTIC,
            on_receive=update_device_ip,
        ),
        HeishaMonSensorEntityDescription(
            heishamon_topic_id="OPT1",
            key=f"{mqtt_prefix}optional/Z1_Mixing_Valve",
            name="Aquarea Zone 1 mixing valve request",
            state=read_mixing_valve_request,
            device_class=SensorDeviceClass.ENUM,
            options=["Off", "Decrease", "Increase"],
            entity_registry_enabled_default=False,  # by default we hide all options related to less common setup (cooling, buffer, solar and pool)
        ),
        HeishaMonSensorEntityDescription(
            heishamon_topic_id="OPT3",
            key=f"{mqtt_prefix}optional/Z2_Mixing_Valve",
            name="Aquarea Zone 2 mixing valve request",
            state=read_mixing_valve_request,
            device_class=SensorDeviceClass.ENUM,
            options=["Off", "Decrease", "Increase"],
            entity_registry_enabled_default=False,  # by default we hide all options related to less common setup (cooling, buffer, solar and pool)
        ),
        HeishaMonSensorEntityDescription(
            heishamon_topic_id="TOP145",
            key=f"{mqtt_prefix}main/DHW_Capacity_Mode",
            name="Aquarea DHW capacity mode",
            state=read_parity_dhw_capacity_mode,
            device_class=SensorDeviceClass.ENUM,
            options=list(PARITY_DHW_CAPACITY_MODE.values()),
            requires=(Feature.DHW,),
            entity_registry_enabled_default=False,
        ),
        HeishaMonSensorEntityDescription(
            heishamon_topic_id="TOP146",
            key=f"{mqtt_prefix}main/Zone_Configuration",
            name="Aquarea Zone configuration",
            state=read_parity_zone_configuration,
            device_class=SensorDeviceClass.ENUM,
            options=list(PARITY_ZONE_CONFIGURATION.values()),
            entity_registry_enabled_default=False,
        ),
        HeishaMonSensorEntityDescription(
            heishamon_topic_id="TOP147",
            key=f"{mqtt_prefix}main/Internal_Heater_Capacity",
            name="Aquarea Internal heater capacity",
            native_unit_of_measurement="kW",
            device_class=SensorDeviceClass.POWER,
            state=read_optional_int,
            entity_registry_enabled_default=False,
        ),
        HeishaMonSensorEntityDescription(
            heishamon_topic_id="TOP148",
            key=f"{mqtt_prefix}main/DHW_Heater_Type",
            name="Aquarea DHW heater type",
            state=read_parity_dhw_heater_type,
            device_class=SensorDeviceClass.ENUM,
            options=list(PARITY_DHW_HEATER_TYPE.values()),
            requires=(Feature.DHW,),
            entity_registry_enabled_default=False,
        ),
        HeishaMonSensorEntityDescription(
            heishamon_topic_id="TOP149",
            key=f"{mqtt_prefix}main/SG_Ready_Control",
            name="Aquarea SG ready control",
            state=read_parity_sg_ready_control,
            device_class=SensorDeviceClass.ENUM,
            options=list(PARITY_SG_READY_CONTROL.values()),
            requires=(Feature.OPTIONAL_PCB,),
            entity_registry_enabled_default=False,
        ),
        HeishaMonSensorEntityDescription(
            heishamon_topic_id="TOP152",
            key=f"{mqtt_prefix}main/Dry_Concrete_Target_Temp",
            name="Aquarea Dry concrete target temperature",
            native_unit_of_measurement="°C",
            device_class=SensorDeviceClass.TEMPERATURE,
            state=float,
            entity_registry_enabled_default=False,
        ),
        HeishaMonSensorEntityDescription(
            heishamon_topic_id="TOP153",
            key=f"{mqtt_prefix}main/Pool_Delta",
            name="Aquarea Pool delta",
            native_unit_of_measurement="K",
            state=float,
            entity_registry_enabled_default=False,
        ),
        HeishaMonSensorEntityDescription(
            heishamon_topic_id="TOP154",
            key=f"{mqtt_prefix}main/SG_Ready_1_Heat_Capacity",
            name="Aquarea SG ready 1 heating capacity",
            native_unit_of_measurement="%",
            state=float,
            requires=(Feature.SG_READY,),
            entity_registry_enabled_default=False,
        ),
        HeishaMonSensorEntityDescription(
            heishamon_topic_id="TOP155",
            key=f"{mqtt_prefix}main/SG_Ready_1_DHW_Capacity",
            name="Aquarea SG ready 1 DHW capacity",
            native_unit_of_measurement="%",
            state=float,
            requires=(Feature.SG_READY, Feature.DHW,),
            entity_registry_enabled_default=False,
        ),
        HeishaMonSensorEntityDescription(
            heishamon_topic_id="TOP156",
            key=f"{mqtt_prefix}main/SG_Ready_2_Heat_Capacity",
            name="Aquarea SG ready 2 heating capacity",
            native_unit_of_measurement="%",
            state=float,
            requires=(Feature.SG_READY,),
            entity_registry_enabled_default=False,
        ),
        HeishaMonSensorEntityDescription(
            heishamon_topic_id="TOP157",
            key=f"{mqtt_prefix}main/SG_Ready_2_DHW_Capacity",
            name="Aquarea SG ready 2 DHW capacity",
            native_unit_of_measurement="%",
            state=float,
            requires=(Feature.SG_READY, Feature.DHW,),
            entity_registry_enabled_default=False,
        ),
        HeishaMonSensorEntityDescription(
            heishamon_topic_id="TOP158",
            key=f"{mqtt_prefix}main/Room_Operation_Max_Time",
            name="Aquarea Room operation maximum time",
            native_unit_of_measurement="min",
            device_class=SensorDeviceClass.DURATION,
            state=float,
            requires=(Feature.DHW,),
            entity_registry_enabled_default=False,
        ),
        HeishaMonSensorEntityDescription(
            heishamon_topic_id="TOP159",
            key=f"{mqtt_prefix}main/DHW_Heatup_Max_Time",
            name="Aquarea DHW heat-up maximum time",
            native_unit_of_measurement="min",
            device_class=SensorDeviceClass.DURATION,
            state=float,
            requires=(Feature.DHW,),
            entity_registry_enabled_default=False,
        ),
        HeishaMonSensorEntityDescription(
            heishamon_topic_id="TOP162",
            key=f"{mqtt_prefix}main/Heat_Cool_Switch_State",
            name="Aquarea Heat/cool switch state",
            state=read_parity_heat_cool_switch,
            device_class=SensorDeviceClass.ENUM,
            options=list(PARITY_HEAT_COOL_SWITCH.values()),
            requires=(Feature.OPTIONAL_PCB,),
            entity_registry_enabled_default=False,
        ),
        HeishaMonSensorEntityDescription(
            heishamon_topic_id="TOP163",
            key=f"{mqtt_prefix}main/External_Switch_State",
            name="Aquarea External switch state",
            state=read_parity_external_switch,
            device_class=SensorDeviceClass.ENUM,
            options=list(PARITY_EXTERNAL_SWITCH.values()),
            entity_registry_enabled_default=False,
        ),
        HeishaMonSensorEntityDescription(
            heishamon_topic_id="TOP169",
            key=f"{mqtt_prefix}main/Heat_Request_Temp_With_Buffer",
            name="Aquarea Heat request temperature with buffer",
            native_unit_of_measurement="°C",
            device_class=SensorDeviceClass.TEMPERATURE,
            state=float,
            requires=(Feature.BUFFER,),
            entity_registry_enabled_default=False,
        ),
        HeishaMonSensorEntityDescription(
            heishamon_topic_id="TOP171",
            key=f"{mqtt_prefix}main/Heating_On_Outdoor_Temp",
            name="Aquarea Outdoor temperature heating on",
            native_unit_of_measurement="°C",
            device_class=SensorDeviceClass.TEMPERATURE,
            state=float,
            entity_registry_enabled_default=False,
        ),
        HeishaMonSensorEntityDescription(
            heishamon_topic_id="TOP172",
            key=f"{mqtt_prefix}main/Heating_On_Delay",
            name="Aquarea Heating on delay",
            native_unit_of_measurement="min",
            device_class=SensorDeviceClass.DURATION,
            state=float,
            entity_registry_enabled_default=False,
        ),
        HeishaMonSensorEntityDescription(
            heishamon_topic_id="TOP173",
            key=f"{mqtt_prefix}main/DHW_Booster_Delay",
            name="Aquarea DHW booster heater delay",
            native_unit_of_measurement="min",
            device_class=SensorDeviceClass.DURATION,
            state=float,
            requires=(Feature.DHW,),
            entity_registry_enabled_default=False,
        ),
        HeishaMonSensorEntityDescription(
            heishamon_topic_id="TOP174",
            key=f"{mqtt_prefix}main/Efficiency_Stage1_Time",
            name="Aquarea Efficiency stage 1 time",
            native_unit_of_measurement="min",
            device_class=SensorDeviceClass.DURATION,
            state=float,
            entity_registry_enabled_default=False,
        ),
        HeishaMonSensorEntityDescription(
            heishamon_topic_id="TOP175",
            key=f"{mqtt_prefix}main/Efficiency_Stage2_Time",
            name="Aquarea Efficiency stage 2 time",
            native_unit_of_measurement="min",
            device_class=SensorDeviceClass.DURATION,
            state=float,
            entity_registry_enabled_default=False,
        ),
        HeishaMonSensorEntityDescription(
            heishamon_topic_id="TOP176",
            key=f"{mqtt_prefix}main/Efficiency_Stage3_Time",
            name="Aquarea Efficiency stage 3 time",
            native_unit_of_measurement="min",
            device_class=SensorDeviceClass.DURATION,
            state=float,
            entity_registry_enabled_default=False,
        ),
        HeishaMonSensorEntityDescription(
            heishamon_topic_id="TOP177",
            key=f"{mqtt_prefix}main/Sensor_Offset_Remote_Th1",
            name="Aquarea Sensor offset remote thermistor 1",
            native_unit_of_measurement="K",
            state=float,
            entity_registry_enabled_default=False,
        ),
        HeishaMonSensorEntityDescription(
            heishamon_topic_id="TOP178",
            key=f"{mqtt_prefix}main/Sensor_Offset_Outdoor",
            name="Aquarea Sensor offset outdoor",
            native_unit_of_measurement="K",
            state=float,
            entity_registry_enabled_default=False,
        ),
        HeishaMonSensorEntityDescription(
            heishamon_topic_id="TOP180",
            key=f"{mqtt_prefix}main/Bivalent_Operating_Mode",
            name="Aquarea Bivalent operating mode",
            state=read_parity_bivalent_operating_mode,
            device_class=SensorDeviceClass.ENUM,
            options=list(PARITY_BIVALENT_OPERATING_MODE.values()),
            requires=(Feature.BIVALENT,),
            entity_registry_enabled_default=False,
        ),
        HeishaMonSensorEntityDescription(
            heishamon_topic_id="TOP182",
            key=f"{mqtt_prefix}main/Extra_Pump_Use",
            name="Aquarea Extra pump use",
            state=read_parity_extra_pump_use,
            device_class=SensorDeviceClass.ENUM,
            options=list(PARITY_EXTRA_PUMP_USE.values()),
            requires=(Feature.OPTIONAL_PCB,),
            entity_registry_enabled_default=False,
        ),
        HeishaMonSensorEntityDescription(
            heishamon_topic_id="TOP183",
            key=f"{mqtt_prefix}main/Extra_Pump_Mode",
            name="Aquarea Extra pump mode",
            state=read_parity_extra_pump_mode,
            device_class=SensorDeviceClass.ENUM,
            options=list(PARITY_EXTRA_PUMP_MODE.values()),
            requires=(Feature.OPTIONAL_PCB,),
            entity_registry_enabled_default=False,
        ),
        HeishaMonSensorEntityDescription(
            heishamon_topic_id="TOP184",
            key=f"{mqtt_prefix}main/SG_Ready_1_DHW_Power",
            name="Aquarea SG ready 1 DHW power",
            native_unit_of_measurement="kW",
            device_class=SensorDeviceClass.POWER,
            state=float,
            requires=(Feature.SG_READY, Feature.DHW,),
            entity_registry_enabled_default=False,
        ),
        HeishaMonSensorEntityDescription(
            heishamon_topic_id="TOP185",
            key=f"{mqtt_prefix}main/SG_Ready_1_Heat_Power",
            name="Aquarea SG ready 1 heating power",
            native_unit_of_measurement="kW",
            device_class=SensorDeviceClass.POWER,
            state=float,
            requires=(Feature.SG_READY,),
            entity_registry_enabled_default=False,
        ),
        HeishaMonSensorEntityDescription(
            heishamon_topic_id="TOP186",
            key=f"{mqtt_prefix}main/SG_Ready_1_Cool_Power",
            name="Aquarea SG ready 1 cooling power",
            native_unit_of_measurement="kW",
            device_class=SensorDeviceClass.POWER,
            state=float,
            requires=(Feature.SG_READY, Feature.COOLING,),
            entity_registry_enabled_default=False,
        ),
        HeishaMonSensorEntityDescription(
            heishamon_topic_id="TOP187",
            key=f"{mqtt_prefix}main/SG_Ready_2_DHW_Power",
            name="Aquarea SG ready 2 DHW power",
            native_unit_of_measurement="kW",
            device_class=SensorDeviceClass.POWER,
            state=float,
            requires=(Feature.SG_READY, Feature.DHW,),
            entity_registry_enabled_default=False,
        ),
        HeishaMonSensorEntityDescription(
            heishamon_topic_id="TOP188",
            key=f"{mqtt_prefix}main/SG_Ready_2_Heat_Power",
            name="Aquarea SG ready 2 heating power",
            native_unit_of_measurement="kW",
            device_class=SensorDeviceClass.POWER,
            state=float,
            requires=(Feature.SG_READY,),
            entity_registry_enabled_default=False,
        ),
        HeishaMonSensorEntityDescription(
            heishamon_topic_id="TOP189",
            key=f"{mqtt_prefix}main/SG_Ready_2_Cool_Power",
            name="Aquarea SG ready 2 cooling power",
            native_unit_of_measurement="kW",
            device_class=SensorDeviceClass.POWER,
            state=float,
            requires=(Feature.SG_READY, Feature.COOLING,),
            entity_registry_enabled_default=False,
        ),
        HeishaMonSensorEntityDescription(
            heishamon_topic_id="TOP190",
            key=f"{mqtt_prefix}main/SG_Ready_Stop_Power",
            name="Aquarea SG ready stop power",
            native_unit_of_measurement="kW",
            device_class=SensorDeviceClass.POWER,
            state=float,
            requires=(Feature.SG_READY,),
            entity_registry_enabled_default=False,
        ),
        HeishaMonSensorEntityDescription(
            heishamon_topic_id="TOP191",
            key=f"{mqtt_prefix}main/SG_Ready_1_Cool_Capacity",
            name="Aquarea SG ready 1 cooling offset",
            native_unit_of_measurement="°C",
            device_class=SensorDeviceClass.TEMPERATURE,
            state=float,
            requires=(Feature.SG_READY, Feature.COOLING,),
            entity_registry_enabled_default=False,
        ),
        HeishaMonSensorEntityDescription(
            heishamon_topic_id="TOP192",
            key=f"{mqtt_prefix}main/SG_Ready_2_Cool_Capacity",
            name="Aquarea SG ready 2 cooling offset",
            native_unit_of_measurement="°C",
            device_class=SensorDeviceClass.TEMPERATURE,
            state=float,
            requires=(Feature.SG_READY, Feature.COOLING,),
            entity_registry_enabled_default=False,
        ),
        HeishaMonSensorEntityDescription(
            heishamon_topic_id="TOP193",
            key=f"{mqtt_prefix}main/Sensor_Offset_Return",
            name="Aquarea Sensor offset return",
            native_unit_of_measurement="K",
            state=float,
            entity_registry_enabled_default=False,
        ),
        HeishaMonSensorEntityDescription(
            heishamon_topic_id="TOP195",
            key=f"{mqtt_prefix}main/Sensor_Offset_DHW_Tank",
            name="Aquarea Sensor offset DHW tank",
            native_unit_of_measurement="K",
            state=float,
            requires=(Feature.DHW,),
            entity_registry_enabled_default=False,
        ),
        HeishaMonSensorEntityDescription(
            heishamon_topic_id="TOP196",
            key=f"{mqtt_prefix}main/Sensor_Offset_Flow",
            name="Aquarea Sensor offset flow",
            native_unit_of_measurement="K",
            state=float,
            entity_registry_enabled_default=False,
        ),
    ]


def build_buttons(
    mqtt_prefix: str,
) -> list[HeishaMonBinarySensorEntityDescription]:
    return [
        HeishaMonButtonEntityDescription(
            heishamon_topic_id="Reboot",
            key=f"{mqtt_prefix}ip",
            name="Reboot",
            device=DeviceType.HEISHAMON,
            entity_category=EntityCategory.DIAGNOSTIC,
            device_class=ButtonDeviceClass.RESTART,
            on_receive=update_device_ip,
        ),
        HeishaMonButtonEntityDescription(
            heishamon_topic_id="SET48",
            key=f"{mqtt_prefix}commands/SetReset",
            command_topic=f"{mqtt_prefix}commands/SetReset",
            name="Reset fault code",
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
    ]


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


def _arranged(build: Callable) -> Callable:
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


build_sensors = _arranged(build_sensors)
build_binary_sensors = _arranged(build_binary_sensors)
build_numbers = _arranged(build_numbers)
build_selects = _arranged(build_selects)
build_switches = _arranged(build_switches)
