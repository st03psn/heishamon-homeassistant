"""Support for HeishaMon controlled heatpumps through MQTT."""
from __future__ import annotations
import re
import logging
import json
import aiohttp
import datetime
import asyncio
import uuid
from dataclasses import dataclass
from typing import Optional, Any

from awesomeversion import AwesomeVersion

from homeassistant.helpers.event import async_track_time_interval
from homeassistant.components import mqtt
from homeassistant.components.mqtt.client import async_publish
from homeassistant.components.update.const import UpdateEntityFeature
from homeassistant.components.update import (
    UpdateEntity,
    UpdateEntityDescription,
    UpdateDeviceClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import slugify
from homeassistant.const import EVENT_HOMEASSISTANT_STOP

from . import build_device_info
from .auth import api_key_headers, board_connection, tls_error
from .const import (
    CONF_FIRMWARE_REPOSITORY,
    CONF_FIRMWARE_SOURCE,
    DEFAULT_FIRMWARE_SOURCE,
    DOMAIN,
    FIRMWARE_REPOSITORY_PATTERN,
    FIRMWARE_SOURCE_CUSTOM,
    FIRMWARE_SOURCE_ORIGINAL,
    FORK_FIRMWARE_REPOSITORY,
    ORIGINAL_FIRMWARE_REPOSITORY,
    DeviceType,
)
from .translated_name import TranslatedNameMixin
from .definitions.descriptions import HeishaMonEntityDescription
from .definitions.values import read_board_type

_LOGGER = logging.getLogger(__name__)


def firmware_repository(options) -> str | None:
    """Return the owner/repo the firmware is taken from, None if not usable.

    Entries created before the option existed have no value and use the fork.
    """
    source = options.get(CONF_FIRMWARE_SOURCE, DEFAULT_FIRMWARE_SOURCE)
    if source == FIRMWARE_SOURCE_ORIGINAL:
        return ORIGINAL_FIRMWARE_REPOSITORY
    if source == FIRMWARE_SOURCE_CUSTOM:
        repository = (options.get(CONF_FIRMWARE_REPOSITORY) or "").strip()
        if re.fullmatch(FIRMWARE_REPOSITORY_PATTERN, repository):
            return repository
        return None
    return FORK_FIRMWARE_REPOSITORY


def latest_release_url(repository: str) -> str:
    return f"https://api.github.com/repos/{repository}/releases/latest"


def release_by_tag_url(repository: str, version: str) -> str:
    return f"https://api.github.com/repos/{repository}/releases/tags/v{version}"


def firmware_asset_names(model_file: str, version: str) -> tuple[str, str]:
    """Names of the firmware binary and its checksum in a release."""
    stem = f"HeishaMon.ino.{model_file}-v{version}"
    return f"{stem}.bin", f"{stem}.md5"


def raw_binaries_urls(
    repository: str, model_path: str, model_file: str, version: str
) -> tuple[str, str]:
    """Files committed to main/binaries (how the original project publishes)."""
    binary, checksum = firmware_asset_names(model_file, version)
    base = f"https://github.com/{repository}/raw/refs/heads/main/binaries/{model_path}"
    return f"{base}/{binary}", f"{base}/{checksum}"


def firmware_download_urls(
    repository: str,
    release: dict | None,
    model_path: str,
    model_file: str,
    version: str,
) -> tuple[str, str]:
    """Return the URLs of binary and checksum for a board model.

    Release assets are preferred. Only the original project falls back to its
    main/binaries folder; any other source must attach both files to the
    release, otherwise nothing is downloaded.
    """
    binary, checksum = firmware_asset_names(model_file, version)
    assets = {
        asset.get("name"): asset.get("browser_download_url")
        for asset in (release or {}).get("assets") or []
    }
    if assets.get(binary) and assets.get(checksum):
        return assets[binary], assets[checksum]
    if repository == ORIGINAL_FIRMWARE_REPOSITORY:
        return raw_binaries_urls(repository, model_path, model_file, version)
    raise HomeAssistantError(
        translation_domain=DOMAIN,
        translation_key="firmware_asset_missing",
        translation_placeholders={
            "version": version,
            "repository": repository,
            "asset": binary if not assets.get(binary) else checksum,
        },
    )


def comparable_version(version: str | None) -> AwesomeVersion | None:
    """Parse a firmware version, None for builds without one (Alpha-<sha>, Nightly-<sha>)."""
    if not version:
        return None
    # firmware older than 3.2 does not report a version, we show "<= 3.1"
    parsed = AwesomeVersion(version.lstrip("<= ").lstrip("vV"))
    return parsed if parsed.valid else None


def is_newer_version(latest_version: str, installed_version: str) -> bool:
    """Only offer an update when both versions are real version numbers."""
    latest = comparable_version(latest_version)
    installed = comparable_version(installed_version)
    if latest is None or installed is None:
        return False
    return latest > installed


def parse_checksum(text: str) -> str:
    """Accept a bare MD5 or the output of md5sum ("<hash>  <file>")."""
    token = (text or "").split()[0] if (text or "").split() else ""
    if not re.fullmatch(r"[0-9a-fA-F]{32}", token):
        raise HomeAssistantError(
            f"The firmware checksum file does not contain an MD5 checksum: {text[:80]!r}"
        )
    return token.lower()


def _firmware_http_error(
    phase: str, status: int, reason: str, version: str
) -> HomeAssistantError:
    """Build an actionable error for an unsuccessful firmware HTTP request."""
    status_detail = f" {reason}" if reason else ""
    if phase == "upload" and status in (401, 403):
        return HomeAssistantError(
            f"HeishaMon rejected the firmware upload (HTTP {status}{status_detail}). "
            "If a password is configured on HeishaMon, set its API key in the "
            "options of the integration."
        )
    if phase == "upload":
        return HomeAssistantError(
            f"HeishaMon returned HTTP {status}{status_detail} while uploading firmware "
            f"version {version}."
        )
    return HomeAssistantError(
        f"Could not {phase} firmware version {version}: HTTP {status}{status_detail}."
    )


def _firmware_upload_error(
    status: int, reason: str, response_body: str, version: str
) -> HomeAssistantError | None:
    """Return an error reported by HeishaMon, if the upload failed."""
    if status != 200:
        return _firmware_http_error("upload", status, reason, version)

    # HeishaMon can report a firmware failure in the response body with HTTP 200.
    if "update failed" in response_body.lower():
        detail = re.sub(r"<[^>]*>", " ", response_body)
        detail = " ".join(detail.split())[:300]
        return HomeAssistantError(
            f"HeishaMon reported a firmware update failure: {detail}"
        )
    return None


# async_setup_platform should be defined if one wants to support config via configuration.yaml


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up HeishaMon updates from config entry."""
    discovery_prefix = config_entry.data["discovery_prefix"]
    _LOGGER.debug(
        f"Starting bootstrap of updates entities with prefix '{discovery_prefix}'"
    )

    firmware_update = HeishaMonUpdateEntityDescription(
        key="heishamon_firmware",
        name="HeishaMon Firmware update",
        translation_key="heishamon_firmware_update",
        heishamon_topic_id=f"{discovery_prefix}stats",
        device_class=UpdateDeviceClass.FIRMWARE,
        device=DeviceType.HEISHAMON,
    )

    update_entity = HeishaMonMQTTUpdate(hass, firmware_update, config_entry)
    async_add_entities([update_entity])


async def async_update_progress_tracking(update_entity) -> None:
    _LOGGER.debug("Update ha state, this periodic task should only run while a firmware update is in progress")
    update_entity.async_write_ha_state()


@dataclass(frozen=True, kw_only=True)
class HeishaMonUpdateEntityDescription(
    HeishaMonEntityDescription, UpdateEntityDescription
):
    pass


class HeishaMonMQTTUpdate(TranslatedNameMixin, UpdateEntity):
    """Representation of a HeishaMon update that is updated via MQTT."""

    entity_description: HeishaMonUpdateEntityDescription

    def __init__(
        self,
        hass: HomeAssistant,
        description: HeishaMonUpdateEntityDescription,
        config_entry: ConfigEntry,
    ) -> None:
        self.entity_description = description
        self.config_entry = config_entry
        self.config_entry_entry_id = config_entry.entry_id
        self.hass = hass
        self.discovery_prefix = config_entry.data["discovery_prefix"]

        slug = slugify(description.key.replace("/", "_"))
        self.entity_id = f"update.{slug}"
        self._attr_unique_id = (
            f"{config_entry.entry_id}-{description.heishamon_topic_id}"
        )

        self.marker3_2_topic = f"{self.discovery_prefix}main/Heat_Power_Production"
        self.marker3_1_and_before_topic = (
            f"{self.discovery_prefix}main/Heat_Energy_Production"
        )
        self.stats_firmware_contain_version: Optional[bool] = None

        self._attr_supported_features = (
            UpdateEntityFeature.RELEASE_NOTES | UpdateEntityFeature.INSTALL | UpdateEntityFeature.PROGRESS | UpdateEntityFeature.SPECIFIC_VERSION
        )
        self._repository = firmware_repository(config_entry.options)
        self._attr_release_url = (
            f"https://github.com/{self._repository}/releases"
            if self._repository
            else None
        )
        self._model_type = None
        self._release_notes = None
        self._latest_release: dict | None = None
        self._attr_in_progress = False

        self._ip_topic = f"{self.discovery_prefix}ip"
        self._heishamon_ip = None

        self._stats_topic = f"{self.discovery_prefix}stats"

    async def async_added_to_hass(self) -> None:
        """Subscribe to MQTT events."""

        @callback
        def ip_received(message):
            self._heishamon_ip = message.payload
        await mqtt.async_subscribe(self.hass, self._ip_topic, ip_received, 1)

        @callback
        def read_model(message):
            self._model_type = read_board_type(message.payload)
        await mqtt.async_subscribe(self.hass, self._stats_topic, read_model, 1)


        @callback
        def message_received(message):
            """Handle new MQTT messages."""
            if (
                self.stats_firmware_contain_version == False
                and message.topic == self.marker3_2_topic
            ):
                self._attr_installed_version = "3.2"
            if (
                self.stats_firmware_contain_version == False
                and message.topic == self.marker3_1_and_before_topic
            ):
                self._attr_installed_version = "<= 3.1"
            if message.topic == self.entity_description.heishamon_topic_id:
                field_value = json.loads(message.payload).get("version", None)
                if field_value:
                    self.stats_firmware_contain_version = True
                    # development builds report "Alpha-<sha>" or "Nightly-<sha>":
                    # shown as they are, version_is_newer never offers them an update
                    self._attr_installed_version = field_value.lstrip('v')
                else:
                    self.stats_firmware_contain_version = False
            # we only write value when we know for sure how to get version
            # this avoids having flickering of value when HA start (if we receive a marker3_2_topic message
            # before we get the stats message)
            if self.stats_firmware_contain_version is not None:
                self.async_write_ha_state()

        await mqtt.async_subscribe(self.hass, self.marker3_2_topic, message_received, 1)
        await mqtt.async_subscribe(
            self.hass, self.marker3_1_and_before_topic, message_received, 1
        )
        await mqtt.async_subscribe(
            self.hass, self.entity_description.heishamon_topic_id, message_received, 1
        )

        # TODO(kamaradclimber): schedule this on a regular basis instead of just at startup
        await self._update_latest_release()

    @property
    def device_info(self):
        return build_device_info(self.hass, self.entity_description.device, self.discovery_prefix, self.config_entry_entry_id)

    def version_is_newer(self, latest_version: str, installed_version: str) -> bool:
        """Never offer an update to or from a build without a version number.

        Home Assistant reports an update when it cannot compare the versions,
        which would offer any release to an "Alpha-<sha>" build, possibly a
        downgrade. Such builds can still be updated with update.install.
        """
        return is_newer_version(latest_version, installed_version)

    async def _update_latest_release(self):
        _LOGGER.debug("Starting refresh latest version info")
        if self._repository is None:
            _LOGGER.warning("No valid firmware repository configured, not looking for releases")
            return
        session = async_get_clientsession(self.hass)
        url = latest_release_url(self._repository)
        _LOGGER.info("Fetching %s", url)
        resp = await session.get(url)

        if resp.status == 404:
            _LOGGER.info("Repository %s has no published release yet", self._repository)
            return
        if resp.status != 200:
            _LOGGER.warning(
                "Impossible to get latest release from repository %s (HTTP %s)",
                self._repository,
                resp.status,
            )
            return

        last_release = await resp.json()
        self._latest_release = last_release
        self._attr_latest_version = re.sub(r"^v", "", last_release["tag_name"])
        self._attr_release_url = last_release.get("html_url") or self._attr_release_url
        self._release_notes = last_release.get("body")
        _LOGGER.debug(f"Latest release is {self._attr_latest_version}")
        self.async_write_ha_state()

    async def _release_for(self, session, version: str) -> dict | None:
        """The release of a version, None if the repository has none for it."""
        latest = self._latest_release
        if latest is not None and re.sub(r"^v", "", latest.get("tag_name", "")) == version:
            return latest
        original = self._repository == ORIGINAL_FIRMWARE_REPOSITORY
        try:
            resp = await session.get(release_by_tag_url(self._repository, version))
        except aiohttp.ClientError as e:
            if original:
                # its main/binaries folder is still there
                _LOGGER.info("Release lookup in %s failed: %s", self._repository, e)
                return None
            raise HomeAssistantError(
                f"Could not look up release v{version} of {self._repository}: {e}"
            ) from e
        if resp.status == 200:
            return await resp.json()
        if resp.status == 404 or original:
            _LOGGER.info(
                "No release v%s in %s (HTTP %s)", version, self._repository, resp.status
            )
            return None
        # e.g. a rate limit: not the same as a release without the file
        raise _firmware_http_error(
            f"look up release v{version} of {self._repository} for",
            resp.status,
            resp.reason or "",
            version,
        )

    @property
    def model_to_path(self) -> str | None:
        return {
            "ESP32": "model-type-large",
            "ESP8266": "model-type-small",
            None: "UNKNOWN",
        }.get(self._model_type, None)

    @property
    def model_to_file(self) -> str | None:
        return {
            "ESP32": "esp32",
            "ESP8266": "d1",
            None: "UNKNOWN",
        }.get(self._model_type, None)


    def release_notes(self) -> str | None:
        return (
            f"⚠️ Automated upgrades will fetch `{self.model_to_path}` binaries "
            f"from `{self._repository}`.\n\nBeware!\n\n" + str(self._release_notes)
        )

    async def async_install(self, version: str | None, backup: bool, **kwargs: Any) -> None:
        if self._model_type is None:
            raise HomeAssistantError(
                "Cannot install HeishaMon firmware automatically because the board "
                "type is unknown."
            )
        if version is None:
            version = self._attr_latest_version
            _LOGGER.info(f"Will install latest version ({version}) of the firmware")
        else:
            version = version.lstrip("v")
            _LOGGER.info(f"Will install version {version} of the firmware")
        if version is None or self._repository is None:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="firmware_version_unknown",
                translation_placeholders={"repository": str(self._repository)},
            )
        session = async_get_clientsession(self.hass)
        # resolved before the update is in progress: a missing asset is an error
        # of its own, never a reason to download something else
        release = await self._release_for(session, version)
        binary_url, checksum_url = firmware_download_urls(
            self._repository, release, self.model_to_path, self.model_to_file, version
        )
        self._attr_in_progress = True
        self._attr_update_percentage = 0
        try:
            url = binary_url
            _LOGGER.debug(f"Will try to download url {url}")
            resp = await session.get(url)

            if resp.status != 200:
                _LOGGER.warning(
                    "Could not download firmware version %s from %s (HTTP %s)",
                    version,
                    url,
                    resp.status,
                )
                raise _firmware_http_error(
                    "download", resp.status, resp.reason or "", version
                )

            firmware_binary = await resp.read()
            _LOGGER.info(f"Firmware is {len(firmware_binary)} bytes long")
            self._attr_update_percentage = 10
            url = checksum_url
            resp = await session.get(url)

            if resp.status != 200:
                _LOGGER.warning(
                    "Could not download checksum for firmware version %s from "
                    "%s (HTTP %s)",
                    version,
                    url,
                    resp.status,
                )
                raise _firmware_http_error(
                    "download checksum", resp.status, resp.reason or "", version
                )
            checksum = parse_checksum(await resp.text())
            self._attr_update_percentage = 20
            _LOGGER.info(f"Downloaded binary and checksum {checksum} of version {version}")

            while self._heishamon_ip is None:
                _LOGGER.warn("Waiting for an mqtt message to get the ip address of heishamon")
                await asyncio.sleep(1)
        except HomeAssistantError:
            self._attr_in_progress = False
            raise
        except Exception as e:
            self._attr_in_progress = False
            _LOGGER.exception("Unable to prepare firmware version %s", version)
            raise HomeAssistantError(
                f"Could not prepare firmware version {version}: {e}"
            ) from e

        # This whole mechanic is made to call async_write_ha_state to make sure the entity state (especially the _attr_in_progress attribute is updated)
        # trying to call this method from a callback when posting the firmware update leads HA to crash the integration
        @callback
        def callback_update_progress_tracking(now) -> None:
            self.config_entry.async_create_background_task(self.hass, async_update_progress_tracking(self), name="update entity to track progress", eager_start=True)
        cancel_update_tracking_schedule = async_track_time_interval(self.hass, callback_update_progress_tracking, datetime.timedelta(seconds=1))
        def stop_update_progress_tracking(*_: Any) -> None:
            cancel_update_tracking_schedule()
        # we stop at the end of the update or (if it crashes badly, at HA stop)
        self.hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, stop_update_progress_tracking)
        self.hass.bus.async_listen_once("stop_heishamon_update_tracker", stop_update_progress_tracking)

        session = async_get_clientsession(self.hass)
        _LOGGER.info(f"Starting upgrade of firmware to version {version} on {self._heishamon_ip}")
        to = aiohttp.ClientTimeout(total=300, connect=10)
        try:
            boundary = uuid.uuid4().hex
            filename = f"HeishaMon.ino.{self.model_to_file}-v{version}.bin"
            body = (
                f"--{boundary}\r\n"
                f"Content-Type: application/octet-stream\r\n"
                f"Content-Disposition: form-data; name=\"firmware\"; filename=\"{filename}\"\r\n"
                f"Content-Length: {len(firmware_binary)}\r\n"
                f"\r\n"
            ).encode() + firmware_binary + (
                f"\r\n"
                f"--{boundary}\r\n"
                f"Content-Disposition: form-data; name=\"md5\"\r\n"
                f"\r\n"
                f"{checksum}\r\n"
                f"--{boundary}--\r\n"
            ).encode()
            base_url, ssl = board_connection(self.config_entry, self._heishamon_ip)
            resp = await session.post(
                f"{base_url}/firmware",
                data=body,
                headers={
                    'Content-Type': f'multipart/form-data; boundary={boundary}',
                    **api_key_headers(self.config_entry),
                },
                timeout=to,
                ssl=ssl,
                allow_redirects=False,  # never follow the board to plain http
            )
            response_body = await resp.text()
        except (TimeoutError, asyncio.TimeoutError):
            _LOGGER.info(f"Firmware upload complete, HeishaMon is rebooting (timeout is expected)")
            return
        except aiohttp.ClientError as e:
            certificate_error = tls_error(e, self._heishamon_ip)
            if certificate_error is not None:
                _LOGGER.warning(
                    "Certificate of HeishaMon at %s rejected during upload of "
                    "firmware version %s: %r", self._heishamon_ip, version, e
                )
                raise certificate_error from e
            # a board with a login closes the connection without an answer
            # when the API key is missing or wrong
            _LOGGER.warning("Connection to HeishaMon failed during upload of firmware version %s: %s", version, e)
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="firmware_upload_connection_failed",
                translation_placeholders={
                    "version": version,
                    "host": str(self._heishamon_ip),
                    "error": f"{type(e).__name__}: {e}",
                },
            ) from e
        except Exception as e:
            _LOGGER.exception("Unable to upload firmware version %s", version)
            raise HomeAssistantError(
                f"Could not upload firmware version {version} to HeishaMon at "
                f"{self._heishamon_ip}: {e}"
            ) from e
        finally:
            self.hass.bus.fire("stop_heishamon_update_tracker")
        upload_error = _firmware_upload_error(
            resp.status, resp.reason or "", response_body, version
        )
        if upload_error is not None:
            _LOGGER.warning(
                "HeishaMon firmware upload failed for version %s: %s",
                version,
                upload_error,
            )
            raise upload_error
        _LOGGER.info(f"Finished uploading firmware. Heishamon should now be rebooting")
