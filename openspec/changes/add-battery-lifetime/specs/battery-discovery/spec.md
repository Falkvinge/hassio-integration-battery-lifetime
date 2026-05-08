## ADDED Requirements

### Requirement: Eligible source entities

The integration SHALL discover battery source entities from the Home Assistant entity registry and treat an entity as eligible if and only if all of the following hold: the entity's `device_class` is `battery`, its `unit_of_measurement` is `%`, its current state is a number between `0` and `100` inclusive, and the entity is not a companion entity created by this integration.

#### Scenario: Numeric percent battery sensor is discovered
- **WHEN** an entity with `device_class: battery`, unit `%`, and a numeric state in the range `[0, 100]` is present in the entity registry
- **THEN** the integration treats that entity as eligible and creates the per-battery companion entity set for it

#### Scenario: Categorical battery sensor is skipped
- **WHEN** a battery entity reports a non-numeric state such as `low`, `normal`, or `full`
- **THEN** the integration logs an info-level message naming the entity and its observed state, and does not create companion entities for it

#### Scenario: Boolean low-battery sensor is skipped
- **WHEN** an entity has `device_class: battery` but is a binary sensor or otherwise reports `on`/`off`
- **THEN** the integration logs an info-level message naming the entity and does not create companion entities for it

#### Scenario: Voltage-only battery sensor is skipped
- **WHEN** a battery entity reports its state in volts or millivolts (`unit_of_measurement` is `V` or `mV`) rather than `%`
- **THEN** the integration logs an info-level message naming the entity and does not create companion entities for it

#### Scenario: Companion entity is not re-discovered as a source
- **WHEN** the integration enumerates eligible entities
- **THEN** entities created by the integration itself (matching its domain prefix in the unique-id namespace) MUST be excluded from the eligible source list

### Requirement: Identity of a tracked battery

The integration SHALL identify each tracked battery by the source entity's entity-registry `unique_id`, not by its `entity_id`. All persistence, companion-entity unique IDs, and replacement-event correlation MUST key off `unique_id`.

#### Scenario: Source entity is renamed
- **WHEN** the user renames the source battery entity (changes `entity_id`)
- **THEN** the integration retains all per-battery state, replaced-on, profile, and history because the underlying `unique_id` is unchanged

#### Scenario: Source entity has no unique_id
- **WHEN** an otherwise-eligible source entity has no `unique_id` in the entity registry
- **THEN** the integration logs a warning naming the entity, does not create companion entities for it, and re-evaluates eligibility if the entity is later assigned a `unique_id`

### Requirement: Continuous discovery

The integration SHALL react to entity-registry changes during runtime so that newly added eligible source entities begin tracking without requiring an integration reload, and removed entities transition gracefully.

#### Scenario: A new battery sensor appears at runtime
- **WHEN** an integration adds a new eligible battery entity to the entity registry while `battery_lifetime` is loaded
- **THEN** the integration creates the per-battery companion entity set within the next coordinator update

#### Scenario: A source battery sensor is removed
- **WHEN** an eligible source entity is removed from the entity registry
- **THEN** the integration marks its companion entities as `unavailable` and retains the persisted per-battery state for at least 30 days in case the source returns

#### Scenario: A removed source entity reappears within the retention window
- **WHEN** a source entity that was removed and is still within the 30-day retention window reappears with the same `unique_id`
- **THEN** the integration restores its companion entities to the previously persisted state without resetting `replaced_on`, profile, or history

### Requirement: Per-battery opt-out

The integration SHALL expose a `switch.<src>_tracking_enabled` companion entity for every tracked battery so the user can disable tracking for a specific battery without removing the integration or deleting the source entity. Disabled batteries MUST NOT participate in replacement detection, prediction, or the forward-prediction service.

#### Scenario: User disables tracking for a battery
- **WHEN** the user turns `switch.<src>_tracking_enabled` to `off`
- **THEN** the integration stops updating the companion sensors' values, stops responding to source-state changes for replacement detection on that battery, and excludes the battery from `predict_at` results when `include_excluded` is `false`

#### Scenario: User re-enables tracking for a previously disabled battery
- **WHEN** the user turns `switch.<src>_tracking_enabled` back to `on`
- **THEN** the integration resumes detection and prediction using whatever persisted state existed when tracking was disabled, without forcing a new `replaced_on`

#### Scenario: Disabled battery is included on explicit request
- **WHEN** a caller invokes `battery_lifetime.predict_at` with `include_excluded: true`
- **THEN** the response includes disabled batteries with their last computed prediction state and a flag indicating they are not currently tracked
