"""The COP is computed once per HeishaMon cycle instead of after every message.

Production and consumption arrive as separate MQTT messages a few
milliseconds apart; computing after each one wrote an intermediate COP
(new production, old consumption) to the recorder in every cycle.
"""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from homeassistant.components.sensor import SensorStateClass

from custom_components.aquarea.definitions.descriptions import (
    MultiMQTTSensorEntityDescription,
)
from custom_components.aquarea.sensor import (
    MultiMQTTSensorEntity,
    compute_cop,
    extract_sum,
)

PREFIX = "prefix/"
CONFIG_ENTRY = SimpleNamespace(entry_id="test", data={"discovery_prefix": PREFIX})
COP_TOPICS = [
    f"{PREFIX}main/Defrosting_State",
    f"{PREFIX}main/DHW_Power_Production",
    f"{PREFIX}main/Heat_Power_Production",
    f"{PREFIX}main/Cool_Power_Production",
    f"{PREFIX}main/DHW_Power_Consumption",
    f"{PREFIX}main/Heat_Power_Consumption",
    f"{PREFIX}main/Cool_Power_Consumption",
] + [f"{PREFIX}unused/{i}" for i in range(18)]


async def _setup(description, monkeypatch):
    entity = MultiMQTTSensorEntity(MagicMock(), CONFIG_ENTRY, description)
    writes = []
    entity.async_write_ha_state = lambda: writes.append(entity.native_value)
    callbacks = {}
    timers = []

    async def fake_subscribe(hass, topic, msg_callback, qos=0):
        callbacks[topic] = msg_callback
        return lambda: None

    def fake_call_later(hass, delay, action):
        cancel = MagicMock()
        timers.append((delay, action, cancel))
        return cancel

    # the timer is started when a message arrives, after setup
    monkeypatch.setattr(
        "custom_components.aquarea.sensor.async_call_later", fake_call_later
    )
    with patch(
        "custom_components.aquarea.sensor.mqtt.async_subscribe",
        side_effect=fake_subscribe,
    ):
        await entity.async_added_to_hass()

    def send(topic, payload):
        topic = f"{PREFIX}{topic}"
        callbacks[topic](SimpleNamespace(topic=topic, payload=payload))

    return entity, send, writes, timers


def _cop_description(debounce_seconds=1):
    return MultiMQTTSensorEntityDescription(
        unique_id="test-heishamon_cop",
        key=f"{PREFIX}/cop",
        name="Aquarea COP",
        state_class=SensorStateClass.MEASUREMENT,
        topics=COP_TOPICS,
        compute_state=compute_cop,
        debounce_seconds=debounce_seconds,
    )


async def test_cop_is_written_once_per_cycle(monkeypatch):
    entity, send, writes, timers = await _setup(_cop_description(), monkeypatch)

    send("main/Heat_Power_Production", "5429")
    send("main/Heat_Power_Consumption", "1382")
    send("main/DHW_Power_Production", "0")

    assert writes == []
    assert len(timers) == 1  # one window per cycle, not one per message
    delay, action, _ = timers[0]
    assert delay == 1

    action(None)
    assert writes == [round(5429 / 1382, 1)]

    # the next cycle opens a new window
    send("main/Heat_Power_Production", "5515")
    assert len(timers) == 2


async def test_cop_keeps_last_value_during_defrost(monkeypatch):
    entity, send, writes, timers = await _setup(_cop_description(), monkeypatch)

    send("main/Heat_Power_Production", "5429")
    send("main/Heat_Power_Consumption", "1382")
    timers[-1][1](None)
    assert writes == [round(5429 / 1382, 1)]

    send("main/Defrosting_State", "1")
    timers[-1][1](None)
    assert writes == [round(5429 / 1382, 1)]
    assert entity.native_value == round(5429 / 1382, 1)


async def test_pending_window_is_cancelled_on_remove(monkeypatch):
    entity, send, writes, timers = await _setup(_cop_description(), monkeypatch)

    send("main/Heat_Power_Production", "5429")
    _, _, cancel = timers[0]
    # what Home Assistant runs when the entity is removed
    for remove in entity._on_remove or []:
        remove()
    cancel.assert_called_once()


async def test_sensors_without_debounce_still_write_every_message(monkeypatch):
    description = MultiMQTTSensorEntityDescription(
        unique_id="test-heishamon_production",
        key=f"{PREFIX}/production",
        name="Aquarea Production",
        native_unit_of_measurement="W",
        state_class=SensorStateClass.MEASUREMENT,
        topics=[
            f"{PREFIX}main/DHW_Power_Production",
            f"{PREFIX}main/Heat_Power_Production",
            f"{PREFIX}main/Cool_Power_Production",
        ],
        compute_state=extract_sum,
    )
    entity, send, writes, timers = await _setup(description, monkeypatch)

    send("main/Heat_Power_Production", "5429")
    send("main/Heat_Power_Production", "5515")

    assert timers == []
    assert writes == [5429, 5515]
