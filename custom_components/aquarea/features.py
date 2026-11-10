"""Follow the installation options reported by the heat pump.

Entities can declare the features they need (``requires`` in their
description). Depending on the option chosen by the user, those entities are
enabled when the feature is reported, shown as unavailable when it is not, or
disabled in the entity registry.
"""
from __future__ import annotations

from dataclasses import dataclass
import logging
import time
from typing import Callable, Iterable, Optional

from homeassistant.components import mqtt
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.storage import Store

from .const import (
    CONF_ENTITY_MANAGEMENT,
    DOMAIN,
    MODE_DISABLE,
    MODE_ENABLE_ONLY,
    Feature,
)

_LOGGER = logging.getLogger(__name__)

# topic (below the "main/" prefix) and payloads meaning "installed"
FEATURE_TOPICS: dict[Feature, tuple[str, frozenset[str]]] = {
    Feature.DHW: ("main/DHW_Installed", frozenset({"1"})),
    Feature.BUFFER: ("main/Buffer_Installed", frozenset({"1"})),
    Feature.SOLAR: ("main/Solar_Mode", frozenset({"1", "2"})),
    Feature.BIVALENT: ("main/Bivalent_Control", frozenset({"1"})),
    Feature.SG_READY: ("main/SG_Ready_Control", frozenset({"1", "2"})),
    Feature.OPTIONAL_PCB: ("main/Optional_PCB", frozenset({"1"})),
    Feature.COOLING: ("main/Cooling_Enable", frozenset({"1"})),
}
# features that only exist when another one is present
FEATURE_PARENTS: dict[Feature, Feature] = {
    Feature.SOLAR: Feature.OPTIONAL_PCB,
    Feature.SG_READY: Feature.OPTIONAL_PCB,
}

# wait for the burst of retained messages before touching the registry
SETTLE_DELAY = 10.0
# a feature must be reported as missing for that long before entities are disabled.
# The heat pump hides the child settings at once when a part is switched off, so
# entities follow right away; the settle delay above already skips the burst of
# retained messages after a start.
DISABLE_DELAY = 0.0

STORAGE_VERSION = 1


@dataclass(frozen=True)
class ManagedEntity:
    """An entity whose registry state follows some features."""

    platform: str
    unique_id: str
    requires: tuple[Feature, ...]
    # topics (without prefix) that must have been received before the entity is
    # enabled: they prove the firmware knows the entity
    topics: tuple[str, ...]


def managed_entities(
    entry_id: str, prefix: str, descriptions_by_platform: dict[str, Iterable]
) -> list[ManagedEntity]:
    """List entities declaring features, from their descriptions."""
    result = []
    for platform, descriptions in descriptions_by_platform.items():
        for description in descriptions:
            requires = tuple(getattr(description, "requires", ()) or ())
            if not requires:
                continue
            topics = [description.key.removeprefix(prefix)]
            marker = getattr(description, "firmware_marker", None)
            if marker is not None:
                topics.append(marker)
            result.append(
                ManagedEntity(
                    platform=platform,
                    unique_id=f"{entry_id}-{description.heishamon_topic_id}",
                    requires=requires,
                    topics=tuple(topics),
                )
            )
    return result


