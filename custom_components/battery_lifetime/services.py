"""Service registration for the Battery Lifetime integration.

Registers four services:

* ``battery_lifetime.predict_at`` — read-only forward simulator.
* ``battery_lifetime.confirm_stale_replacement`` — confirm a stale-prior
  replacement candidate raised via persistent notification.
* ``battery_lifetime.dismiss_stale_replacement`` — dismiss the candidate
  without committing a replacement; tracking stays on.
* ``battery_lifetime.exclude_stale_replacement`` — dismiss the candidate
  *and* flip ``tracking_enabled`` off for the affected battery.

The three stale-prior services are the user-facing path that backs the
"Confirm / Dismiss / Exclude" choices documented in
``replacement-detection/spec.md``.
"""

from __future__ import annotations

import logging
from datetime import date as date_type
from datetime import datetime, timezone
from typing import Any

import voluptuous as vol
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
)
from homeassistant.helpers import config_validation as cv

from .const import (
    DOMAIN,
    SERVICE_CONFIRM_STALE_REPLACEMENT,
    SERVICE_DISMISS_STALE_REPLACEMENT,
    SERVICE_EXCLUDE_STALE_REPLACEMENT,
    SERVICE_PREDICT_AT,
)
from .coordinator import BatteryLifetimeCoordinator

_LOGGER = logging.getLogger(__name__)

UTC = timezone.utc

PREDICT_AT_SCHEMA = vol.Schema(
    {
        vol.Required("date"): cv.date,
        vol.Optional("margin_days", default=0): vol.All(
            vol.Coerce(int), vol.Range(min=0)
        ),
        vol.Optional("actionable_only", default=False): cv.boolean,
        vol.Optional("include_excluded", default=False): cv.boolean,
    }
)

STALE_ACTION_SCHEMA = vol.Schema({vol.Required("entity_id"): cv.entity_id})

_STALE_SERVICE_NAMES = (
    SERVICE_CONFIRM_STALE_REPLACEMENT,
    SERVICE_DISMISS_STALE_REPLACEMENT,
    SERVICE_EXCLUDE_STALE_REPLACEMENT,
)


def _find_record_by_entity_id(
    hass: HomeAssistant, entity_id: str
) -> tuple[BatteryLifetimeCoordinator, str] | None:
    """Return ``(coordinator, unique_id)`` for the given source entity."""
    for coordinator in _coordinators(hass):
        for record in coordinator.iter_active_records():
            if record.entity_id == entity_id:
                return coordinator, record.unique_id
    return None


def _coordinators(hass: HomeAssistant) -> list[BatteryLifetimeCoordinator]:
    bucket = hass.data.get(DOMAIN, {})
    return [
        entry["coordinator"]
        for entry in bucket.values()
        if isinstance(entry, dict) and "coordinator" in entry
    ]


def _to_datetime(value: date_type | datetime) -> datetime:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
    return datetime(value.year, value.month, value.day, 12, 0, 0, tzinfo=UTC)


def async_register_services(hass: HomeAssistant) -> None:
    """Register the integration's services. Idempotent."""
    if hass.services.has_service(DOMAIN, SERVICE_PREDICT_AT):
        return

    async def _predict_at(call: ServiceCall) -> ServiceResponse:
        params = PREDICT_AT_SCHEMA(dict(call.data))
        target_date = _to_datetime(params["date"])
        margin_days: int = params["margin_days"]
        actionable_only: bool = params["actionable_only"]
        include_excluded: bool = params["include_excluded"]

        results: list[dict[str, Any]] = []
        for coordinator in _coordinators(hass):
            for record in coordinator.iter_active_records():
                if not record.tracking_enabled and not include_excluded:
                    continue
                simulation = coordinator.forward_simulate_record(
                    record,
                    target_date=target_date,
                    margin_days=margin_days,
                )
                if (
                    actionable_only
                    and simulation["predicted_state"] != "below_threshold"
                ):
                    continue
                entry: dict[str, Any] = {
                    "entity_id": record.entity_id,
                    "replace_by_entity": _replace_by_entity_id(
                        record.entity_id
                    ),
                    "unique_id": record.unique_id,
                    "profile": simulation["profile"],
                    "threshold_pct": simulation["threshold_pct"],
                    "drain_rate_pct_day": simulation["drain_rate_pct_day"],
                    "predicted_pct_at_date": simulation[
                        "predicted_pct_at_date"
                    ],
                    "predicted_state": simulation["predicted_state"],
                    "confidence": simulation["confidence"],
                    "tracking_enabled": record.tracking_enabled,
                }
                if include_excluded and not record.tracking_enabled:
                    entry["excluded"] = True
                results.append(entry)
        return {"results": results}

    hass.services.async_register(
        DOMAIN,
        SERVICE_PREDICT_AT,
        _predict_at,
        schema=PREDICT_AT_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )

    async def _confirm_stale(call: ServiceCall) -> None:
        params = STALE_ACTION_SCHEMA(dict(call.data))
        entity_id: str = params["entity_id"]
        match = _find_record_by_entity_id(hass, entity_id)
        if match is None:
            _LOGGER.warning(
                "battery_lifetime.confirm_stale_replacement: unknown "
                "entity_id %s; ignoring",
                entity_id,
            )
            return
        coordinator, unique_id = match
        committed = await coordinator.detector.confirm_stale(
            unique_id, entity_id
        )
        if not committed:
            _LOGGER.info(
                "battery_lifetime.confirm_stale_replacement: %s had no "
                "pending stale candidate; nothing to confirm",
                entity_id,
            )

    async def _dismiss_stale(call: ServiceCall) -> None:
        params = STALE_ACTION_SCHEMA(dict(call.data))
        entity_id: str = params["entity_id"]
        match = _find_record_by_entity_id(hass, entity_id)
        if match is None:
            _LOGGER.warning(
                "battery_lifetime.dismiss_stale_replacement: unknown "
                "entity_id %s; ignoring",
                entity_id,
            )
            return
        coordinator, unique_id = match
        await coordinator.detector.dismiss_stale(unique_id)

    async def _exclude_stale(call: ServiceCall) -> None:
        params = STALE_ACTION_SCHEMA(dict(call.data))
        entity_id: str = params["entity_id"]
        match = _find_record_by_entity_id(hass, entity_id)
        if match is None:
            _LOGGER.warning(
                "battery_lifetime.exclude_stale_replacement: unknown "
                "entity_id %s; ignoring",
                entity_id,
            )
            return
        coordinator, unique_id = match
        await coordinator.detector.exclude_stale(unique_id)
        await coordinator.set_tracking_enabled(unique_id, False)

    hass.services.async_register(
        DOMAIN,
        SERVICE_CONFIRM_STALE_REPLACEMENT,
        _confirm_stale,
        schema=STALE_ACTION_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_DISMISS_STALE_REPLACEMENT,
        _dismiss_stale,
        schema=STALE_ACTION_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_EXCLUDE_STALE_REPLACEMENT,
        _exclude_stale,
        schema=STALE_ACTION_SCHEMA,
    )


def async_unregister_services(hass: HomeAssistant) -> None:
    for name in (SERVICE_PREDICT_AT, *_STALE_SERVICE_NAMES):
        if hass.services.has_service(DOMAIN, name):
            hass.services.async_remove(DOMAIN, name)


def _replace_by_entity_id(source_entity_id: str) -> str:
    object_id = source_entity_id.split(".", 1)[1]
    return f"sensor.{object_id}_replace_by"


__all__ = (
    "PREDICT_AT_SCHEMA",
    "async_register_services",
    "async_unregister_services",
)
