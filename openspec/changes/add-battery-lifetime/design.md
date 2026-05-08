## Context

Home Assistant battery sensors come from many integrations (Zigbee, Z-Wave, Bluetooth, cloud APIs, etc.) and report under a common pattern: an entity with `device_class: battery` and `unit_of_measurement: %` whose state is a number from 0 to 100. Some integrations use boolean low-battery sensors or categorical states (`low`/`normal`/`full`); a small number report raw voltage. This integration only targets the numeric percent case.

The repository is greenfield — no existing code, no existing specs. The sibling `PerfectDraft` integration (in another folder) is the structural reference for HACS layout and HA integration scaffolding.

The user is the operator and the developer. Realistic constraints:

- Python 3.x, HA core integration patterns (config flow, options flow, `DataUpdateCoordinator`, entity platforms).
- HACS distribution via `hacs.json` and `info.md` at repository root, integration code at `custom_components/battery_lifetime/`.
- HA recorder defaults to ~10 days of detailed history; long-term statistics are stored at hourly granularity for years and are the right source for cold-start backfill.
- Battery sensors update at wildly different cadences (minutes for some Zigbee devices, daily for some BLE devices); the model must not assume a specific update frequency.

## Goals / Non-Goals

**Goals:**

- Turn raw HA battery percentages into per-battery predicted replacement dates that are good enough to plan around.
- Detect replacement events automatically in the common case, fall back to user confirmation for ambiguous cases, and never silently corrupt history with false replacements.
- Adapt to two chemistry profiles (`alkaline`, `lithium` primary) with different curve shapes and default thresholds, and let the user override per battery.
- Support a forward-prediction service that powers "before I leave the cottage" use cases.
- Honest confidence reporting — predictions in the first weeks after install or replacement are explicitly low-confidence and the system says so.
- Single integration instance, autodiscovery on by default, individual batteries can be opted out without removing them from HA.
- HACS-installable from day one.

**Non-Goals:**

- Categorical (`low`/`normal`/`full`) and boolean low-battery sensors — skipped at discovery time with an info-level log.
- Voltage-only (mV) battery sensors — out of scope for v1.
- Rechargeable battery modeling (NiMH eneloops, Li-ion packs, USB-backup devices, EcoFlow whole-house batteries) — users must exclude these manually; the auto-replacement rule will fire spuriously on rechargeables.
- Multi-cell awareness ("3×AA dies as a set") — each entity is modeled independently.
- Custom Lovelace cards — left to a sibling project.
- Cross-device learning, Bayesian priors, ML-based prediction. v1 uses a transparent EWMA extrapolation gated by chemistry profile.
- Bulk-edit UX for very large fleets (50+ batteries) is acknowledged but not prioritized; pagination/search in the options flow is deferred.

## Decisions

### Decision: Single integration instance, not one-per-battery

Adding the integration once gives it ownership over all numeric battery entities globally, rather than requiring a config entry per battery. Alternative considered: one config entry per battery. Rejected because it would force the user to manually wire up dozens of entries on first install and would not match how cross-cutting HA integrations (e.g., `utility_meter`, `statistics`, `mqtt_statestream`) typically work.

### Decision: Autodiscovery is the default, opt-out is per-battery

The integration enumerates eligible source entities continuously (entity registry events) and creates companion entities for each. A `switch.<src>_tracking_enabled` per battery turns tracking off without removing the battery from HA. Alternative considered: explicit user-managed list of tracked batteries. Rejected because it adds friction for the common case (track everything) and the opt-out switch is just as cheap to implement as a config entry list.

### Decision: Replacement detection is a deterministic rule, not a learned model

The rule is: previous reading `<80%` AND new reading `≥100%` AND previous reading is `≤30 days` old AND the `100%` reading persists across at least one more update or one hour, whichever comes first AND the battery is not opted out. Stale jumps (previous reading older than 30 days) raise a persistent HA notification asking the user to confirm; they are never auto-committed. Sub-95% drops within an hour of a 100% sample invalidate that sample (glitch protection). Alternative considered: a learned threshold or curve-shape detector. Rejected because it adds complexity, requires training data the user doesn't have, and the failure mode (wrong replaced-on date) is much worse than the false-negative mode (ask user to confirm).

### Decision: Two chemistry profiles, lithium-default at integration level, switch entity per battery

`alkaline` (smooth taper, default threshold 15%, default lifetime 365 days, EWMA from day one) and `lithium` (plateau-then-cliff, default threshold 5%, default lifetime 1825 days, EWMA only after the source reading drops below 85%). The integration-level default is `lithium` because the operator's fleet is predominantly lithium-primary AA/AAA cells; an options-flow setting lets installers with mostly-alkaline fleets flip the default. Per battery, the choice is exposed as a `switch.<src>_profile_lithium` entity (on = lithium, off = alkaline) so the chosen profile shows as a click-to-toggle icon next to the battery in the device card. Alternative considered: `select` entity with two options. Rejected because `select` renders as a dropdown in HA's UI, which is clunky for a binary choice; also rejected: three profiles (alkaline, lithium-cliff, lithium-linearized). Rejected because the cliff is genuinely the lithium-primary chemistry — the rare "linearized" reporting case is handled by setting that battery's profile to `alkaline`, which is documented.

