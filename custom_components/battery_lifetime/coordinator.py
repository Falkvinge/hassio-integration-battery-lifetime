"""Coordinator that drives the Battery Lifetime integration.

The coordinator is the spine: it owns the in-memory ``BatteryRecord`` map,
listens to source-state-change events, drives the replacement detector,
maintains EWMA state, asks the projector for ``replace_by`` values, and
pushes the resulting snapshots to the companion entities.

It also runs a low-frequency "tick" (every ten minutes by default) so that
``replace_by`` and confidence respond to wall-clock time without needing a
fresh reading -- otherwise a battery that hasn't reported in 8 days would
not flip to ``stale`` until the source happens to publish.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from homeassistant.components import persistent_notification
from homeassistant.const import EVENT_STATE_CHANGED
from homeassistant.core import (
    CALLBACK_TYPE,
    Event,
    EventStateChangedData,
    HomeAssistant,
    callback,
)
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import (
    CONFIDENCE_LOW_DAYS,
    CONFIDENCE_LOW_DRAIN_PCT,
    DOMAIN,
    REMOVED_SOURCE_RETENTION_DAYS,
    UPDATE_INTERVAL_SECONDS,
)
from .detection import (
    ColdStartBackfiller,
    ReplacementDetector,
    commit_cold_start_hit,
    estimate_replaced_on_from_drain,
)
from .discovery import is_eligible, iter_eligible_entities
from .prediction import (
    BatteryState,
    EwmaState,
    Prediction,
    forward_simulate,
    project_replace_by,
    reset_ewma_for_replacement,
    update_ewma,
)
from .store import BatteryLifetimeStore

_LOGGER = logging.getLogger(__name__)
UTC = timezone.utc


def _utcnow() -> datetime:
    return datetime.now(tz=UTC)


def _to_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _isoformat_or_none(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _parse_or_none(value: str | None) -> datetime | None:
    if value is None:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


@dataclass(slots=True)
class BatteryRecord:
    """In-memory mirror of a tracked battery's persistent state."""

    unique_id: str
    entity_id: str
    profile_id: str
    tracking_enabled: bool
    threshold_override: float | None
    replaced_on: datetime | None
    last_reading_pct: float | None
    last_reading_at: datetime | None
    ewma: EwmaState
    last_replace_by: datetime | None
    backfill_attempted: bool = False
    backwards_extrapolated: bool = False

    def to_state(self) -> BatteryState:
        return BatteryState(
            profile_id=self.profile_id,
            replaced_on=self.replaced_on,
            threshold_override=self.threshold_override,
            last_reading_pct=self.last_reading_pct,
            last_reading_at=self.last_reading_at,
            ewma=self.ewma,
        )


@dataclass(slots=True, frozen=True)
class CoordinatorSnapshot:
    """The publishable view of a single battery."""

    record: BatteryRecord
    prediction: Prediction


