"""Sensor platform: per-battery prediction sensors plus integration summaries."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    CONFIDENCE_LOW,
    CONFIDENCE_MEDIUM,
    CONFIDENCE_HIGH,
    DOMAIN,
)
from .coordinator import BatteryLifetimeCoordinator
from .entity import BatteryCompanionEntity, companion_unique_id

UTC = timezone.utc

_REPLACE_BY_SUFFIX = "replace_by"
_PREDICTION_QUALITY_SUFFIX = "prediction_quality"
_DRAIN_RATE_SUFFIX = "drain_rate"

_DUE_THIS_MONTH_UNIQUE = "battery_lifetime:summary:due_this_month"
_DUE_NEXT_3_MONTHS_UNIQUE = "battery_lifetime:summary:due_next_3_months"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create sensor entities for every tracked battery, plus the summaries."""
    coordinator: BatteryLifetimeCoordinator = hass.data[DOMAIN][entry.entry_id][
        "coordinator"
    ]

    @callback
    def _add_for_record(unique_id: str) -> list[SensorEntity]:
        return [
            ReplaceBySensor(coordinator, unique_id),
            PredictionQualitySensor(coordinator, unique_id),
            DrainRateSensor(coordinator, unique_id),
        ]

    initial: list[SensorEntity] = []
    for unique_id in coordinator.records:
        initial.extend(_add_for_record(unique_id))
    initial.append(DueThisMonthSensor(coordinator))
    initial.append(DueNext3MonthsSensor(coordinator))
    async_add_entities(initial)

    seen: set[str] = set(coordinator.records)

    @callback
    def _on_update() -> None:
        new_entities: list[SensorEntity] = []
        for unique_id in coordinator.records:
            if unique_id in seen:
                continue
            seen.add(unique_id)
            new_entities.extend(_add_for_record(unique_id))
        if new_entities:
            async_add_entities(new_entities)

    entry.async_on_unload(coordinator.async_add_listener(_on_update))


class _PerBatterySensor(BatteryCompanionEntity, SensorEntity):
    """Common base for the three per-battery sensors."""

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        record = self.record
        snapshot = (self.coordinator.data or {}).get(self._source_unique_id)
        if record is None or snapshot is None:
            return {}
        prediction = snapshot.prediction
        return {
            "source_entity": record.entity_id,
            "profile": prediction.profile_id,
            "threshold_pct": prediction.threshold_pct,
            "drain_rate_pct_day": prediction.drain_rate_pct_day,
            "confidence": prediction.confidence,
            "replaced_on": (
                record.replaced_on.isoformat()
                if record.replaced_on is not None
                else None
            ),
            "last_observed_pct": record.last_reading_pct,
            "last_seen": (
                record.last_reading_at.isoformat()
                if record.last_reading_at is not None
                else None
            ),
            "tracking_enabled": record.tracking_enabled,
        }


class ReplaceBySensor(_PerBatterySensor):
    """Predicted replacement datetime."""

    _attr_translation_key = "replace_by"
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(
        self, coordinator: BatteryLifetimeCoordinator, unique_id: str
    ) -> None:
        super().__init__(coordinator, unique_id, _REPLACE_BY_SUFFIX)
        self._attr_translation_placeholders = {"name": "Replace by"}
        self._attr_name = "Replace by"

    @property
    def native_value(self) -> datetime | None:
        snapshot = (self.coordinator.data or {}).get(self._source_unique_id)
        if snapshot is None:
            return None
        return snapshot.prediction.replace_by


class PredictionQualitySensor(_PerBatterySensor):
    """Confidence ladder value as an enum sensor."""

    _attr_translation_key = "prediction_quality"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = [
        "no_data",
        "profile_default",
        CONFIDENCE_LOW,
        CONFIDENCE_MEDIUM,
        CONFIDENCE_HIGH,
        "stale",
    ]

    def __init__(
        self, coordinator: BatteryLifetimeCoordinator, unique_id: str
    ) -> None:
        super().__init__(coordinator, unique_id, _PREDICTION_QUALITY_SUFFIX)
        self._attr_name = "Prediction quality"

    @property
    def native_value(self) -> str | None:
        snapshot = (self.coordinator.data or {}).get(self._source_unique_id)
        if snapshot is None:
            return None
        return snapshot.prediction.confidence


