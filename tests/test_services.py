"""Tests for the ``battery_lifetime.predict_at`` service."""

from __future__ import annotations

from datetime import date as date_type
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
import voluptuous as vol
from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.const import PERCENTAGE
from homeassistant.helpers import entity_registry as er

from custom_components.battery_lifetime.const import (
    DOMAIN,
    SERVICE_CONFIRM_STALE_REPLACEMENT,
    SERVICE_DISMISS_STALE_REPLACEMENT,
    SERVICE_EXCLUDE_STALE_REPLACEMENT,
    SERVICE_PREDICT_AT,
)
from custom_components.battery_lifetime.detection import Candidate
from custom_components.battery_lifetime.coordinator import (
    BatteryLifetimeCoordinator,
)
from custom_components.battery_lifetime.services import (
    async_register_services,
    async_unregister_services,
)
from custom_components.battery_lifetime.store import BatteryLifetimeStore

UTC = timezone.utc


@pytest.fixture
async def coord_with_two_batteries(
    hass: Any,
) -> BatteryLifetimeCoordinator:
    registry = er.async_get(hass)
    for unique_id, entity_id in (
        ("uid-foo", "sensor.foo_battery"),
        ("uid-bar", "sensor.bar_battery"),
    ):
        registry.async_get_or_create(
            domain="sensor",
            platform="demo",
            unique_id=unique_id,
            suggested_object_id=entity_id.split(".", 1)[1],
            original_device_class=SensorDeviceClass.BATTERY,
            unit_of_measurement=PERCENTAGE,
        )
    hass.states.async_set("sensor.foo_battery", "84", {})
    hass.states.async_set("sensor.bar_battery", "20", {})

    store = BatteryLifetimeStore(hass)
    await store.async_load()
    coord = BatteryLifetimeCoordinator(hass, store=store)
    await coord.async_setup()

    now = datetime.now(tz=UTC)
    foo = coord.records["uid-foo"]
    foo.replaced_on = now - timedelta(days=70)
    foo.ewma.baseline_pct = 100.0
    foo.ewma.baseline_at = foo.replaced_on
    foo.ewma.last_pct = 84.0
    foo.ewma.last_at = now
    foo.last_reading_at = now
    foo.ewma.rate = 0.2

    bar = coord.records["uid-bar"]
    bar.replaced_on = now - timedelta(days=70)
    bar.ewma.baseline_pct = 100.0
    bar.ewma.baseline_at = bar.replaced_on
    bar.ewma.last_pct = 20.0
    bar.ewma.last_at = now
    bar.last_reading_at = now
    bar.ewma.rate = 1.0

    coord.data = await coord._async_update_data()

    hass.data.setdefault(DOMAIN, {})["entry_test"] = {"coordinator": coord}
    async_register_services(hass)
    yield coord
    async_unregister_services(hass)
    hass.data[DOMAIN].pop("entry_test", None)
    await coord.async_shutdown()


async def test_service_default_returns_all(
    hass: Any, coord_with_two_batteries: BatteryLifetimeCoordinator
) -> None:
    result = await hass.services.async_call(
        DOMAIN,
        SERVICE_PREDICT_AT,
        {"date": (datetime.now(tz=UTC).date() + timedelta(days=10))},
        blocking=True,
        return_response=True,
    )
    results = result["results"]
    assert len(results) == 2
    entity_ids = {entry["entity_id"] for entry in results}
    assert entity_ids == {"sensor.foo_battery", "sensor.bar_battery"}


async def test_service_actionable_only_filters(
    hass: Any, coord_with_two_batteries: BatteryLifetimeCoordinator
) -> None:
    result = await hass.services.async_call(
        DOMAIN,
        SERVICE_PREDICT_AT,
        {
            "date": (datetime.now(tz=UTC).date() + timedelta(days=20)),
            "actionable_only": True,
        },
        blocking=True,
        return_response=True,
    )
    results = result["results"]
    assert len(results) == 1
    assert results[0]["entity_id"] == "sensor.bar_battery"
    assert results[0]["predicted_state"] == "below_threshold"


