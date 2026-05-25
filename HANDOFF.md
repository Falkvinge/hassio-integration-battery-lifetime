# Agent Handoff — Battery Lifetime

## Current State (2026-05-11, late-morning)

The Battery Lifetime custom Home Assistant integration is working and deployed via HACS on the user's live install (70 battery-powered devices → 554 companion entities). Current release is **v0.1.6** on GitHub via HACS.

The OpenSpec change `add-battery-lifetime` is at 56/62 tasks; the remaining six (10.2–10.7) are manual-validation gates against a real HA install. Some are implicitly being validated right now by the live install; see "What Needs Doing Next" below.

The OpenSpec changes `optimize-coordinator-tick` (v0.1.2), `defer-cold-start-backfill` (v0.1.3), and `autoclean-orphan-companion-entities` (v0.1.4) are fully archived under `openspec/changes/archive/`. All three have their specs synced into `openspec/specs/coordinator-scheduling/spec.md`.

## What's Done

- Full implementation of the Battery Lifetime integration:
  - Auto-discovery of every numeric percent battery sensor in the HA entity registry; categorical / boolean / voltage-only / no-`unique_id` sensors are skipped (and logged once).
  - Eight per-battery companion entities: `sensor.<src>_replace_by` (timestamp), `sensor.<src>_prediction_quality` (enum), `sensor.<src>_drain_rate` (`%/d`), `switch.<src>_profile_lithium`, `switch.<src>_tracking_enabled`, `button.<src>_mark_replaced`, `date.<src>_replaced_on`, `number.<src>_threshold_override`.
  - Two integration-level summary sensors: `sensor.battery_lifetime_due_this_month`, `sensor.battery_lifetime_due_next_3_months`.
  - Two chemistry profiles (`alkaline` 15%/365d, `lithium` 5%/1825d with 85% plateau gate); default is `lithium`, switchable per battery.
  - Auto-replacement detection (jump from `<80%` to `≥100%` with confirmation, 30-day staleness window, 1-hour glitch protection).
  - Stale-prior workflow exposed as three HA services (`battery_lifetime.confirm_stale_replacement`, `dismiss_stale_replacement`, `exclude_stale_replacement`); the persistent notification names the entity_id and the three services.
  - Cold-start backfill from HA long-term statistics (preferred) and recorder (fallback); backwards-extrapolation fallback after `≥7 days` and `≥1%` drain.
  - Confidence ladder (`no_data` → `profile_default` → `low` → `medium` → `high`, plus orthogonal `stale`).
  - Forward-prediction service `battery_lifetime.predict_at` with `actionable_only`, `margin_days` (extends evaluation date forward — be conservative), `include_excluded` flags.
  - Single-instance config flow + options flow (default profile + bulk overview).
  - Persistent state via HA `Store` helper at `.storage/battery_lifetime` with versioned schema and migration scaffold.
- HACS packaging (`hacs.json`, `info.md`, `README.md`, `LICENSE`, `manifest.json`).
- 107 unit tests passing under `pytest-homeassistant-custom-component`.
- v0.1.0 released and installed live on the user's HA install. v0.1.1 follow-up adds a bold/all-caps setup-time warning to the config dialog and ships icon assets in `custom_components/battery_lifetime/brand/` (256×256 + 512×512).
- v0.1.2 ships three coordinator scheduling optimizations (drop redundant 10-minute timer, per-source-event O(1) update via `async_set_updated_data`, diff-gated heartbeat publish). 5 new tests in `tests/test_coordinator.py`, full suite 112 passed.
- v0.1.3 defers cold-start backfill out of `async_setup`'s await chain via `hass.async_create_task`, removing the multi-minute config-entry freeze on installs with many batteries (the v0.1.1 dialog warning is no longer applicable and was softened). Adds a one-shot `persistent_notification` (`battery_lifetime_cold_start_complete`) when the initial backfill batch finishes. Ships `brand/logo.png` + `brand/logo@2x.png` (copies of the icon assets) for HA's Brands Proxy logo slot. 3 new tests in `tests/test_coordinator.py`, full suite 115 passed.
- v0.1.4 closes the orphan-companion-entity gap: when `prune_removed_older_than` actually drops a `unique_id` from the JSON store (after the 30-day grace window), the coordinator now removes the per-source companion device via `device_registry.async_remove_device`. HA's device-registry removal cascades to the entity registry and clears the eight per-source companion entries automatically. Cleanup runs from both prune call sites (`_async_registry_changed action: remove` + `_handle_tick`). Idempotent on missing device. Soft-deleted entries within their grace window are NOT touched; restore semantics are unchanged. 3 new tests, full suite 118 passed.
- v0.1.6 fixes the cold-start backfill completion notification firing on every HA restart. The one-shot `persistent_notification` (`battery_lifetime_cold_start_complete`) is now gated by a persisted `cold_start_backfill_announced` flag in the JSON store; backfill still re-runs silently on restart for batteries without `replaced_on` (idempotent, per spec). Upgrades with existing battery entries migrate the flag to `true` so no spurious notification on first restart after update. 1 new test, full suite 127 passed.
- Both `master` and tags `v0.1.0`/`v0.1.1`/`v0.1.2`/`v0.1.3`/`v0.1.4`/`v0.1.5`/`v0.1.6` pushed to gitea (origin) and GitHub (github).
- README and OpenSpec specs aligned with the implementation; `replacement-detection/spec.md` enumerates the three stale-prior services explicitly. `coordinator-scheduling/spec.md` documents the per-event vs heartbeat contracts, the non-blocking cold-start contract, AND the prune-driven companion-device purge.

