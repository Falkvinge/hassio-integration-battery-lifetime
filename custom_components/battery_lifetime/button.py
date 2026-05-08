"""Button platform: 'I just replaced the batteries' single-press action."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import BatteryLifetimeCoordinator
from .entity import BatteryCompanionEntity

_MARK_REPLACED_SUFFIX = "mark_replaced"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: BatteryLifetimeCoordinator = hass.data[DOMAIN][entry.entry_id][
        "coordinator"
    ]

    @callback
    def _build(unique_id: str) -> list[ButtonEntity]:
        return [MarkReplacedButton(coordinator, unique_id)]

    initial: list[ButtonEntity] = []
    for unique_id in coordinator.records:
        initial.extend(_build(unique_id))
    async_add_entities(initial)

    seen: set[str] = set(coordinator.records)

    @callback
    def _on_update() -> None:
        new_entities: list[ButtonEntity] = []
        for unique_id in coordinator.records:
            if unique_id in seen:
                continue
            seen.add(unique_id)
            new_entities.extend(_build(unique_id))
        if new_entities:
            async_add_entities(new_entities)

    entry.async_on_unload(coordinator.async_add_listener(_on_update))


class MarkReplacedButton(BatteryCompanionEntity, ButtonEntity):
    _attr_translation_key = "mark_replaced"

    def __init__(
        self, coordinator: BatteryLifetimeCoordinator, unique_id: str
    ) -> None:
        super().__init__(coordinator, unique_id, _MARK_REPLACED_SUFFIX)
        self._attr_name = "Mark replaced"
        self._attr_icon = "mdi:battery-plus-variant"

    @property
    def available(self) -> bool:
        return self.record is not None

    async def async_press(self) -> None:
        await self.coordinator.mark_replaced_now(self._source_unique_id)
