"""End-to-end lifecycle tests: setup, unload, reload."""

from __future__ import annotations

from typing import Any

import pytest
from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.const import PERCENTAGE
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.battery_lifetime.const import (
    CONF_DEFAULT_PROFILE,
    DOMAIN,
    PROFILE_LITHIUM,
    SERVICE_PREDICT_AT,
)


async def _add_battery(hass: Any, *, unique_id: str, entity_id: str) -> None:
    registry = er.async_get(hass)
    registry.async_get_or_create(
        domain="sensor",
        platform="demo",
        unique_id=unique_id,
        suggested_object_id=entity_id.split(".", 1)[1],
        original_device_class=SensorDeviceClass.BATTERY,
        unit_of_measurement=PERCENTAGE,
    )
    hass.states.async_set(entity_id, "84", {})


async def test_async_setup_entry_creates_companion_entities(hass: Any) -> None:
    await _add_battery(
        hass, unique_id="uid-foo", entity_id="sensor.foo_battery"
    )
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=DOMAIN,
        options={CONF_DEFAULT_PROFILE: PROFILE_LITHIUM},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    states = hass.states.async_entity_ids()
    assert "sensor.foo_battery_replace_by" in states
    assert "sensor.foo_battery_prediction_quality" in states
    assert "sensor.foo_battery_drain_rate" in states
    assert "switch.foo_battery_profile_lithium" in states
    assert "switch.foo_battery_tracking_enabled" in states
    assert "button.foo_battery_mark_replaced" in states
    assert "date.foo_battery_replaced_on" in states
    assert "number.foo_battery_threshold_override" in states
    assert "binary_sensor.foo_battery_due_next_quarter" in states
    assert "sensor.battery_lifetime_due_this_month" in states
    assert "sensor.battery_lifetime_due_next_3_months" in states
    assert "sensor.battery_lifetime_due_next_quarter" in states
    assert hass.services.has_service(DOMAIN, SERVICE_PREDICT_AT)

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert not hass.services.has_service(DOMAIN, SERVICE_PREDICT_AT)


async def test_async_unload_entry_cleans_up(hass: Any) -> None:
    await _add_battery(
        hass, unique_id="uid-foo", entity_id="sensor.foo_battery"
    )
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=DOMAIN,
        options={CONF_DEFAULT_PROFILE: PROFILE_LITHIUM},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert DOMAIN not in hass.data or entry.entry_id not in hass.data[DOMAIN]


async def test_options_change_triggers_reload(hass: Any) -> None:
    await _add_battery(
        hass, unique_id="uid-foo", entity_id="sensor.foo_battery"
    )
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=DOMAIN,
        options={CONF_DEFAULT_PROFILE: PROFILE_LITHIUM},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    hass.config_entries.async_update_entry(
        entry, options={CONF_DEFAULT_PROFILE: "alkaline"}
    )
    await hass.async_block_till_done()
    bucket = hass.data[DOMAIN][entry.entry_id]
    assert bucket["store"].default_profile == "alkaline"
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


async def test_predict_at_service_runs_after_setup(hass: Any) -> None:
    from datetime import datetime, timedelta, timezone

    await _add_battery(
        hass, unique_id="uid-foo", entity_id="sensor.foo_battery"
    )
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=DOMAIN,
        options={CONF_DEFAULT_PROFILE: PROFILE_LITHIUM},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    target_date = datetime.now(tz=timezone.utc).date() + timedelta(days=10)
    result = await hass.services.async_call(
        DOMAIN,
        SERVICE_PREDICT_AT,
        {"date": target_date},
        blocking=True,
        return_response=True,
    )
    assert any(
        entry["entity_id"] == "sensor.foo_battery"
        for entry in result["results"]
    )
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
