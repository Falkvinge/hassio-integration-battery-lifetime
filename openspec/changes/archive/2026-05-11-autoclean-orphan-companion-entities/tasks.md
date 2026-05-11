## 1. Coordinator: purge orphan companion devices on prune

- [x] 1.1 Imported `device_registry as dr` in `coordinator.py`.
- [x] 1.2 Added `_purge_companions_for_pruned(self, unique_ids: list[str]) -> None`. Idempotent on missing device; logs at info level when a device is actually removed.
- [x] 1.3 Captured the return value of `prune_removed_older_than` in `_async_registry_changed` and fed it to the purge.
- [x] 1.4 Same in `_handle_tick`.

## 2. Tests

- [x] 2.1 `test_purge_companions_for_pruned_removes_device` — uses `MockConfigEntry` to satisfy `device_registry.async_get_or_create`'s `config_entry_id` requirement; pre-creates the device, calls the purge, asserts gone.
- [x] 2.2 `test_purge_companions_for_pruned_is_noop_for_missing_device` — calls with a never-existed unique_id and with `[]`. No exception, no notification.
- [x] 2.3 `test_remove_event_chain_purges_after_grace_window` — full chain. Forges `removed_at` directly via `store._data["batteries"]["uid-foo"]["removed_at"] = time.time() - (REMOVED_SOURCE_RETENTION_DAYS + 1) * 86400` to fast-forward the 30-day clock without monkey-patching `time.time`. Drives `_handle_tick` to trigger prune+purge. Asserts both store entry and device entry gone.

## 3. Release plumbing

- [x] 3.1 Bumped `manifest.json` `version` to `0.1.4`.
- [x] 3.2 Added "When a battery disappears" section to `README.md` documenting the soft-delete + 30-day restore window + auto-purge lifecycle.
- [x] 3.3 Full test suite green: 118 passed (115 prior + 3 new).

## 4. Close-out (executed from main checkout, not the worktree)

- [x] 4.1 Committed implementation on `agent/autoclean-orphan-companion-entities` (commit 13b3dd6).
- [ ] 4.2 Merge `agent/autoclean-orphan-companion-entities` into `master` via the main checkout (`git merge --no-ff`).
- [ ] 4.3 Push `master` to both `origin` (gitea) and `github`; push tag `v0.1.4` to both.
- [ ] 4.4 Create GitHub release `v0.1.4` via `gh release create`.
- [ ] 4.5 Sync the delta into `openspec/specs/coordinator-scheduling/spec.md` and archive the change.
- [ ] 4.6 Remove the worktree and branch.
- [ ] 4.7 Update `HANDOFF.md` to reflect v0.1.4 shipped.
