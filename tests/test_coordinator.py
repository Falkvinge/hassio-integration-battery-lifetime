"""Tests for entity-source discovery and the coordinator."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.const import PERCENTAGE
from homeassistant.helpers import entity_registry as er

from custom_components.battery_lifetime.const import DOMAIN
from custom_components.battery_lifetime.coordinator import (
    BatteryLifetimeCoordinator,
)
from custom_components.battery_lifetime.discovery import (
    is_eligible,
    iter_eligible_entities,
    reset_skip_log,
)
from custom_components.battery_lifetime.store import BatteryLifetimeStore

UTC = timezone.utc


@pytest.fixture(autouse=True)
def _reset_skip_log() -> None:
    reset_skip_log()


def _register(
    registry: er.EntityRegistry,
    *,
    entity_id: str,
    unique_id: str,
    platform: str = "demo",
    device_class: str | None = SensorDeviceClass.BATTERY,
    unit: str | None = PERCENTAGE,
) -> er.RegistryEntry:
    domain, object_id = entity_id.split(".", 1)
    return registry.async_get_or_create(
        domain=domain,
        platform=platform,
        unique_id=unique_id,
        suggested_object_id=object_id,
        original_device_class=device_class,
        unit_of_measurement=unit,
    )


async def test_is_eligible_accepts_numeric_percent_battery(hass: Any) -> None:
    registry = er.async_get(hass)
    entry = _register(
        registry, entity_id="sensor.foo_battery", unique_id="uid-foo"
    )
    hass.states.async_set("sensor.foo_battery", "62", {})
    assert is_eligible(hass, entry) is True


async def test_is_eligible_rejects_categorical_state(hass: Any) -> None:
    registry = er.async_get(hass)
    entry = _register(
        registry, entity_id="sensor.foo_battery", unique_id="uid-foo"
    )
    hass.states.async_set("sensor.foo_battery", "low", {})
    assert is_eligible(hass, entry) is False


async def test_is_eligible_rejects_voltage_unit(hass: Any) -> None:
    registry = er.async_get(hass)
    entry = _register(
        registry,
        entity_id="sensor.foo_battery",
        unique_id="uid-foo",
        unit="V",
    )
    hass.states.async_set("sensor.foo_battery", "1.5", {})
    assert is_eligible(hass, entry) is False


async def test_is_eligible_rejects_binary_battery(hass: Any) -> None:
    registry = er.async_get(hass)
    entry = _register(
        registry,
        entity_id="binary_sensor.foo_battery_low",
        unique_id="uid-foo",
        device_class=SensorDeviceClass.BATTERY,
        unit=None,
    )
    hass.states.async_set("binary_sensor.foo_battery_low", "off", {})
    assert is_eligible(hass, entry) is False


async def test_is_eligible_rejects_companion_entities(hass: Any) -> None:
    registry = er.async_get(hass)
    entry = registry.async_get_or_create(
        domain="sensor",
        platform=DOMAIN,
        unique_id="battery_lifetime:foo:replace_by",
        suggested_object_id="foo_battery_replace_by",
        original_device_class="timestamp",
    )
    hass.states.async_set("sensor.foo_battery_replace_by", "2026-09-14T00:00:00+00:00", {})
    assert is_eligible(hass, entry) is False


async def test_iter_eligible_filters_correctly(hass: Any) -> None:
    registry = er.async_get(hass)
    _register(registry, entity_id="sensor.foo_battery", unique_id="uid-foo")
    hass.states.async_set("sensor.foo_battery", "73", {})
    _register(
        registry, entity_id="sensor.bar_battery", unique_id="uid-bar"
    )
    hass.states.async_set("sensor.bar_battery", "low", {})
    eligible = [e.entity_id for e in iter_eligible_entities(hass)]
    assert eligible == ["sensor.foo_battery"]


async def test_coordinator_creates_record_for_eligible_entity(
    hass: Any,
) -> None:
    registry = er.async_get(hass)
    _register(registry, entity_id="sensor.foo_battery", unique_id="uid-foo")
    hass.states.async_set("sensor.foo_battery", "84", {})

    store = BatteryLifetimeStore(hass)
    await store.async_load()
    coord = BatteryLifetimeCoordinator(hass, store=store)
    await coord.async_setup()

    assert "uid-foo" in coord.records
    record = coord.records["uid-foo"]
    assert record.entity_id == "sensor.foo_battery"
    assert record.last_reading_pct == 84.0
    await coord.async_shutdown()


async def test_coordinator_handles_state_change(hass: Any) -> None:
    registry = er.async_get(hass)
    _register(registry, entity_id="sensor.foo_battery", unique_id="uid-foo")
    hass.states.async_set("sensor.foo_battery", "84", {})

    store = BatteryLifetimeStore(hass)
    await store.async_load()
    coord = BatteryLifetimeCoordinator(hass, store=store)
    await coord.async_setup()
    record = coord.records["uid-foo"]
    record.replaced_on = datetime.now(tz=UTC) - timedelta(days=10)
    record.ewma.baseline_pct = 100.0
    record.ewma.baseline_at = record.replaced_on
    record.ewma.last_pct = 84.0
    record.ewma.last_at = record.replaced_on

    hass.states.async_set("sensor.foo_battery", "82", {})
    await hass.async_block_till_done()

    assert coord.records["uid-foo"].last_reading_pct == 82.0
    await coord.async_shutdown()


async def test_coordinator_summary_data_via_refresh(hass: Any) -> None:
    registry = er.async_get(hass)
    _register(registry, entity_id="sensor.foo_battery", unique_id="uid-foo")
    hass.states.async_set("sensor.foo_battery", "84", {})

    store = BatteryLifetimeStore(hass)
    await store.async_load()
    coord = BatteryLifetimeCoordinator(hass, store=store)
    await coord.async_setup()
    record = coord.records["uid-foo"]
    record.replaced_on = datetime.now(tz=UTC) - timedelta(days=70)
    record.ewma.baseline_pct = 100.0
    record.ewma.baseline_at = record.replaced_on
    record.ewma.last_pct = 84.0
    record.ewma.last_at = record.replaced_on
    record.ewma.rate = 0.2

    snapshots = await coord._async_update_data()
    assert "uid-foo" in snapshots
    snap = snapshots["uid-foo"]
    assert snap.prediction.replace_by is not None
    await coord.async_shutdown()


async def test_coordinator_persists_state_across_restart(hass: Any) -> None:
    registry = er.async_get(hass)
    _register(registry, entity_id="sensor.foo_battery", unique_id="uid-foo")
    hass.states.async_set("sensor.foo_battery", "84", {})

    store_a = BatteryLifetimeStore(hass)
    await store_a.async_load()
    coord_a = BatteryLifetimeCoordinator(hass, store=store_a)
    await coord_a.async_setup()
    record = coord_a.records["uid-foo"]
    record.replaced_on = datetime(2026, 4, 1, tzinfo=UTC)
    coord_a._persist(record)
    await store_a.async_save()
    await coord_a.async_shutdown()

    store_b = BatteryLifetimeStore(hass)
    await store_b.async_load()
    coord_b = BatteryLifetimeCoordinator(hass, store=store_b)
    await coord_b.async_setup()
    assert coord_b.records["uid-foo"].replaced_on == datetime(
        2026, 4, 1, tzinfo=UTC
    )
    await coord_b.async_shutdown()


async def test_set_replaced_on_rejects_future(hass: Any) -> None:
    registry = er.async_get(hass)
    _register(registry, entity_id="sensor.foo_battery", unique_id="uid-foo")
    hass.states.async_set("sensor.foo_battery", "84", {})

    store = BatteryLifetimeStore(hass)
    await store.async_load()
    coord = BatteryLifetimeCoordinator(hass, store=store)
    await coord.async_setup()
    with pytest.raises(ValueError):
        await coord.set_replaced_on(
            "uid-foo", datetime.now(tz=UTC) + timedelta(days=1)
        )
    await coord.async_shutdown()


async def test_runtime_registry_add_creates_record(hass: Any) -> None:
    """A new eligible battery added at runtime gets a record without reload."""
    registry = er.async_get(hass)
    store = BatteryLifetimeStore(hass)
    await store.async_load()
    coord = BatteryLifetimeCoordinator(hass, store=store)
    await coord.async_setup()
    assert coord.records == {}

    _register(registry, entity_id="sensor.late_battery", unique_id="uid-late")
    hass.states.async_set("sensor.late_battery", "73", {})
    hass.bus.async_fire(
        "entity_registry_updated",
        {"action": "create", "entity_id": "sensor.late_battery"},
    )
    await hass.async_block_till_done()

    assert "uid-late" in coord.records
    assert coord.records["uid-late"].entity_id == "sensor.late_battery"
    await coord.async_shutdown()


async def test_removed_source_within_retention_restores_state(
    hass: Any,
) -> None:
    """A removed-then-readded source within retention keeps replaced_on, profile.

    Drives the registry directly (``async_remove`` / ``async_get_or_create``)
    so the registry's own remove/create events flow into the coordinator's
    listener, mirroring real HA behaviour.
    """
    registry = er.async_get(hass)
    entry = _register(
        registry, entity_id="sensor.foo_battery", unique_id="uid-foo"
    )
    hass.states.async_set("sensor.foo_battery", "84", {})

    store = BatteryLifetimeStore(hass)
    await store.async_load()
    coord = BatteryLifetimeCoordinator(hass, store=store)
    await coord.async_setup()

    pinned_replaced_on = datetime(2026, 4, 1, tzinfo=UTC)
    record = coord.records["uid-foo"]
    record.replaced_on = pinned_replaced_on
    record.profile_id = "alkaline"
    record.threshold_override = 22.0
    coord._persist(record)
    await store.async_save()

    registry.async_remove(entry.entity_id)
    hass.states.async_remove("sensor.foo_battery")
    hass.bus.async_fire(
        "entity_registry_updated",
        {"action": "remove", "entity_id": "sensor.foo_battery"},
    )
    await hass.async_block_till_done()
    assert "uid-foo" not in coord.records
    stored = store.get_battery("uid-foo")
    assert stored is not None
    assert stored.get("removed_at") is not None

    _register(registry, entity_id="sensor.foo_battery", unique_id="uid-foo")
    hass.states.async_set("sensor.foo_battery", "84", {})
    hass.bus.async_fire(
        "entity_registry_updated",
        {"action": "create", "entity_id": "sensor.foo_battery"},
    )
    await hass.async_block_till_done()

    assert "uid-foo" in coord.records
    restored = coord.records["uid-foo"]
    assert restored.replaced_on == pinned_replaced_on
    assert restored.profile_id == "alkaline"
    assert restored.threshold_override == 22.0
    await coord.async_shutdown()


async def test_coordinator_uses_single_periodic_timer(hass: Any) -> None:
    """The framework's update_interval must be off; only the explicit tick fires."""
    store = BatteryLifetimeStore(hass)
    await store.async_load()
    coord = BatteryLifetimeCoordinator(hass, store=store)
    await coord.async_setup()
    assert coord.update_interval is None
    assert coord._unsub_tick is not None
    await coord.async_shutdown()


