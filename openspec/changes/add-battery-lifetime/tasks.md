## 1. Repository skeleton & HACS packaging

- [x] 1.1 Create `custom_components/battery_lifetime/` directory and an empty `__init__.py`
- [x] 1.2 Write `custom_components/battery_lifetime/manifest.json` with `domain: battery_lifetime`, name, version, documentation/issue URLs, codeowner, `iot_class: local_polling`, and a `requirements: []` list
- [x] 1.3 Write `custom_components/battery_lifetime/const.py` with the integration domain, default profile constants, plateau gate, threshold defaults, lifetime defaults, EWMA window cap, confidence-ladder thresholds, staleness windows, and event/service names
- [x] 1.4 Write repository-root `hacs.json` with name, required HA version, and category
- [x] 1.5 Write repository-root `info.md` describing the integration for the HACS UI
- [x] 1.6 Write repository-root `README.md` covering installation, eligibility rules, replacement detection, manual controls, profiles, default-profile setting, companion entities, confidence ladder (with the 30–60 day caveat), lithium plateau caveat, the `predict_at` service signature, and explicit non-goals
- [x] 1.7 Add a minimal `LICENSE` file at the repository root

## 2. Persistence layer

- [x] 2.1 Create `custom_components/battery_lifetime/store.py` with a `BatteryLifetimeStore` class wrapping HA's `Store` helper at `.storage/battery_lifetime`
- [x] 2.2 Define the on-disk schema: integration-level (`version`, `default_profile`) and per-battery entries keyed by source `unique_id` containing `replaced_on`, `profile`, `threshold_override`, `tracking_enabled`, `ewma_state`, `last_reading_pct`, `last_reading_at`, `last_replace_by`, `removed_at`
- [x] 2.3 Implement `async_load`, `async_save`, and a debounced/coalescing save path so frequent updates do not thrash disk
- [x] 2.4 Implement `migrate(data, from_version)` that returns the upgraded structure, logs the migration step at info level, and is invoked on load
- [x] 2.5 Implement helpers: `get_battery(unique_id)`, `upsert_battery(unique_id, **fields)`, `remove_battery(unique_id)`, `iter_batteries()`, `prune_removed_older_than(days)`
- [x] 2.6 Cover the store with unit tests for round-trip, schema migration, debounced save, and the 30-day prune behavior

## 3. Profiles & prediction model

- [x] 3.1 Create `custom_components/battery_lifetime/models/__init__.py` exposing a `Profile` dataclass with `id`, `default_threshold_pct`, `default_lifetime_days`, `plateau_pct` (nullable), `description`
- [x] 3.2 Create `custom_components/battery_lifetime/models/alkaline.py` implementing the alkaline profile (smooth taper, threshold 15%, lifetime 365d, no plateau)
- [x] 3.3 Create `custom_components/battery_lifetime/models/lithium.py` implementing the lithium profile (plateau-then-cliff, threshold 5%, lifetime 1825d, plateau gate at 85%)
- [x] 3.4 Create `custom_components/battery_lifetime/prediction.py` containing the EWMA drain-rate updater, the `replace_by` projector (handling no_data / profile_default / plateau / EWMA-extrapolation cases), and a `forward_simulate(target_date)` helper that returns `predicted_pct_at_date` and `predicted_state` without mutating state
- [x] 3.5 Implement the confidence-ladder evaluator (`no_data`, `profile_default`, `low`, `medium`, `high`, `stale`) gated on time-since-replacement, observed drain, and last-source-update age
- [x] 3.6 Cover models and prediction with unit tests: alkaline projection, lithium plateau hold, lithium cliff projection after leaving plateau, threshold override, EWMA reset on replacement, EWMA ignores increases without replacement, confidence-ladder transitions including `stale`

## 4. Replacement detection

