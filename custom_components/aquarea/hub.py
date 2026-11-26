"""One picture of the heat pump for everything that needs more than one topic.

The hub listens to all topics of the heat pump, keeps their last payloads,
derives the operating state and follows the compressor runs. Entities and
later logic read from the hub instead of each keeping their own copies.
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import timedelta
from typing import Any, Optional

from homeassistant.components import mqtt
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STOP
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .logic.cycles import CycleTracker, RunFinished, RunStarted
from .logic.state import OperatingState, Snapshot, operating_state

_LOGGER = logging.getLogger(__name__)

STORAGE_VERSION = 1
# how often the run tracker is fed while no topic changes
TICK = timedelta(seconds=30)
# counters are written to disk at the end of a run and at most this often
SAVE_DELAY = 600

RunEvent = RunStarted | RunFinished


class HeatPumpHub:
    """State of one heat pump, shared by the entities of its config entry."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, mqtt_prefix: str) -> None:
        self.hass = hass
        self.entry = entry
        self.mqtt_prefix = mqtt_prefix
        # last payload of every topic below main/, keyed by topic name
        self.topics: dict[str, str] = {}
        # None until HeishaMon has reported whether it is connected
        self.online: Optional[bool] = None
        self.snapshot = Snapshot()
        self.state: Optional[OperatingState] = None
        self.cycles = CycleTracker()
        self._store: Store = Store(hass, STORAGE_VERSION, storage_key(entry.entry_id))
        self._listeners: list[Callable[[], None]] = []
        self._run_listeners: list[Callable[[RunEvent], None]] = []
        self._unsubscribe: list[CALLBACK_TYPE] = []
        self._saved_at = dt_util.utcnow().timestamp()

    async def async_load(self) -> None:
        """Restore the counters; called before the entities are created."""
        stored = await self._store.async_load()
        if stored is not None:
            try:
                self.cycles = CycleTracker.from_dict(stored["cycles"])
            except (KeyError, TypeError):
                _LOGGER.warning("Stored compressor run counters are not readable, starting new")

    async def async_start(self) -> None:
        """Start listening."""
        try:
            self._unsubscribe.append(
                await mqtt.async_subscribe(
                    self.hass, f"{self.mqtt_prefix}main/#", self._topic_received, 1
                )
            )
            self._unsubscribe.append(
                await mqtt.async_subscribe(
                    self.hass, f"{self.mqtt_prefix}LWT", self._lwt_received, 1
                )
            )
        except Exception:
            self._stop_listening()
            raise
        self._unsubscribe.append(
            async_track_time_interval(self.hass, self._tick, TICK)
        )
        # a normal stop of Home Assistant does not unload config entries
        self._unsubscribe.append(
            self.hass.bus.async_listen(EVENT_HOMEASSISTANT_STOP, self._save_on_stop)
        )

    async def _save_on_stop(self, _event: Any) -> None:
        await self._store.async_save(self._data_to_store())

    def _stop_listening(self) -> None:
        for unsubscribe in self._unsubscribe:
            unsubscribe()
        self._unsubscribe.clear()

    async def async_stop(self) -> None:
        """Stop listening and write the counters to disk."""
        self._stop_listening()
        await self._store.async_save(self._data_to_store())

    def async_add_listener(self, listener: Callable[[], None]) -> CALLBACK_TYPE:
        """Call `listener` whenever the state or a counter may have changed."""
        self._listeners.append(listener)
        return lambda: self._listeners.remove(listener)

    def async_add_run_listener(
        self, listener: Callable[[RunEvent], None]
    ) -> CALLBACK_TYPE:
        """Call `listener` when the compressor starts or stops."""
        self._run_listeners.append(listener)
        return lambda: self._run_listeners.remove(listener)

    @property
    def known_state(self) -> Optional[OperatingState]:
        """The operating state, None while HeishaMon is offline."""
        return None if self.online is False else self.state

    @callback
    def _topic_received(self, message: mqtt.ReceiveMessage) -> None:
        name = message.topic.rsplit("/", 1)[-1]
        payload = message.payload
        if not isinstance(payload, str):
            return
        if self.topics.get(name) == payload:
            return
        self.topics[name] = payload
        self._evaluate()

    @callback
    def _lwt_received(self, message: mqtt.ReceiveMessage) -> None:
        online = message.payload == "Online"
        if online != self.online:
            self.online = online
            self._evaluate()

    @callback
    def _tick(self, _now: Any = None) -> None:
        self._evaluate()

    @callback
    def _evaluate(self) -> None:
        self.snapshot = Snapshot.from_topics(self.topics)
        self.state = operating_state(self.snapshot)
        now = dt_util.utcnow()
        events = self.cycles.update(
            now.timestamp(), dt_util.as_local(now).date().isoformat(), self.known_state
        )
        for event in events:
            for run_listener in list(self._run_listeners):
                run_listener(event)
        finished = any(isinstance(event, RunFinished) for event in events)
        if finished or now.timestamp() - self._saved_at >= SAVE_DELAY:
            self._saved_at = now.timestamp()
            self.hass.async_create_task(self._store.async_save(self._data_to_store()))
        for listener in list(self._listeners):
            listener()

    def _data_to_store(self) -> dict[str, Any]:
        return {"cycles": self.cycles.as_dict()}


def storage_key(entry_id: str) -> str:
    """Return the key of the file that holds the run counters of an entry."""
    return f"{DOMAIN}.{entry_id}.cycles"


def get_hub(hass: HomeAssistant, entry_id: str) -> HeatPumpHub:
    """Return the hub of a config entry."""
    return hass.data[DOMAIN][entry_id]["hub"]


def find_hub(hass: HomeAssistant, entry_id: str) -> Optional[HeatPumpHub]:
    """Return the hub of a config entry, None when the entry is not set up."""
    return hass.data.get(DOMAIN, {}).get(entry_id, {}).get("hub")
