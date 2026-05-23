"""Binary sensor platform: per-battery due-next-quarter flag."""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONFIDENCE_NO_DATA, DOMAIN
from .coordinator import BatteryLifetimeCoordinator
from .entity import BatteryCompanionEntity
from .quarters import is_due_by_quarter_end

_DUE_NEXT_QUARTER_SUFFIX = "due_next_quarter"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: BatteryLifetimeCoordinator = hass.data[DOMAIN][entry.entry_id][
        "coordinator"
    ]

    @callback
    def _build(unique_id: str) -> list[BinarySensorEntity]:
        return [DueNextQuarterBinarySensor(coordinator, unique_id)]

    initial: list[BinarySensorEntity] = []
    for unique_id in coordinator.records:
        initial.extend(_build(unique_id))
    async_add_entities(initial)

    seen: set[str] = set(coordinator.records)

    @callback
    def _on_update() -> None:
        new_entities: list[BinarySensorEntity] = []
        for unique_id in coordinator.records:
            if unique_id in seen:
                continue
            seen.add(unique_id)
            new_entities.extend(_build(unique_id))
        if new_entities:
            async_add_entities(new_entities)

    entry.async_on_unload(coordinator.async_add_listener(_on_update))


class DueNextQuarterBinarySensor(BatteryCompanionEntity, BinarySensorEntity):
    """Whether the battery is projected to need replacement next quarter."""

    _attr_translation_key = "due_next_quarter"

    def __init__(
        self, coordinator: BatteryLifetimeCoordinator, unique_id: str
    ) -> None:
        super().__init__(coordinator, unique_id, _DUE_NEXT_QUARTER_SUFFIX)
        self._attr_name = "Due next quarter"

    @property
    def is_on(self) -> bool | None:
        record = self.record
        snapshot = (self.coordinator.data or {}).get(self._source_unique_id)
        if record is None or snapshot is None:
            return None
        if not record.tracking_enabled:
            return False
        prediction = snapshot.prediction
        if prediction.confidence == CONFIDENCE_NO_DATA:
            return False
        return is_due_by_quarter_end(prediction.replace_by)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        record = self.record
        if record is None:
            return {}
        return {"source_entity": record.entity_id}
