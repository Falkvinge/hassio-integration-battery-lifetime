# coordinator-scheduling

## Purpose

Defines the internal contract for when the Battery Lifetime coordinator recomputes records, when it publishes snapshots to listeners, and which trigger paths are O(1) vs O(N). The contract distinguishes the periodic heartbeat (diff-gated) from per-source-event updates (single-record) from user-action / detector / registry callbacks (unconditional publish).

## Requirements

### Requirement: Single 10-minute heartbeat

The coordinator SHALL drive its periodic recompute from exactly one timer at the configured `UPDATE_INTERVAL_SECONDS` cadence (default 600 seconds). The `DataUpdateCoordinator.update_interval` framework parameter SHALL NOT be set in addition to the explicit `async_track_time_interval` tick.

#### Scenario: One timer, not two
- **WHEN** the integration is set up against a Home Assistant instance
- **THEN** exactly one periodic recompute fires per `UPDATE_INTERVAL_SECONDS` window — i.e. the coordinator does not call `_async_update_data` twice per interval out of phase

### Requirement: Per-source-event O(1) update

The coordinator SHALL update only the affected record when a single source `state_changed` event arrives, leaving all other records' `Prediction` instances unchanged in the published snapshot dict. The publish path for source-event updates SHALL be `async_set_updated_data`, not `async_request_refresh`.

#### Scenario: One source change updates one record
- **WHEN** a tracked battery's source sensor publishes a new percentage value (e.g. `82.0` → `81.0`) and no other source changes
- **THEN** the coordinator computes a fresh `Prediction` for that battery only, leaves every other record's `Prediction` reference unchanged in the published snapshot, and emits exactly one snapshot to listeners

#### Scenario: Burst of source changes does not multiply work
- **WHEN** N tracked batteries each publish a single new reading inside one debounce window
- **THEN** the coordinator computes exactly N fresh `Prediction` instances total (one per changed record), not N × N

### Requirement: Diff-gated heartbeat publish

On each periodic heartbeat the coordinator SHALL recompute every record's `Prediction`, compare the result against the currently published snapshot, and call `async_set_updated_data` only if at least one record's `Prediction.replace_by`, `Prediction.confidence`, `Prediction.drain_rate_pct_day`, or `Prediction.threshold_pct` differs, or if the set of tracked record keys differs.

#### Scenario: Idle heartbeat publishes nothing
- **WHEN** a heartbeat fires and every record's recomputed `Prediction` matches the four observable fields of its previously published `Prediction`, and the set of tracked records is unchanged
- **THEN** the coordinator does NOT call `async_set_updated_data`, no `CoordinatorEntity` listener is notified, and no entity-state change is written to Home Assistant's state machine

#### Scenario: Stale flip publishes
- **WHEN** a tracked battery's source has produced no update for `STALE_SOURCE_DAYS` (7) days and the next heartbeat fires
- **THEN** that battery's recomputed `Prediction.confidence` becomes `stale`, the coordinator detects the change, and publishes a new snapshot

#### Scenario: Confidence-ladder ratchet publishes
- **WHEN** a tracked battery has crossed the `CONFIDENCE_MEDIUM_DAYS` (30) boundary with sufficient observed drain since the previous heartbeat and no new source reading has arrived
- **THEN** that battery's recomputed `Prediction.confidence` advances from `low` to `medium`, the coordinator detects the change, and publishes a new snapshot

#### Scenario: User-action setters bypass the diff gate
- **WHEN** a user toggles `switch.<src>_profile_lithium`, presses `button.<src>_mark_replaced`, edits `date.<src>_replaced_on`, sets `number.<src>_threshold_override`, or toggles `switch.<src>_tracking_enabled`
- **THEN** the coordinator publishes a fresh snapshot unconditionally, even if the four observable `Prediction` fields happen to be unchanged
