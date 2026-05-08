"""Source-entity discovery for the Battery Lifetime integration.

Eligibility rules (mirroring the spec):

* ``device_class: battery``
* ``unit_of_measurement: %``
* current state is a number in the range ``[0, 100]``
* the entity has a stable ``unique_id``
* the entity is not a companion entity created by this integration

Categorical / boolean / voltage-only battery sensors are deliberately skipped
and logged at info level on first sight so the user can spot misconfiguration.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable

from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.const import PERCENTAGE, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

_LOGGED_SKIPS: set[str] = set()


def _state_is_numeric(state_value: str | None) -> bool:
    if state_value is None or state_value in (STATE_UNKNOWN, STATE_UNAVAILABLE):
        return False
    try:
        pct = float(state_value)
    except (TypeError, ValueError):
        return False
    return 0.0 <= pct <= 100.0


def _is_companion(entry: er.RegistryEntry) -> bool:
    return entry.platform == DOMAIN


def is_eligible(
    hass: HomeAssistant,
    entry: er.RegistryEntry,
    *,
    log_first_skip: bool = True,
) -> bool:
    """Return True if the registry entry can be tracked by the integration."""
    if entry.disabled or entry.hidden_by:
        return False
    if _is_companion(entry):
        return False
    if entry.unique_id is None:
        if log_first_skip and entry.entity_id not in _LOGGED_SKIPS:
            _LOGGED_SKIPS.add(entry.entity_id)
            _LOGGER.warning(
                "battery_lifetime: %s has no unique_id; skipping",
                entry.entity_id,
            )
        return False
    if entry.entity_id.split(".", 1)[0] != "sensor":
        if entry.original_device_class == SensorDeviceClass.BATTERY:
            if log_first_skip and entry.entity_id not in _LOGGED_SKIPS:
                _LOGGED_SKIPS.add(entry.entity_id)
                _LOGGER.info(
                    "battery_lifetime: %s is not a numeric percent sensor; "
                    "skipping",
                    entry.entity_id,
                )
        return False
    device_class = entry.device_class or entry.original_device_class
    if device_class != SensorDeviceClass.BATTERY:
        return False
    unit = entry.unit_of_measurement
    if unit != PERCENTAGE:
        if log_first_skip and entry.entity_id not in _LOGGED_SKIPS:
            _LOGGED_SKIPS.add(entry.entity_id)
            _LOGGER.info(
                "battery_lifetime: %s reports unit %r (not %%); skipping",
                entry.entity_id,
                unit,
            )
        return False
    state = hass.states.get(entry.entity_id)
    if state is None:
        return False
    if not _state_is_numeric(state.state):
        if log_first_skip and entry.entity_id not in _LOGGED_SKIPS:
            _LOGGED_SKIPS.add(entry.entity_id)
            _LOGGER.info(
                "battery_lifetime: %s reports non-numeric state %r; skipping",
                entry.entity_id,
                state.state,
            )
        return False
    return True


def iter_eligible_entities(
    hass: HomeAssistant,
) -> Iterable[er.RegistryEntry]:
    """Yield every registry entry that currently meets the eligibility rules."""
    registry = er.async_get(hass)
    for entry in registry.entities.values():
        if is_eligible(hass, entry):
            yield entry


def reset_skip_log() -> None:
    """Clear the "already-logged a skip" cache.

    Useful in tests to avoid cross-test bleed of log suppression.
    """
    _LOGGED_SKIPS.clear()


__all__ = ("is_eligible", "iter_eligible_entities", "reset_skip_log")
