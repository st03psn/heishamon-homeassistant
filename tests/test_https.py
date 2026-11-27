"""HTTPS to the HeishaMon board, with a pinned certificate fingerprint or CA verification."""
import hashlib
import ssl

import aiohttp
import pytest
from aiohttp.client_reqrep import ConnectionKey
from homeassistant.exceptions import HomeAssistantError
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_mqtt_message,
)
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
    AiohttpClientMockResponse,
)

from custom_components.aquarea.auth import board_connection, normalize_fingerprint
from custom_components.aquarea.const import (
    CONF_API_KEY,
    CONF_CERT_FINGERPRINT,
    CONF_USE_HTTPS,
    DOMAIN,
)
from custom_components.aquarea.diagnostics import async_get_config_entry_diagnostics

PREFIX = "panasonic_heat_pump/"
IP = "192.168.1.50"
KEY = "0123456789abcdef0123456789abcdef"
FP = hashlib.sha256(b"heishamon certificate").hexdigest()
FP_COLONS = ":".join(FP[i : i + 2] for i in range(0, 64, 2)).upper()


@pytest.fixture(autouse=True)
def mock_response_reason(monkeypatch):
    """The test double of a response has no reason phrase, a real one has."""
    monkeypatch.setattr(AiohttpClientMockResponse, "reason", "OK", raising=False)


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


@pytest.fixture
def request_kwargs(monkeypatch):
    """Record the keyword arguments of every request; the mock drops ``ssl``."""
    calls = []
    original = AiohttpClientMocker.match_request

    async def match_request(self, method, url, **kwargs):
        calls.append((method, str(url), kwargs))
        return await original(self, method, url, **kwargs)

    monkeypatch.setattr(AiohttpClientMocker, "match_request", match_request)
    return calls


def _board_calls(calls):
    return [c for c in calls if IP in c[1]]


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


# helper


def test_normalize_fingerprint():
    assert normalize_fingerprint(None) == ""
    assert normalize_fingerprint("  ") == ""
    assert normalize_fingerprint(FP) == FP
    assert normalize_fingerprint(FP.upper()) == FP
    assert normalize_fingerprint(FP_COLONS) == FP
    assert normalize_fingerprint(" ".join(FP_COLONS.split(":"))) == FP
    assert normalize_fingerprint(f" {FP_COLONS}\n") == FP
    for bad in ("abc", FP[:-1], FP + "0", "g" + FP[1:], FP[:40], FP.replace("a", "-")):
        assert normalize_fingerprint(bad) is None


def test_board_connection_http_by_default():
    entry = MockConfigEntry(domain=DOMAIN, options={CONF_CERT_FINGERPRINT: FP})
    assert board_connection(entry, IP) == (f"http://{IP}", True)


def test_board_connection_https_with_fingerprint():
    entry = MockConfigEntry(
        domain=DOMAIN, options={CONF_USE_HTTPS: True, CONF_CERT_FINGERPRINT: FP}
    )
    url, ssl_param = board_connection(entry, IP)
    assert url == f"https://{IP}"
    assert isinstance(ssl_param, aiohttp.Fingerprint)
    assert ssl_param.fingerprint == bytes.fromhex(FP)
    assert len(ssl_param.fingerprint) == 32


def test_board_connection_https_with_system_cas():
    entry = MockConfigEntry(domain=DOMAIN, options={CONF_USE_HTTPS: True})
    # True: the verifying SSL context of the Home Assistant session, never unverified
    assert board_connection(entry, IP) == (f"https://{IP}", True)


# options flow


async def test_options_store_https_and_normalised_fingerprint(hass, mqtt_mock):
    entry = await _setup(hass, {CONF_API_KEY: KEY})
    result = await _submit(
        hass, entry, api_key=KEY, use_https=True, cert_fingerprint=FP_COLONS
    )
    assert result["type"] == "create_entry"
    await hass.async_block_till_done()
    assert entry.options[CONF_USE_HTTPS] is True
    assert entry.options[CONF_CERT_FINGERPRINT] == FP
    assert entry.options[CONF_API_KEY] == KEY
    await hass.config_entries.async_unload(entry.entry_id)