class DrainRateSensor(_PerBatterySensor):
    """EWMA drain rate in %/day."""

    _attr_translation_key = "drain_rate"
    _attr_native_unit_of_measurement = "%/d"
    _attr_suggested_display_precision = 3

    def __init__(
        self, coordinator: BatteryLifetimeCoordinator, unique_id: str
    ) -> None:
        super().__init__(coordinator, unique_id, _DRAIN_RATE_SUFFIX)
        self._attr_name = "Drain rate"

    @property
    def native_value(self) -> float | None:
        snapshot = (self.coordinator.data or {}).get(self._source_unique_id)
        if snapshot is None:
            return None
        rate = snapshot.prediction.drain_rate_pct_day
        return None if rate is None else float(rate)


class _SummarySensor(
    CoordinatorEntity[BatteryLifetimeCoordinator], SensorEntity
):
    """Base class for integration-level summary sensors."""

    _attr_has_entity_name = False
    _attr_native_unit_of_measurement = "batteries"
    _attr_state_class = "measurement"

    def __init__(
        self,
        coordinator: BatteryLifetimeCoordinator,
        *,
        unique_id: str,
        translation_key: str,
        name: str,
        object_id: str,
    ) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = unique_id
        self._attr_translation_key = translation_key
        self._attr_name = f"Battery Lifetime {name}"
        self._attr_suggested_object_id = object_id

    @property
    def device_info(self) -> dict[str, Any]:
        return {
            "identifiers": {(DOMAIN, "summary")},
            "name": "Battery Lifetime",
            "manufacturer": "Battery Lifetime",
        }


class DueThisMonthSensor(_SummarySensor):
    def __init__(self, coordinator: BatteryLifetimeCoordinator) -> None:
        super().__init__(
            coordinator,
            unique_id=_DUE_THIS_MONTH_UNIQUE,
            translation_key="due_this_month",
            name="Due this month",
            object_id="battery_lifetime_due_this_month",
        )

    @property
    def native_value(self) -> int:
        snapshots = self.coordinator.data or {}
        now = datetime.now(tz=UTC)
        cutoff = _last_day_of_month(now)
        count = 0
        for snap in snapshots.values():
            if not snap.record.tracking_enabled:
                continue
            replace_by = snap.prediction.replace_by
            if replace_by is not None and replace_by <= cutoff:
                count += 1
        return count


class DueNext3MonthsSensor(_SummarySensor):
    def __init__(self, coordinator: BatteryLifetimeCoordinator) -> None:
        super().__init__(
            coordinator,
            unique_id=_DUE_NEXT_3_MONTHS_UNIQUE,
            translation_key="due_next_3_months",
            name="Due next 3 months",
            object_id="battery_lifetime_due_next_3_months",
        )

    @property
    def native_value(self) -> int:
        snapshots = self.coordinator.data or {}
        cutoff = datetime.now(tz=UTC) + timedelta(days=90)
        count = 0
        for snap in snapshots.values():
            if not snap.record.tracking_enabled:
                continue
            replace_by = snap.prediction.replace_by
            if replace_by is not None and replace_by <= cutoff:
                count += 1
        return count


def _last_day_of_month(now: datetime) -> datetime:
    if now.month == 12:
        next_month = now.replace(
            year=now.year + 1, month=1, day=1, hour=0, minute=0, second=0, microsecond=0
        )
    else:
        next_month = now.replace(
            month=now.month + 1, day=1, hour=0, minute=0, second=0, microsecond=0
        )
    return next_month - timedelta(microseconds=1)


__all__ = (
    "DrainRateSensor",
    "PredictionQualitySensor",
    "ReplaceBySensor",
    "async_setup_entry",
    "companion_unique_id",
)
