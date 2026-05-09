## Context

`BatteryLifetimeCoordinator` extends `DataUpdateCoordinator[dict[str, CoordinatorSnapshot]]`. Today it sets `update_interval=600s`, registers a separate `async_track_time_interval(_handle_tick, 600s)` that calls `async_request_refresh`, and implements `_async_update_data` as a full O(N) walk that recomputes every tracked battery's `Prediction` and replaces the whole snapshot dict.

`async_request_refresh` is also the only refresh path used by source-state-change handlers, the registry handler, and every user-action setter (`set_profile`, `mark_replaced_now`, etc.). It is debounced at the HA framework level (~10 s cooldown), so bursts coalesce, but each refresh that does fire still does the full O(N) walk and unconditionally publishes to all `CoordinatorEntity` listeners (8 companions × N + 2 summaries).

User's current install: 70 batteries / 554 entities. The math cost is sub-millisecond per refresh. The cost that's worth caring about is the entity-state fan-out (writes to the HA state machine, recorder, and any listening automations) on every refresh.

## Goals / Non-Goals

**Goals:**
- Eliminate the duplicate 10-minute timer.
- Avoid recomputing N records when only one source's value actually changed.
- Avoid publishing a fresh snapshot when no record's externally observable `Prediction` changed.
- Preserve the three time-driven flips that are the heartbeat's reason to exist: stale flip at 7-day source idleness, confidence-ladder ratchet at 7/30/60 days, and summary-sensor month/quarter cutoff transitions.
- Preserve all current spec-level behavior. No requirement changes.

**Non-Goals:**
- No change to the prediction math (`project_replace_by`, `evaluate_confidence`, `forward_simulate`).
- No change to the storage schema, persistent state, services, events, or companion-entity layout.
- No introduction of a smarter scheduler (e.g. per-record next-flip timer). The current "tick everything every 10 min" cadence is kept; only the *push* is gated.
- No change to `_async_update_data`'s contract for `coordinator.async_refresh()` callers — it still returns the full snapshot dict so external callers (services, options flow) get the current view.

## Decisions

### Decision 1: Drop `update_interval`, keep the explicit tick

`DataUpdateCoordinator(update_interval=…)` and the explicit `async_track_time_interval(_handle_tick, …)` both call `_async_update_data` every 10 minutes. The explicit tick has a side effect we want to keep — `prune_removed_older_than` — and gives us a callback hook where we can implement the diff gate without overriding `_async_update_data`'s framework contract.

We pass `update_interval=None` to the superclass and let `_handle_tick` drive the cadence via `_async_recompute_and_publish` (a new private method). `_async_update_data` is still implemented (the framework calls it from `async_refresh`/`async_request_refresh`), but it just delegates to a pure recompute that returns the snapshot dict without any "did anything change?" gate, because callers of `async_refresh` explicitly want a fresh snapshot.

**Alternative considered:** keep `update_interval=600s` and drop the explicit tick. Rejected because we'd lose the natural place to put the diff gate (we'd have to override `_async_update_data` to skip publishing, but the superclass calls `async_set_updated_data` itself based on the returned value — there's no clean "compute but don't push" path through the framework).

### Decision 2: O(1) per-source-event update via `async_set_updated_data`

In `_handle_source_update`, after the existing record mutation (detector, EWMA, persistence), build the snapshot dict locally:

```python
snapshots = dict(self.data) if self.data else {}
snapshots[unique_id] = CoordinatorSnapshot(
    record=record,
    prediction=project_replace_by(
        record.to_state(),
        now=_utcnow(),
        last_replace_by_fallback=record.last_replace_by,
    ),
)
self.async_set_updated_data(snapshots)
```

This replaces the existing `await self.async_request_refresh()` call. Only the changed record gets a fresh `Prediction`; the rest are carried forward by reference. Companion entities for the unchanged batteries still get a `_handle_coordinator_update` call (HA's `CoordinatorEntity` doesn't diff), but their `native_value` reads return the same value, so HA's state machine dedupes the write (no new `state_changed` event). Net: O(1) math + O(1) recorder writes per source event.

