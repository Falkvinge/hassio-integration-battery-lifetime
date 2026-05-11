## 1. Coordinator: defer cold-start backfill

- [ ] 1.1 Add `_pending_backfills: set[str]` instance attribute to `BatteryLifetimeCoordinator.__init__`.
- [ ] 1.2 Add `_run_backfill_with_tracking(record)` method that wraps `_attempt_cold_start_backfill` in a `try/finally`, discards `record.unique_id` from `_pending_backfills` in `finally`, and calls `_announce_backfill_complete()` if the set is now empty.
- [ ] 1.3 Add `_announce_backfill_complete()` method that calls `persistent_notification.async_create` with `notification_id="battery_lifetime_cold_start_complete"` and a short user-facing message.
- [ ] 1.4 In `_ensure_record`, replace the `await self._attempt_cold_start_backfill(record)` line with: add `unique_id` to `_pending_backfills`, then `self.hass.async_create_task(self._run_backfill_with_tracking(record), name=...)`.
- [ ] 1.5 Verify `_attempt_cold_start_backfill` already short-circuits when `record.replaced_on is not None` (existing behavior) so that races between background backfill and live detection do not double-commit.

## 2. UI strings

- [ ] 2.1 Replace the bold/all-caps freeze warning in `custom_components/battery_lifetime/strings.json` `config.step.user.description` with a calmer paragraph: setup completes immediately; background backfill of historical `replaced_on` may take several minutes for installs with many batteries; a notification appears when complete; per-battery opt-out via options.
- [ ] 2.2 Mirror the new text into `custom_components/battery_lifetime/translations/en.json`.

## 3. Tests

- [ ] 3.1 Add `test_setup_does_not_await_cold_start_backfill` in `tests/test_coordinator.py`: patch `_attempt_cold_start_backfill` to a coroutine that blocks on an `asyncio.Event`; assert `await coord.async_setup()` returns before the event is released; release the event and `await hass.async_block_till_done()` to drain the task; shut down cleanly.
- [ ] 3.2 Add `test_cold_start_completion_fires_notification`: set up coordinator with one eligible battery whose record has no `replaced_on`; let the (real) backfill run (returns None in tests because recorder isn't bootstrapped); `await hass.async_block_till_done()`; assert that a state with entity_id matching the persistent-notification pattern and the expected `notification_id` exists.
- [ ] 3.3 Add `test_no_pending_backfill_no_notification`: pre-populate `replaced_on` in the store for the only eligible battery; run setup; assert no `battery_lifetime_cold_start_complete` notification is created.

## 4. Release plumbing

- [ ] 4.1 Bump `custom_components/battery_lifetime/manifest.json` `version` to `0.1.3`.
- [ ] 4.2 Add `custom_components/battery_lifetime/brand/logo.png` (copy of `icon.png`) and `brand/logo@2x.png` (copy of `icon@2x.png`) for HA's brands-proxy logo asset slot.
- [ ] 4.3 Update `README.md` to reflect v0.1.3 (mention the non-blocking setup change and the completion notification under a "v0.1.3" subhead in whatever release-notes structure README uses).
- [ ] 4.4 Update `info.md` similarly so the HACS card shows the v0.1.3 change.
- [ ] 4.5 Run the full test suite: `.venv/bin/pytest tests/ -q`. Expect green: prior 112 tests + 3 new = 115 passed.

## 5. Close-out (executed from main checkout, not the worktree)

- [ ] 5.1 Commit implementation work in the agent worktree on branch `agent/defer-cold-start-backfill`.
- [ ] 5.2 Merge `agent/defer-cold-start-backfill` into `master` via the main checkout.
- [ ] 5.3 Push `master` to both `origin` (gitea) and `github`; push tag `v0.1.3` to both.
- [ ] 5.4 Create GitHub release `v0.1.3` via `gh release create` with release notes summarizing the non-blocking setup change and the brand-logo polish.
- [ ] 5.5 Archive the OpenSpec change: `openspec sync-specs defer-cold-start-backfill` (sync delta into `openspec/specs/coordinator-scheduling/spec.md`), then `mv openspec/changes/defer-cold-start-backfill openspec/changes/archive/YYYY-MM-DD-defer-cold-start-backfill`.
- [ ] 5.6 Remove the worktree and branch: `git worktree remove .worktree/defer-cold-start-backfill` and `git branch -d agent/defer-cold-start-backfill`.
- [ ] 5.7 Update `HANDOFF.md` to reflect v0.1.3 shipped and the freeze closed.
