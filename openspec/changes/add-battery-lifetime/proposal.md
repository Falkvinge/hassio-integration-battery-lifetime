## Why

Home Assistant exposes battery percentage sensors for hundreds of integrations, but those readings are not actionable: a user looking at their dashboard cannot easily answer "which batteries do I need to replace this month?" or "which batteries will fail before I return from a four-month stay at the summer cottage?". Cells last anywhere from a few months to a decade, drain profiles differ by chemistry, and replacement events are not currently tracked anywhere in HA. This change introduces a HACS-installable custom integration that turns raw battery percentages into per-battery predicted replacement dates, so the user can plan replacements ahead of trips or as part of a routine maintenance pass.

## What Changes

- New HA custom integration `battery_lifetime` (single-instance), packaged for HACS distribution alongside the existing PerfectDraft sibling project.
- Autodiscovery of all numeric battery sensors (`device_class: battery`, unit `%`); categorical, boolean, and voltage-only battery sensors are skipped with an info-level log entry.
- Per-battery companion entities: predicted replacement date sensor, prediction-quality sensor, observed drain-rate sensor, chemistry-profile switch (alkaline/lithium), tracking-enabled switch, replaced-on date, mark-replaced button, and optional per-battery threshold override.
- Integration-level entities and controls: "due this month" and "due next 3 months" count sensors, plus an options flow exposing the default profile and a bulk overview of all discovered batteries.
- Automatic replacement detection rule: a `<80% → ≥100%` jump within a 30-day window, with persistence and glitch-protection guards, commits a replacement event and emits a HA event `battery_lifetime_replacement_detected`. Stale jumps (>30 days between readings) raise a confirmation notification instead of auto-committing.
- Cold-start support: on first install or first-seen battery, the integration scans HA recorder and long-term statistics for the most recent qualifying jump to seed `replaced_on`; if none is found, it enters an `unknown`/`no_data` state and continues observing.
- Two chemistry profiles, each with their own discharge model, default threshold, and default lifetime: `alkaline` (smooth taper, EWMA from day one) and `lithium` (plateau-then-cliff, EWMA only after the % drops below the plateau). The integration-level default profile is `lithium`, overridable per battery.
- Graduated confidence ladder for predictions (`no_data`, `profile_default`, `low`, `medium`, `high`, `stale`) gated on time-since-replacement and observed drain, exposed as a companion sensor and as an attribute on the replace-by sensor.
- New service `battery_lifetime.predict_at` that forward-simulates every (non-excluded) battery to a target date and returns either the full list or only those projected to be below threshold, powering the cottage-departure use case.
- Persistent state via HA Storage helper, keyed by source-entity unique ID, containing replaced-on, profile, threshold override, tracking-enabled, and a small history snapshot used for the prediction.
- HACS packaging: repository-root `hacs.json`, `info.md`, `README.md`, and the canonical `custom_components/battery_lifetime/` integration layout with config and options flows.

## Capabilities

### New Capabilities
- `battery-discovery`: Enumerate HA battery entities, decide which are eligible for tracking, and let users opt individual batteries out without removing them from HA.
- `replacement-detection`: Detect battery-replacement events automatically from the source sensor's value pattern, allow manual marking, and seed `replaced_on` on cold start from HA recorder and long-term statistics.
- `lifetime-prediction`: Model per-battery drain using a chemistry profile, expose companion entities (replace-by date, drain rate, prediction quality, replaced-on, mark-replaced, threshold override, profile, tracking-enabled), and surface a graduated confidence value.
- `forward-prediction`: Provide a `battery_lifetime.predict_at` service that simulates each tracked battery forward to a target date and returns either all batteries or only the actionable ones.
- `battery-configuration`: Provide a single-instance HA config flow plus an options flow that exposes the default profile and a bulk per-battery overview, persist all tracking state across restarts, and package the integration for HACS distribution.

### Modified Capabilities
- (none — this is a greenfield repository with no existing specs.)

## Impact

- New repository content under `custom_components/battery_lifetime/` (config flow, options flow, coordinator, sensor/select-or-switch/button/date/number platforms, persistence, prediction model).
- New HACS metadata at the repository root (`hacs.json`, `info.md`, `README.md`).
- New service registered with HA: `battery_lifetime.predict_at`.
- New HA event emitted: `battery_lifetime_replacement_detected`.
- New `.storage/battery_lifetime` persistence file managed via the HA Storage helper.
- Depends on HA core APIs (entity registry, recorder, long-term statistics, storage helper, config/options flow); no third-party Python dependencies beyond what HA already ships.
- Documented expectation: predictions stay at `low` or below confidence for roughly the first 30–60 days post-install; this is honest behaviour, not a defect.