- [x] 4.1 Create `custom_components/battery_lifetime/detection.py` implementing the auto-replacement rule (`<80% → ≥100%`, `≤30 days` prior age, persistence confirmation, glitch protection)
- [x] 4.2 Implement candidate-event tracking: hold an unconfirmed `100%` candidate, await a follow-up update or one-hour timer, and discard if the source drops below `95%` within an hour
- [x] 4.3 Implement stale-prior handling: when prior reading is older than 30 days, raise a persistent HA notification with Confirm / Dismiss / Exclude actions, and only commit on confirmation
- [x] 4.4 Implement cold-start backfill that queries HA long-term statistics first, then the recorder, for the most recent qualifying jump and seeds `replaced_on`
- [x] 4.5 Implement the post-attach backwards extrapolation fallback (used when neither long-term statistics nor recorder yield a hit) once `≥7 days` and `≥1%` drain are observed
- [x] 4.6 Emit the `battery_lifetime_replacement_detected` HA event with the full payload schema (`entity_id`, `unique_id`, `previous_pct`, `current_pct`, `prior_reading_age_seconds`, `replaced_on`, `confirmed`, `source`)
- [x] 4.7 Cover detection with unit tests: standard auto-detection, jump from `≥80%` is ignored, single-sample spike rejected, confirmation by elapsed time, stale-prior raises notification (and does not auto-commit), confirm/dismiss/exclude paths, cold-start LTS hit, cold-start recorder fallback, cold-start no-history fallback, post-attach backwards extrapolation

## 5. Discovery & coordinator

- [x] 5.1 Create `custom_components/battery_lifetime/discovery.py` implementing eligibility (`device_class: battery`, unit `%`, numeric state, has `unique_id`, not a battery_lifetime companion entity)
- [x] 5.2 Subscribe to entity-registry updates so newly added eligible entities are picked up at runtime and removed entities transition companion entities to `unavailable`
- [x] 5.3 Implement the 30-day retention for removed sources (delegating to `store.prune_removed_older_than`)
- [x] 5.4 Create `custom_components/battery_lifetime/coordinator.py` with a `BatteryLifetimeCoordinator(DataUpdateCoordinator)` that, on each refresh, iterates tracked batteries, ingests recent source updates into the EWMA, runs the prediction projector, updates summary counts, and writes the store
- [x] 5.5 Wire source-state-change listeners that feed both the coordinator's EWMA path and the replacement-detection candidate flow
- [x] 5.6 Cover discovery and coordinator with unit tests: eligibility filter, runtime add/remove, retention prune, coordinator refresh ordering, summary count math

## 6. Companion entities

- [x] 6.1 Create `custom_components/battery_lifetime/sensor.py` providing `BatterySensor` base class plus three concrete sensors: `replace_by` (`device_class: timestamp`, attributes including `confidence`, `profile`, `threshold_pct`, `drain_rate_pct_day`, `replaced_on`, `last_observed_pct`, `last_seen`, `source_entity`), `prediction_quality` (string enum), `drain_rate` (unit `%/d`)
- [x] 6.2 Add the integration-level summary sensors `battery_lifetime_due_this_month` and `battery_lifetime_due_next_3_months` in the same module
- [x] 6.3 Create `custom_components/battery_lifetime/switch.py` with `profile_lithium` (icons differ per state) and `tracking_enabled` switches, both persisting through the store
- [x] 6.4 Create `custom_components/battery_lifetime/button.py` with `mark_replaced` button that sets `replaced_on = utcnow()`, resets EWMA, and emits the replacement event with `source: manual_button`
- [x] 6.5 Create `custom_components/battery_lifetime/date.py` with `replaced_on` date entity that rejects future dates and emits the replacement event with `source: manual_date_edit`
- [x] 6.6 Create `custom_components/battery_lifetime/number.py` with `threshold_override` (blank/null = use profile default; bounded `0–100`)
- [x] 6.7 Ensure each companion entity's `unique_id` is derived deterministically from the source `unique_id` and is stable across restarts
- [x] 6.8 Cover companion entities with unit tests: state derivation from store, switch toggles persist and reach coordinator, button press emits event, date validation rejects future, number override flows into prediction

## 7. Forward-prediction service