async def test_service_margin_pulls_evaluation_forward(
    hass: Any, coord_with_two_batteries: BatteryLifetimeCoordinator
) -> None:
    foo = coord_with_two_batteries.records["uid-foo"]
    foo.last_reading_pct = 30.0
    foo.ewma.last_pct = 30.0
    foo.ewma.rate = 1.0
    coord_with_two_batteries.data = (
        await coord_with_two_batteries._async_update_data()
    )

    target = datetime.now(tz=UTC).date() + timedelta(days=20)
    result_no_margin = await hass.services.async_call(
        DOMAIN,
        SERVICE_PREDICT_AT,
        {"date": target, "actionable_only": True},
        blocking=True,
        return_response=True,
    )
    result_with_margin = await hass.services.async_call(
        DOMAIN,
        SERVICE_PREDICT_AT,
        {
            "date": target,
            "margin_days": 30,
            "actionable_only": True,
        },
        blocking=True,
        return_response=True,
    )
    assert len(result_no_margin["results"]) >= 1
    assert len(result_with_margin["results"]) >= len(
        result_no_margin["results"]
    )


async def test_service_excludes_disabled_by_default(
    hass: Any, coord_with_two_batteries: BatteryLifetimeCoordinator
) -> None:
    coord_with_two_batteries.records["uid-bar"].tracking_enabled = False
    coord_with_two_batteries.data = (
        await coord_with_two_batteries._async_update_data()
    )
    result = await hass.services.async_call(
        DOMAIN,
        SERVICE_PREDICT_AT,
        {"date": (datetime.now(tz=UTC).date() + timedelta(days=10))},
        blocking=True,
        return_response=True,
    )
    entity_ids = {entry["entity_id"] for entry in result["results"]}
    assert entity_ids == {"sensor.foo_battery"}


async def test_service_include_excluded(
    hass: Any, coord_with_two_batteries: BatteryLifetimeCoordinator
) -> None:
    coord_with_two_batteries.records["uid-bar"].tracking_enabled = False
    coord_with_two_batteries.data = (
        await coord_with_two_batteries._async_update_data()
    )
    result = await hass.services.async_call(
        DOMAIN,
        SERVICE_PREDICT_AT,
        {
            "date": (datetime.now(tz=UTC).date() + timedelta(days=10)),
            "include_excluded": True,
        },
        blocking=True,
        return_response=True,
    )
    excluded_entries = [
        entry for entry in result["results"] if entry.get("excluded")
    ]
    assert len(excluded_entries) == 1
    assert excluded_entries[0]["entity_id"] == "sensor.bar_battery"


async def test_service_rejects_missing_date(
    hass: Any, coord_with_two_batteries: BatteryLifetimeCoordinator
) -> None:
    with pytest.raises(vol.Invalid):
        await hass.services.async_call(
            DOMAIN,
            SERVICE_PREDICT_AT,
            {},
            blocking=True,
            return_response=True,
        )


async def test_service_confirm_stale_commits_replacement(
    hass: Any, coord_with_two_batteries: BatteryLifetimeCoordinator
) -> None:
    """Confirm-stale service writes ``replaced_on`` and emits the event."""
    candidate_at = datetime(2026, 5, 1, tzinfo=UTC)
    coord_with_two_batteries.detector._stale_pending["uid-foo"] = Candidate(
        new_pct=100.0,
        new_at=candidate_at,
        prior_pct=72.0,
        prior_at=datetime(2026, 3, 1, tzinfo=UTC),
    )
    events: list[Any] = []
    hass.bus.async_listen(
        "battery_lifetime_replacement_detected",
        lambda event: events.append(event.data),
    )

    await hass.services.async_call(
        DOMAIN,
        SERVICE_CONFIRM_STALE_REPLACEMENT,
        {"entity_id": "sensor.foo_battery"},
        blocking=True,
    )

    assert "uid-foo" not in coord_with_two_batteries.detector.stale_pending
    assert any(
        e["source"] == "stale_confirmed"
        and e["entity_id"] == "sensor.foo_battery"
        for e in events
    )
    assert (
        coord_with_two_batteries.records["uid-foo"].replaced_on
        == candidate_at
    )