async def test_options_https_without_fingerprint(hass, mqtt_mock):
    entry = await _setup(hass, {CONF_CERT_FINGERPRINT: FP})
    result = await _submit(hass, entry, use_https=True, cert_fingerprint="")
    assert result["type"] == "create_entry"
    await hass.async_block_till_done()
    assert entry.options[CONF_USE_HTTPS] is True
    assert CONF_CERT_FINGERPRINT not in entry.options
    await hass.config_entries.async_unload(entry.entry_id)


async def test_options_https_off_by_default(hass, mqtt_mock):
    entry = await _setup(hass)
    result = await _submit(hass, entry)
    assert result["type"] == "create_entry"
    await hass.async_block_till_done()
    assert entry.options[CONF_USE_HTTPS] is False
    assert CONF_CERT_FINGERPRINT not in entry.options
    await hass.config_entries.async_unload(entry.entry_id)


@pytest.mark.parametrize("bad", ["abc", FP[:-1], FP + "00", "x" * 64])
async def test_options_reject_invalid_fingerprint(hass, mqtt_mock, bad):
    entry = await _setup(hass)
    result = await _submit(hass, entry, use_https=True, cert_fingerprint=bad)
    assert result["type"] == "form"
    assert result["errors"] == {CONF_CERT_FINGERPRINT: "invalid_cert_fingerprint"}
    assert CONF_USE_HTTPS not in entry.options
    await hass.config_entries.async_unload(entry.entry_id)


async def test_options_reject_invalid_fingerprint_with_https_off(hass, mqtt_mock):
    """Deliberately stricter than needed: junk is never stored."""
    entry = await _setup(hass)
    result = await _submit(hass, entry, use_https=False, cert_fingerprint="abc")
    assert result["type"] == "form"
    assert result["errors"] == {CONF_CERT_FINGERPRINT: "invalid_cert_fingerprint"}
    await hass.config_entries.async_unload(entry.entry_id)


async def test_options_report_both_errors(hass, mqtt_mock):
    entry = await _setup(hass)
    result = await _submit(
        hass, entry, api_key="abc", use_https=True, cert_fingerprint="abc"
    )
    assert result["type"] == "form"
    assert result["errors"] == {
        CONF_API_KEY: "invalid_api_key",
        CONF_CERT_FINGERPRINT: "invalid_cert_fingerprint",
    }
    await hass.config_entries.async_unload(entry.entry_id)


async def test_diagnostics_keep_fingerprint_and_redact_key(hass, mqtt_mock):
    entry = await _setup(
        hass, {CONF_API_KEY: KEY, CONF_USE_HTTPS: True, CONF_CERT_FINGERPRINT: FP}
    )
    diagnostics = await async_get_config_entry_diagnostics(hass, entry)
    options = diagnostics["entry"]["options"]
    assert options[CONF_API_KEY] == "**REDACTED**"
    assert options[CONF_CERT_FINGERPRINT] == FP
    assert options[CONF_USE_HTTPS] is True
    await hass.config_entries.async_unload(entry.entry_id)


# reboot


async def _press_reboot(hass):
    async_fire_mqtt_message(hass, f"{PREFIX}ip", IP)
    await hass.async_block_till_done()
    await hass.services.async_call(
        "button", "press", {"entity_id": "button.panasonic_heat_pump_ip"}, blocking=True
    )


def _certificate_error():
    key = ConnectionKey(IP, 443, True, True, None, None, None)
    return aiohttp.ClientConnectorCertificateError(
        key, ssl.SSLCertVerificationError("self-signed certificate")
    )


def _mismatch():
    return aiohttp.ServerFingerprintMismatch(
        bytes.fromhex(FP), hashlib.sha256(b"other").digest(), IP, 443
    )


async def test_reboot_over_https_pins_fingerprint(hass, mqtt_mock, aioclient_mock, request_kwargs):
    aioclient_mock.get(f"https://{IP}/reboot", text="ok")
    entry = await _setup(
        hass, {CONF_API_KEY: KEY, CONF_USE_HTTPS: True, CONF_CERT_FINGERPRINT: FP}
    )
    await _press_reboot(hass)
    ((method, url, kwargs),) = _board_calls(request_kwargs)
    assert url == f"https://{IP}/reboot"
    assert isinstance(kwargs["ssl"], aiohttp.Fingerprint)
    assert kwargs["ssl"].fingerprint == bytes.fromhex(FP)
    assert kwargs["headers"]["Authorization"] == f"Bearer {KEY}"
    await hass.config_entries.async_unload(entry.entry_id)


