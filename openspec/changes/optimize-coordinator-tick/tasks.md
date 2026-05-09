## 1. Coordinator refactor

- [ ] 1.1 Pass `update_interval=None` to the `DataUpdateCoordinator` superclass constructor
- [ ] 1.2 Add a private `_compute_snapshots()` helper that walks `self._records` and returns a fresh `dict[str, CoordinatorSnapshot]` (used by both `_async_update_data` and the heartbeat path)
- [ ] 1.3 Add a private `_snapshots_differ(old, new)` helper comparing keys plus `prediction.replace_by`, `prediction.confidence`, `prediction.drain_rate_pct_day`, `prediction.threshold_pct` per shared key
- [ ] 1.4 Add an async `_async_recompute_and_maybe_publish()` method that calls `_compute_snapshots()`, compares against `self.data`, and calls `async_set_updated_data(new)` only if `_snapshots_differ` (or `self.data is None`)
- [ ] 1.5 Rewrite `_handle_tick` to call `prune_removed_older_than` and schedule `_async_recompute_and_maybe_publish()`
- [ ] 1.6 Reimplement `_async_update_data` to delegate to `_compute_snapshots()` (so external `async_refresh()`/`async_request_refresh()` callers still get a publish)
- [ ] 1.7 In `_handle_source_update`, replace the trailing `await self.async_request_refresh()` with: build `snapshots = dict(self.data) if self.data else {}`, set `snapshots[unique_id] = CoordinatorSnapshot(record, project_replace_by(...))`, then `self.async_set_updated_data(snapshots)`
- [ ] 1.8 Verify all user-action setters (`set_profile`, `set_threshold_override`, `set_tracking_enabled`, `mark_replaced_now`, `set_replaced_on`) and `_async_registry_changed` still call `async_request_refresh` (unconditional publish path)
- [ ] 1.9 Verify `_apply_commit` (replacement-detector callback) still calls `async_request_refresh` (unconditional publish path)

## 2. Tests

- [ ] 2.1 Add a test that asserts only one heartbeat fires per `UPDATE_INTERVAL_SECONDS` window (e.g. by counting `async_set_updated_data` calls or `_compute_snapshots` invocations across a simulated interval)
- [ ] 2.2 Add a test that drives a source state change for one battery and asserts `Prediction` is recomputed for that battery only, while the other batteries' `Prediction` references in the published snapshot are identical (`is`) to the previous snapshot's
- [ ] 2.3 Add a test that fires a heartbeat with no source changes, no time-driven boundary crossings, and asserts no publish (`async_set_updated_data` not called, listener notification count unchanged)
- [ ] 2.4 Add a test that fires a heartbeat after a battery has crossed `STALE_SOURCE_DAYS` (advancing virtual time), asserts the published snapshot's `Prediction.confidence` for that battery is `stale`
- [ ] 2.5 Add a test that fires a heartbeat after a battery has crossed `CONFIDENCE_MEDIUM_DAYS` with sufficient simulated drain, asserts the published snapshot's `Prediction.confidence` advances from `low` to `medium`
- [ ] 2.6 Add a test that calls a user-action setter (e.g. `set_tracking_enabled` toggle) when no `Prediction` field would change and asserts the publish still happens
- [ ] 2.7 Run the full existing suite (`.venv/bin/pytest tests/ -q`) and confirm zero regressions

## 3. Release

- [ ] 3.1 Bump `custom_components/battery_lifetime/manifest.json` `version` to `0.1.2`
- [ ] 3.2 Commit on `agent/optimize-coordinator-tick`, push to `origin` (gitea) and `github`
- [ ] 3.3 Open + merge PR into `master` (or merge directly per project workflow)
- [ ] 3.4 Tag `v0.1.2`, push tag to both remotes
- [ ] 3.5 Create GitHub release `v0.1.2` with notes summarizing the three optimizations
- [ ] 3.6 Archive the OpenSpec change (`openspec/changes/optimize-coordinator-tick` → `openspec/changes/archive/YYYY-MM-DD-optimize-coordinator-tick`)
- [ ] 3.7 Remove the worktree and `agent/optimize-coordinator-tick` branch
- [ ] 3.8 Update HANDOFF.md with the v0.1.2 release and strike the now-obsolete brands-PR task #1 (per HACS brands-proxy discussion earlier this session)