async def test_source_event_does_not_recompute_other_records(
    hass: Any,
) -> None:
    """A single source's state change must not recompute peers' Predictions."""
    registry = er.async_get(hass)
    _register(registry, entity_id="sensor.foo_battery", unique_id="uid-foo")
    _register(registry, entity_id="sensor.bar_battery", unique_id="uid-bar")
    hass.states.async_set("sensor.foo_battery", "84", {})
    hass.states.async_set("sensor.bar_battery", "60", {})

    store = BatteryLifetimeStore(hass)
    await store.async_load()
    coord = BatteryLifetimeCoordinator(hass, store=store)
    await coord.async_setup()
    for uid in ("uid-foo", "uid-bar"):
        rec = coord.records[uid]
        rec.replaced_on = datetime.now(tz=UTC) - timedelta(days=70)
        rec.ewma.baseline_pct = 100.0
        rec.ewma.baseline_at = rec.replaced_on
        rec.ewma.last_pct = rec.last_reading_pct
        rec.ewma.last_at = rec.replaced_on
        rec.ewma.rate = 0.2

    await coord.async_request_refresh()
    await hass.async_block_till_done()
    assert coord.data is not None
    bar_pred_before = coord.data["uid-bar"].prediction

    hass.states.async_set("sensor.foo_battery", "82", {})
    await hass.async_block_till_done()

    bar_pred_after = coord.data["uid-bar"].prediction
    assert bar_pred_after is bar_pred_before
    assert coord.data["uid-foo"].record.last_reading_pct == 82.0
    await coord.async_shutdown()


