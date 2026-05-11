## Context

Each tracked battery is represented in HA by a per-source companion device whose identifier tuple is `(DOMAIN, source_unique_id)`. The eight companion entities (replace-by sensor, prediction-quality sensor, drain-rate sensor, two switches, button, date, number) all attach to that device via their `device_info` returned from `BatteryCompanionEntity.device_info`. When the source disappears, `_async_registry_changed`'s `action: remove` branch:

1. Pops `entity_id → unique_id` from `self._source_to_unique`.
2. Soft-deletes the JSON-store entry (`store.remove_battery(unique_id)` stamps `removed_at = time.time()`; the rest of the persisted state — `replaced_on`, profile, threshold override, EWMA state — is retained against possible restore within 30 days).
3. Pops the in-memory `BatteryRecord` from `self._records`. The companion entities' `available` property flips to `False` because `record` becomes `None`, so the eight entities show as `unavailable` in the UI immediately.
4. Calls `prune_removed_older_than(REMOVED_SOURCE_RETENTION_DAYS)` to garbage-collect any *other* soft-deleted entries whose `removed_at` is older than 30 days.

The same `prune_removed_older_than` call also runs on every 10-minute heartbeat tick (`_handle_tick`), so the prune is in fact reasonably continuous — within ten minutes of crossing the 30-day threshold for any soft-deleted entry, the JSON store is cleaned up.

What's missing today: at the moment the JSON store actually drops a `unique_id`, the corresponding companion device + its eight entity-registry entries remain in HA's registry forever. They're orphan rows that the user must manually delete via Settings → Devices & Services → device card → ⋮ → Delete. Over a long-lived install with periodic battery-device churn (Z2M re-pairs, integration churn, sensor renames that change `unique_id`), this accumulates.

## Goals / Non-Goals

**Goals:**
- When `prune_removed_older_than` actually removes a `unique_id` from the JSON store, the matching HA device entry (`identifiers={(DOMAIN, source_unique_id)}`) and all its child entity-registry entries are removed from the HA registry in the same code path.
- The cleanup runs in both the on-remove-event path (`_async_registry_changed`) and the heartbeat path (`_handle_tick`), so cleanup happens as soon as the prune itself fires, regardless of which path triggered it.
- The cleanup is idempotent: if the device is already gone (manually deleted, race with another integration, never created in the first place), the purge step is a no-op rather than an error.

**Non-Goals:**
- Cleaning up legacy orphans accumulated before v0.1.4. Their JSON-store entries are already long pruned, so the new purge — which is keyed by the prune's return value — has nothing to act on for them. A separate one-shot "scan registry for our companion device entries with no matching JSON-store source" pass would be needed; deferred until/unless asked for.
- Changing the 30-day retention window or the prune cadence. Those are governed by `REMOVED_SOURCE_RETENTION_DAYS` and `_handle_tick`'s timer respectively and are unaffected.
- Direct entity-registry walks. HA's device-registry removal cascades the entity removals for us (see Decision 2).

## Decisions

### Decision 1: Purge by device, not by entity prefix

**Choice**: At purge time, look up the per-source companion device via `device_registry.async_get_device(identifiers={(DOMAIN, source_unique_id)})`. If found, call `device_registry.async_remove_device(device.id)`. HA's device-registry removal cascades to the entity registry, which removes all entity entries tied to that device. Since the Battery Lifetime device card is exclusively owned by this integration's eight companion entities (the source battery has its *own* device, separate from ours), the cascade removes exactly what we want.

**Alternatives considered**:
- *Walk entity registry, match by `unique_id` prefix `battery_lifetime:<source_uid>:`*: works but is O(N entities) per purge and duplicates the device-registry's cascade machinery. We'd still need to clean up the device entry separately to avoid an empty-card orphan. Rejected as more code for less cleanup.
- *Iterate the eight known suffixes and look up by exact companion `unique_id`*: brittle to suffix additions/renames. Rejected.

### Decision 2: Trust HA's device-removal cascade rather than walking the entity registry

**Choice**: After `async_remove_device(device_id)`, do not separately walk the entity registry to confirm the entries are gone. HA fires `device_registry_updated` (with `action: remove`) on device removal, and the entity registry has its own listener that removes child entities. This is HA-core behavior and is relied upon by every standard integration.

**Alternative considered**: belt-and-braces walk after the device removal. Rejected — adds code for no real benefit, and would mask if HA ever changed the cascade behavior (which would be a regression we'd want to surface, not paper over).

### Decision 3: Purge only after a successful prune, never speculatively

**Choice**: The purge is keyed off `prune_removed_older_than`'s return value (the list of `unique_id`s it actually dropped). Soft-deleted entries within their grace window are never touched. An entry that's still in the store but has `removed_at != None` is recoverable (via `store.restore_battery`) and its companion device + entities are still intact (they're just `unavailable`); restoring within the window resurrects the user's previous configuration with no UI rebuild needed.

This means: the new behavior is invisible until the 30-day grace window elapses for some real source. For the user's live install, no immediate UI change after the v0.1.4 upgrade.

## Risks / Trade-offs

- **Risk**: A user has manually deleted the device entry already (e.g. cleaned up an orphan via the UI yesterday) but the corresponding store entry hasn't yet been pruned. → Mitigation: `async_get_device` returns `None`, the purge step is a no-op for that source. No error, no warning needed.
- **Risk**: A user has manually re-added entities to our device card (e.g. via customize, or an automation that pinned an entity to our device). On purge, those would also be cascaded out. → Mitigation: practically impossible — HA's customize doesn't let you reparent entities to arbitrary devices, and our device identifiers are a tuple opaque to other integrations. If someone has truly done this, they can re-add post-purge; this risk is theoretical.
- **Risk**: HA removes the device-removal cascade or changes its semantics. → Mitigation: covered by tests; would surface as a regression rather than silent dust accumulation.
- **Trade-off**: Pre-existing orphans (sources removed before v0.1.4) are not cleaned up by this change. Acceptable because: (a) the user's current install only has them if some battery has actually been deleted in the past — observable, finite, and manually fixable; (b) bolting on a one-shot legacy scanner risks racing with the brand-new install's own platform-forward setup; (c) keeping this change small makes it easy to review and easy to ship.

## Migration Plan

No migration required. Persistent state in `.storage/battery_lifetime` is unchanged. After in-place upgrade via HACS, any source whose grace window expires (now or in the future) gets its companion device + entities cleaned up automatically. No user action needed.

## Open Questions

None.
