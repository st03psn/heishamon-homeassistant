"""Optional API key of the HeishaMon web login."""
import aiohttp
import pytest
from homeassistant.exceptions import HomeAssistantError
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_mqtt_message,
)

from custom_components.aquarea.auth import api_key_headers, normalize_api_key
from custom_components.aquarea.const import CONF_API_KEY, DOMAIN
from custom_components.aquarea.diagnostics import async_get_config_entry_diagnostics

PREFIX = "panasonic_heat_pump/"
KEY = "0123456789abcdef0123456789ABCDEF"
KEY_LOWER = KEY.lower()
IP = "192.168.1.50"


@pytest.fixture(autouse=True)
def mock_response_reason(monkeypatch):
    """The test double of a response has no reason phrase, a real one has."""
    from pytest_homeassistant_custom_component.test_util.aiohttp import (
        AiohttpClientMockResponse,
    )

    monkeypatch.setattr(AiohttpClientMockResponse, "reason", "OK", raising=False)


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


async def _setup(hass, options=None):
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"discovery_prefix": PREFIX},
        options=options or {},
        version=2,
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def _submit(hass, entry, **extra):
    result = await hass.config_entries.options.async_init(entry.entry_id)
    return await hass.config_entries.options.async_configure(
        result["flow_id"], {"entity_management": "enable_only", **extra}
    )


def test_normalize_api_key():
    assert normalize_api_key(None) == ""
    assert normalize_api_key("") == ""
    assert normalize_api_key(KEY) == KEY_LOWER
    assert normalize_api_key(f" {KEY} ") == KEY_LOWER
    for bad in ("abc", KEY + "0", KEY[:-1], "g" * 32, "0123456789abcdef0123456789abcde-"):
        assert normalize_api_key(bad) is None


async def test_options_accept_empty_key(hass, mqtt_mock):
    entry = await _setup(hass)
    result = await _submit(hass, entry, api_key="")
    assert result["type"] == "create_entry"
    assert CONF_API_KEY not in entry.options
    await hass.config_entries.async_unload(entry.entry_id)


async def test_options_store_valid_key_in_lowercase(hass, mqtt_mock):
    entry = await _setup(hass)
    result = await _submit(hass, entry, api_key=KEY)
    assert result["type"] == "create_entry"
    await hass.async_block_till_done()
    assert entry.options[CONF_API_KEY] == KEY_LOWER
    await hass.config_entries.async_unload(entry.entry_id)


async def test_options_clearing_the_key_removes_it(hass, mqtt_mock):
    entry = await _setup(hass, {CONF_API_KEY: KEY_LOWER})
    result = await _submit(hass, entry)  # field left out: cleared in the form
    assert result["type"] == "create_entry"
    await hass.async_block_till_done()
    assert CONF_API_KEY not in entry.options
    await hass.config_entries.async_unload(entry.entry_id)


@pytest.mark.parametrize("bad", ["abc", "z" * 32, KEY + "0"])
async def test_options_reject_invalid_key(hass, mqtt_mock, bad):
    entry = await _setup(hass)
    result = await _submit(hass, entry, api_key=bad)
    assert result["type"] == "form"
    assert result["errors"] == {CONF_API_KEY: "invalid_api_key"}
    assert CONF_API_KEY not in entry.options
    await hass.config_entries.async_unload(entry.entry_id)


async def test_diagnostics_redact_key(hass, mqtt_mock):
    entry = await _setup(hass, {CONF_API_KEY: KEY_LOWER})
    diagnostics = await async_get_config_entry_diagnostics(hass, entry)
    assert KEY_LOWER not in str(diagnostics)
    assert diagnostics["entry"]["options"][CONF_API_KEY] == "**REDACTED**"
    await hass.config_entries.async_unload(entry.entry_id)


def test_headers():
    with_key = MockConfigEntry(domain=DOMAIN, options={CONF_API_KEY: KEY_LOWER})
    assert api_key_headers(with_key) == {"Authorization": f"Bearer {KEY_LOWER}"}
    assert api_key_headers(MockConfigEntry(domain=DOMAIN, options={})) == {}
    assert api_key_headers(MockConfigEntry(domain=DOMAIN, options={CONF_API_KEY: ""})) == {}


