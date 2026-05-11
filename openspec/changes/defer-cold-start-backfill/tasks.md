## 1. Coordinator: defer cold-start backfill

- [x] 1.1 Add `_pending_backfills: set[str]` instance attribute to `BatteryLifetimeCoordinator.__init__`.
- [x] 1.2 Add `_run_backfill_with_tracking(record)` method that wraps `_attempt_cold_start_backfill` in a `try/finally`, discards `record.unique_id` from `_pending_backfills` in `finally`, and calls `_announce_backfill_complete()` if the set is now empty.
- [x] 1.3 Add `_announce_backfill_complete()` method that calls `persistent_notification.async_create` with `notification_id="battery_lifetime_cold_start_complete"` and a short user-facing message.
- [x] 1.4 In `_ensure_record`, replace the `await self._attempt_cold_start_backfill(record)` line with: gate on `record.replaced_on is None`, add `unique_id` to `_pending_backfills`, then `self.hass.async_create_task(self._run_backfill_with_tracking(record), name=...)`. (Tightened from spec: also gates on `replaced_on is None` so the wrapper isn't scheduled — and the completion notification doesn't fire — when the record already has a persisted replaced_on.)
- [x] 1.5 Verified `_attempt_cold_start_backfill` already short-circuits when `record.replaced_on is not None`; race with live detection is therefore safe.

## 2. UI strings

- [x] 2.1 Replaced the bold/all-caps freeze warning in `custom_components/battery_lifetime/strings.json` with a calmer paragraph.
- [x] 2.2 Mirrored the new text into `custom_components/battery_lifetime/translations/en.json`.

## 3. Tests

- [x] 3.1 Added `test_setup_does_not_await_cold_start_backfill` — uses `patch.object(coord, "_attempt_cold_start_backfill", side_effect=_slow_backfill)` with an `asyncio.Event` gate. Confirms `coord._pending_backfills` contains the unique_id immediately after `await coord.async_setup()` returns and before the event is released.
- [x] 3.2 Added `test_cold_start_completion_fires_notification` — uses `_async_get_or_create_notifications(hass)` to read the persistent-notification dict directly. With recorder not bootstrapped in tests, the real backfill returns None instantly, then the wrapper drains `_pending_backfills` and fires the notification.
- [x] 3.3 Added `test_no_pending_backfill_no_notification` — pre-populates `replaced_on` via `store.upsert_battery("uid-foo", replaced_on=...)`. Asserts the wrapper is never scheduled and no notification is fired.

## 4. Release plumbing

- [x] 4.1 Bumped `manifest.json` `version` to `0.1.3`.
- [x] 4.2 Added `brand/logo.png` (copy of `icon.png`, 29776 B) and `brand/logo@2x.png` (copy of `icon@2x.png`, 97771 B).
- [x] 4.3 README "Cold start" section now mentions the background-backfill behaviour and the completion notification. (README has no per-version changelog section; release notes live on the GitHub release page, matching v0.1.2's pattern.)
- [x] 4.4 `info.md` left unchanged. It contains a generic feature description with no per-version notes; the cold-start defer doesn't change what the integration *does*, only when. (Same call as v0.1.2.)
- [x] 4.5 Full test suite green: 115 passed (prior 112 + 3 new).

## 5. Close-out (executed from main checkout, not the worktree)

- [x] 5.1 Committed implementation on `agent/defer-cold-start-backfill` (commit 006771a).
- [ ] 5.2 Merge `agent/defer-cold-start-backfill` into `master` via the main checkout (`git merge --no-ff`).
- [ ] 5.3 Push `master` to both `origin` (gitea) and `github`; push tag `v0.1.3` to both.
- [ ] 5.4 Create GitHub release `v0.1.3` via `gh release create` with release notes summarizing the non-blocking setup change and the brand-logo polish.
- [ ] 5.5 Archive the OpenSpec change: `openspec sync-specs defer-cold-start-backfill` (sync delta into `openspec/specs/coordinator-scheduling/spec.md`), then `mv openspec/changes/defer-cold-start-backfill openspec/changes/archive/YYYY-MM-DD-defer-cold-start-backfill`.
- [ ] 5.6 Remove the worktree and branch: `git worktree remove .worktree/defer-cold-start-backfill` and `git branch -d agent/defer-cold-start-backfill`.
- [ ] 5.7 Update `HANDOFF.md` to reflect v0.1.3 shipped and the freeze closed.
