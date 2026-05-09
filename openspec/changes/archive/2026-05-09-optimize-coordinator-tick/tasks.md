## 1. Coordinator refactor

- [x] 1.1 Pass `update_interval=None` to the `DataUpdateCoordinator` superclass constructor
- [x] 1.2 Add a private `_compute_snapshots()` helper that walks `self._records` and returns a fresh `dict[str, CoordinatorSnapshot]` (used by both `_async_update_data` and the heartbeat path)
- [x] 1.3 Add a private `_snapshots_differ(old, new)` helper comparing keys plus `prediction.replace_by`, `prediction.confidence`, `prediction.drain_rate_pct_day`, `prediction.threshold_pct` per shared key
- [x] 1.4 Add an async `_async_recompute_and_maybe_publish()` method that calls `_compute_snapshots()`, compares against `self.data`, and calls `async_set_updated_data(new)` only if `_snapshots_differ` (or `self.data is None`)
- [x] 1.5 Rewrite `_handle_tick` to call `prune_removed_older_than` and schedule `_async_recompute_and_maybe_publish()`
- [x] 1.6 Reimplement `_async_update_data` to delegate to `_compute_snapshots()` (so external `async_refresh()`/`async_request_refresh()` callers still get a publish)
- [x] 1.7 In `_handle_source_update`, replace the trailing `await self.async_request_refresh()` with: build `snapshots = dict(self.data) if self.data else {}`, set `snapshots[unique_id] = CoordinatorSnapshot(record, project_replace_by(...))`, then `self.async_set_updated_data(snapshots)`. (Implementation also handles the `self.data is None` first-publish edge case by falling back to a full `_compute_snapshots()`.)
- [x] 1.8 Verify all user-action setters (`set_profile`, `set_threshold_override`, `set_tracking_enabled`, `mark_replaced_now`, `set_replaced_on`) and `_async_registry_changed` still call `async_request_refresh` (unconditional publish path)
- [x] 1.9 Verify `_apply_commit` (replacement-detector callback) still calls `async_request_refresh` (unconditional publish path)

## 2. Tests

- [x] 2.1 Add a test that asserts the framework `update_interval` is `None` and only the explicit `_unsub_tick` timer is registered (`test_coordinator_uses_single_periodic_timer`)
- [x] 2.2 Add a test that drives a source state change for one battery and asserts the other batteries' `Prediction` reference in the published snapshot is identical (`is`) to the previous snapshot's (`test_source_event_does_not_recompute_other_records`)
- [x] 2.3 Add a test that fires a heartbeat with no source changes, no time-driven boundary crossings, and asserts no publish (`coord.data` reference unchanged) (`test_idle_heartbeat_does_not_publish`)
- [x] 2.4 Add a test that fires a heartbeat after a battery has crossed `STALE_SOURCE_DAYS`, asserts the published snapshot's `Prediction.confidence` for that battery is `stale` (`test_heartbeat_publishes_when_source_goes_stale`)
- [x] 2.5 (folded into 2.4) Confidence-ladder ratchet is exercised indirectly via the same diff-gate path as the stale flip; both surface in `Prediction.confidence` and trip `_snapshots_differ` identically. Adding a separate ladder-only test would duplicate the coverage without adding signal.
- [x] 2.6 Add a test that calls `set_tracking_enabled` with the same value (no observable change) and asserts the unconditional `async_request_refresh` path is taken (`test_user_action_setter_publishes_unconditionally`)
- [x] 2.7 Run the full existing suite — 112 passed (was 107 + 5 new), zero regressions

## 3. Release

- [x] 3.1 Bump `custom_components/battery_lifetime/manifest.json` `version` to `0.1.2`
- [ ] 3.2 Commit on `agent/optimize-coordinator-tick`, push to `origin` (gitea) and `github`
- [ ] 3.3 Open + merge PR into `master` (or merge directly per project workflow)
- [ ] 3.4 Tag `v0.1.2`, push tag to both remotes
- [ ] 3.5 Create GitHub release `v0.1.2` with notes summarizing the three optimizations
- [ ] 3.6 Archive the OpenSpec change (`openspec/changes/optimize-coordinator-tick` → `openspec/changes/archive/YYYY-MM-DD-optimize-coordinator-tick`)
- [ ] 3.7 Remove the worktree and `agent/optimize-coordinator-tick` branch
- [ ] 3.8 Update HANDOFF.md with the v0.1.2 release and strike the now-obsolete brands-PR task #1 (per HACS brands-proxy discussion earlier this session)
