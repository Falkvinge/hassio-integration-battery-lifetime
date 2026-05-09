## Why

`BatteryLifetimeCoordinator` currently does redundant and overly broad work on every refresh, costing extra entity-state writes and (at scale) recorder churn:

1. The coordinator runs `_async_update_data` twice every 10 minutes — once via the `DataUpdateCoordinator`'s built-in `update_interval`, once via a separate `async_track_time_interval(_handle_tick, 600s)` that calls `async_request_refresh`. The two timers do the same work out of phase.
2. Every source `state_changed` event triggers a full O(N) recalc of every tracked battery's `Prediction`, even though only the one battery that fired the event has new data.
3. Every 10-minute heartbeat unconditionally pushes a fresh snapshot to all `CoordinatorEntity` listeners (8 companion entities × N batteries + 2 summary sensors), forcing recomputation downstream and recorder writes, even on idle systems where no record's `Prediction` actually changed.

For the user's 70-battery / 554-entity install this is harmless today; at 1 000+ batteries the entity fan-out and recorder pressure become the dominant cost. The math itself is cheap.

## What Changes

- Drop the redundant 10-minute timer: keep the explicit `async_track_time_interval` tick (it owns `prune_removed_older_than` as a side effect) and remove `update_interval` from the `DataUpdateCoordinator` constructor.
- Convert per-source-event refreshes from O(N) full recalc to O(1) single-record update via `async_set_updated_data` on a shallow-copied snapshot dict with only the changed entry replaced.
- Make the heartbeat diff-gated: walk all records, compute a fresh `Prediction` per record, and only call `async_set_updated_data` if at least one record's externally-observable snapshot fields (`Prediction.replace_by`, `Prediction.confidence`, `Prediction.drain_rate_pct_day`, `Prediction.threshold_pct`) changed against the previous snapshot. On idle systems where nothing time-driven crossed a boundary, the heartbeat becomes a no-op.

The heartbeat is intentionally *not* gated on "source value changed". Three time-driven flips happen with no source change: stale flip at 7 days, confidence-ladder ratchet at 7/30/60-day boundaries, and summary-sensor month/quarter cutoff transitions. All three surface in `Prediction`, so a `Prediction`-diff gate preserves them while suppressing no-op pushes.

## Capabilities

### New Capabilities
- `coordinator-scheduling`: Internal contract for when the coordinator recomputes records, when it publishes snapshots to listeners, and which trigger paths are O(1) vs O(N). Captures the diff-gated heartbeat and the per-source-event single-record update introduced in this change as testable requirements.

### Modified Capabilities
- (none — no requirements in the existing `lifetime-prediction`, `replacement-detection`, `forward-prediction`, `battery-discovery`, or `battery-configuration` capabilities change. The new `coordinator-scheduling` spec sits alongside them and documents the scheduling contract that those specs implicitly relied on.)

## Impact

- **Code**: `custom_components/battery_lifetime/coordinator.py` (constructor, `async_setup`, `_handle_state_changed`, `_handle_source_update`, `_handle_tick`, `_async_update_data`).
- **Tests**: `tests/test_coordinator.py` (or equivalent) — add cases for single-record update, diff-gated heartbeat skip, and verify the three time-driven flips still publish.
- **Manifest**: `custom_components/battery_lifetime/manifest.json` version bump to `0.1.2`.
- **Public API / spec**: unchanged. No new entities, services, events, or storage-schema changes.
- **HACS / install**: drop-in replacement; users get the optimization on next HACS update with no configuration steps.
