## 1. Coordinator: purge orphan companion devices on prune

- [ ] 1.1 Import `device_registry as dr` in `custom_components/battery_lifetime/coordinator.py`.
- [ ] 1.2 Add `_purge_companions_for_pruned(self, unique_ids: list[str]) -> None`. For each `unique_id`, look up the device via `device_registry.async_get_device(identifiers={(DOMAIN, source_unique_id)})`; if non-`None`, call `device_registry.async_remove_device(device.id)`. Log at info level when a device is actually removed; silent no-op when not.
- [ ] 1.3 In `_async_registry_changed` (action: `remove`), capture the return value of `prune_removed_older_than` and pass it to `_purge_companions_for_pruned`.
- [ ] 1.4 In `_handle_tick`, capture the return value of `prune_removed_older_than` and pass it to `_purge_companions_for_pruned`.

## 2. Tests

- [ ] 2.1 Add `test_purge_companions_for_pruned_removes_device` to `tests/test_coordinator.py`: pre-create a device in the device registry with `identifiers={(DOMAIN, "uid-foo")}`, call `coord._purge_companions_for_pruned(["uid-foo"])` directly, assert `device_registry.async_get_device(identifiers={(DOMAIN, "uid-foo")})` is `None` after.
- [ ] 2.2 Add `test_purge_companions_for_pruned_is_noop_for_missing_device`: call `coord._purge_companions_for_pruned(["uid-never-existed"])` against an empty device registry; assert no exception raised and no notification fires.
- [ ] 2.3 Add `test_remove_event_chain_purges_after_grace_window`: register a source battery, set up coordinator, manually create a device for it, soft-delete via the registry-remove event, then forge an old `removed_at` directly in the store JSON to simulate elapsed grace, fire another remove event (or call `_handle_tick` directly) to drive prune+purge, assert device is gone.

## 3. Release plumbing

- [ ] 3.1 Bump `manifest.json` `version` to `0.1.4`.
- [ ] 3.2 Update `README.md` removal/cleanup narrative (the implicit "what happens when batteries disappear" section is currently absent — add a short paragraph documenting the soft-delete + 30-day grace + auto-purge behavior, since v0.1.4 makes the auto-purge true).
- [ ] 3.3 Run `.venv/bin/pytest tests/ -q`. Expect 118 passed (115 prior + 3 new).

## 4. Close-out (executed from main checkout, not the worktree)

- [ ] 4.1 Commit implementation work in the agent worktree on branch `agent/autoclean-orphan-companion-entities`.
- [ ] 4.2 Merge `agent/autoclean-orphan-companion-entities` into `master` via the main checkout (`git merge --no-ff`).
- [ ] 4.3 Push `master` to both `origin` (gitea) and `github`; push tag `v0.1.4` to both.
- [ ] 4.4 Create GitHub release `v0.1.4` via `gh release create`.
- [ ] 4.5 Sync the delta into `openspec/specs/coordinator-scheduling/spec.md` and archive the change to `openspec/changes/archive/YYYY-MM-DD-autoclean-orphan-companion-entities`.
- [ ] 4.6 Remove the worktree and branch.
- [ ] 4.7 Update `HANDOFF.md` to reflect v0.1.4 shipped.