async def test_idle_heartbeat_does_not_publish(hass: Any) -> None:
    """When nothing observable changed, the heartbeat must not push a snapshot."""
    registry = er.async_get(hass)
    _register(registry, entity_id="sensor.foo_battery", unique_id="uid-foo")
    hass.states.async_set("sensor.foo_battery", "84", {})

    store = BatteryLifetimeStore(hass)
    await store.async_load()
    coord = BatteryLifetimeCoordinator(hass, store=store)
    await coord.async_setup()
    rec = coord.records["uid-foo"]
    rec.replaced_on = datetime.now(tz=UTC) - timedelta(days=70)
    rec.ewma.baseline_pct = 100.0
    rec.ewma.baseline_at = rec.replaced_on
    rec.ewma.last_pct = 84.0
    rec.ewma.last_at = rec.replaced_on
    rec.ewma.rate = 0.2

    await coord.async_request_refresh()
    await hass.async_block_till_done()
    data_before = coord.data

    await coord._async_recompute_and_maybe_publish()
    await hass.async_block_till_done()

    assert coord.data is data_before
    await coord.async_shutdown()


async def test_heartbeat_publishes_when_source_goes_stale(hass: Any) -> None:
    """A heartbeat that crosses the staleness threshold must publish."""
    from custom_components.battery_lifetime.const import (
        CONFIDENCE_STALE,
        STALE_SOURCE_DAYS,
    )

    registry = er.async_get(hass)
    _register(registry, entity_id="sensor.foo_battery", unique_id="uid-foo")
    hass.states.async_set("sensor.foo_battery", "84", {})

    store = BatteryLifetimeStore(hass)
    await store.async_load()
    coord = BatteryLifetimeCoordinator(hass, store=store)
    await coord.async_setup()
    rec = coord.records["uid-foo"]
    fresh_anchor = datetime.now(tz=UTC) - timedelta(days=70)
    rec.replaced_on = fresh_anchor
    rec.ewma.baseline_pct = 100.0
    rec.ewma.baseline_at = fresh_anchor
    rec.ewma.last_pct = 84.0
    rec.ewma.last_at = fresh_anchor
    rec.ewma.rate = 0.2
    rec.last_reading_at = datetime.now(tz=UTC) - timedelta(hours=1)

    await coord.async_request_refresh()
    await hass.async_block_till_done()
    assert coord.data["uid-foo"].prediction.confidence != CONFIDENCE_STALE

    rec.last_reading_at = datetime.now(tz=UTC) - timedelta(
        days=STALE_SOURCE_DAYS + 1
    )
    await coord._async_recompute_and_maybe_publish()
    await hass.async_block_till_done()

    assert coord.data["uid-foo"].prediction.confidence == CONFIDENCE_STALE
    await coord.async_shutdown()