## What Needs Doing Next (Immediate)

### 1. ~~Brands PR for the HACS icon~~ — OBSOLETE as of HA 2026.3

Home Assistant 2026.3 (announcement: <https://developers.home-assistant.io/blog/2026/02/24/brands-proxy-api>) introduced a local Brands Proxy API. Custom integrations now ship `brand/icon.png`, `brand/icon@2x.png`, `brand/logo.png`, and `brand/logo@2x.png` inside their own repository, and HA serves them from `/api/brands/integration/<domain>/...`. The `home-assistant/brands` repo **auto-closes** PRs for `custom_integrations/*` and tells contributors to use the inline mechanism.

We ship all four assets as of v0.1.3 (icons in v0.1.1, logos added in v0.1.3 as copies of the icons). On the user's HA 2026.4.x install the icon and logo are served by HA core in **Settings → Devices & Services**, the integration card, and the config-flow dialog. **No PR needed.**

The one remaining gap is HACS's own dashboard (Downloads / repository list), which still calls the old CDN URL because `hacs/frontend` hasn't been bumped past the brands-proxy rewrite. Tracked in `hacs/integration#5179` and `#5223`; fix PRs `hacs/integration#5228`, `hacs/frontend#937`, `#929`, `#5249` are open but unmerged. Until HACS frontend ships those, the HACS Downloads panel will keep showing "icon not available". This is a HACS issue, not ours.

### 2. OpenSpec manual-validation gates 10.2 – 10.7

These are the only remaining tasks in `openspec/changes/add-battery-lifetime/tasks.md`. Some are implicitly being validated by the live install right now:

- **10.2** Walk each replacement-detection branch (auto, glitch, stale-prior confirm/dismiss/exclude, cold-start LTS, cold-start recorder, cold-start no-history) end-to-end on real HA. Programmatic coverage is in `tests/test_detection.py` and `tests/test_e2e.py`.
- **10.3** Walk each prediction-quality state transition (`no_data → profile_default → low → medium → high`) by driving simulated drain. Programmatic coverage in `tests/test_prediction.py`.
- **10.4** Validate cold-start backfill against ≥60 d of long-term statistics. Live install with 70 devices triggered this at first boot — it's the apparent cause of the multi-minute initial-setup freeze that v0.1.1 now warns about. Worth observing whether `replaced_on` got populated for batteries that had a `<80% → ≥100%` jump in the recorder.
- **10.5** Validate `predict_at` via Developer Tools → Services with `actionable_only: true`, `include_excluded: true`, and various `margin_days`.
- **10.6** Implicitly validated — HACS install succeeded, integration loaded, 70 devices / 554 entities created.
- **10.7** Tag `v0.1.0` and note the first-30-to-60-day low-confidence behaviour in release notes — **DONE** (v0.1.0 released; release notes do mention the caveat).

Once 10.2 – 10.5 are observed in the live install, mark them in `tasks.md` and run `openspec archive --change "add-battery-lifetime"` (the OpenSpec workflow). The change has `isComplete: true` per `openspec status` (all artifacts are done; the open task checkboxes don't block archive).

### 3. ~~Investigate the multi-minute initial-setup freeze~~ — FIXED in v0.1.3

v0.1.3 ships the cold-start defer: `_ensure_record` schedules `_attempt_cold_start_backfill` via `hass.async_create_task` instead of awaiting it, so `async_setup` returns within the time bounded by the entity-registry scan (sub-second on the user's install). The coordinator tracks in-flight backfills in `_pending_backfills: set[str]` and fires one persistent notification (`battery_lifetime_cold_start_complete`) when the set drains.

The dialog warning was softened from the bold/all-caps freeze warning to a calmer "background backfill may take several minutes; a notification will appear when complete" note in `strings.json` and `translations/en.json`.

**Worth observing on the live install after upgrade:** confirm that (a) re-adding the integration completes within seconds rather than minutes; (b) the `battery_lifetime_cold_start_complete` notification appears once the background backfill finishes; (c) the per-battery `replaced_on` values populate over the following minutes; (d) no regressions in the 70 → 554 entity registration.

### 4. ~~Orphan companion entities after permanent removal~~ — FIXED in v0.1.4

v0.1.4 hooks the device-registry purge into the existing prune path. When `prune_removed_older_than` returns a non-empty list (which only happens after the 30-day grace window has expired for a soft-deleted source), the coordinator looks up the matching companion device via `device_registry.async_get_device(identifiers={(DOMAIN, source_uid)})` and calls `async_remove_device`, which cascades to all eight companion entity-registry entries.

**Pre-existing orphans accumulated before v0.1.4 are NOT retroactively cleaned.** Their JSON-store entries are already gone (so the prune-driven purge has nothing to act on for them). User can manually delete via Settings → Devices & Services. If accumulated orphans become a real pain point on the live install, a one-shot legacy-orphan scanner could be added in a future release; deferred until asked.

### 5. Loose ends from earlier sessions

- **Branch tracking.** `master` currently tracks `github/master` (because of `git push -u github master`). Sibling repos track `origin/master`. To match the sibling pattern:
  ```bash
  git branch --set-upstream-to=origin/master master
  ```
- **Credential helper.** This local repo doesn't have `credential.helper = store --file=.git/credentials` set in `.git/config` like the siblings do. Every gitea push needs an inline `-c credential.helper="store --file=.git/credentials"` until that's set. To match the sibling pattern:
  ```bash
  git config --local credential.helper "store --file=.git/credentials"
  ```
- **`.github-token` in this repo.** GitHub operations have been using `/home/rick/Lab/Dev/Hassio-PerfectDraftPro/.github-token` as the source of truth. To make this project self-contained:
  ```bash
  cp /home/rick/Lab/Dev/Hassio-PerfectDraftPro/.github-token .github-token
  ```
  Already in `.gitignore`, so it stays local.

These were deliberately not done by the previous agent because of the project's "NEVER update the git config" guardrail; the user can do them in three short commands.

## Architecture Notes

- **Repo layout**: standard HACS custom-integration layout. Source under `custom_components/battery_lifetime/`. Tests under `tests/`. OpenSpec artefacts under `openspec/changes/add-battery-lifetime/`. Brand assets under `custom_components/battery_lifetime/brand/`.
- **Storage**: `.storage/battery_lifetime` (JSON, versioned schema, debounced save). Per-battery entries keyed by source `unique_id`, never `entity_id`.
- **Identity**: `unique_id` is the canonical key everywhere — companion entities, store, replacement events.
- **Profiles**: pure-Python dataclasses in `custom_components/battery_lifetime/models/`.
- **Detection**: pure-logic helpers (`classify_reading`, `classify_followup`, `_scan_for_jump`, `estimate_replaced_on_from_drain`) in `detection.py`, plus an HA-aware `ReplacementDetector` wrapper that holds candidates, arms 1-hour `async_call_later` timers, and emits `battery_lifetime_replacement_detected` events.
- **Coordinator**: `BatteryLifetimeCoordinator(DataUpdateCoordinator)` owns the in-memory `BatteryRecord` map, listens to source state changes + entity-registry updates, and ticks every 10 minutes so `replace_by` and confidence respond to wall-clock time.
- **Companion entities**: derive their `unique_id` deterministically from the source `unique_id` via `companion_unique_id(source_uid, suffix)`. `_attr_has_entity_name = False` and a custom `suggested_object_id` property keep entity IDs in the documented `sensor.<src>_<suffix>` format.
- **Services**: `predict_at` (read-only, response-only), `confirm_stale_replacement`, `dismiss_stale_replacement`, `exclude_stale_replacement`. Defined in `services.py` + `services.yaml`.
- **HACS**: Releases on GitHub are the install source. `manifest.json` `version` field must match the tag.
- **Remotes**: `origin` = Gitea (git.falkvinge.net), `github` = GitHub (`Falkvinge/hassio-integration-battery-lifetime`).
- **Test harness**: `pytest-homeassistant-custom-component` against HA `2024.4+`. Run with `.venv/bin/pytest tests/`. Conftest is minimal (`enable_custom_integrations` fixture).

## Known Gotchas (from `PROJECT_HYGIENE.md` § 11)

These were learned the hard way during initial implementation; future sessions should heed them:

- HA `Entity.suggested_object_id` is a property derived from `self.name`, not the `_attr_suggested_object_id` attribute. Override the property to control companion `entity_id`.
- Single-instance config flow aborts use `_async_current_entries() → async_abort(reason="single_instance_allowed")`, NOT `_abort_if_unique_id_configured` (which aborts with `already_configured`).
- `RegistryEntry.unit_of_measurement` is the only unit field; `original_unit_of_measurement` does not exist on modern HA `RegistryEntry` objects.
- `EntityRegistry.async_get_or_create(unit_of_measurement=...)` accepts `unit_of_measurement`, not `original_unit_of_measurement`.
- `DataUpdateCoordinator.async_shutdown` overrides MUST `await super().async_shutdown()` or the test harness's `verify_cleanup` fixture will trip on a lingering `Debouncer._on_debounce` timer.
- `predict_at`'s `margin_days` *extends* the evaluation date forward (cottage-departure semantic — be conservative, flag MORE batteries).
- When a battery's last reading is already at or below threshold, `replace_by` is the last reading time ("due now"), not `replaced_on + default_lifetime` (which would be years in the future and break the `due_this_month` summary).
- Recorder/LTS calls fail in tests where the recorder isn't bootstrapped. `get_instance(hass)` is wrapped in `try/except (KeyError, RuntimeError)` and `recorder` is in `after_dependencies`, not `dependencies`.
- Two consecutive `hass.states.async_set(entity_id, "100", ...)` with the same string value get deduped by HA's state machine. Use `force_update=True` when a test needs the second one to fire a `state_changed` event.

## Useful Commands

```bash
# Run all tests
.venv/bin/pytest tests/ -q

# Run a single test
.venv/bin/pytest tests/test_prediction.py::test_lithium_plateau_holds_at_default_lifetime

# OpenSpec status
openspec status --change "add-battery-lifetime" --json

# OpenSpec validate
openspec validate "add-battery-lifetime"

# Push to gitea (credential helper not configured locally; inline it)
git -c credential.helper="store --file=.git/credentials" push origin master

# Push to GitHub (PAT is embedded in the remote URL already)
git push github master

# Create release via gh CLI (token from sibling)
GH_TOKEN=$(cat /home/rick/Lab/Dev/Hassio-PerfectDraftPro/.github-token) \
  gh release create vX.Y.Z --repo Falkvinge/hassio-integration-battery-lifetime \
  --title "..." --notes "..."
```

## Sibling Projects

- **`/home/rick/Lab/Dev/Hassio-PerfectDraftPro`** — the integration this project's `.gitignore` was originally copied from. Source of `.github-token` and the embedded-PAT remote pattern.
- **`/home/rick/Lab/Dev/Hassio-Thermostat-Fork-Darklight`** — source of `scripts/agent-worktree.sh`.
- **`/home/rick/Lab/Dev/Template`** — source of `AGENTS.md` and `PROJECT_HYGIENE.md`.

## OpenSpec Status

### Active changes

Change directory: `openspec/changes/add-battery-lifetime/`

| Artifact | Status |
| -------- | ------ |
| `proposal.md` | Done |
| `design.md` | Done |
| `specs/**/*.md` (5 capabilities) | Done |
| `tasks.md` | 56/62 (10.2 – 10.7 are the manual-validation gates) |

Ready to archive once 10.2 – 10.5 are observed live and the boxes are checked. 10.6 and 10.7 are already effectively done.

### Archived changes

- `openspec/changes/archive/2026-05-09-optimize-coordinator-tick/` — v0.1.2 release. Synced spec `coordinator-scheduling` is at `openspec/specs/coordinator-scheduling/spec.md`.
- `openspec/changes/archive/2026-05-11-defer-cold-start-backfill/` — v0.1.3 release. Same target spec; adds two requirements (Cold-start backfill is non-blocking; Backfill batch completion is announced exactly once).
- `openspec/changes/archive/2026-05-11-autoclean-orphan-companion-entities/` — v0.1.4 release. Same target spec; adds one requirement (Pruned sources have their companion device removed).
