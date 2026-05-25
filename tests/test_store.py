"""Tests for the persistent-state store."""

from __future__ import annotations

import time
from typing import Any

import pytest

from custom_components.battery_lifetime.const import (
    DEFAULT_PROFILE,
    PROFILE_ALKALINE,
    PROFILE_LITHIUM,
    REMOVED_SOURCE_RETENTION_DAYS,
    STORAGE_KEY,
    STORAGE_VERSION,
)
from custom_components.battery_lifetime.store import BatteryLifetimeStore


@pytest.fixture
async def store(hass: Any) -> BatteryLifetimeStore:
    s = BatteryLifetimeStore(hass)
    await s.async_load()
    return s


async def test_fresh_store_loads_defaults(store: BatteryLifetimeStore) -> None:
    assert store.default_profile == DEFAULT_PROFILE
    assert store.cold_start_backfill_announced is False
    assert list(store.iter_batteries()) == []


async def test_upsert_creates_entry_with_profile_default(
    store: BatteryLifetimeStore,
) -> None:
    entry = store.upsert_battery("uid-a", replaced_on="2026-04-01T12:00:00+00:00")
    assert entry["profile"] == DEFAULT_PROFILE
    assert entry["tracking_enabled"] is True
    assert entry["replaced_on"] == "2026-04-01T12:00:00+00:00"
    assert entry["threshold_override"] is None


async def test_upsert_rejects_unknown_field(store: BatteryLifetimeStore) -> None:
    with pytest.raises(KeyError):
        store.upsert_battery("uid-a", bogus=True)  # type: ignore[arg-type]


async def test_get_battery_returns_copy(store: BatteryLifetimeStore) -> None:
    store.upsert_battery("uid-a", profile=PROFILE_ALKALINE)
    snapshot = store.get_battery("uid-a")
    assert snapshot is not None
    snapshot["profile"] = "tampered"
    assert store.get_battery("uid-a")["profile"] == PROFILE_ALKALINE


async def test_round_trip_through_disk(hass: Any, hass_storage: dict) -> None:
    store_a = BatteryLifetimeStore(hass)
    await store_a.async_load()
    store_a.set_default_profile(PROFILE_ALKALINE)
    store_a.upsert_battery(
        "uid-a",
        replaced_on="2026-01-01T00:00:00+00:00",
        profile=PROFILE_LITHIUM,
        last_reading_pct=72.5,
    )
    await store_a.async_save()

    raw = hass_storage[STORAGE_KEY]["data"]
    assert raw["version"] == STORAGE_VERSION
    assert raw["default_profile"] == PROFILE_ALKALINE
    assert raw["batteries"]["uid-a"]["profile"] == PROFILE_LITHIUM
    assert raw["batteries"]["uid-a"]["last_reading_pct"] == 72.5

    store_b = BatteryLifetimeStore(hass)
    await store_b.async_load()
    assert store_b.default_profile == PROFILE_ALKALINE
    entry = store_b.get_battery("uid-a")
    assert entry is not None
    assert entry["profile"] == PROFILE_LITHIUM
    assert entry["last_reading_pct"] == 72.5
    assert entry["tracking_enabled"] is True


async def test_migration_fills_missing_fields(
    hass: Any, hass_storage: dict
) -> None:
    hass_storage[STORAGE_KEY] = {
        "version": 1,
        "key": STORAGE_KEY,
        "data": {
            "version": 1,
            "batteries": {
                "uid-old": {
                    "replaced_on": "2025-12-31T00:00:00+00:00",
                }
            },
        },
    }
    store = BatteryLifetimeStore(hass)
    await store.async_load()
    assert store.default_profile == DEFAULT_PROFILE
    entry = store.get_battery("uid-old")
    assert entry is not None
    assert entry["profile"] == DEFAULT_PROFILE
    assert entry["tracking_enabled"] is True
    assert entry["threshold_override"] is None
    assert store.cold_start_backfill_announced is True


async def test_remove_then_prune(store: BatteryLifetimeStore) -> None:
    store.upsert_battery("uid-a")
    store.upsert_battery("uid-b")
    store.remove_battery("uid-a")
    pruned = store.prune_removed_older_than(
        days=REMOVED_SOURCE_RETENTION_DAYS,
        now=time.time() + (REMOVED_SOURCE_RETENTION_DAYS + 1) * 86400.0,
    )
    assert pruned == ["uid-a"]
    assert store.get_battery("uid-a") is None
    assert store.get_battery("uid-b") is not None


async def test_remove_inside_retention_window_keeps_entry(
    store: BatteryLifetimeStore,
) -> None:
    store.upsert_battery("uid-a")
    store.remove_battery("uid-a")
    pruned = store.prune_removed_older_than(
        days=REMOVED_SOURCE_RETENTION_DAYS,
        now=time.time() + (REMOVED_SOURCE_RETENTION_DAYS - 1) * 86400.0,
    )
    assert pruned == []
    assert store.get_battery("uid-a") is not None


async def test_restore_battery_clears_removed_at(
    store: BatteryLifetimeStore,
) -> None:
    store.upsert_battery("uid-a")
    store.remove_battery("uid-a")
    assert store.get_battery("uid-a")["removed_at"] is not None
    store.restore_battery("uid-a")
    assert store.get_battery("uid-a")["removed_at"] is None


async def test_iter_batteries_returns_copies(
    store: BatteryLifetimeStore,
) -> None:
    store.upsert_battery("uid-a", profile=PROFILE_ALKALINE)
    snapshot = list(store.iter_batteries())
    assert len(snapshot) == 1
    unique_id, entry = snapshot[0]
    assert unique_id == "uid-a"
    entry["profile"] = "tampered"
    assert store.get_battery("uid-a")["profile"] == PROFILE_ALKALINE