async def test_user_action_setter_publishes_unconditionally(hass: Any) -> None:
    """User-action setters route through the unconditional refresh path.

    The heartbeat path (``_async_recompute_and_maybe_publish``) is diff-gated;
    the setter path (``async_request_refresh`` → ``_async_update_data`` →
    framework publish) is not, so the user always sees their toggle reflected
    even when it leaves the four observable Prediction fields unchanged.
    """
    from unittest.mock import patch

    registry = er.async_get(hass)
    _register(registry, entity_id="sensor.foo_battery", unique_id="uid-foo")
    hass.states.async_set("sensor.foo_battery", "84", {})

    store = BatteryLifetimeStore(hass)
    await store.async_load()
    coord = BatteryLifetimeCoordinator(hass, store=store)
    await coord.async_setup()
    rec = coord.records["uid-foo"]
    rec.replaced_on = datetime.now(tz=UTC) - timedelta(days=70)
    rec.ewma.baseline_pct = 100.0
    rec.ewma.baseline_at = rec.replaced_on
    rec.ewma.last_pct = 84.0
    rec.ewma.last_at = rec.replaced_on
    rec.ewma.rate = 0.2

    with patch.object(
        coord, "async_request_refresh", wraps=coord.async_request_refresh
    ) as request_refresh:
        await coord.set_tracking_enabled("uid-foo", rec.tracking_enabled)
        assert request_refresh.call_count == 1
    await coord.async_shutdown()


