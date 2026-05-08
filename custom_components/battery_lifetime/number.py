"""Number platform: optional per-battery threshold override."""

from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import BatteryLifetimeCoordinator
from .entity import BatteryCompanionEntity

_THRESHOLD_OVERRIDE_SUFFIX = "threshold_override"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: BatteryLifetimeCoordinator = hass.data[DOMAIN][entry.entry_id][
        "coordinator"
    ]

    @callback
    def _build(unique_id: str) -> list[NumberEntity]:
        return [ThresholdOverrideNumber(coordinator, unique_id)]

    initial: list[NumberEntity] = []
    for unique_id in coordinator.records:
        initial.extend(_build(unique_id))
    async_add_entities(initial)

    seen: set[str] = set(coordinator.records)

    @callback
    def _on_update() -> None:
        new_entities: list[NumberEntity] = []
        for unique_id in coordinator.records:
            if unique_id in seen:
                continue
            seen.add(unique_id)
            new_entities.extend(_build(unique_id))
        if new_entities:
            async_add_entities(new_entities)

    entry.async_on_unload(coordinator.async_add_listener(_on_update))


class ThresholdOverrideNumber(BatteryCompanionEntity, NumberEntity):
    _attr_translation_key = "threshold_override"
    _attr_native_min_value = 0.0
    _attr_native_max_value = 100.0
    _attr_native_step = 1.0
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_mode = NumberMode.BOX
    _attr_icon = "mdi:battery-alert"

    def __init__(
        self, coordinator: BatteryLifetimeCoordinator, unique_id: str
    ) -> None:
        super().__init__(coordinator, unique_id, _THRESHOLD_OVERRIDE_SUFFIX)
        self._attr_name = "Threshold override"

    @property
    def native_value(self) -> float | None:
        record = self.record
        return None if record is None else record.threshold_override

    @property
    def available(self) -> bool:
        return self.record is not None

    async def async_set_native_value(self, value: float) -> None:
        await self.coordinator.set_threshold_override(
            self._source_unique_id, float(value)
        )
