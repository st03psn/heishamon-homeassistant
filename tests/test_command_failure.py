"""Test what happens when the heat pump does not take over a command."""
import asyncio

import pytest
from homeassistant.helpers import issue_registry as ir
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_capture_events,
    async_fire_mqtt_message,
)

from custom_components.aquarea.const import DOMAIN
from custom_components.aquarea.retry_mixin import EVENT_COMMAND_FAILED, CommandRetryMixin

PREFIX = "panasonic_heat_pump/"
NUMBER = "number.panasonic_heat_pump_main_z1_heat_request_temp"
ISSUE = f"command_failed_{NUMBER}"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


@pytest.fixture(autouse=True)
def fast_retries(monkeypatch):
    monkeypatch.setattr(CommandRetryMixin, "RETRY_TIMEOUT", 0.01)
    monkeypatch.setattr(CommandRetryMixin, "RETRY_JITTER", 0.0)


async def set_value(hass, value):
    await hass.services.async_call(
        "number", "set_value", {"entity_id": NUMBER, "value": value}, blocking=True
    )


async def test_issue_and_event_after_the_last_retry(hass, mqtt_mock):
    entry = MockConfigEntry(domain=DOMAIN, data={"discovery_prefix": PREFIX}, version=2)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    async_fire_mqtt_message(hass, f"{PREFIX}main/Z1_Heat_Request_Temp", "0")
    await hass.async_block_till_done()
    events = async_capture_events(hass, EVENT_COMMAND_FAILED)
    registry = ir.async_get(hass)

    await set_value(hass, 2)
    # the heat pump keeps reporting the old value
    for _ in range(20):
        async_fire_mqtt_message(hass, f"{PREFIX}main/Z1_Heat_Request_Temp", "0")
        await asyncio.sleep(0.01)
    await hass.async_block_till_done()

    assert len(events) == 1
    assert events[0].data == {
        "entity_id": NUMBER,
        "expected": "2.0",
        "received": "0",
        "attempts": 4,
    }
    issue = registry.async_get_issue(DOMAIN, ISSUE)
    assert issue is not None
    assert issue.translation_placeholders["expected"] == "2.0"
    # initial command and three retries
    topic = f"{PREFIX}commands/SetZ1HeatRequestTemperature"
    sent = [call for call in mqtt_mock.async_publish.mock_calls if call.args[0] == topic]
    assert len(sent) == 4

    # the next command is taken over: the issue goes away
    await set_value(hass, 1)
    async_fire_mqtt_message(hass, f"{PREFIX}main/Z1_Heat_Request_Temp", "1")
    await hass.async_block_till_done()
    assert registry.async_get_issue(DOMAIN, ISSUE) is None
    assert len(events) == 1

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


async def test_issue_is_removed_with_the_entry(hass, mqtt_mock):
    entry = MockConfigEntry(domain=DOMAIN, data={"discovery_prefix": PREFIX}, version=2)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    registry = ir.async_get(hass)
    await set_value(hass, 2)
    for _ in range(20):
        async_fire_mqtt_message(hass, f"{PREFIX}main/Z1_Heat_Request_Temp", "0")
        await asyncio.sleep(0.01)
    await hass.async_block_till_done()
    assert registry.async_get_issue(DOMAIN, ISSUE) is not None

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert registry.async_get_issue(DOMAIN, ISSUE) is None
