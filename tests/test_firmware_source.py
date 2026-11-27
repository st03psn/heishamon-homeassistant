"""Firmware source of the update entity: repository, releases, assets and versions."""
import pytest
from homeassistant.exceptions import HomeAssistantError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.aquarea.const import (
    CONF_FIRMWARE_REPOSITORY,
    CONF_FIRMWARE_SOURCE,
    DOMAIN,
)
from custom_components.aquarea.update import (
    HeishaMonMQTTUpdate,
    firmware_download_urls,
    firmware_repository,
    is_newer_version,
    parse_checksum,
)

# conftest replaces the lookup for all other tests, keep the real one here
REAL_LOOKUP = HeishaMonMQTTUpdate._update_latest_release

PREFIX = "panasonic_heat_pump/"
IP = "192.168.1.50"
MD5 = "0123456789abcdef0123456789abcdef"
ENTITY_ID = "update.heishamon_firmware"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


@pytest.fixture(autouse=True)
def mock_response_reason(monkeypatch):
    from pytest_homeassistant_custom_component.test_util.aiohttp import (
        AiohttpClientMockResponse,
    )

    monkeypatch.setattr(AiohttpClientMockResponse, "reason", "OK", raising=False)


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


def _entity(hass):
    entity = hass.data["update"].get_entity(ENTITY_ID)
    entity._model_type = "ESP32"
    entity._heishamon_ip = IP
    return entity


def _release(repository, version, names):
    files = f"https://github.com/{repository}/releases/download/v{version}"
    return {
        "tag_name": f"v{version}",
        "html_url": f"https://github.com/{repository}/releases/tag/v{version}",
        "body": "notes",
        "assets": [
            {"name": n, "browser_download_url": f"{files}/{n}"} for n in names
        ],
    }


ESP32_ASSETS = ("HeishaMon.ino.esp32-v4.5.0.bin", "HeishaMon.ino.esp32-v4.5.0.md5")


# repository


@pytest.mark.parametrize(
    ("options", "repository"),
    [
        ({}, "st03psn/HeishaMon"),  # entries from before the option
        ({CONF_FIRMWARE_SOURCE: "fork"}, "st03psn/HeishaMon"),
        ({CONF_FIRMWARE_SOURCE: "original"}, "heishamon/HeishaMon"),
        (
            {CONF_FIRMWARE_SOURCE: "custom", CONF_FIRMWARE_REPOSITORY: "me/Heisha.Mon_x"},
            "me/Heisha.Mon_x",
        ),
        ({CONF_FIRMWARE_SOURCE: "custom", CONF_FIRMWARE_REPOSITORY: "bad"}, None),
        ({CONF_FIRMWARE_SOURCE: "custom"}, None),
    ],
)
def test_firmware_repository(options, repository):
    assert firmware_repository(options) == repository


# options flow


async def _options_form(hass, entry):
    return await hass.config_entries.options.async_init(entry.entry_id)


def _default(result, key):
    for marker in result["data_schema"].schema:
        if marker == key:
            return marker.default()
    raise KeyError(key)


async def test_old_entry_defaults_to_the_fork(hass, mqtt_mock):
    entry = await _setup(hass, {"entity_management": "enable_only"})
    result = await _options_form(hass, entry)
    assert _default(result, CONF_FIRMWARE_SOURCE) == "fork"
    entity = hass.data["update"].get_entity(ENTITY_ID)
    assert entity.release_url == "https://github.com/st03psn/HeishaMon/releases"
    await hass.config_entries.async_unload(entry.entry_id)


@pytest.mark.parametrize(
    "repository",
    ["", "noslash", "a/b/c", "own er/repo", "owner/re po", "owner_x/repo", "https://github.com/a/b"],
)
async def test_custom_repository_is_validated(hass, mqtt_mock, repository):
    entry = await _setup(hass)
    result = await _options_form(hass, entry)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            "entity_management": "enable_only",
            CONF_FIRMWARE_SOURCE: "custom",
            CONF_FIRMWARE_REPOSITORY: repository,
        },
    )
    assert result["type"] == "form"
    assert result["errors"] == {CONF_FIRMWARE_REPOSITORY: "invalid_firmware_repository"}
    await hass.config_entries.async_unload(entry.entry_id)


