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

### Requirement: Cold-start backfill is non-blocking

The coordinator's `async_setup` SHALL NOT await `_attempt_cold_start_backfill` for any record. When `_ensure_record` determines that a record needs cold-start backfill, it SHALL schedule the backfill via `hass.async_create_task` and return without awaiting it. `async_setup` SHALL therefore complete in time bounded by the entity-registry scan, independent of how many tracked batteries need cold-start backfill or how slow the recorder is.

#### Scenario: Setup returns before backfill completes
- **WHEN** the coordinator is set up against an HA instance with one or more eligible source batteries that need cold-start backfill, and `_attempt_cold_start_backfill` is patched to a coroutine that does not return until externally released
- **THEN** `await coordinator.async_setup()` completes (returns control to the caller) before the patched backfill coroutine has been allowed to return

#### Scenario: Setup completes regardless of recorder availability
- **WHEN** the coordinator is set up against an HA instance where the recorder is bootstrapped but slow (or not bootstrapped at all)
- **THEN** `await coordinator.async_setup()` completes within the time bounded by the entity-registry scan; no recorder query is on its await path

### Requirement: Backfill batch completion is announced exactly once

The coordinator SHALL track in-flight cold-start backfill work via an internal `_pending_backfills: set[str]` keyed by source `unique_id`. Each backfill task SHALL add its `unique_id` to the set before it starts and remove it from the set when it finishes (success, no-hit, or exception). When the set transitions from non-empty to empty, the coordinator SHALL fire exactly one `persistent_notification` with `notification_id="battery_lifetime_cold_start_complete"` informing the user that the initial cold-start backfill phase is done.

#### Scenario: First setup with one battery needing backfill fires the notification
- **WHEN** the coordinator is set up with one eligible source battery whose persisted record has no `replaced_on`, `_attempt_cold_start_backfill` runs to completion, and `hass.async_block_till_done()` is awaited
- **THEN** exactly one persistent notification with `notification_id="battery_lifetime_cold_start_complete"` exists in the HA state machine

#### Scenario: First setup with no batteries needing backfill fires no notification
- **WHEN** the coordinator is set up against an HA instance where every eligible source battery already has a `replaced_on` persisted in the store
- **THEN** no persistent notification with `notification_id="battery_lifetime_cold_start_complete"` is created

#### Scenario: Late-discovered battery extends the batch
- **WHEN** the coordinator's initial scan starts a backfill for battery A, and a new eligible source battery B is added via `entity_registry_updated` while A's backfill is still in flight
- **THEN** B's backfill task is added to `_pending_backfills` before A finishes, and the completion notification fires only after BOTH backfills have completed
