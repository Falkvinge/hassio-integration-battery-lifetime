## Why

When a tracked battery's source entity is removed from Home Assistant (device deleted, integration uninstalled, Z2M un-paired), the coordinator soft-deletes the JSON-store entry and the in-memory `BatteryRecord`, and after `REMOVED_SOURCE_RETENTION_DAYS = 30` the JSON entry is hard-deleted by `BatteryLifetimeStore.prune_removed_older_than`. But the eight HA entity-registry entries for the per-source companion entities (`sensor.<src>_replace_by`, `..._prediction_quality`, `..._drain_rate`, `switch.<src>_profile_lithium`, `..._tracking_enabled`, `button.<src>_mark_replaced`, `date.<src>_replaced_on`, `number.<src>_threshold_override`) plus the per-source companion device entry (`identifiers={(DOMAIN, source_unique_id)}`) are never removed. They stay in HA's registry indefinitely as `unavailable` orphans, and the user has to garbage-collect them manually via Settings → Devices & Services.

This is the moment where "the integration knows the source is gone for good" actually arrives — `prune_removed_older_than` returns the list of `unique_id`s it just dropped from the store. Cleaning up the corresponding companion device at that point is cheap, well-bounded, and matches user expectation.

## What Changes

- The coordinator SHALL purge each pruned source's companion device from Home Assistant's device registry whenever `prune_removed_older_than` returns a non-empty list. Removing the device is sufficient: HA's device-registry removal cascades to all entity-registry entries tied to that device, which on the Battery Lifetime device card means exactly the eight per-source companion entries.
- The two existing call sites that drive prune (`_async_registry_changed` on `action: remove`, and `_handle_tick` on every 10-minute heartbeat) SHALL feed the pruned list into the new purge step. No new call sites; no change to prune timing or the 30-day retention window.

Out of scope: legacy orphans accumulated before v0.1.4 are not retroactively cleaned up. Their JSON-store entries are already gone (so the new purge has no `unique_id` to act on), but their HA registry entries linger. Users can either delete them manually via the UI today, or wait for a future explicit "cleanup pre-existing orphans" pass if this becomes a real pain point. Not adding it now to keep the diff focused on the user's request.

## Capabilities

### New Capabilities

(none)

### Modified Capabilities

- `coordinator-scheduling`: adds a "Pruned sources have their companion device removed" requirement governing the cleanup step that runs after every prune.

## Impact

- `custom_components/battery_lifetime/coordinator.py`: add `_purge_companions_for_pruned(unique_ids)` helper; update both prune call sites to capture the return value and pass it to the purge.
- `custom_components/battery_lifetime/manifest.json`: version bump to `0.1.4`.
- `tests/test_coordinator.py`: two new tests — one direct on the purge helper, one end-to-end driving through a registry-remove + forced-old prune.
- `README.md`: short note in the existing removal/restore narrative (or a "v0.1.4 cleanup" sentence in the cold-start section, depending on what reads cleanest).
- No new runtime dependencies. No schema migration. No public service or event payload changes. No breaking changes for existing installs.