async def test_custom_repository_is_stored(hass, mqtt_mock):
    entry = await _setup(hass)
    result = await _options_form(hass, entry)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            "entity_management": "enable_only",
            CONF_FIRMWARE_SOURCE: "custom",
            CONF_FIRMWARE_REPOSITORY: " my-name/Heisha.Mon_2 ",
        },
    )
    assert result["type"] == "create_entry"
    await hass.async_block_till_done()
    assert entry.options[CONF_FIRMWARE_SOURCE] == "custom"
    assert entry.options[CONF_FIRMWARE_REPOSITORY] == "my-name/Heisha.Mon_2"
    await hass.config_entries.async_unload(entry.entry_id)


async def test_repository_is_dropped_for_other_sources(hass, mqtt_mock):
    entry = await _setup(hass)
    result = await _options_form(hass, entry)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            "entity_management": "enable_only",
            CONF_FIRMWARE_SOURCE: "original",
            CONF_FIRMWARE_REPOSITORY: "ignored",
        },
    )
    assert result["type"] == "create_entry"
    await hass.async_block_till_done()
    assert entry.options[CONF_FIRMWARE_SOURCE] == "original"
    assert CONF_FIRMWARE_REPOSITORY not in entry.options
    await hass.config_entries.async_unload(entry.entry_id)


# release lookup


@pytest.mark.parametrize(
    ("options", "repository"),
    [
        ({}, "st03psn/HeishaMon"),
        ({CONF_FIRMWARE_SOURCE: "original"}, "heishamon/HeishaMon"),
        ({CONF_FIRMWARE_SOURCE: "custom", CONF_FIRMWARE_REPOSITORY: "me/fw"}, "me/fw"),
    ],
)
async def test_lookup_uses_the_chosen_repository(hass, mqtt_mock, aioclient_mock, options, repository):
    url = f"https://api.github.com/repos/{repository}/releases/latest"
    aioclient_mock.get(url, json=_release(repository, "4.5.0", ESP32_ASSETS))
    entry = await _setup(hass, options)
    entity = hass.data["update"].get_entity(ENTITY_ID)
    await REAL_LOOKUP(entity)
    assert [str(c[1]) for c in aioclient_mock.mock_calls] == [url]
    assert entity.latest_version == "4.5.0"
    assert entity.release_url == f"https://github.com/{repository}/releases/tag/v4.5.0"
    assert f"`{repository}`" in entity.release_notes()
    await hass.config_entries.async_unload(entry.entry_id)


async def test_repository_without_release_offers_nothing(hass, mqtt_mock, aioclient_mock):
    aioclient_mock.get(
        "https://api.github.com/repos/st03psn/HeishaMon/releases/latest", status=404
    )
    entry = await _setup(hass)
    entity = _entity(hass)
    await REAL_LOOKUP(entity)
    assert entity.latest_version is None
    with pytest.raises(HomeAssistantError) as err:
        await entity.async_install(None, False)
    assert err.value.translation_key == "firmware_version_unknown"
    await hass.config_entries.async_unload(entry.entry_id)


# downloads


def test_assets_are_preferred():
    release = _release("heishamon/HeishaMon", "4.5.0", ESP32_ASSETS)
    files = "https://github.com/heishamon/HeishaMon/releases/download/v4.5.0"
    assert firmware_download_urls(
        "heishamon/HeishaMon", release, "model-type-large", "esp32", "4.5.0"
    ) == (f"{files}/{ESP32_ASSETS[0]}", f"{files}/{ESP32_ASSETS[1]}")