class BatteryLifetimeCoordinator(
    DataUpdateCoordinator[dict[str, CoordinatorSnapshot]]
):
    """Drives discovery, detection, and prediction for every tracked battery."""

    def __init__(
        self,
        hass: HomeAssistant,
        *,
        store: BatteryLifetimeStore,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name="battery_lifetime",
            update_interval=None,
        )
        self._store = store
        self._records: dict[str, BatteryRecord] = {}
        self._source_to_unique: dict[str, str] = {}
        self._unsub_state: CALLBACK_TYPE | None = None
        self._unsub_registry: CALLBACK_TYPE | None = None
        self._unsub_tick: CALLBACK_TYPE | None = None
        self._detector = ReplacementDetector(hass, self._apply_commit)
        self._backfiller = ColdStartBackfiller(hass)
        self._known_entities: set[str] = set()
        self._pending_backfills: set[str] = set()

    @property
    def store(self) -> BatteryLifetimeStore:
        return self._store

    @property
    def detector(self) -> ReplacementDetector:
        return self._detector

    @property
    def records(self) -> dict[str, BatteryRecord]:
        return self._records

    async def async_setup(self) -> None:
        """Hydrate state from the store and start listeners."""
        for unique_id, entry in self._store.iter_batteries():
            if entry.get("removed_at") is not None:
                continue
        self._unsub_state = self.hass.bus.async_listen(
            EVENT_STATE_CHANGED, self._handle_state_changed
        )
        self._unsub_registry = self.hass.bus.async_listen(
            "entity_registry_updated", self._handle_registry_update
        )
        self._unsub_tick = async_track_time_interval(
            self.hass,
            self._handle_tick,
            timedelta(seconds=UPDATE_INTERVAL_SECONDS),
        )
        await self._scan_initial_entities()

    async def async_shutdown(self) -> None:
        if self._unsub_state is not None:
            self._unsub_state()
            self._unsub_state = None
        if self._unsub_registry is not None:
            self._unsub_registry()
            self._unsub_registry = None
        if self._unsub_tick is not None:
            self._unsub_tick()
            self._unsub_tick = None
        self._detector.shutdown()
        await self._store.async_save()
        await super().async_shutdown()

    async def _scan_initial_entities(self) -> None:
        for entry in iter_eligible_entities(self.hass):
            await self._ensure_record(entry)

    async def _ensure_record(self, entry: er.RegistryEntry) -> BatteryRecord:
        unique_id = entry.unique_id
        assert unique_id is not None
        record = self._records.get(unique_id)
        if record is not None:
            record.entity_id = entry.entity_id
            self._source_to_unique[entry.entity_id] = unique_id
            return record

        stored = self._store.get_battery(unique_id)
        if stored is None:
            stored = self._store.upsert_battery(unique_id)
        elif stored.get("removed_at") is not None:
            self._store.restore_battery(unique_id)
            stored = self._store.get_battery(unique_id) or {}

        ewma = EwmaState.from_dict(stored.get("ewma_state"))
        record = BatteryRecord(
            unique_id=unique_id,
            entity_id=entry.entity_id,
            profile_id=str(stored.get("profile") or self._store.default_profile),
            tracking_enabled=bool(stored.get("tracking_enabled", True)),
            threshold_override=(
                float(stored["threshold_override"])
                if stored.get("threshold_override") is not None
                else None
            ),
            replaced_on=_parse_or_none(stored.get("replaced_on")),
            last_reading_pct=stored.get("last_reading_pct"),
            last_reading_at=_parse_or_none(stored.get("last_reading_at")),
            ewma=ewma,
            last_replace_by=_parse_or_none(stored.get("last_replace_by")),
        )
        self._records[unique_id] = record
        self._source_to_unique[entry.entity_id] = unique_id
        self._known_entities.add(entry.entity_id)

        state = self.hass.states.get(entry.entity_id)
        if state is not None:
            try:
                pct = float(state.state)
            except (TypeError, ValueError):
                pct = None
            if pct is not None and record.last_reading_pct is None:
                record.last_reading_pct = pct
                record.last_reading_at = _utcnow()
                self._persist(record)

        if not record.backfill_attempted:
            record.backfill_attempted = True
            if record.replaced_on is None:
                self._pending_backfills.add(unique_id)
                self.hass.async_create_task(
                    self._run_backfill_with_tracking(record),
                    name=f"battery_lifetime_cold_start_{unique_id}",
                )

        return record

    async def _run_backfill_with_tracking(
        self, record: BatteryRecord
    ) -> None:
        """Run cold-start backfill and announce completion of the batch.

        Cold-start backfill is dispatched as a background task per record so
        it never blocks ``async_setup``. ``_pending_backfills`` is the
        single source of truth for "is the initial backfill phase still
        running"; when the last task removes its ``unique_id`` the user
        gets one persistent notification.
        """
        try:
            await self._attempt_cold_start_backfill(record)
        finally:
            self._pending_backfills.discard(record.unique_id)
            if not self._pending_backfills:
                self._announce_backfill_complete()

    def _announce_backfill_complete(self) -> None:
        if self._store.cold_start_backfill_announced:
            return
        persistent_notification.async_create(
            self.hass,
            (
                "Battery Lifetime has finished its initial cold-start "
                "backfill. Per-battery 'Replaced on' values inferred from "
                "long-term statistics are now populated."
            ),
            title="Battery Lifetime: backfill complete",
            notification_id="battery_lifetime_cold_start_complete",
        )
        self._store.set_cold_start_backfill_announced()

    def _purge_companions_for_pruned(self, unique_ids: list[str]) -> None:
        """Remove the companion device for each pruned source.

        HA's device-registry removal cascades to the entity registry and
        drops every entry tied to the device, which on the Battery Lifetime
        device card is exactly the nine per-source companion entries.
        Idempotent: a missing device is a silent no-op.
        """
        if not unique_ids:
            return
        device_registry = dr.async_get(self.hass)
        for source_uid in unique_ids:
            device = device_registry.async_get_device(
                identifiers={(DOMAIN, source_uid)}
            )
            if device is None:
                continue
            device_registry.async_remove_device(device.id)
            _LOGGER.info(
                "battery_lifetime: removed orphan companion device for "
                "pruned source %s",
                source_uid,
            )

    async def _attempt_cold_start_backfill(
        self, record: BatteryRecord
    ) -> None:
        if record.replaced_on is not None:
            return
        try:
            hit = await self._backfiller.find_most_recent_jump(record.entity_id)
        except Exception:  # pragma: no cover - defensive
            _LOGGER.exception(
                "battery_lifetime: cold-start backfill failed for %s",
                record.entity_id,
            )
            return
        if hit is None:
            return

        async def _apply(replaced_on: datetime) -> None:
            record.replaced_on = replaced_on
            record.ewma = reset_ewma_for_replacement(hit.current_pct, replaced_on)
            self._persist(record)

        await commit_cold_start_hit(
            self.hass,
            entity_id=record.entity_id,
            unique_id=record.unique_id,
            hit=hit,
            apply=_apply,
        )

    @callback
    def _handle_registry_update(self, event: Event) -> None:
        action = event.data.get("action")
        if action not in {"create", "update", "remove"}:
            return
        self.hass.async_create_task(self._async_registry_changed(event))

    async def _async_registry_changed(self, event: Event) -> None:
        action = event.data.get("action")
        entity_id = event.data.get("entity_id")
        if entity_id is None:
            return
        if action == "remove":
            unique_id = self._source_to_unique.pop(entity_id, None)
            if unique_id is not None:
                self._store.remove_battery(unique_id)
                record = self._records.pop(unique_id, None)
                if record is not None:
                    record.tracking_enabled = False
            pruned = self._store.prune_removed_older_than(
                REMOVED_SOURCE_RETENTION_DAYS
            )
            self._purge_companions_for_pruned(pruned)
            return
        registry = er.async_get(self.hass)
        entry = registry.async_get(entity_id)
        if entry is None:
            return
        if not is_eligible(self.hass, entry):
            return
        await self._ensure_record(entry)
        await self.async_request_refresh()

    @callback
    def _handle_state_changed(self, event: Event[EventStateChangedData]) -> None:
        entity_id = event.data["entity_id"]
        if entity_id not in self._source_to_unique:
            return
        new_state = event.data.get("new_state")
        if new_state is None:
            return
        try:
            pct = float(new_state.state)
        except (TypeError, ValueError):
            return
        ts = _to_utc(new_state.last_updated)
        self.hass.async_create_task(
            self._handle_source_update(entity_id, pct, ts)
        )

    async def _handle_source_update(
        self, entity_id: str, pct: float, ts: datetime
    ) -> None:
        unique_id = self._source_to_unique.get(entity_id)
        if unique_id is None:
            return
        record = self._records.get(unique_id)
        if record is None:
            return

        prev_pct = record.last_reading_pct
        prev_at = record.last_reading_at

        committed = await self._detector.process_reading(
            unique_id,
            entity_id,
            prev_pct=prev_pct,
            prev_at=prev_at,
            new_pct=pct,
            new_at=ts,
            tracking_enabled=record.tracking_enabled,
        )
        if committed:
            return

        if record.tracking_enabled:
            record.ewma = update_ewma(record.ewma, pct, ts)
        record.last_reading_pct = pct
        record.last_reading_at = ts
        await self._maybe_backwards_extrapolate(record)

        self._persist(record)
        self._publish_single_record_update(unique_id, record)

    async def _maybe_backwards_extrapolate(
        self, record: BatteryRecord
    ) -> None:
        if record.replaced_on is not None:
            return
        if record.backwards_extrapolated:
            return
        if record.ewma.rate is None or record.ewma.rate <= 0:
            return
        if record.last_reading_pct is None or record.last_reading_at is None:
            return
        baseline_at = record.ewma.baseline_at
        baseline_pct = record.ewma.baseline_pct
        if baseline_at is None or baseline_pct is None:
            return
        days_observed = (
            record.last_reading_at - baseline_at
        ).total_seconds() / 86400.0
        drain_pct = baseline_pct - record.last_reading_pct
        if days_observed < CONFIDENCE_LOW_DAYS:
            return
        if drain_pct < CONFIDENCE_LOW_DRAIN_PCT:
            return
        estimated = estimate_replaced_on_from_drain(
            last_pct=record.last_reading_pct,
            last_at=record.last_reading_at,
            drain_rate_pct_day=record.ewma.rate,
            starting_pct=100.0,
        )
        if estimated is None:
            return
        record.replaced_on = estimated
        record.backwards_extrapolated = True
        _LOGGER.info(
            "battery_lifetime: backwards-extrapolated replaced_on=%s for %s",
            estimated.isoformat(),
            record.entity_id,
        )

    async def _apply_commit(
        self,
        unique_id: str,
        replaced_on: datetime,
        payload: dict[str, Any],
    ) -> None:
        record = self._records.get(unique_id)
        if record is None:
            return
        pct = float(payload.get("current_pct", 100.0))
        record.replaced_on = replaced_on
        record.ewma = reset_ewma_for_replacement(pct, replaced_on)
        record.last_reading_pct = pct
        record.last_reading_at = replaced_on
        record.backwards_extrapolated = False
        self._persist(record)
        await self.async_request_refresh()

    async def mark_replaced_now(self, unique_id: str) -> None:
        """Manual mark-replaced: anchor `replaced_on` at utcnow()."""
        record = self._records.get(unique_id)
        if record is None:
            return
        now = _utcnow()
        record.replaced_on = now
        record.ewma = reset_ewma_for_replacement(
            record.last_reading_pct or 100.0, now
        )
        record.backwards_extrapolated = False
        self._persist(record)
        from .const import (
            EVENT_REPLACEMENT_DETECTED,
            REPLACEMENT_SOURCE_MANUAL_BUTTON,
        )

        self.hass.bus.async_fire(
            EVENT_REPLACEMENT_DETECTED,
            {
                "entity_id": record.entity_id,
                "unique_id": unique_id,
                "previous_pct": record.last_reading_pct,
                "current_pct": record.last_reading_pct or 100.0,
                "prior_reading_age_seconds": 0,
                "replaced_on": now.isoformat(),
                "confirmed": True,
                "source": REPLACEMENT_SOURCE_MANUAL_BUTTON,
            },
        )
        await self.async_request_refresh()

    async def set_replaced_on(
        self, unique_id: str, replaced_on: datetime
    ) -> None:
        """Manual edit: directly set replaced_on to a non-future date."""
        record = self._records.get(unique_id)
        if record is None:
            return
        replaced_on = _to_utc(replaced_on)
        if replaced_on > _utcnow():
            raise ValueError("replaced_on cannot be in the future")
        record.replaced_on = replaced_on
        record.ewma = reset_ewma_for_replacement(
            record.last_reading_pct or 100.0, replaced_on
        )
        record.backwards_extrapolated = False
        self._persist(record)
        from .const import (
            EVENT_REPLACEMENT_DETECTED,
            REPLACEMENT_SOURCE_MANUAL_DATE_EDIT,
        )

        self.hass.bus.async_fire(
            EVENT_REPLACEMENT_DETECTED,
            {
                "entity_id": record.entity_id,
                "unique_id": unique_id,
                "previous_pct": record.last_reading_pct,
                "current_pct": record.last_reading_pct or 100.0,
                "prior_reading_age_seconds": 0,
                "replaced_on": replaced_on.isoformat(),
                "confirmed": True,
                "source": REPLACEMENT_SOURCE_MANUAL_DATE_EDIT,
            },
        )
        await self.async_request_refresh()

    async def set_profile(self, unique_id: str, profile_id: str) -> None:
        record = self._records.get(unique_id)
        if record is None:
            return
        record.profile_id = profile_id
        self._persist(record)
        await self.async_request_refresh()

    async def set_tracking_enabled(
        self, unique_id: str, enabled: bool
    ) -> None:
        record = self._records.get(unique_id)
        if record is None:
            return
        record.tracking_enabled = enabled
        self._persist(record)
        await self.async_request_refresh()

    async def set_threshold_override(
        self, unique_id: str, override: float | None
    ) -> None:
        record = self._records.get(unique_id)
        if record is None:
            return
        if override is not None:
            override = float(override)
            if not 0.0 <= override <= 100.0:
                raise ValueError("threshold override must be in 0..100")
        record.threshold_override = override
        self._persist(record)
        await self.async_request_refresh()

    @callback
    def _handle_tick(self, _now: datetime) -> None:
        pruned = self._store.prune_removed_older_than(
            REMOVED_SOURCE_RETENTION_DAYS
        )
        self._purge_companions_for_pruned(pruned)
        self.hass.async_create_task(self._async_recompute_and_maybe_publish())

    async def _async_recompute_and_maybe_publish(self) -> None:
        """Heartbeat path: recompute every record and publish only if changed.

        The unconditional publish path (``async_request_refresh``) is reserved
        for explicit user actions and registry/detector callbacks; the periodic
        heartbeat exists to surface time-driven flips (stale, confidence
        ladder, summary cutoffs) without flooding listeners on idle systems.
        """
        new_snapshots = self._compute_snapshots()
        if self.data is None or self._snapshots_differ(self.data, new_snapshots):
            self.async_set_updated_data(new_snapshots)

    def _publish_single_record_update(
        self, unique_id: str, record: BatteryRecord
    ) -> None:
        """Per-source-event path: replace one record's snapshot, publish.

        Other records' ``Prediction`` instances are carried forward by
        reference so the publish is O(1) in the number of tracked batteries.
        On the very first publish (``self.data is None``) we compute every
        record so the snapshot dict is complete from the start.
        """
        if self.data is None:
            self.async_set_updated_data(self._compute_snapshots())
            return
        snapshots = dict(self.data)
        prediction = project_replace_by(
            record.to_state(),
            now=_utcnow(),
            last_replace_by_fallback=record.last_replace_by,
        )
        if prediction.replace_by is not None:
            record.last_replace_by = prediction.replace_by
            self._persist(record)
        snapshots[unique_id] = CoordinatorSnapshot(
            record=record, prediction=prediction
        )
        self.async_set_updated_data(snapshots)

    def _compute_snapshots(self) -> dict[str, CoordinatorSnapshot]:
        snapshots: dict[str, CoordinatorSnapshot] = {}
        now = _utcnow()
        for unique_id, record in list(self._records.items()):
            prediction = project_replace_by(
                record.to_state(),
                now=now,
                last_replace_by_fallback=record.last_replace_by,
            )
            if prediction.replace_by is not None:
                record.last_replace_by = prediction.replace_by
                self._persist(record)
            snapshots[unique_id] = CoordinatorSnapshot(
                record=record, prediction=prediction
            )
        return snapshots

    @staticmethod
    def _snapshots_differ(
        old: dict[str, CoordinatorSnapshot],
        new: dict[str, CoordinatorSnapshot],
    ) -> bool:
        if old.keys() != new.keys():
            return True
        for unique_id, new_snap in new.items():
            old_snap = old[unique_id]
            op = old_snap.prediction
            np = new_snap.prediction
            if (
                op.replace_by != np.replace_by
                or op.confidence != np.confidence
                or op.drain_rate_pct_day != np.drain_rate_pct_day
                or op.threshold_pct != np.threshold_pct
            ):
                return True
        return False

    def _persist(self, record: BatteryRecord) -> None:
        self._store.upsert_battery(
            record.unique_id,
            replaced_on=_isoformat_or_none(record.replaced_on),
            profile=record.profile_id,
            threshold_override=record.threshold_override,
            tracking_enabled=record.tracking_enabled,
            ewma_state=record.ewma.to_dict(),
            last_reading_pct=record.last_reading_pct,
            last_reading_at=_isoformat_or_none(record.last_reading_at),
            last_replace_by=_isoformat_or_none(record.last_replace_by),
        )

    async def _async_update_data(self) -> dict[str, CoordinatorSnapshot]:
        return self._compute_snapshots()

    def iter_active_records(self) -> Iterable[BatteryRecord]:
        for record in self._records.values():
            yield record

    def forward_simulate_record(
        self,
        record: BatteryRecord,
        *,
        target_date: datetime,
        margin_days: int,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        return forward_simulate(
            record.to_state(),
            target_date=target_date,
            margin_days=margin_days,
            now=now,
        )
