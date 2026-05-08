"""Switch platform: chemistry profile (lithium/alkaline) and tracking-enabled."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, PROFILE_ALKALINE, PROFILE_LITHIUM
from .coordinator import BatteryLifetimeCoordinator
from .entity import BatteryCompanionEntity

_PROFILE_LITHIUM_SUFFIX = "profile_lithium"
_TRACKING_ENABLED_SUFFIX = "tracking_enabled"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: BatteryLifetimeCoordinator = hass.data[DOMAIN][entry.entry_id][
        "coordinator"
    ]

    @callback
    def _build(unique_id: str) -> list[SwitchEntity]:
        return [
            ProfileLithiumSwitch(coordinator, unique_id),
            TrackingEnabledSwitch(coordinator, unique_id),
        ]

    initial: list[SwitchEntity] = []
    for unique_id in coordinator.records:
        initial.extend(_build(unique_id))
    async_add_entities(initial)

    seen: set[str] = set(coordinator.records)

    @callback
    def _on_update() -> None:
        new_entities: list[SwitchEntity] = []
        for unique_id in coordinator.records:
            if unique_id in seen:
                continue
            seen.add(unique_id)
            new_entities.extend(_build(unique_id))
        if new_entities:
            async_add_entities(new_entities)

    entry.async_on_unload(coordinator.async_add_listener(_on_update))


class ProfileLithiumSwitch(BatteryCompanionEntity, SwitchEntity):
    """Chemistry profile selector. ``on`` = lithium, ``off`` = alkaline."""

    _attr_translation_key = "profile_lithium"

    def __init__(
        self, coordinator: BatteryLifetimeCoordinator, unique_id: str
    ) -> None:
        super().__init__(coordinator, unique_id, _PROFILE_LITHIUM_SUFFIX)
        self._attr_name = "Lithium chemistry"

    @property
    def is_on(self) -> bool | None:
        record = self.record
        if record is None:
            return None
        return record.profile_id == PROFILE_LITHIUM

    @property
    def icon(self) -> str:
        return (
            "mdi:battery-charging-high"
            if self.is_on
            else "mdi:battery-high"
        )

    @property
    def available(self) -> bool:
        return self.record is not None

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.set_profile(self._source_unique_id, PROFILE_LITHIUM)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.set_profile(self._source_unique_id, PROFILE_ALKALINE)


class TrackingEnabledSwitch(BatteryCompanionEntity, SwitchEntity):
    """Per-battery opt-out switch. ``on`` means the integration tracks it."""

    _attr_translation_key = "tracking_enabled"

    def __init__(
        self, coordinator: BatteryLifetimeCoordinator, unique_id: str
    ) -> None:
        super().__init__(coordinator, unique_id, _TRACKING_ENABLED_SUFFIX)
        self._attr_name = "Tracking enabled"
        self._attr_icon = "mdi:eye"

    @property
    def is_on(self) -> bool | None:
        record = self.record
        return None if record is None else record.tracking_enabled

    @property
    def available(self) -> bool:
        return self.record is not None

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.set_tracking_enabled(self._source_unique_id, True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.set_tracking_enabled(self._source_unique_id, False)