@pytest.mark.parametrize("release", [None, {"tag_name": "v4.5.0", "assets": []}])
def test_original_falls_back_to_main_binaries(release):
    base = "https://github.com/heishamon/HeishaMon/raw/refs/heads/main/binaries/model-type-small"
    assert firmware_download_urls(
        "heishamon/HeishaMon", release, "model-type-small", "d1", "4.5.0"
    ) == (
        f"{base}/HeishaMon.ino.d1-v4.5.0.bin",
        f"{base}/HeishaMon.ino.d1-v4.5.0.md5",
    )


@pytest.mark.parametrize("repository", ["st03psn/HeishaMon", "me/fw"])
@pytest.mark.parametrize(
    ("names", "missing"),
    [
        ((), "HeishaMon.ino.d1-v4.5.0.bin"),
        (ESP32_ASSETS, "HeishaMon.ino.d1-v4.5.0.bin"),  # only the other board
        (("HeishaMon.ino.d1-v4.5.0.bin",), "HeishaMon.ino.d1-v4.5.0.md5"),
    ],
)
def test_missing_asset_is_an_error(repository, names, missing):
    release = _release(repository, "4.5.0", names)
    with pytest.raises(HomeAssistantError) as err:
        firmware_download_urls(repository, release, "model-type-small", "d1", "4.5.0")
    assert err.value.translation_domain == DOMAIN
    assert err.value.translation_key == "firmware_asset_missing"
    assert err.value.translation_placeholders == {
        "version": "4.5.0",
        "repository": repository,
        "asset": missing,
    }


async def test_install_downloads_release_assets(hass, mqtt_mock, aioclient_mock):
    repository = "me/fw"
    release = _release(repository, "4.5.0", ESP32_ASSETS)
    files = f"https://github.com/{repository}/releases/download/v4.5.0"
    aioclient_mock.get(f"https://api.github.com/repos/{repository}/releases/latest", json=release)
    aioclient_mock.get(f"{files}/{ESP32_ASSETS[0]}", content=b"firmware")
    aioclient_mock.get(f"{files}/{ESP32_ASSETS[1]}", text=f"{MD5.upper()}  HeishaMon.ino.bin\n")
    aioclient_mock.post(f"http://{IP}/firmware", text="Update success! Rebooting.")
    entry = await _setup(
        hass, {CONF_FIRMWARE_SOURCE: "custom", CONF_FIRMWARE_REPOSITORY: repository}
    )
    entity = _entity(hass)
    await REAL_LOOKUP(entity)
    await entity.async_install(None, False)
    urls = [str(c[1]) for c in aioclient_mock.mock_calls]
    # the latest release is known: no further lookup, no raw files
    assert urls == [
        f"https://api.github.com/repos/{repository}/releases/latest",
        f"{files}/{ESP32_ASSETS[0]}",
        f"{files}/{ESP32_ASSETS[1]}",
        f"http://{IP}/firmware",
    ]
    assert f"\r\n{MD5}\r\n".encode() in aioclient_mock.mock_calls[-1][2]
    await hass.config_entries.async_unload(entry.entry_id)


async def test_install_of_original_uses_main_binaries(hass, mqtt_mock, aioclient_mock):
    base = "https://github.com/heishamon/HeishaMon/raw/refs/heads/main/binaries/model-type-large"
    aioclient_mock.get(
        "https://api.github.com/repos/heishamon/HeishaMon/releases/tags/v4.4.1",
        json={"tag_name": "v4.4.1", "assets": []},
    )
    aioclient_mock.get(f"{base}/HeishaMon.ino.esp32-v4.4.1.bin", content=b"firmware")
    aioclient_mock.get(f"{base}/HeishaMon.ino.esp32-v4.4.1.md5", text=MD5)
    aioclient_mock.post(f"http://{IP}/firmware", text="Update success! Rebooting.")
    entry = await _setup(hass, {CONF_FIRMWARE_SOURCE: "original"})
    await _entity(hass).async_install("4.4.1", False)
    assert [str(c[1]) for c in aioclient_mock.mock_calls][1:3] == [
        f"{base}/HeishaMon.ino.esp32-v4.4.1.bin",
        f"{base}/HeishaMon.ino.esp32-v4.4.1.md5",
    ]
    await hass.config_entries.async_unload(entry.entry_id)