### Decision: Drain rate is EWMA over data since replacement, capped at last 60 days

The exponentially-weighted moving average over `%/day` since the last replacement, with the window capped at the most recent 60 days, balances responsiveness to seasonal change (cold cottage in winter) against stability (a single noisy week shouldn't shift predictions). Alternative considered: simple linear regression over the entire post-replacement series. Rejected because seasonal drift would be invisible. Alternative considered: 14-day moving window. Rejected as too volatile for slow-reporting devices.

### Decision: Profile-specific extrapolation handles the lithium plateau

For `alkaline`, EWMA-based extrapolation runs from day one. For `lithium`, while the source reading is `≥85%` the integration treats the battery as on the chemistry plateau and reports `replaced_on + profile.default_lifetime` instead of extrapolating the (misleadingly slow) observed drain; once the reading drops below `85%`, the integration switches to EWMA extrapolation against the lithium threshold. Alternative considered: always EWMA-extrapolate. Rejected because a lithium primary that sits at 100% for 11 months would project an EOL of millennia. Alternative considered: introduce a third "cliff-aware" profile. Rejected because the chemistry already determines this; one profile, two phases is cleaner.

### Decision: Graduated confidence ladder

`no_data` (no replaced-on, no recorder match), `profile_default` (replaced-on known, not enough drain observed yet — also used during the lithium plateau), `low` (`≥7 days` since replacement and `≥1%` drain), `medium` (`≥30 days` and `≥5%` drain), `high` (`≥60 days` and `≥10%` drain), `stale` (orthogonal — no source updates in the last 7 days). Exposed as a separate companion `sensor.<src>_prediction_quality` entity and as an attribute on the replace-by sensor. Alternative considered: binary `observed`/`profile_default` flag. Rejected because the operator needs to know the difference between "no data yet" and "weak signal" when sorting batteries before a long absence.

### Decision: Cold-start uses long-term statistics, then recorder, then observation

Order of attempts when a battery is first seen by the integration: (1) scan HA long-term statistics for the most recent qualifying `<80% → ≥100%` jump; (2) scan recorder for the same; (3) if neither finds anything, set `replaced_on = unknown`, confidence = `no_data`, continue listening — once `≥7 days` of post-attach data with `≥1%` drop accumulate, extrapolate backwards along the active profile to estimate `replaced_on`. Alternative considered: prompt the user during config flow. Rejected because the user has no way to remember the answer for dozens of devices.

### Decision: Forward prediction is one service with a filter flag, not two services

`battery_lifetime.predict_at(date, margin_days, actionable_only, include_excluded)` returns either every tracked battery (default) or only those projected to be below threshold (`actionable_only: true`). One service is a smaller API surface and the filter is cheap. Alternative considered: split `predict_at` (all) and `actionable_at` (filtered). Rejected as needless duplication.

### Decision: Persistence via HA Storage helper, not HA recorder

A single store per integration instance, schema-versioned, holding per-battery `replaced_on`, `profile`, `tracking_enabled`, optional `threshold_override`, last good prediction snapshot, and the EWMA state needed to recompute drain rate without a full history rescan. Recorder is unsuitable because HA users routinely tune retention and may purge historical data; the integration's own state must survive that. Alternative considered: per-entity attributes (transient). Rejected because attributes do not survive restarts in any robust way.

### Decision: Companion entity surface

Per battery: `sensor.<src>_replace_by` (datetime), `sensor.<src>_prediction_quality` (string-state), `sensor.<src>_drain_rate` (`%/day`), `switch.<src>_profile_lithium` (binary chemistry), `switch.<src>_tracking_enabled` (binary opt-out), `date.<src>_replaced_on` (manual edit), `button.<src>_mark_replaced` (manual replacement event), `number.<src>_threshold_override` (optional, blank means use profile default). Integration-level: `sensor.battery_lifetime_due_this_month`, `sensor.battery_lifetime_due_next_3_months`. Alternative considered: a single sensor with everything in attributes. Rejected because HA's UI is entity-oriented and the operator wants to see/manipulate these from the device card.

### Decision: Source entity identity is the entity registry unique ID, not the entity ID

Persistence keys, companion entity unique IDs, and replacement event correlations all key off the source entity's `unique_id` from the entity registry. The visible `entity_id` (`sensor.kitchen_motion_battery`) is volatile (renames, integrations rebuilding entities) and unsuitable. Alternative considered: keep on `entity_id`. Rejected because renames would orphan history.

### Decision: Replacement events emit a HA event for automation

`battery_lifetime_replacement_detected` event (with `entity_id`, `unique_id`, `previous_pct`, `current_pct`, `prior_reading_age`, `confirmed: bool`) gives users an automation hook ("notify me when an auto-detected replacement happened"). Alternative considered: only logbook entries. Rejected because that's not automation-friendly.

### Decision: HACS layout follows the standard pattern

Repository root: `hacs.json`, `info.md`, `README.md`, plus the integration at `custom_components/battery_lifetime/` containing `manifest.json`, `__init__.py`, `config_flow.py`, `const.py`, `coordinator.py`, platform files (`sensor.py`, `switch.py`, `button.py`, `date.py`, `number.py`), `models/` with one Python module per profile, `store.py`, and `services.yaml`. No deviation from this layout is justified.

## Risks / Trade-offs

- **HA recorder default retention is 10 days** → Cold-start backfill from recorder alone will often fail. **Mitigation**: also query long-term statistics (hourly granularity, multi-year retention is fine for processes that take months). Document that users with long-term statistics disabled get a degraded cold-start experience.
- **Lithium primaries can plateau for ~11 months at 100%** → A naive linear model would predict EOL of decades. **Mitigation**: profile-specific extrapolation with the `≥85%` plateau gate; confidence stays at `profile_default` while on plateau. Document that lithium-default predictions look identical for the first many months after replacement.
- **Sensor update intervals vary** (Zigbee minutes, BLE daily) → "Drain rate" can be very noisy for slow-reporting devices. **Mitigation**: 60-day cap on the EWMA window dampens jitter; confidence ladder gates `high` on `≥60 days` and `≥10%` drop, which slow reporters genuinely need.
- **Rechargeables look like infinitely-replaced primaries** → The `<80% → ≥100%` rule fires every recharge cycle. **Mitigation**: exclusion via `switch.<src>_tracking_enabled`; documented as the v1 strategy. Future capability could add a `rechargeable` profile.
- **Sensor glitches** (single-sample 100% spike) → False replacement events. **Mitigation**: persistence requirement (the 100% reading must be confirmed by a follow-up update or one full hour) plus the `<95%` revert-within-an-hour discard rule.
- **Long offline gaps** (battery in a freezer with bad signal, last seen two months ago at 75%) → A new 100% reading after a long gap looks like a replacement. **Mitigation**: 30-day staleness threshold; older gaps raise a persistent notification rather than auto-committing.
- **Battery sensors that report on power-cycle resets to 100%** → Looks like replacement. **Mitigation**: same staleness/glitch rules catch most of these; users can manually correct via `date.<src>_replaced_on` and `button.<src>_mark_replaced`.
- **First-month-after-install user expectation gap** → Confidence will sit at `low` or `profile_default` for 30–60 days. **Mitigation**: README explicitly sets this expectation; `prediction_quality` is a first-class sensor so dashboards can filter on it.
- **Options flow with very many batteries** → Slow rendering in HA UI. **Mitigation**: the per-battery companion entities are usable on their own; the bulk overview is a convenience. Pagination/search deferred.
- **Renames or replaced source integrations** → Companion entities orphaned if the source disappears. **Mitigation**: store per-source state by `unique_id`; on source-entity-removed events, mark companions as `unavailable` but retain state for 30 days in case the source comes back (e.g. user re-paired the device).

## Migration Plan

Greenfield repository, no migration concerns. Steps to first usable release:

1. Land repository skeleton (`custom_components/battery_lifetime/`, `hacs.json`, `info.md`, `README.md`).
2. Implement the integration in dependency order (discovery → persistence → coordinator → companion entities → replacement detection → prediction model → forward-prediction service → options flow).
3. Manual smoke test in a HA dev container against a synthetic source sensor (a `template.sensor` whose state can be driven by the developer) for each branch of the replacement-detection rule.
4. Validate cold-start backfill against a real HA install with a few months of long-term statistics.
5. Tag a v0.1.0 release, register the repo with HACS as a custom repository for early users.

Rollback: removing the integration removes its config entry and stops creating companion entities; the persistent store can be deleted from `.storage/battery_lifetime` if desired. Source battery sensors are unaffected.

## Open Questions

- **Confidence-ladder thresholds** are currently fixed (`7/30/60` days, `1/5/10%` drop). Should they be tunable per profile? Deferred — picked sensible defaults; revisit if real-world fleets show systematic miscalibration.
- **Threshold override units** — `number.<src>_threshold_override` is in `%` of the source sensor's reported state. If a user genuinely cares about voltage, that's a different (out-of-scope) profile.
- **Devices that report battery only as a sub-attribute** of a parent entity (e.g. `attributes.battery_level` on a non-battery main sensor) — covered by `device_class: battery` enumeration only if HA exposes them as their own entity. Some integrations don't. Deferred — most devices that need this expose a proper battery entity.
- **Future profile additions** — `nimh_rechargeable`, `lead_acid` are plausible v2 candidates. The profile abstraction is designed to accept new entries without restructuring existing data.
