## Context

The Battery Lifetime coordinator's `async_setup` currently hydrates state from the store, registers two HA event listeners and a periodic timer, then calls `_scan_initial_entities`. The scan iterates every eligible source entity (via `iter_eligible_entities`) and `await`s `_ensure_record(entry)` per entity. Inside `_ensure_record`, when a record is new (or persisted state has no `replaced_on`), the code awaits `_attempt_cold_start_backfill(record)`, which awaits `ColdStartBackfiller.find_most_recent_jump`, which dispatches one `recorder.async_add_executor_job` for the LTS query (5-year lookback, hourly stats) and, if that miss, a second one for the recorder-history query (60-day lookback). Home Assistant's recorder runs on a single worker thread (`_RecorderPool` defaults to one writer to keep SQLite serialized), so all per-battery queries serialize behind whatever else the recorder is doing during HA startup.

For the user's live install (70 batteries × ~2 queries = ~140 serialized executor jobs), this turns config-entry setup into a multi-minute blocking operation. v0.1.1 papered over the symptom with a bold/all-caps "this will freeze" warning in the config dialog. v0.1.2 optimized the heartbeat path but did not touch this codepath. The freeze remains in v0.1.2.

The HANDOFF document lists three candidate mitigations: (1) defer cold-start to a background task; (2) batch recorder queries across entities; (3) defer to the first scheduled coordinator tick (10 minutes out). Option (3) hides the backfill for ten minutes after install, which is poor UX. Option (2) requires a meaningful refactor of `find_most_recent_jump` and the `_scan_for_jump` helper, plus careful attention to LTS API shapes — out of scope for a small follow-up release. Option (1) is the smallest viable fix that fully removes the freeze.

## Goals / Non-Goals

**Goals:**
- `async_setup` returns within a small constant time (sub-second on a typical install) regardless of how many batteries are tracked.
- Cold-start backfill semantics (LTS-then-recorder fallback, qualifying-jump rules, event payload, persisted `replaced_on`) are unchanged from v0.1.2.
- The user has visibility into when the initial backfill batch has completed: a single persistent notification fires when the last in-flight initial backfill task finishes.
- The config-dialog warning text is updated to match the new behavior — accurate, not alarming.

**Non-Goals:**
- Speeding up cold-start backfill itself. Total backfill duration is governed by the recorder thread; the change does not parallelize across batteries.
- Adding per-battery progress UI. One terminal "complete" notification is enough to confirm the phase finished.
- Changing the heartbeat (10-minute) timer or its diff-gated publish. The v0.1.2 contract in `coordinator-scheduling/spec.md` is unchanged.
- Persisting backfill progress across HA restarts. If HA restarts mid-backfill, the next start re-attempts backfill for any record without `replaced_on` (current behavior). This is fine because backfill is idempotent and cheap to re-attempt.

## Decisions

### Decision 1: Per-record fire-and-forget via `hass.async_create_task`

**Choice**: In `_ensure_record`, replace `await self._attempt_cold_start_backfill(record)` with `self.hass.async_create_task(self._run_backfill_with_tracking(record))`. The `_ensure_record` method still completes synchronously w.r.t. the source entity's first reading and the `_known_entities` bookkeeping; only the recorder-touching backfill becomes background work.

**Alternatives considered**:
- *Single batched runner*: collect pending `unique_id`s during the scan, schedule one background coroutine via `async_call_later(hass, 0, ...)` that processes them sequentially. Pro: explicit "starting backfill for N batteries" log line. Con: adds ~30 lines, requires its own state machine, and the per-battery serialization on the recorder thread happens either way. Rejected as over-engineered.
- *Defer to first heartbeat*: skip backfill in `_ensure_record` entirely, run pending backfills inside the first `_handle_tick`. Pro: zero new code in setup path. Con: user waits 10 minutes after install before any historical `replaced_on` populates — visibly worse UX. Rejected.

### Decision 2: Track in-flight backfills via a simple `set[str]`

