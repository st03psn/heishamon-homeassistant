"""Shared fixtures."""
from unittest.mock import AsyncMock, patch

import pytest


@pytest.fixture(autouse=True)
def no_release_lookup():
    """Keep the firmware update entity from asking GitHub for the latest release."""
    with patch(
        "custom_components.aquarea.update.HeishaMonMQTTUpdate._update_latest_release",
        AsyncMock(),
    ):
        yield


@pytest.fixture
async def mqtt_mock(hass, mqtt_mock):
    """The MQTT mock, with the timer of the MQTT client stopped afterwards.

    The MQTT client reschedules a one-second timer for as long as it is
    connected, and the test harness fails a test that leaves a timer behind.
    Only this timer is stopped, so a timer left by the integration still fails.
    """
    yield mqtt_mock
    client = hass.data["mqtt"].client
    if client._misc_timer is not None:
        client._misc_timer.cancel()
        client._misc_timer = None
