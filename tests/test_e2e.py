"""End-to-end synthetic-source tests.

These tests drive the integration's full pipeline (config entry setup,
discovery, replacement detection, prediction, companion entities, the
predict_at service) by programmatically poking a fake source sensor's
state and asserting behaviour through the HA states/services API. They
cover the detection branches and the confidence ladder transitions called
out in section 10 of the implementation tasks.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.const import PERCENTAGE
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.battery_lifetime.const import (
    CONF_DEFAULT_PROFILE,
    DOMAIN,
    EVENT_REPLACEMENT_DETECTED,
    PROFILE_LITHIUM,
    SERVICE_PREDICT_AT,
)
from custom_components.battery_lifetime.coordinator import (
    BatteryLifetimeCoordinator,
)

UTC = timezone.utc


async def _add_source(hass: Any, *, unique_id: str, entity_id: str) -> None:
    registry = er.async_get(hass)
    registry.async_get_or_create(
        domain="sensor",
        platform="demo",
        unique_id=unique_id,
        suggested_object_id=entity_id.split(".", 1)[1],
        original_device_class=SensorDeviceClass.BATTERY,
        unit_of_measurement=PERCENTAGE,
    )


async def _set_source_state(
    hass: Any, entity_id: str, value: float, *, force: bool = False
) -> None:
    hass.states.async_set(entity_id, str(value), {}, force_update=force)
    await hass.async_block_till_done()


def _coord(hass: Any, entry_id: str) -> BatteryLifetimeCoordinator:
    return hass.data[DOMAIN][entry_id]["coordinator"]


@pytest.fixture
async def setup_entry(hass: Any) -> MockConfigEntry:
    await _add_source(hass, unique_id="uid-foo", entity_id="sensor.foo_battery")
    await _set_source_state(hass, "sensor.foo_battery", 50.0)

    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=DOMAIN,
        options={CONF_DEFAULT_PROFILE: PROFILE_LITHIUM},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    yield entry
    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


async def test_e2e_auto_detection_commits_on_followup(
    hass: Any, setup_entry: MockConfigEntry
) -> None:
    """Source goes 50% → 100% → 100%; replacement event fires."""
    coord = _coord(hass, setup_entry.entry_id)
    coord.records["uid-foo"].last_reading_pct = 50.0
    coord.records["uid-foo"].last_reading_at = datetime.now(tz=UTC)

    events: list[Any] = []
    hass.bus.async_listen(EVENT_REPLACEMENT_DETECTED, lambda e: events.append(e.data))

    await _set_source_state(hass, "sensor.foo_battery", 100.0)
    assert "uid-foo" in coord.detector.candidates

    await _set_source_state(hass, "sensor.foo_battery", 100.0, force=True)

    assert len(events) >= 1
    assert events[0]["source"] == "auto"
    assert events[0]["confirmed"] is True
    assert coord.records["uid-foo"].replaced_on is not None


async def test_e2e_glitch_is_rejected(
    hass: Any, setup_entry: MockConfigEntry
) -> None:
    """Source goes 50% → 100% → 30%; candidate is discarded as glitch."""
    coord = _coord(hass, setup_entry.entry_id)
    coord.records["uid-foo"].last_reading_pct = 50.0
    coord.records["uid-foo"].last_reading_at = datetime.now(tz=UTC)

    events: list[Any] = []
    hass.bus.async_listen(EVENT_REPLACEMENT_DETECTED, lambda e: events.append(e.data))

    await _set_source_state(hass, "sensor.foo_battery", 100.0)
    await _set_source_state(hass, "sensor.foo_battery", 30.0)

    assert events == []
    assert "uid-foo" not in coord.detector.candidates


async def test_e2e_jump_from_above_80_is_ignored(
    hass: Any, setup_entry: MockConfigEntry
) -> None:
    """A jump from 85% → 100% does not even start a candidate."""
    coord = _coord(hass, setup_entry.entry_id)
    coord.records["uid-foo"].last_reading_pct = 85.0
    coord.records["uid-foo"].last_reading_at = datetime.now(tz=UTC)

    await _set_source_state(hass, "sensor.foo_battery", 100.0)
    assert "uid-foo" not in coord.detector.candidates


async def test_e2e_mark_replaced_button_works(
    hass: Any, setup_entry: MockConfigEntry
) -> None:
    coord = _coord(hass, setup_entry.entry_id)
    events: list[Any] = []
    hass.bus.async_listen(EVENT_REPLACEMENT_DETECTED, lambda e: events.append(e.data))

    await hass.services.async_call(
        "button",
        "press",
        {"entity_id": "button.foo_battery_mark_replaced"},
        blocking=True,
    )
    await hass.async_block_till_done()

    assert any(e["source"] == "manual_button" for e in events)
    assert coord.records["uid-foo"].replaced_on is not None


async def test_e2e_predict_at_returns_data_for_tracked_battery(
    hass: Any, setup_entry: MockConfigEntry
) -> None:
    coord = _coord(hass, setup_entry.entry_id)
    record = coord.records["uid-foo"]
    record.replaced_on = datetime.now(tz=UTC) - timedelta(days=70)
    record.ewma.baseline_pct = 100.0
    record.ewma.baseline_at = record.replaced_on
    record.ewma.last_pct = 50.0
    record.ewma.last_at = datetime.now(tz=UTC)
    record.last_reading_at = record.ewma.last_at
    record.ewma.rate = 0.5

    target = (datetime.now(tz=UTC).date() + timedelta(days=120))
    result = await hass.services.async_call(
        DOMAIN,
        SERVICE_PREDICT_AT,
        {"date": target, "actionable_only": True},
        blocking=True,
        return_response=True,
    )
    assert any(
        entry["entity_id"] == "sensor.foo_battery"
        and entry["predicted_state"] == "below_threshold"
        for entry in result["results"]
    )


async def test_e2e_tracking_disabled_pauses_detection(
    hass: Any, setup_entry: MockConfigEntry
) -> None:
    coord = _coord(hass, setup_entry.entry_id)
    coord.records["uid-foo"].tracking_enabled = False
    coord.records["uid-foo"].last_reading_pct = 50.0
    coord.records["uid-foo"].last_reading_at = datetime.now(tz=UTC)

    events: list[Any] = []
    hass.bus.async_listen(EVENT_REPLACEMENT_DETECTED, lambda e: events.append(e.data))

    await _set_source_state(hass, "sensor.foo_battery", 100.0)
    await _set_source_state(hass, "sensor.foo_battery", 100.0, force=True)

    assert events == []
    assert "uid-foo" not in coord.detector.candidates


async def test_e2e_summary_sensor_reflects_state(
    hass: Any, setup_entry: MockConfigEntry
) -> None:
    coord = _coord(hass, setup_entry.entry_id)
    record = coord.records["uid-foo"]
    record.replaced_on = datetime.now(tz=UTC) - timedelta(days=70)
    record.ewma.baseline_pct = 100.0
    record.ewma.baseline_at = record.replaced_on
    record.last_reading_pct = 5.0
    record.last_reading_at = datetime.now(tz=UTC)
    record.ewma.last_pct = 5.0
    record.ewma.last_at = record.last_reading_at
    record.ewma.rate = 1.0
    await coord.async_request_refresh()
    await hass.async_block_till_done()

    state = hass.states.get("sensor.battery_lifetime_due_this_month")
    assert state is not None
    assert int(state.state) >= 1
