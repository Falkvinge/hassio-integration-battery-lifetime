## ADDED Requirements

### Requirement: Pruned sources have their companion device removed

When `BatteryLifetimeStore.prune_removed_older_than(REMOVED_SOURCE_RETENTION_DAYS)` returns a non-empty list of pruned source `unique_id`s, the coordinator SHALL look up the per-source companion device in HA's device registry by `identifiers={(DOMAIN, source_unique_id)}` and, if found, call `device_registry.async_remove_device(device.id)` for each pruned `unique_id`. HA's device-registry removal cascades to the entity registry and removes all entries tied to that device, which on the Battery Lifetime device card is exactly the eight per-source companion entries (`*_replace_by`, `*_prediction_quality`, `*_drain_rate`, `*_profile_lithium`, `*_tracking_enabled`, `*_mark_replaced`, `*_replaced_on`, `*_threshold_override`).

The cleanup SHALL run in both prune call sites:
- `_async_registry_changed` on `action: remove` (after the soft-delete + prune sweep).
- `_handle_tick` on every periodic heartbeat (after the prune sweep).

The cleanup SHALL be idempotent: looking up a device that does not exist (already manually removed, or never created because the source was removed before any platform forward completed) SHALL be a silent no-op.

The cleanup SHALL NOT run for soft-deleted entries that are still within their 30-day grace window. Those remain recoverable via `store.restore_battery`, and their companion devices and entities remain in the HA registry (showing `unavailable`) so that restore re-enables them without rebuilding the UI.

#### Scenario: Source pruned past the grace window has its device removed
- **WHEN** a source battery is removed from the entity registry, then enough time passes that its `removed_at` is older than `REMOVED_SOURCE_RETENTION_DAYS` (30 days), then the coordinator's heartbeat runs and `prune_removed_older_than` returns the source's `unique_id` in its drop list
- **THEN** the corresponding device entry with `identifiers={(DOMAIN, source_unique_id)}` is no longer present in HA's device registry, and the eight per-source companion entries are no longer present in HA's entity registry

#### Scenario: Source removed but still within grace window keeps its device
- **WHEN** a source battery is removed from the entity registry and the next heartbeat fires within the 30-day retention window
- **THEN** the prune returns an empty list for this source, the device entry remains in the registry, the eight companion entries remain in the registry showing `unavailable`, and a subsequent `store.restore_battery(unique_id)` call (e.g. because the source reappeared) re-enables the entities without rebuilding them

#### Scenario: Purge of a source whose device was already manually removed is a no-op
- **WHEN** `prune_removed_older_than` returns a `unique_id` for which the user has already manually deleted the companion device via the HA UI
- **THEN** `device_registry.async_get_device(identifiers={(DOMAIN, source_unique_id)})` returns `None`, the purge step is a silent no-op for that source, and no error is logged
