## ADDED Requirements

### Requirement: Single-instance config flow

The integration SHALL provide a Home Assistant config flow that allows the user to add the integration once. Subsequent attempts to add a second instance SHALL be rejected with a `single_instance_allowed` reason. The initial config flow SHALL NOT require any per-battery configuration; autodiscovery handles enumeration.

#### Scenario: First add succeeds without per-battery questions
- **WHEN** the user adds the `Battery Lifetime` integration via the Home Assistant UI for the first time
- **THEN** the config flow completes without asking the user about specific batteries and the integration begins discovering eligible batteries on next coordinator update

#### Scenario: Second add is rejected
- **WHEN** the user attempts to add a second instance of `Battery Lifetime`
- **THEN** the config flow aborts with reason `single_instance_allowed`

### Requirement: Options flow with default profile and bulk overview

The integration SHALL provide an options flow with two sections: (1) a default-profile selector (`alkaline` or `lithium`) used as the initial profile for newly discovered batteries, defaulting to `lithium`; (2) a bulk overview that lists every currently tracked battery with editable `tracking_enabled`, `profile_lithium`, optional `threshold_override`, and read-only `replaced_on`, `prediction_quality`, `replace_by`. Edits made in the bulk overview SHALL persist to the same store used by the per-battery companion entities and SHALL be reflected by those entities on the next coordinator update.

#### Scenario: Default profile applies to newly discovered batteries
- **WHEN** the user changes the integration-level default profile from `lithium` to `alkaline` and a new eligible battery is discovered later
- **THEN** the new battery's `switch.<src>_profile_lithium` defaults to `off`

#### Scenario: Default profile change does not retroactively change existing batteries
- **WHEN** the user changes the integration-level default profile and existing batteries have already been discovered
- **THEN** the existing batteries' profiles are unchanged; the change applies only to batteries discovered after the setting change

#### Scenario: Bulk-overview edit propagates to companion entities
- **WHEN** the user changes a battery's `tracking_enabled` or `profile_lithium` from the bulk overview
- **THEN** within the next coordinator update, the corresponding `switch.<src>_tracking_enabled` or `switch.<src>_profile_lithium` reflects the new state and the change is persisted in the integration's store

### Requirement: Persistent state via Home Assistant Storage

The integration SHALL persist its state via the Home Assistant Storage helper at `.storage/battery_lifetime`. The store schema SHALL be versioned. Per-battery entries SHALL be keyed by source `unique_id` and SHALL contain at minimum: `replaced_on`, active `profile` selection, `threshold_override` (nullable), `tracking_enabled`, the EWMA drain-rate state, the most recent observed reading, the timestamp of that reading, the last computed `replace_by`, and `removed_at` (nullable, the timestamp at which the source entity was removed from the registry, used to drive the 30-day retention window before the entry is pruned). Integration-level entries SHALL contain at minimum: schema version and `default_profile`.

#### Scenario: State survives a Home Assistant restart
- **WHEN** Home Assistant restarts after the integration has tracked batteries for any duration
- **THEN** all per-battery `replaced_on`, profile, threshold override, tracking-enabled, EWMA state, and last-good `replace_by` values are restored from `.storage/battery_lifetime` and the companion entities reflect that state on first coordinator update after restart

#### Scenario: Schema version is recorded
- **WHEN** the integration writes to the store
- **THEN** the on-disk JSON contains a `version` field reflecting the current schema version of the integration

#### Scenario: Forward-compatible schema migration
- **WHEN** the integration loads a store written by an older schema version
- **THEN** the integration migrates the data forward, writes the migrated form back to disk on next save, and logs the migration step at info level

### Requirement: HACS packaging

The repository SHALL be installable via HACS as a custom integration. The repository root SHALL contain `hacs.json` with the integration's name and required HA version, an `info.md` rendered inside HACS, and a `README.md` at minimum describing installation, the discovery model, the chemistry profiles, the cold-start expectation, and the `predict_at` service. The integration source SHALL live at `custom_components/battery_lifetime/` and SHALL include a valid `manifest.json` with `domain: battery_lifetime`, an entry in HACS's expected directory layout, and HACS-compatible versioning.

#### Scenario: HACS metadata is present at repository root
- **WHEN** the repository is inspected after the change is applied
- **THEN** `hacs.json`, `info.md`, and `README.md` exist at the repository root and `custom_components/battery_lifetime/manifest.json` declares the integration's domain, name, version, and required HA version

#### Scenario: HACS-installable from a custom repository
- **WHEN** a HACS user adds the repository as a custom integration repository in HACS
- **THEN** HACS lists the integration with its name, description (from `info.md`), and version, and the install action places the contents of `custom_components/battery_lifetime/` into the user's HA `custom_components/` folder

### Requirement: Integration documentation expectations

The integration's `README.md` SHALL document at minimum: the install path (HACS), the eligibility rules for source entities (numeric percent battery sensors only; categorical/boolean/voltage skipped), the auto-replacement rule and its glitch and stale-prior protections, the manual replacement controls, the two chemistry profiles and their default thresholds and lifetimes, the integration-level default-profile setting, the per-battery companion entities and their meanings, the confidence ladder including the explicit caveat that fresh installs spend 30–60 days at low confidence, the lithium plateau caveat, the `predict_at` service signature with response schema, and the explicit non-goals (rechargeables, voltage-only, categorical, multi-cell awareness).

#### Scenario: README covers the documented surfaces
- **WHEN** a new user reads `README.md` end-to-end
- **THEN** they can identify which of their HA battery entities will be tracked, understand why predictions look stale or default for the first weeks, know how to mark a battery as replaced manually, and know how to call `predict_at` from an automation or template
