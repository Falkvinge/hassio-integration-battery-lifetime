## ADDED Requirements

### Requirement: predict_at service

The integration SHALL register a Home Assistant service `battery_lifetime.predict_at` that simulates each tracked battery forward to a target date and returns either every battery's projected state (default) or only those projected to be at or below their active threshold (`actionable_only: true`). The service SHALL accept a service-call response so callers can use the result in scripts, automations, and templates.

#### Scenario: Service is registered
- **WHEN** the integration finishes loading
- **THEN** Home Assistant's service registry contains `battery_lifetime.predict_at` and its `services.yaml` description matches the schema below

#### Scenario: Default returns every tracked battery
- **WHEN** the service is called with `data: { date: "2026-10-15" }`
- **THEN** the response includes one entry per tracked, non-excluded battery, regardless of whether each is projected above or below threshold

#### Scenario: actionable_only filters the result
- **WHEN** the service is called with `data: { date: "2026-10-15", actionable_only: true }`
- **THEN** the response includes only batteries whose `predicted_state` would be `below_threshold` at the target date

### Requirement: Service input schema

The integration SHALL accept the following service-call data fields: `date` (required, ISO 8601 calendar date), `margin_days` (optional integer, default `0`, applied as a safety margin that extends the effective evaluation date so callers can be conservative about prediction noise), `actionable_only` (optional boolean, default `false`), `include_excluded` (optional boolean, default `false`).

#### Scenario: Missing date is rejected
- **WHEN** the service is called with no `date` field
- **THEN** the call fails with a Home Assistant service-validation error and no response is returned

#### Scenario: Margin extends the effective evaluation date
- **WHEN** the service is called with `data: { date: "2026-10-15", margin_days: 14, actionable_only: true }`
- **THEN** any battery whose projected reading at `2026-10-29` is at or below its active threshold is included in the response — applying a positive margin makes the actionable filter MORE inclusive, not less

#### Scenario: Excluded batteries are included on request
- **WHEN** the service is called with `data: { date: "2026-10-15", include_excluded: true }`
- **THEN** the response includes batteries whose `switch.<src>_tracking_enabled` is `off`, each carrying a flag indicating they are not currently tracked, and each carrying their last computed prediction state

### Requirement: Service response schema

The service SHALL return a response object with a top-level `results` key whose value is a list. Each list entry SHALL include: `entity_id` (source), `replace_by_entity` (the integration's companion `sensor.<src>_replace_by`), `unique_id` (source), `profile` (`alkaline` or `lithium`), `threshold_pct` (the active threshold for the battery, accounting for any per-battery override), `drain_rate_pct_day` (current EWMA), `predicted_pct_at_date` (the projected source reading at the target date), `predicted_state` (one of `ok`, `below_threshold`, `unknown`), `confidence` (the same value as the battery's `prediction_quality`), `tracking_enabled` (boolean), and where applicable `excluded` (boolean, set to `true` when `include_excluded: true` causes a disabled battery to appear).

#### Scenario: Ok and below-threshold cases are reported
- **WHEN** the service projects a battery to `52%` at the target date and its threshold is `15%`
- **THEN** that battery's response entry has `predicted_pct_at_date: 52`, `predicted_state: "ok"`, and includes its current `confidence`

#### Scenario: Unknown is reported when prediction is not possible
- **WHEN** the service projects a battery whose `prediction_quality` is `no_data`
- **THEN** that battery's response entry has `predicted_pct_at_date: null` and `predicted_state: "unknown"`

#### Scenario: Lithium plateau is honored in projection
- **WHEN** the service projects a lithium-profile battery whose source currently reads `93%` to a target date 60 days out
- **THEN** the projection reflects the plateau (the projected reading does not drop below `85%` before its plateau is exhausted relative to `replaced_on`), and the entry's `confidence` remains `profile_default` if the projection has not yet left the plateau by the target date

### Requirement: Forward simulation honors profile shape

The integration SHALL simulate each battery forward to the target date using the active profile's discharge-curve shape, the EWMA drain rate, the source's most recent reading, the active threshold (including any override), and (for lithium) the plateau gate. The simulation SHALL NOT alter persisted state; it is read-only.

#### Scenario: Forward simulation does not alter state
- **WHEN** the service is invoked any number of times
- **THEN** no battery's `replaced_on`, EWMA state, or companion-entity values are altered as a side effect of those invocations

#### Scenario: Profile change after a forward simulation
- **WHEN** a user runs the service, then toggles `switch.<src>_profile_lithium` for a battery, then runs the service again with the same arguments
- **THEN** the second response reflects the new profile's shape and threshold for that battery