class FeatureTracker:
    """Track features of one heat pump and manage the entities needing them."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        entities: list[ManagedEntity],
    ) -> None:
        self.hass = hass
        self.entry_id = entry.entry_id
        self.prefix: str = entry.data["discovery_prefix"]
        self.mode: str = entry.options.get(CONF_ENTITY_MANAGEMENT, MODE_ENABLE_ONLY)
        self.entities = entities
        self._reported: dict[Feature, Optional[bool]] = {f: None for f in Feature}
        self._missing_since: dict[Feature, float] = {}
        self._seen_topics: set[str] = set()
        self._listeners: list[Callable[[], None]] = []
        self._unsubscribe: Optional[CALLBACK_TYPE] = None
        self._cancel_evaluation: Optional[CALLBACK_TYPE] = None
        self._store: Store = Store(
            hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}.entity_management"
        )
        # unique ids disabled by this tracker, and the ones the user enabled again
        self._auto_disabled: set[str] = set()
        self._user_kept: set[str] = set()
        self._stored_missing_since: dict[Feature, float] = {}

    async def async_start(self) -> None:
        data = await self._store.async_load() or {}
        self._auto_disabled = set(data.get("auto_disabled", []))
        self._user_kept = set(data.get("user_kept", []))
        # when a feature was first reported missing, kept across restarts and reloads
        # so that the delay before disabling does not start again each time
        self._stored_missing_since = {
            feature: since
            for feature in Feature
            if (since := data.get("missing_since", {}).get(feature.value)) is not None
        }
        self._unsubscribe = await mqtt.async_subscribe(
            self.hass, f"{self.prefix}main/+", self._message_received, 1
        )

    @callback
    def async_stop(self) -> None:
        if self._unsubscribe is not None:
            self._unsubscribe()
            self._unsubscribe = None
        if self._cancel_evaluation is not None:
            self._cancel_evaluation()
            self._cancel_evaluation = None

    async def async_remove_storage(self) -> None:
        await self._store.async_remove()

    def is_installed(self, feature: Feature) -> Optional[bool]:
        """Return whether a feature is installed, None while unknown."""
        own = self._reported[feature]
        if own is not True:
            return own
        parent = FEATURE_PARENTS.get(feature)
        if parent is not None and self.is_installed(parent) is False:
            return False
        return True

    def is_available(self, requires: Iterable[Feature]) -> bool:
        """Return False for entities to show as unavailable."""
        if self.mode == MODE_ENABLE_ONLY:
            return True
        return not any(self.is_installed(feature) is False for feature in requires)

    @callback
    def async_add_listener(self, listener: Callable[[], None]) -> CALLBACK_TYPE:
        self._listeners.append(listener)

        def remove() -> None:
            if listener in self._listeners:
                self._listeners.remove(listener)

        return remove

    @callback
    def _message_received(self, message) -> None:
        topic = message.topic.removeprefix(self.prefix)
        changed = False
        if topic not in self._seen_topics:
            self._seen_topics.add(topic)
            changed = True
        for feature, (feature_topic, installed_payloads) in FEATURE_TOPICS.items():
            if topic != feature_topic:
                continue
            payload = message.payload
            if isinstance(payload, bytes):
                payload = payload.decode("utf-8", errors="replace")
            reported = str(payload).strip() in installed_payloads
            if self._reported[feature] != reported:
                self._reported[feature] = reported
                self._features_changed()
                changed = True
        if changed:
            self._schedule_evaluation(SETTLE_DELAY)

    @callback
    def _features_changed(self) -> None:
        now = time.time()
        before = dict(self._missing_since)
        for feature in Feature:
            installed = self.is_installed(feature)
            if installed is False:
                self._missing_since.setdefault(
                    feature, self._stored_missing_since.get(feature, now)
                )
            elif installed is True:
                self._missing_since.pop(feature, None)
                self._stored_missing_since.pop(feature, None)
        if self._missing_since != before:
            self._save()
        for listener in list(self._listeners):
            listener()

    @callback
    def _save(self) -> None:
        self._store.async_delay_save(
            lambda: {
                "auto_disabled": sorted(self._auto_disabled),
                "user_kept": sorted(self._user_kept),
                "missing_since": {
                    feature.value: since
                    for feature, since in {
                        **self._stored_missing_since,
                        **self._missing_since,
                    }.items()
                },
            },
            1.0,
        )

    @callback
    def _schedule_evaluation(self, delay: float) -> None:
        if self._cancel_evaluation is not None:
            self._cancel_evaluation()
        self._cancel_evaluation = async_call_later(
            self.hass, delay, self._evaluate_later
        )

    @callback
    def _evaluate_later(self, _now) -> None:
        self._cancel_evaluation = None
        self.async_evaluate()

    @callback
    def async_evaluate(self) -> None:
        """Apply the features to the entity registry."""
        registry = er.async_get(self.hass)
        now = time.time()
        enabled = False
        stored_before = (set(self._auto_disabled), set(self._user_kept))
        next_check: Optional[float] = None

        for entity in self.entities:
            entity_id = registry.async_get_entity_id(
                entity.platform, DOMAIN, entity.unique_id
            )
            if entity_id is None:
                self._auto_disabled.discard(entity.unique_id)
                continue
            registry_entry = registry.async_get(entity_id)
            installed = [self.is_installed(feature) for feature in entity.requires]
            missing = any(state is False for state in installed)

            if entity.unique_id in self._auto_disabled and registry_entry.disabled_by is None:
                # enabled again by somebody else than this tracker
                self._auto_disabled.discard(entity.unique_id)
                if missing:
                    self._user_kept.add(entity.unique_id)
                    _LOGGER.info(
                        "%s was enabled by hand, it will not be disabled again",
                        entity_id,
                    )

            if all(state is True for state in installed):
                if (
                    registry_entry.disabled_by == er.RegistryEntryDisabler.INTEGRATION
                    and all(topic in self._seen_topics for topic in entity.topics)
                ):
                    registry.async_update_entity(entity_id, disabled_by=None)
                    self._auto_disabled.discard(entity.unique_id)
                    enabled = True
                    _LOGGER.info(
                        "Enabling %s: %s reported by the heat pump",
                        entity_id,
                        ", ".join(feature.value for feature in entity.requires),
                    )
                continue

            if (
                self.mode != MODE_DISABLE
                or not missing
                or registry_entry.disabled_by is not None
                or entity.unique_id in self._user_kept
            ):
                continue
            missing_features = [
                feature
                for feature in entity.requires
                if self.is_installed(feature) is False
            ]
            remaining = min(
                DISABLE_DELAY - (now - self._missing_since.get(feature, now))
                for feature in missing_features
            )
            if remaining > 0:
                next_check = remaining if next_check is None else min(next_check, remaining)
                continue
            registry.async_update_entity(
                entity_id, disabled_by=er.RegistryEntryDisabler.INTEGRATION
            )
            self._auto_disabled.add(entity.unique_id)
            _LOGGER.info(
                "Disabling %s: %s not installed according to the heat pump",
                entity_id,
                ", ".join(feature.value for feature in missing_features),
            )

        if (self._auto_disabled, self._user_kept) != stored_before:
            self._save()
        if next_check is not None:
            self._schedule_evaluation(next_check + 1.0)
        if enabled:
            self.hass.async_create_task(
                self.hass.config_entries.async_reload(self.entry_id)
            )


class FeatureGatedEntity:
    """Mixin showing an entity as unavailable while a feature it needs is missing."""

    def _feature_tracker(self) -> Optional[FeatureTracker]:
        hass = getattr(self, "hass", None)
        if hass is None:
            return None
        entry_id = getattr(self, "config_entry_entry_id", None)
        return hass.data.get(DOMAIN, {}).get(entry_id, {}).get("features")

    def _feature_requires(self) -> tuple[Feature, ...]:
        description = getattr(self, "entity_description", None)
        return tuple(getattr(description, "requires", ()) or ())

    @property
    def available(self) -> bool:
        requires = self._feature_requires()
        tracker = self._feature_tracker()
        if requires and tracker is not None and not tracker.is_available(requires):
            return False
        return super().available

    def _setup_feature_gating(self) -> None:
        """Refresh the state when features change. To call from async_added_to_hass."""
        tracker = self._feature_tracker()
        if tracker is not None and self._feature_requires():
            self.async_on_remove(tracker.async_add_listener(self.async_write_ha_state))