async def test_service_dismiss_stale_clears_candidate(
    hass: Any, coord_with_two_batteries: BatteryLifetimeCoordinator
) -> None:
    """Dismiss-stale service clears the candidate; tracking stays on."""
    coord_with_two_batteries.detector._stale_pending["uid-foo"] = Candidate(
        new_pct=100.0,
        new_at=datetime(2026, 5, 1, tzinfo=UTC),
        prior_pct=72.0,
        prior_at=datetime(2026, 3, 1, tzinfo=UTC),
    )
    events: list[Any] = []
    hass.bus.async_listen(
        "battery_lifetime_replacement_detected",
        lambda event: events.append(event.data),
    )

    await hass.services.async_call(
        DOMAIN,
        SERVICE_DISMISS_STALE_REPLACEMENT,
        {"entity_id": "sensor.foo_battery"},
        blocking=True,
    )

    assert "uid-foo" not in coord_with_two_batteries.detector.stale_pending
    assert events == []
    assert (
        coord_with_two_batteries.records["uid-foo"].tracking_enabled is True
    )


async def test_service_exclude_stale_disables_tracking(
    hass: Any, coord_with_two_batteries: BatteryLifetimeCoordinator
) -> None:
    """Exclude-stale service clears the candidate AND turns tracking off."""
    coord_with_two_batteries.detector._stale_pending["uid-foo"] = Candidate(
        new_pct=100.0,
        new_at=datetime(2026, 5, 1, tzinfo=UTC),
        prior_pct=72.0,
        prior_at=datetime(2026, 3, 1, tzinfo=UTC),
    )
    events: list[Any] = []
    hass.bus.async_listen(
        "battery_lifetime_replacement_detected",
        lambda event: events.append(event.data),
    )

    await hass.services.async_call(
        DOMAIN,
        SERVICE_EXCLUDE_STALE_REPLACEMENT,
        {"entity_id": "sensor.foo_battery"},
        blocking=True,
    )

    assert "uid-foo" not in coord_with_two_batteries.detector.stale_pending
    assert events == []
    assert (
        coord_with_two_batteries.records["uid-foo"].tracking_enabled is False
    )


async def test_service_stale_action_unknown_entity_is_noop(
    hass: Any, coord_with_two_batteries: BatteryLifetimeCoordinator
) -> None:
    """Calling a stale-action service with an unknown entity is a safe no-op."""
    await hass.services.async_call(
        DOMAIN,
        SERVICE_DISMISS_STALE_REPLACEMENT,
        {"entity_id": "sensor.does_not_exist_battery"},
        blocking=True,
    )


async def test_service_returns_unknown_when_no_data(hass: Any) -> None:
    registry = er.async_get(hass)
    registry.async_get_or_create(
        domain="sensor",
        platform="demo",
        unique_id="uid-fresh",
        suggested_object_id="fresh_battery",
        original_device_class=SensorDeviceClass.BATTERY,
        unit_of_measurement=PERCENTAGE,
    )
    hass.states.async_set("sensor.fresh_battery", "84", {})
    store = BatteryLifetimeStore(hass)
    await store.async_load()
    coord = BatteryLifetimeCoordinator(hass, store=store)
    await coord.async_setup()
    coord.records["uid-fresh"].last_reading_pct = None
    coord.records["uid-fresh"].last_reading_at = None
    coord.data = await coord._async_update_data()
    hass.data.setdefault(DOMAIN, {})["entry_fresh"] = {"coordinator": coord}
    async_register_services(hass)

    result = await hass.services.async_call(
        DOMAIN,
        SERVICE_PREDICT_AT,
        {"date": (datetime.now(tz=UTC).date() + timedelta(days=10))},
        blocking=True,
        return_response=True,
    )
    assert result["results"][0]["predicted_state"] == "unknown"
    assert result["results"][0]["predicted_pct_at_date"] is None

    async_unregister_services(hass)
    hass.data[DOMAIN].pop("entry_fresh", None)
    await coord.async_shutdown()