async def _press_reboot(hass):
    async_fire_mqtt_message(hass, f"{PREFIX}ip", IP)
    await hass.async_block_till_done()
    await hass.services.async_call(
        "button", "press", {"entity_id": "button.panasonic_heat_pump_ip"}, blocking=True
    )


async def test_reboot_sends_key(hass, mqtt_mock, aioclient_mock):
    aioclient_mock.get(f"http://{IP}/reboot", text="ok")
    entry = await _setup(hass, {CONF_API_KEY: KEY_LOWER})
    await _press_reboot(hass)
    assert len(aioclient_mock.mock_calls) == 1
    assert aioclient_mock.mock_calls[0][3]["Authorization"] == f"Bearer {KEY_LOWER}"
    await hass.config_entries.async_unload(entry.entry_id)


async def test_reboot_without_key_sends_no_header(hass, mqtt_mock, aioclient_mock):
    aioclient_mock.get(f"http://{IP}/reboot", text="ok")
    entry = await _setup(hass)
    await _press_reboot(hass)
    assert len(aioclient_mock.mock_calls) == 1
    assert "Authorization" not in (aioclient_mock.mock_calls[0][3] or {})
    await hass.config_entries.async_unload(entry.entry_id)


async def test_reboot_401_is_translated_error(hass, mqtt_mock, aioclient_mock):
    aioclient_mock.get(f"http://{IP}/reboot", status=401)
    entry = await _setup(hass)
    with pytest.raises(HomeAssistantError) as err:
        await _press_reboot(hass)
    assert err.value.translation_domain == DOMAIN
    assert err.value.translation_key == "reboot_unauthorized"
    await hass.config_entries.async_unload(entry.entry_id)


async def _update_entity(hass, entry):
    entity = hass.data["update"].get_entity("update.heishamon_firmware")
    entity._model_type = "ESP32"
    entity._heishamon_ip = IP
    entity._attr_latest_version = "4.3.1"
    return entity


def _mock_github(aioclient_mock):
    base = "https://github.com/heishamon/HeishaMon/raw/refs/heads/main/binaries/model-type-large"
    aioclient_mock.get(f"{base}/HeishaMon.ino.esp32-v4.3.1.bin", content=b"firmware")
    aioclient_mock.get(f"{base}/HeishaMon.ino.esp32-v4.3.1.md5", text="abc123")


def _upload_calls(aioclient_mock):
    return [c for c in aioclient_mock.mock_calls if c[0] == "POST"]


async def test_upload_sends_key(hass, mqtt_mock, aioclient_mock):
    _mock_github(aioclient_mock)
    aioclient_mock.post(f"http://{IP}/firmware", text="Update success! Rebooting.")
    entry = await _setup(hass, {CONF_API_KEY: KEY_LOWER})
    entity = await _update_entity(hass, entry)
    await entity.async_install("4.3.1", False)
    (call,) = _upload_calls(aioclient_mock)
    assert call[3]["Authorization"] == f"Bearer {KEY_LOWER}"
    assert call[3]["Content-Type"].startswith("multipart/form-data")
    await hass.config_entries.async_unload(entry.entry_id)


async def test_upload_without_key_sends_no_header(hass, mqtt_mock, aioclient_mock):
    _mock_github(aioclient_mock)
    aioclient_mock.post(f"http://{IP}/firmware", text="Update success! Rebooting.")
    entry = await _setup(hass)
    entity = await _update_entity(hass, entry)
    await entity.async_install("4.3.1", False)
    (call,) = _upload_calls(aioclient_mock)
    assert "Authorization" not in call[3]
    await hass.config_entries.async_unload(entry.entry_id)


async def test_upload_disconnect_mentions_api_key(hass, mqtt_mock, aioclient_mock):
    _mock_github(aioclient_mock)
    aioclient_mock.post(
        f"http://{IP}/firmware", exc=aiohttp.ServerDisconnectedError("closed")
    )
    entry = await _setup(hass)
    entity = await _update_entity(hass, entry)
    with pytest.raises(HomeAssistantError) as err:
        await entity.async_install("4.3.1", False)
    assert err.value.translation_key == "firmware_upload_connection_failed"
    assert err.value.translation_placeholders["host"] == IP
    assert "ServerDisconnectedError" in err.value.translation_placeholders["error"]
    assert isinstance(err.value.__cause__, aiohttp.ServerDisconnectedError)
    await hass.config_entries.async_unload(entry.entry_id)