async def test_reboot_over_https_with_system_cas(hass, mqtt_mock, aioclient_mock, request_kwargs):
    aioclient_mock.get(f"https://{IP}/reboot", text="ok")
    entry = await _setup(hass, {CONF_USE_HTTPS: True})
    await _press_reboot(hass)
    ((method, url, kwargs),) = _board_calls(request_kwargs)
    assert url == f"https://{IP}/reboot"
    assert kwargs["ssl"] is True
    await hass.config_entries.async_unload(entry.entry_id)


async def test_reboot_over_http_unchanged(hass, mqtt_mock, aioclient_mock, request_kwargs):
    aioclient_mock.get(f"http://{IP}/reboot", text="ok")
    entry = await _setup(hass, {CONF_CERT_FINGERPRINT: FP})  # HTTPS off
    await _press_reboot(hass)
    ((method, url, kwargs),) = _board_calls(request_kwargs)
    assert url == f"http://{IP}/reboot"
    assert kwargs["ssl"] is True
    await hass.config_entries.async_unload(entry.entry_id)


async def test_reboot_fingerprint_mismatch(hass, mqtt_mock, aioclient_mock, request_kwargs):
    aioclient_mock.get(f"https://{IP}/reboot", exc=_mismatch())
    aioclient_mock.get(f"http://{IP}/reboot", text="ok")
    entry = await _setup(hass, {CONF_USE_HTTPS: True, CONF_CERT_FINGERPRINT: FP})
    with pytest.raises(HomeAssistantError) as err:
        await _press_reboot(hass)
    assert err.value.translation_domain == DOMAIN
    assert err.value.translation_key == "certificate_fingerprint_mismatch"
    assert err.value.translation_placeholders == {"host": IP}
    assert isinstance(err.value.__cause__, aiohttp.ServerFingerprintMismatch)
    assert "access page" in str(err.value)
    assert IP in str(err.value)
    # no fallback to plain HTTP
    assert [url for _, url, _ in _board_calls(request_kwargs)] == [f"https://{IP}/reboot"]
    await hass.config_entries.async_unload(entry.entry_id)


async def test_reboot_certificate_not_trusted(hass, mqtt_mock, aioclient_mock, request_kwargs):
    aioclient_mock.get(f"https://{IP}/reboot", exc=_certificate_error())
    aioclient_mock.get(f"http://{IP}/reboot", text="ok")
    entry = await _setup(hass, {CONF_USE_HTTPS: True})
    with pytest.raises(HomeAssistantError) as err:
        await _press_reboot(hass)
    assert err.value.translation_key == "certificate_verification_failed"
    assert err.value.translation_placeholders == {"host": IP}
    assert "certificate authorities" in str(err.value)
    assert [url for _, url, _ in _board_calls(request_kwargs)] == [f"https://{IP}/reboot"]
    await hass.config_entries.async_unload(entry.entry_id)


async def test_reboot_other_connection_error_is_not_a_certificate_error(
    hass, mqtt_mock, aioclient_mock
):
    aioclient_mock.get(f"https://{IP}/reboot", exc=aiohttp.ClientConnectionError("refused"))
    entry = await _setup(hass, {CONF_USE_HTTPS: True, CONF_CERT_FINGERPRINT: FP})
    with pytest.raises(aiohttp.ClientConnectionError):
        await _press_reboot(hass)
    await hass.config_entries.async_unload(entry.entry_id)


# firmware upload


def _mock_github(aioclient_mock):
    """Release v4.3.1 of the fork (the default source) with its firmware assets."""
    files = "https://github.com/st03psn/HeishaMon/releases/download/v4.3.1"
    aioclient_mock.get(
        "https://api.github.com/repos/st03psn/HeishaMon/releases/tags/v4.3.1",
        json={
            "tag_name": "v4.3.1",
            "assets": [
                {"name": n, "browser_download_url": f"{files}/{n}"}
                for n in ("HeishaMon.ino.esp32-v4.3.1.bin", "HeishaMon.ino.esp32-v4.3.1.md5")
            ],
        },
    )
    aioclient_mock.get(f"{files}/HeishaMon.ino.esp32-v4.3.1.bin", content=b"firmware")
    aioclient_mock.get(
        f"{files}/HeishaMon.ino.esp32-v4.3.1.md5", text="0123456789abcdef0123456789abcdef"
    )


