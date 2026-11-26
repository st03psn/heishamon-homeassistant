"""Entity description dataclasses used by the HeishaMon platforms."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Optional

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntityDescription,
)
from homeassistant.components.button import ButtonEntityDescription
from homeassistant.components.number import NumberEntityDescription
from homeassistant.components.select import SelectEntityDescription
from homeassistant.components.sensor import SensorEntityDescription
from homeassistant.components.switch import SwitchEntityDescription

from ..const import DeviceType
from ..const import Feature
from homeassistant.const import MAJOR_VERSION


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
