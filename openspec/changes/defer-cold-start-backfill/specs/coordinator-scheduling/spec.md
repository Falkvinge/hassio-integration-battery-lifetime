## ADDED Requirements

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