- [x] 7.1 Create `custom_components/battery_lifetime/services.py` with the `predict_at` async service handler honoring `date`, `margin_days`, `actionable_only`, `include_excluded` and returning a service-call response
- [x] 7.2 Write `custom_components/battery_lifetime/services.yaml` describing the service for the HA UI, including field types, defaults, and example values
- [x] 7.3 Build response entries strictly matching the documented schema (`entity_id`, `replace_by_entity`, `unique_id`, `profile`, `threshold_pct`, `drain_rate_pct_day`, `predicted_pct_at_date`, `predicted_state`, `confidence`, `tracking_enabled`, `excluded` when applicable)
- [x] 7.4 Ensure the service is purely read-only (no store writes, no companion-entity mutation)
- [x] 7.5 Cover the service with unit tests: missing `date` rejected, default returns all tracked, `actionable_only: true` filters correctly, `margin_days` shifts the evaluation window, `include_excluded: true` adds disabled batteries with the `excluded` flag, lithium plateau honored, `unknown` reported when prediction not possible

## 8. Config & options flows

- [x] 8.1 Create `custom_components/battery_lifetime/config_flow.py` with a `ConfigFlow` enforcing single-instance via `async_set_unique_id` + `_abort_if_unique_id_configured` (or equivalent) and creating an empty entry without per-battery questions
- [x] 8.2 Implement an `OptionsFlow` exposing `default_profile` (`alkaline` / `lithium`, default `lithium`)
- [x] 8.3 Implement the bulk-overview options screen that lists every tracked battery with editable `tracking_enabled`, `profile_lithium`, optional `threshold_override`, and read-only `replaced_on`, `prediction_quality`, `replace_by`
- [x] 8.4 Wire bulk-overview saves through the store and ensure the next coordinator update propagates changes to the companion entities
- [x] 8.5 Cover the flows with unit tests: first add succeeds, second add aborts with `single_instance_allowed`, default-profile change applies only to subsequently discovered batteries, bulk-overview edits persist and propagate

## 9. Wiring & lifecycle

- [x] 9.1 Implement `async_setup_entry` to load the store, build the coordinator, register the service, register entity platforms, subscribe to entity-registry updates, and arm the cold-start backfill
- [x] 9.2 Implement `async_unload_entry` to deregister the service, unsubscribe listeners, flush the store, and unload platforms cleanly
- [x] 9.3 Implement `async_reload_entry` so options-flow saves apply without a full HA restart
- [x] 9.4 Add `strings.json` and `translations/en.json` with config/options-flow strings, notification strings, and entity name translations
- [x] 9.5 Cover lifecycle with unit tests: setup creates expected entities, unload tears down cleanly, reload picks up options changes

## 10. End-to-end smoke testing & release prep

- [x] 10.1 Build a HA dev container or `pytest-homeassistant-custom-component` scaffolding that exercises a synthetic source sensor whose state can be programmatically driven
- [ ] 10.2 Walk through each replacement-detection branch end-to-end (auto, glitch-rejected, stale-prior with all three confirm/dismiss/exclude responses, cold-start LTS, cold-start recorder, cold-start no-history) — programmatic coverage exists in `tests/test_detection.py` and `tests/test_e2e.py`; this checkbox stays open until the operator has watched each branch fire in a real HA install
- [ ] 10.3 Walk through each prediction-quality state transition end-to-end (`no_data → profile_default → low → medium → high`) by driving simulated drain — programmatic coverage exists in `tests/test_prediction.py`; this checkbox stays open until the operator has watched the transitions in a real HA install
- [ ] 10.4 Validate cold-start backfill against a real HA install with at least 60 days of long-term statistics for at least one battery sensor
- [ ] 10.5 Validate the `predict_at` service via HA Developer Tools → Services with `actionable_only: true`, `include_excluded: true`, and various `margin_days`
- [ ] 10.6 Confirm HACS-installable behavior by adding the repository as a custom integration repository in a test HA install
- [ ] 10.7 Tag a `v0.1.0` release and note the expected first-30-to-60-day low-confidence behavior in the release notes