async def test_install_with_missing_asset_downloads_nothing(hass, mqtt_mock, aioclient_mock):
    aioclient_mock.get(
        "https://api.github.com/repos/st03psn/HeishaMon/releases/tags/v4.5.0",
        json=_release("st03psn/HeishaMon", "4.5.0", ("HeishaMon.ino.d1-v4.5.0.bin",)),
    )
    entry = await _setup(hass)
    entity = _entity(hass)
    with pytest.raises(HomeAssistantError) as err:
        await entity.async_install("4.5.0", False)
    assert err.value.translation_key == "firmware_asset_missing"
    assert len(aioclient_mock.mock_calls) == 1
    assert entity.in_progress is False
    await hass.config_entries.async_unload(entry.entry_id)


def test_checksum_is_parsed():
    assert parse_checksum(MD5) == MD5
    assert parse_checksum(f"{MD5.upper()}  HeishaMon.ino.bin\n") == MD5
    for bad in ("", "abc123", "<html>Not Found</html>"):
        with pytest.raises(HomeAssistantError):
            parse_checksum(bad)


# versions


@pytest.mark.parametrize(
    ("latest", "installed", "newer"),
    [
        ("4.5.0", "4.4.1", True),
        ("4.4.1", "4.5.0", False),  # never a downgrade
        ("4.5.0", "<= 3.1", True),
        ("4.5.0", "3.2", True),
        ("4.5.0", "Alpha-1a2b3c4", False),
        ("4.5.0", "alpha-1a2b3c4", False),
        ("4.5.0", "Nightly-1a2b3c4", False),
        ("4.5.0", "Local build", False),
        ("Alpha-1a2b3c4", "4.4.1", False),
    ],
)
def test_is_newer_version(latest, installed, newer):
    assert is_newer_version(latest, installed) is newer


@pytest.mark.parametrize(
    ("installed", "state"),
    [("4.4.1", "on"), ("4.5.0", "off"), ("Alpha-1a2b3c4", "off"), ("4.6.0", "off")],
)
async def test_state_of_development_builds(hass, mqtt_mock, installed, state):
    entry = await _setup(hass)
    entity = hass.data["update"].get_entity(ENTITY_ID)
    entity._attr_installed_version = installed
    entity._attr_latest_version = "4.5.0"
    entity.async_write_ha_state()
    current = hass.states.get(ENTITY_ID)
    assert current.state == state
    # the development build and the release stay visible
    assert current.attributes["installed_version"] == installed
    assert current.attributes["latest_version"] == "4.5.0"
    await hass.config_entries.async_unload(entry.entry_id)


async def test_alpha_build_reported_over_mqtt_is_not_offered_an_update(hass, mqtt_mock):
    from pytest_homeassistant_custom_component.common import async_fire_mqtt_message

    entry = await _setup(hass)
    entity = hass.data["update"].get_entity(ENTITY_ID)
    entity._attr_latest_version = "4.5.0"
    async_fire_mqtt_message(hass, f"{PREFIX}stats", '{"version": "Alpha-1a2b3c4"}')
    await hass.async_block_till_done()
    current = hass.states.get(ENTITY_ID)
    assert current.attributes["installed_version"] == "Alpha-1a2b3c4"
    assert current.state == "off"
    async_fire_mqtt_message(hass, f"{PREFIX}stats", '{"version": "v4.4.1"}')
    await hass.async_block_till_done()
    assert hass.states.get(ENTITY_ID).state == "on"
    await hass.config_entries.async_unload(entry.entry_id)
