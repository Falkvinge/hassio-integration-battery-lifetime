"""Tests for companion-entity classes (focused, not full-integration setup)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.const import PERCENTAGE
from homeassistant.helpers import entity_registry as er

from custom_components.battery_lifetime.binary_sensor import DueNextQuarterBinarySensor
from custom_components.battery_lifetime.button import MarkReplacedButton
from custom_components.battery_lifetime.coordinator import (
    BatteryLifetimeCoordinator,
)
from custom_components.battery_lifetime.date import ReplacedOnDate
from custom_components.battery_lifetime.entity import companion_unique_id
from custom_components.battery_lifetime.number import ThresholdOverrideNumber
from custom_components.battery_lifetime.sensor import (
    DrainRateSensor,
    DueNext3MonthsSensor,
    DueNextQuarterSensor,
    PredictionQualitySensor,
    ReplaceBySensor,
)
from custom_components.battery_lifetime.store import BatteryLifetimeStore
from custom_components.battery_lifetime.switch import (
    ProfileLithiumSwitch,
    TrackingEnabledSwitch,
)

UTC = timezone.utc


@pytest.fixture
async def coord_with_battery(hass: Any) -> BatteryLifetimeCoordinator:
    registry = er.async_get(hass)
    registry.async_get_or_create(
        domain="sensor",
        platform="demo",
        unique_id="uid-foo",
        suggested_object_id="foo_battery",
        original_device_class=SensorDeviceClass.BATTERY,
        unit_of_measurement=PERCENTAGE,
    )
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
    coord.data = await coord._async_update_data()
    yield coord
    await coord.async_shutdown()


def test_companion_unique_id_is_deterministic() -> None:
    a = companion_unique_id("uid-foo", "replace_by")
    b = companion_unique_id("uid-foo", "replace_by")
    c = companion_unique_id("uid-foo", "drain_rate")
    assert a == b
    assert a != c


async def test_replace_by_sensor_returns_prediction(
    coord_with_battery: BatteryLifetimeCoordinator,
) -> None:
    sensor = ReplaceBySensor(coord_with_battery, "uid-foo")
    assert sensor.native_value is not None
    assert sensor.unique_id == companion_unique_id("uid-foo", "replace_by")
    attrs = sensor.extra_state_attributes
    assert attrs["source_entity"] == "sensor.foo_battery"
    assert attrs["confidence"] in ("low", "medium", "high")
    assert "days_until_replace" in attrs
    assert isinstance(attrs["days_until_replace"], int)


async def test_prediction_quality_sensor_returns_string(
    coord_with_battery: BatteryLifetimeCoordinator,
) -> None:
    sensor = PredictionQualitySensor(coord_with_battery, "uid-foo")
    assert sensor.native_value in ("low", "medium", "high")


async def test_drain_rate_sensor_returns_rate(
    coord_with_battery: BatteryLifetimeCoordinator,
) -> None:
    sensor = DrainRateSensor(coord_with_battery, "uid-foo")
    assert sensor.native_value == pytest.approx(0.2)


async def test_summary_sensor_counts_due_next_3_months(
    coord_with_battery: BatteryLifetimeCoordinator,
) -> None:
    record = coord_with_battery.records["uid-foo"]
    record.last_reading_pct = 18.0
    record.ewma.last_pct = 18.0
    record.ewma.last_at = datetime.now(tz=UTC)
    record.last_reading_at = record.ewma.last_at
    record.ewma.rate = 1.0
    coord_with_battery.data = await coord_with_battery._async_update_data()
    sensor = DueNext3MonthsSensor(coord_with_battery)
    assert sensor.native_value == 1


async def test_summary_sensors_exclude_disabled_batteries(
    coord_with_battery: BatteryLifetimeCoordinator,
) -> None:
    """Disabled (`tracking_enabled=False`) batteries MUST NOT count.

    Pinned to ``lifetime-prediction/spec.md`` "Integration-level summary
    sensors → Disabled batteries are excluded".
    """
    from custom_components.battery_lifetime.sensor import DueThisMonthSensor

    record = coord_with_battery.records["uid-foo"]
    record.last_reading_pct = 12.0
    record.ewma.last_pct = 12.0
    record.ewma.last_at = datetime.now(tz=UTC)
    record.last_reading_at = record.ewma.last_at
    record.ewma.rate = 1.5
    coord_with_battery.data = await coord_with_battery._async_update_data()

    due_this = DueThisMonthSensor(coord_with_battery)
    due_next = DueNext3MonthsSensor(coord_with_battery)
    assert due_this.native_value == 1
    assert due_next.native_value == 1

    record.tracking_enabled = False
    coord_with_battery.data = await coord_with_battery._async_update_data()
    assert due_this.native_value == 0
    assert due_next.native_value == 0


async def test_summary_sensor_counts_due_next_quarter(
    coord_with_battery: BatteryLifetimeCoordinator,
) -> None:
    record = coord_with_battery.records["uid-foo"]
    record.last_reading_pct = 18.0
    record.ewma.last_pct = 18.0
    record.ewma.last_at = datetime.now(tz=UTC)
    record.last_reading_at = record.ewma.last_at
    record.ewma.rate = 1.0
    coord_with_battery.data = await coord_with_battery._async_update_data()
    sensor = DueNextQuarterSensor(coord_with_battery)
    assert sensor.native_value == 1
    assert "next_quarter_end" in sensor.extra_state_attributes


async def test_due_next_quarter_binary_sensor(
    coord_with_battery: BatteryLifetimeCoordinator,
) -> None:
    record = coord_with_battery.records["uid-foo"]
    record.last_reading_pct = 18.0
    record.ewma.last_pct = 18.0
    record.ewma.last_at = datetime.now(tz=UTC)
    record.last_reading_at = record.ewma.last_at
    record.ewma.rate = 1.0
    coord_with_battery.data = await coord_with_battery._async_update_data()
    binary = DueNextQuarterBinarySensor(coord_with_battery, "uid-foo")
    assert binary.is_on is True

    record.tracking_enabled = False
    coord_with_battery.data = await coord_with_battery._async_update_data()
    assert binary.is_on is False


async def test_replace_by_omits_days_until_for_no_data(
    coord_with_battery: BatteryLifetimeCoordinator,
) -> None:
    record = coord_with_battery.records["uid-foo"]
    record.replaced_on = None
    record.ewma.rate = None
    coord_with_battery.data = await coord_with_battery._async_update_data()
    sensor = ReplaceBySensor(coord_with_battery, "uid-foo")
    assert "days_until_replace" not in sensor.extra_state_attributes


async def test_profile_switch_toggles_profile(
    coord_with_battery: BatteryLifetimeCoordinator,
) -> None:
    switch = ProfileLithiumSwitch(coord_with_battery, "uid-foo")
    assert switch.is_on is True
    await switch.async_turn_off()
    assert (
        coord_with_battery.records["uid-foo"].profile_id == "alkaline"
    )
    assert switch.is_on is False


async def test_tracking_enabled_switch_toggles(
    coord_with_battery: BatteryLifetimeCoordinator,
) -> None:
    switch = TrackingEnabledSwitch(coord_with_battery, "uid-foo")
    assert switch.is_on is True
    await switch.async_turn_off()
    assert coord_with_battery.records["uid-foo"].tracking_enabled is False


async def test_mark_replaced_button_press_updates_replaced_on(
    coord_with_battery: BatteryLifetimeCoordinator, hass: Any
) -> None:
    events: list[Any] = []
    hass.bus.async_listen(
        "battery_lifetime_replacement_detected",
        lambda event: events.append(event.data),
    )
    button = MarkReplacedButton(coord_with_battery, "uid-foo")
    await button.async_press()
    await hass.async_block_till_done()
    record = coord_with_battery.records["uid-foo"]
    assert record.replaced_on is not None
    delta = datetime.now(tz=UTC) - record.replaced_on
    assert abs(delta.total_seconds()) < 5
    assert any(e["source"] == "manual_button" for e in events)


async def test_replaced_on_date_rejects_future(
    coord_with_battery: BatteryLifetimeCoordinator,
) -> None:
    date_entity = ReplacedOnDate(coord_with_battery, "uid-foo")
    today = datetime.now(tz=UTC).date()
    with pytest.raises(ValueError):
        await date_entity.async_set_value(today + timedelta(days=1))


async def test_replaced_on_date_accepts_past(
    coord_with_battery: BatteryLifetimeCoordinator, hass: Any
) -> None:
    events: list[Any] = []
    hass.bus.async_listen(
        "battery_lifetime_replacement_detected",
        lambda event: events.append(event.data),
    )
    date_entity = ReplacedOnDate(coord_with_battery, "uid-foo")
    past = datetime.now(tz=UTC).date() - timedelta(days=14)
    await date_entity.async_set_value(past)
    await hass.async_block_till_done()
    record = coord_with_battery.records["uid-foo"]
    assert record.replaced_on is not None
    assert record.replaced_on.date() == past
    assert any(e["source"] == "manual_date_edit" for e in events)


async def test_threshold_override_number_persists(
    coord_with_battery: BatteryLifetimeCoordinator,
) -> None:
    number = ThresholdOverrideNumber(coord_with_battery, "uid-foo")
    await number.async_set_native_value(20.0)
    assert (
        coord_with_battery.records["uid-foo"].threshold_override == 20.0
    )
