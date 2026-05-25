"""Persistent state for the Battery Lifetime integration.

The store keeps integration-level settings and per-battery state keyed by
the source entity's ``unique_id`` from the entity registry. State survives
HA restarts and is independent of the recorder's retention policy.

Schema is versioned so future migrations can be applied without losing data.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Iterable, Iterator, Mapping
from copy import deepcopy
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import (
    DEFAULT_PROFILE,
    REMOVED_SOURCE_RETENTION_DAYS,
    STORAGE_KEY,
    STORAGE_VERSION,
)

_LOGGER = logging.getLogger(__name__)

_SAVE_DEBOUNCE_SECONDS = 10.0

_PER_BATTERY_FIELDS: tuple[str, ...] = (
    "replaced_on",
    "profile",
    "threshold_override",
    "tracking_enabled",
    "ewma_state",
    "last_reading_pct",
    "last_reading_at",
    "last_replace_by",
    "removed_at",
)


def _empty_data(default_profile: str = DEFAULT_PROFILE) -> dict[str, Any]:
    return {
        "version": STORAGE_VERSION,
        "default_profile": default_profile,
        "cold_start_backfill_announced": False,
        "batteries": {},
    }


class BatteryLifetimeStore:
    """Wrapper around HA's :class:`Store` helper.

    All write operations go through ``async_save_debounced``: small, frequent
    updates from the coordinator are coalesced into a single disk write so we
    don't thrash the storage on every state-change event.
    """

    def __init__(self, hass: HomeAssistant) -> None:
        self._hass = hass
        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, STORAGE_KEY
        )
        self._data: dict[str, Any] = _empty_data()
        self._loaded = False

    async def async_load(self) -> None:
        """Load state from disk, applying schema migrations if needed."""
        raw = await self._store.async_load()
        if raw is None:
            self._data = _empty_data()
        else:
            self._data = self._migrate(raw)
        self._loaded = True

    async def async_save(self) -> None:
        """Force-write the current state to disk."""
        await self._store.async_save(self._data)

    def async_save_debounced(self) -> None:
        """Schedule a disk write, coalescing rapid successive calls."""
        self._store.async_delay_save(self._data_provider, _SAVE_DEBOUNCE_SECONDS)

    def _data_provider(self) -> dict[str, Any]:
        return self._data

    def _ensure_loaded(self) -> None:
        if not self._loaded:
            raise RuntimeError("BatteryLifetimeStore used before async_load()")

    @staticmethod
    def _migrate(raw: Mapping[str, Any]) -> dict[str, Any]:
        """Bring a loaded dict up to the current ``STORAGE_VERSION``."""
        data = deepcopy(dict(raw))
        version = int(data.get("version", 1))
        if version > STORAGE_VERSION:
            _LOGGER.warning(
                "Battery Lifetime store version %s is newer than supported %s; "
                "loading as-is",
                version,
                STORAGE_VERSION,
            )
        elif version < STORAGE_VERSION:
            _LOGGER.info(
                "Migrating Battery Lifetime store from version %s to %s",
                version,
                STORAGE_VERSION,
            )
        data.setdefault("default_profile", DEFAULT_PROFILE)
        data.setdefault("batteries", {})
        if "cold_start_backfill_announced" not in data:
            # Existing installs already passed the initial backfill phase.
            data["cold_start_backfill_announced"] = bool(data["batteries"])
        data["version"] = STORAGE_VERSION
        for entry in data["batteries"].values():
            for field in _PER_BATTERY_FIELDS:
                entry.setdefault(field, None)
            if entry.get("tracking_enabled") is None:
                entry["tracking_enabled"] = True
            if entry.get("profile") is None:
                entry["profile"] = data["default_profile"]
        return data

    @property
    def default_profile(self) -> str:
        self._ensure_loaded()
        return str(self._data.get("default_profile", DEFAULT_PROFILE))

    @property
    def cold_start_backfill_announced(self) -> bool:
        """Whether the one-time cold-start backfill notification was shown."""
        self._ensure_loaded()
        return bool(self._data.get("cold_start_backfill_announced"))

    def set_cold_start_backfill_announced(self) -> None:
        """Mark the initial cold-start backfill batch as announced."""
        self._ensure_loaded()
        self._data["cold_start_backfill_announced"] = True
        self.async_save_debounced()

    def set_default_profile(self, profile: str) -> None:
        self._ensure_loaded()
        self._data["default_profile"] = profile
        self.async_save_debounced()

    def get_battery(self, unique_id: str) -> dict[str, Any] | None:
        """Return the per-battery dict, or ``None`` if not stored yet."""
        self._ensure_loaded()
        entry = self._data["batteries"].get(unique_id)
        if entry is None:
            return None
        return deepcopy(entry)

    def upsert_battery(self, unique_id: str, **fields: Any) -> dict[str, Any]:
        """Create or update the per-battery entry. Returns the new state."""
        self._ensure_loaded()
        batteries = self._data["batteries"]
        entry = batteries.get(unique_id)
        if entry is None:
            entry = {field: None for field in _PER_BATTERY_FIELDS}
            entry["tracking_enabled"] = True
            entry["profile"] = self.default_profile
            batteries[unique_id] = entry
        for key, value in fields.items():
            if key not in _PER_BATTERY_FIELDS:
                raise KeyError(
                    f"unknown per-battery field {key!r}; "
                    f"allowed: {_PER_BATTERY_FIELDS}"
                )
            entry[key] = value
        self.async_save_debounced()
        return deepcopy(entry)

    def remove_battery(self, unique_id: str) -> None:
        """Mark the battery's source as removed; pruning happens later."""
        self._ensure_loaded()
        entry = self._data["batteries"].get(unique_id)
        if entry is None:
            return
        entry["removed_at"] = time.time()
        self.async_save_debounced()

    def restore_battery(self, unique_id: str) -> None:
        """Reverse a previous ``remove_battery``; the source returned."""
        self._ensure_loaded()
        entry = self._data["batteries"].get(unique_id)
        if entry is None:
            return
        entry["removed_at"] = None
        self.async_save_debounced()

    def iter_batteries(self) -> Iterator[tuple[str, dict[str, Any]]]:
        """Yield ``(unique_id, entry_copy)`` for every stored battery."""
        self._ensure_loaded()
        for unique_id, entry in self._data["batteries"].items():
            yield unique_id, deepcopy(entry)

    def prune_removed_older_than(
        self,
        days: int = REMOVED_SOURCE_RETENTION_DAYS,
        *,
        now: float | None = None,
    ) -> list[str]:
        """Drop entries whose source has been gone longer than ``days``.

        Returns the list of pruned ``unique_id`` values.
        """
        self._ensure_loaded()
        now_ts = time.time() if now is None else now
        cutoff = now_ts - days * 86400.0
        to_remove: list[str] = []
        for unique_id, entry in self._data["batteries"].items():
            removed_at = entry.get("removed_at")
            if removed_at is not None and float(removed_at) < cutoff:
                to_remove.append(unique_id)
        for unique_id in to_remove:
            self._data["batteries"].pop(unique_id, None)
        if to_remove:
            self.async_save_debounced()
        return to_remove

    def known_unique_ids(self) -> Iterable[str]:
        self._ensure_loaded()
        return list(self._data["batteries"].keys())