def _update_entity(hass):
    entity = hass.data["update"].get_entity("update.heishamon_firmware")
    entity._model_type = "ESP32"
    entity._heishamon_ip = IP
    entity._attr_latest_version = "4.3.1"
    return entity


async def test_upload_over_https_pins_fingerprint(hass, mqtt_mock, aioclient_mock, request_kwargs):
    _mock_github(aioclient_mock)
    aioclient_mock.post(f"https://{IP}/firmware", text="Update success! Rebooting.")
    entry = await _setup(
        hass, {CONF_API_KEY: KEY, CONF_USE_HTTPS: True, CONF_CERT_FINGERPRINT: FP}
    )
    await _update_entity(hass).async_install("4.3.1", False)
    ((method, url, kwargs),) = _board_calls(request_kwargs)
    assert method.upper() == "POST"
    assert url == f"https://{IP}/firmware"
    assert isinstance(kwargs["ssl"], aiohttp.Fingerprint)
    assert kwargs["ssl"].fingerprint == bytes.fromhex(FP)
    assert kwargs["headers"]["Authorization"] == f"Bearer {KEY}"
    # the GitHub downloads are not touched by the board settings
    github = [c for c in request_kwargs if "github.com" in c[1]]
    # release lookup, binary and checksum
    assert len(github) == 3
    assert all("ssl" not in kwargs for _, _, kwargs in github)
    await hass.config_entries.async_unload(entry.entry_id)


async def test_upload_over_https_with_system_cas(hass, mqtt_mock, aioclient_mock, request_kwargs):
    _mock_github(aioclient_mock)
    aioclient_mock.post(f"https://{IP}/firmware", text="Update success! Rebooting.")
    entry = await _setup(hass, {CONF_USE_HTTPS: True})
    await _update_entity(hass).async_install("4.3.1", False)
    ((method, url, kwargs),) = _board_calls(request_kwargs)
    assert url == f"https://{IP}/firmware"
    assert kwargs["ssl"] is True
    await hass.config_entries.async_unload(entry.entry_id)


async def test_upload_over_http_unchanged(hass, mqtt_mock, aioclient_mock, request_kwargs):
    _mock_github(aioclient_mock)
    aioclient_mock.post(f"http://{IP}/firmware", text="Update success! Rebooting.")
    entry = await _setup(hass)
    await _update_entity(hass).async_install("4.3.1", False)
    ((method, url, kwargs),) = _board_calls(request_kwargs)
    assert url == f"http://{IP}/firmware"
    await hass.config_entries.async_unload(entry.entry_id)


@pytest.mark.parametrize(
    ("options", "exc", "key"),
    [
        (
            {CONF_USE_HTTPS: True, CONF_CERT_FINGERPRINT: FP},
            _mismatch(),
            "certificate_fingerprint_mismatch",
        ),
        ({CONF_USE_HTTPS: True}, _certificate_error(), "certificate_verification_failed"),
    ],
)
async def test_upload_certificate_errors(
    hass, mqtt_mock, aioclient_mock, request_kwargs, options, exc, key
):
    _mock_github(aioclient_mock)
    aioclient_mock.post(f"https://{IP}/firmware", exc=exc)
    aioclient_mock.post(f"http://{IP}/firmware", text="Update success! Rebooting.")
    entry = await _setup(hass, options)
    with pytest.raises(HomeAssistantError) as err:
        await _update_entity(hass).async_install("4.3.1", False)
    assert err.value.translation_domain == DOMAIN
    assert err.value.translation_key == key
    assert err.value.translation_placeholders == {"host": IP}
    assert err.value.__cause__ is exc
    assert [url for _, url, _ in _board_calls(request_kwargs)] == [f"https://{IP}/firmware"]
    await hass.config_entries.async_unload(entry.entry_id)