async def test_setup_does_not_await_cold_start_backfill(hass: Any) -> None:
    """async_setup must return before per-record cold-start backfill completes.

    The freeze fixed by v0.1.3: with N batteries needing cold-start backfill,
    pre-fix `_scan_initial_entities` awaited each backfill in series, so HA's
    config-entry setup blocked for minutes. Post-fix, backfill is scheduled
    via `hass.async_create_task` and `async_setup` returns immediately.
    """
    import asyncio
    from unittest.mock import patch

    registry = er.async_get(hass)
    _register(registry, entity_id="sensor.foo_battery", unique_id="uid-foo")
    hass.states.async_set("sensor.foo_battery", "84", {})

    store = BatteryLifetimeStore(hass)
    await store.async_load()
    coord = BatteryLifetimeCoordinator(hass, store=store)

    backfill_started = asyncio.Event()
    release_backfill = asyncio.Event()

    async def _slow_backfill(record: Any) -> None:
        backfill_started.set()
        await release_backfill.wait()

    with patch.object(
        coord, "_attempt_cold_start_backfill", side_effect=_slow_backfill
    ):
        await coord.async_setup()
        # async_setup has returned. The backfill task may have started (event
        # loop tick) but MUST not yet have completed, since we haven't
        # released the gate.
        assert "uid-foo" in coord._pending_backfills
        assert backfill_started.is_set()

        release_backfill.set()
        await hass.async_block_till_done()
        assert coord._pending_backfills == set()

    await coord.async_shutdown()


async def test_cold_start_completion_fires_notification(hass: Any) -> None:
    """Once the last in-flight backfill finishes, exactly one notification fires."""
    from homeassistant.components.persistent_notification import (
        _async_get_or_create_notifications,
    )

    registry = er.async_get(hass)
    _register(registry, entity_id="sensor.foo_battery", unique_id="uid-foo")
    hass.states.async_set("sensor.foo_battery", "84", {})

    store = BatteryLifetimeStore(hass)
    await store.async_load()
    coord = BatteryLifetimeCoordinator(hass, store=store)
    await coord.async_setup()
    await hass.async_block_till_done()

    notifications = _async_get_or_create_notifications(hass)
    assert "battery_lifetime_cold_start_complete" in notifications
    assert coord._pending_backfills == set()
    await coord.async_shutdown()


async def test_no_pending_backfill_no_notification(hass: Any) -> None:
    """If every record has a persisted replaced_on, no backfill task is scheduled."""
    from homeassistant.components.persistent_notification import (
        _async_get_or_create_notifications,
    )

    registry = er.async_get(hass)
    _register(registry, entity_id="sensor.foo_battery", unique_id="uid-foo")
    hass.states.async_set("sensor.foo_battery", "84", {})

    store = BatteryLifetimeStore(hass)
    await store.async_load()
    store.upsert_battery("uid-foo", replaced_on="2026-04-01T00:00:00+00:00")
    await store.async_save()

    coord = BatteryLifetimeCoordinator(hass, store=store)
    await coord.async_setup()
    await hass.async_block_till_done()

    notifications = _async_get_or_create_notifications(hass)
    assert "battery_lifetime_cold_start_complete" not in notifications
    assert coord._pending_backfills == set()
    await coord.async_shutdown()


async def test_source_without_unique_id_logged_and_skipped(
    hass: Any, caplog: pytest.LogCaptureFixture
) -> None:
    """A registry entry without a unique_id is skipped and warned about.

    HA's public ``async_get_or_create`` requires ``unique_id``, so this
    scenario is reached by forging a synthetic registry-entry-like object
    and calling ``is_eligible`` directly. The branch under test is defensive
    code for legacy registry rows that predate the unique_id requirement.
    """
    import logging
    from types import SimpleNamespace

    caplog.set_level(
        logging.WARNING, logger="custom_components.battery_lifetime"
    )
    hass.states.async_set(
        "sensor.no_uid_battery",
        "55",
        {"device_class": "battery", "unit_of_measurement": "%"},
    )
    fake_entry = SimpleNamespace(
        entity_id="sensor.no_uid_battery",
        unique_id=None,
        platform="demo",
        disabled=False,
        hidden_by=None,
        device_class=SensorDeviceClass.BATTERY,
        original_device_class=SensorDeviceClass.BATTERY,
        unit_of_measurement=PERCENTAGE,
    )

    assert is_eligible(hass, fake_entry) is False  # type: ignore[arg-type]
    assert any(
        "no unique_id" in record.message
        and "sensor.no_uid_battery" in record.message
        for record in caplog.records
    )