**Choice**: Add `self._pending_backfills: set[str]` to the coordinator. `_ensure_record` adds the `unique_id` to the set before scheduling the task. The wrapper `_run_backfill_with_tracking(record)` runs the actual backfill in a `try/finally`, and the `finally` discards the `unique_id` and — if the set is now empty — calls `_announce_backfill_complete()`.

**Alternatives considered**:
- *No tracking, no notification*: simplest possible diff. Rejected because the user explicitly asked for a way to know when initial population finishes; without it, a quiet HA install gives no feedback that backfill ran at all.
- *Per-battery progress notification*: one notification per backfill completion. Rejected — for 70 batteries that's 70 notifications spamming the persistent-notification panel.
- *Counter + condvar / event*: use `asyncio.Event` set when the count reaches zero. Rejected — a `set[str]` is no harder to reason about, and inspecting which `unique_id`s are still pending is useful for debugging via `repr(coord._pending_backfills)`.

### Decision 3: Notification only when at least one backfill ran

**Choice**: `_run_backfill_with_tracking` is the only place that adds to `_pending_backfills` and the only place that announces completion. If no batteries need backfill (e.g. all records have `replaced_on` from the store, or the integration has no eligible source entities), the set never gets a member and the notification never fires. The notification is informational about a phase that did happen, not a "setup complete" beacon.

**Alternatives considered**:
- *Always fire notification at end of `async_setup`*: would notify even on uneventful starts. Rejected as noise.

### Decision 4: Notification uses `persistent_notification` domain, not the integration's domain

**Choice**: Call `persistent_notification.async_create(hass, message, title, notification_id)` with `notification_id="battery_lifetime_cold_start_complete"`. This matches the established pattern in `detection.py` (stale-prior notifications use the same helper) and makes the notification dismissible from the UI.

### Decision 5: Updated dialog text omits the all-caps freeze warning entirely

**Choice**: Replace the v0.1.1 dialog text with a calmer paragraph that mentions: (a) auto-discovery and ~8 entities per battery; (b) setup completes immediately; (c) background backfill of historical `replaced_on` may take several minutes for installs with many batteries; (d) a notification appears when backfill finishes; (e) per-battery opt-out via options. The all-caps "DON'T RELOAD, DON'T CANCEL" sentence is no longer applicable and is removed.

## Risks / Trade-offs

- **Risk**: A new source entity is discovered via `entity_registry_updated` *during* the initial backfill batch. Its backfill task is added to `_pending_backfills` and the completion notification waits for it too. → Mitigation: this is the desired behavior. The "complete" notification means "all initial-and-runtime-discovered backfills queued so far are done." Subsequent late additions extend the phase.
- **Risk**: HA shutdown during background backfill. The `async_create_task`-scheduled coroutine may be cancelled mid-flight, leaving `_pending_backfills` non-empty. → Mitigation: `async_shutdown` does not await pending backfills or fire the completion notification. On the next start, `_attempt_cold_start_backfill` re-runs for any record still missing `replaced_on` — idempotent, no state corruption.
- **Risk**: A live source-state event arrives mid-backfill and commits a fresh replacement via the live detector before backfill finishes for the same battery. → Mitigation: `_attempt_cold_start_backfill` checks `if record.replaced_on is not None: return` early, so the live commit wins (correctly — live evidence is stronger than historical inference).
- **Trade-off**: The user no longer sees a synchronous "setup is taking N minutes" in the UI; instead they see a fast Submit and then a delayed notification. Acceptable: the dialog text now sets that expectation.

## Migration Plan

No migration required. Persistent state in `.storage/battery_lifetime` is unchanged. On the first start after upgrading from v0.1.2 to v0.1.3, the user sees the new dialog text only if they re-add the integration (existing entries already in the registry skip the user step). Existing in-place upgrades just see the faster setup and the new notification. Rollback is simply downgrading via HACS.

## Open Questions

None. The design space was bounded by "smallest fix that removes the freeze" plus the user-requested completion-notification UX.
