"""Shared base class for Battery Lifetime companion entities.

Every companion is anchored to a source battery and identified by a
deterministic ``unique_id`` derived from the source's own ``unique_id``,
so the relationship survives entity-id renames or HA restarts.

Companion ``entity_id`` values follow the documented format
``<platform>.<source_object_id>_<suffix>`` (e.g.
``sensor.foo_battery_replace_by`` for a source of ``sensor.foo_battery``)
via ``suggested_object_id``. Users can rename them in the registry; the
unique_id keeps the relationship stable across renames.
"""

from __future__ import annotations

from typing import Any

from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, UNIQUE_ID_PREFIX
from .coordinator import BatteryLifetimeCoordinator, BatteryRecord


def companion_unique_id(source_unique_id: str, suffix: str) -> str:
    """Build a deterministic unique-id for a companion entity."""
    return f"{UNIQUE_ID_PREFIX}:{source_unique_id}:{suffix}"


def _source_object_id(entity_id: str) -> str:
    return entity_id.split(".", 1)[1]


class BatteryCompanionEntity(CoordinatorEntity[BatteryLifetimeCoordinator]):
    """Base class wiring a companion entity to its source battery's record."""

    _attr_has_entity_name = False

    def __init__(
        self,
        coordinator: BatteryLifetimeCoordinator,
        unique_id: str,
        suffix: str,
    ) -> None:
        super().__init__(coordinator)
        self._source_unique_id = unique_id
        self._suffix = suffix
        self._attr_unique_id = companion_unique_id(unique_id, suffix)
        record = coordinator.records.get(unique_id)
        source_object_id = (
            _source_object_id(record.entity_id) if record is not None else unique_id
        )
        self._suggested_object_id_value = f"{source_object_id}_{suffix}"

    @property
    def suggested_object_id(self) -> str | None:
        """Return the desired object_id for the registry.

        Overrides :meth:`Entity.suggested_object_id` (which would derive from
        ``self.name``) so the resulting entity_id matches the format
        documented in ``README.md`` regardless of the friendly name.
        """
        return self._suggested_object_id_value

    @property
    def record(self) -> BatteryRecord | None:
        return self.coordinator.records.get(self._source_unique_id)

    @property
    def available(self) -> bool:
        record = self.record
        return record is not None and record.tracking_enabled

    @property
    def device_info(self) -> dict[str, Any]:
        record = self.record
        if record is None:
            return {}
        return {
            "identifiers": {(DOMAIN, self._source_unique_id)},
            "name": f"Battery: {record.entity_id}",
            "manufacturer": "Battery Lifetime",
            "model": record.profile_id.title(),
        }
