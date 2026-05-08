# Agent Handoff — Battery Lifetime

## Current State (2026-05-08)

The Battery Lifetime custom Home Assistant integration is working and deployed via HACS on the user's live install (70 battery-powered devices → 554 companion entities). Current release is **v0.1.1** on GitHub via HACS.

The OpenSpec change `add-battery-lifetime` is at 56/62 tasks; the remaining six (10.2–10.7) are manual-validation gates against a real HA install. Some are implicitly being validated right now by the live install; see "What Needs Doing Next" below.

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
- Both `master` and tags `v0.1.0`/`v0.1.1` pushed to gitea (origin) and GitHub (github).
- README and OpenSpec specs aligned with the implementation; `replacement-detection/spec.md` enumerates the three stale-prior services explicitly.

## What Needs Doing Next (Immediate)

### 1. Brands PR for the HACS icon

HACS sources its integration icons from [home-assistant/brands](https://github.com/home-assistant/brands), not from the integration repo. The local assets at `custom_components/battery_lifetime/brand/icon.png` (256) and `icon@2x.png` (512) are ready to ship. To make HACS display them:

```bash
GH_TOKEN=$(cat /home/rick/Lab/Dev/Hassio-PerfectDraftPro/.github-token) gh repo fork home-assistant/brands --clone --remote
cd brands
git checkout -b add-battery-lifetime
mkdir -p custom_integrations/battery_lifetime
cp /home/rick/Lab/Dev/Hassio-Battery-Lifetimes/custom_components/battery_lifetime/brand/icon.png      custom_integrations/battery_lifetime/icon.png
cp /home/rick/Lab/Dev/Hassio-Battery-Lifetimes/custom_components/battery_lifetime/brand/icon@2x.png   custom_integrations/battery_lifetime/icon@2x.png
# logo.png + logo@2x.png are usually required too — same image is fine for an icon-only brand
cp /home/rick/Lab/Dev/Hassio-Battery-Lifetimes/custom_components/battery_lifetime/brand/icon.png      custom_integrations/battery_lifetime/logo.png
cp /home/rick/Lab/Dev/Hassio-Battery-Lifetimes/custom_components/battery_lifetime/brand/icon@2x.png   custom_integrations/battery_lifetime/logo@2x.png
git add custom_integrations/battery_lifetime
git commit -m "Add battery_lifetime"
git push origin add-battery-lifetime
GH_TOKEN=... gh pr create --repo home-assistant/brands \
  --title "Add battery_lifetime" \
  --body "Custom integration: https://github.com/Falkvinge/hassio-integration-battery-lifetime"
```

CI in brands runs Pillow checks for image dimensions and format; the assets satisfy them (sized correctly, transparent, RGBA).

### 2. OpenSpec manual-validation gates 10.2 – 10.7

These are the only remaining tasks in `openspec/changes/add-battery-lifetime/tasks.md`. Some are implicitly being validated by the live install right now:

- **10.2** Walk each replacement-detection branch (auto, glitch, stale-prior confirm/dismiss/exclude, cold-start LTS, cold-start recorder, cold-start no-history) end-to-end on real HA. Programmatic coverage is in `tests/test_detection.py` and `tests/test_e2e.py`.
- **10.3** Walk each prediction-quality state transition (`no_data → profile_default → low → medium → high`) by driving simulated drain. Programmatic coverage in `tests/test_prediction.py`.
- **10.4** Validate cold-start backfill against ≥60 d of long-term statistics. Live install with 70 devices triggered this at first boot — it's the apparent cause of the multi-minute initial-setup freeze that v0.1.1 now warns about. Worth observing whether `replaced_on` got populated for batteries that had a `<80% → ≥100%` jump in the recorder.
- **10.5** Validate `predict_at` via Developer Tools → Services with `actionable_only: true`, `include_excluded: true`, and various `margin_days`.
- **10.6** Implicitly validated — HACS install succeeded, integration loaded, 70 devices / 554 entities created.
- **10.7** Tag `v0.1.0` and note the first-30-to-60-day low-confidence behaviour in release notes — **DONE** (v0.1.0 released; release notes do mention the caveat).

Once 10.2 – 10.5 are observed in the live install, mark them in `tasks.md` and run `openspec archive --change "add-battery-lifetime"` (the OpenSpec workflow). The change has `isComplete: true` per `openspec status` (all artifacts are done; the open task checkboxes don't block archive).

### 3. Investigate the multi-minute initial-setup freeze

User reported that pressing **Submit** on the config dialog locked the UI for several minutes on a 70-device / 554-entity install. v0.1.1 warns about this in the dialog, but the underlying cause should be confirmed before considering it acceptable. Likely culprits:

- `_scan_initial_entities` in `custom_components/battery_lifetime/coordinator.py` calls `_ensure_record` for every eligible entity sequentially, and each call awaits the cold-start backfill (`_attempt_cold_start_backfill` → `recorder.async_add_executor_job` → two recorder queries per battery). With 70 batteries that's 140 recorder queries serialized.
- Mitigations to consider: gate cold-start backfill behind a background task instead of blocking setup; batch the recorder queries via `recorder.history.get_significant_states` for all entity_ids at once; or just defer the backfill to the first scheduled coordinator tick (already 10 minutes after setup) and let setup return immediately.
- Lazy-import note: cold-start should not block any of the *other* setup steps — the entity platforms are forwarded after `coordinator.async_setup()` returns. So the freeze is squarely in `_scan_initial_entities`.

### 4. Loose ends from earlier sessions

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

Change directory: `openspec/changes/add-battery-lifetime/`

| Artifact | Status |
| -------- | ------ |
| `proposal.md` | Done |
| `design.md` | Done |
| `specs/**/*.md` (5 capabilities) | Done |
| `tasks.md` | 56/62 (10.2 – 10.7 are the manual-validation gates) |

Ready to archive once 10.2 – 10.5 are observed live and the boxes are checked. 10.6 and 10.7 are already effectively done.
