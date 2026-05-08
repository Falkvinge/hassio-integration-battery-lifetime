"""Date platform: ``replaced_on`` editable date entity."""

from __future__ import annotations

from datetime import date, datetime, timezone

from homeassistant.components.date import DateEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import BatteryLifetimeCoordinator
from .entity import BatteryCompanionEntity

UTC = timezone.utc

_REPLACED_ON_SUFFIX = "replaced_on"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: BatteryLifetimeCoordinator = hass.data[DOMAIN][entry.entry_id][
        "coordinator"
    ]

    @callback
    def _build(unique_id: str) -> list[DateEntity]:
        return [ReplacedOnDate(coordinator, unique_id)]

    initial: list[DateEntity] = []
    for unique_id in coordinator.records:
        initial.extend(_build(unique_id))
    async_add_entities(initial)

    seen: set[str] = set(coordinator.records)

    @callback
    def _on_update() -> None:
        new_entities: list[DateEntity] = []
        for unique_id in coordinator.records:
            if unique_id in seen:
                continue
            seen.add(unique_id)
            new_entities.extend(_build(unique_id))
        if new_entities:
            async_add_entities(new_entities)

    entry.async_on_unload(coordinator.async_add_listener(_on_update))


class ReplacedOnDate(BatteryCompanionEntity, DateEntity):
    _attr_translation_key = "replaced_on"

    def __init__(
        self, coordinator: BatteryLifetimeCoordinator, unique_id: str
    ) -> None:
        super().__init__(coordinator, unique_id, _REPLACED_ON_SUFFIX)
        self._attr_name = "Replaced on"
        self._attr_icon = "mdi:calendar-check"

    @property
    def native_value(self) -> date | None:
        record = self.record
        if record is None or record.replaced_on is None:
            return None
        return record.replaced_on.date()

    @property
    def available(self) -> bool:
        return self.record is not None

    async def async_set_value(self, value: date) -> None:
        today = datetime.now(tz=UTC).date()
        if value > today:
            raise ValueError("replaced_on cannot be in the future")
        replaced_on = datetime(
            value.year, value.month, value.day, 12, 0, 0, tzinfo=UTC
        )
        await self.coordinator.set_replaced_on(
            self._source_unique_id, replaced_on
        )