**Alternative considered:** custom listener layer that only notifies the affected entities. Rejected as overkill — the `state_machine` dedupe already gives us the recorder savings, and the entity-level diff is HA's job.

### Decision 3: Diff-gated heartbeat

`_handle_tick` becomes:

```python
@callback
def _handle_tick(self, _now):
    self._store.prune_removed_older_than(REMOVED_SOURCE_RETENTION_DAYS)
    self.hass.async_create_task(self._async_recompute_and_maybe_publish())

async def _async_recompute_and_maybe_publish(self):
    new = self._compute_snapshots()
    old = self.data
    if old is None or self._snapshots_differ(old, new):
        self.async_set_updated_data(new)
```

`_snapshots_differ(old, new)` returns True if:
- `old.keys() != new.keys()` (a record was added or removed), OR
- for any shared key, any of `prediction.replace_by`, `prediction.confidence`, `prediction.drain_rate_pct_day`, `prediction.threshold_pct` differs.

These four fields are the externally observable surface of a `Prediction`. The summary sensors derive from `prediction.replace_by`, so if every record's `replace_by` is unchanged the summary sensors are also unchanged, and skipping the push is safe.

User-action setters (`set_profile`, `set_threshold_override`, etc.) keep using `await self.async_request_refresh()` because they explicitly want an immediate publish (the user just changed something and expects the UI to update). The diff gate would skip cases where, say, toggling the lithium switch on a battery that's currently on plateau happens to leave `replace_by` the same — even though the chemistry change is itself something a user might want reflected. Keeping the unconditional path for explicit user actions is cleaner.

**Alternative considered:** tighter diff (include `record.profile_id`, `record.tracking_enabled`, etc.). Rejected — those fields only change via user-action setters, which already publish unconditionally. Adding them to the diff is dead code on the heartbeat path.

**Alternative considered:** snapshot-equality via `__eq__`. Rejected — `BatteryRecord` is `@dataclass(slots=True)` (mutable, identity-equal by default) and `Prediction` is `frozen=True` (value-equal). Mixing the two equality semantics inside a single comparator is fragile. Explicit field comparison on `Prediction` is clearer.

## Risks / Trade-offs

- **Risk:** A bug in `_snapshots_differ` could swallow a real change. → Mitigation: unit test that asserts a published snapshot for each of the three time-driven flip scenarios (stale at day 7, confidence ratchet from `low` to `medium` at day 30, summary recount on month rollover); plus a test that asserts no publish on a tick where nothing changed.
- **Risk:** `async_set_updated_data` from `_handle_source_update` skips the framework debouncer, so a burst of 70 simultaneous source events publishes 70 snapshots back-to-back. → Acceptance: that's still 1 recompute per event (was: 70 × 70 = 4 900 with `async_request_refresh` even *with* the debouncer eventually settling). Companion-entity dedupe at the HA state-machine level absorbs the rest. If this turns out to be a problem at scale we can wrap the publish in our own asyncio.Lock + small coalescing window, but it's not needed today.
- **Trade-off:** The heartbeat no longer publishes "I ran" — there's no observable signal that the coordinator is alive on idle systems. → Acceptable: the framework's `last_update_success`/`last_update_success_time` already exposes liveness for the framework path; for our explicit tick we accept silence as the success signal. If a diagnostic hook is needed later it can be added without spec change.
- **Trade-off:** Carrying forward unchanged `CoordinatorSnapshot` references means `record` mutations made in place between snapshots are visible in old snapshots too (since both reference the same `BatteryRecord`). → Already true today: `BatteryRecord` is mutable and shared. No regression.

## Migration Plan

In-place upgrade. No storage migration, no service or event signature changes, no entity-id changes.

- Pre-deploy: ensure full test suite passes.
- Deploy via HACS as v0.1.2; HA reloads the integration cleanly on update.
- Rollback: revert to v0.1.1 via HACS; the storage schema is unchanged (still version 1).
