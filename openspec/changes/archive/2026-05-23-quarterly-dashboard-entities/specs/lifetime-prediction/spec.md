## ADDED Requirements

### Requirement: Next-quarter summary sensor

The integration SHALL provide an integration-level sensor `sensor.battery_lifetime_due_next_quarter` that counts tracked batteries whose `replace_by` timestamp is on or before 23:59:59 UTC on the last day of the calendar quarter immediately following the reference quarter of the current UTC date. Disabled batteries (`switch.<src>_tracking_enabled` off) MUST be excluded. Batteries whose `replace_by` is unknown (`no_data`) MUST NOT be counted.

#### Scenario: Count reflects next-quarter cutoff

- **WHEN** the current UTC date is 15 May 2026 and 4 tracked batteries have `replace_by` on or before 30 September 2026 23:59:59 UTC
- **THEN** `sensor.battery_lifetime_due_next_quarter` reports `4`

#### Scenario: Disabled batteries are excluded

- **WHEN** a tracked battery has `replace_by` within the next-quarter window but `switch.<src>_tracking_enabled` is `off`
- **THEN** that battery is NOT included in the count

#### Scenario: December rolls into March next year

- **WHEN** the current UTC date is 10 December 2026 and a battery has `replace_by` on 15 March 2027
- **THEN** that battery IS counted because the next-quarter end is 31 March 2027 23:59:59 UTC

### Requirement: days_until_replace attribute on replace-by sensor

Each `sensor.<src>_replace_by` companion SHALL expose a `days_until_replace` attribute when `replace_by` is known: the signed integer number of whole UTC days from the current instant to `replace_by`, rounded toward zero (negative when overdue). When `replace_by` is unknown (`no_data`), the attribute MUST be omitted.

#### Scenario: Future replacement

- **WHEN** `replace_by` is 10 UTC days in the future
- **THEN** `days_until_replace` is `10`

#### Scenario: Overdue replacement

- **WHEN** `replace_by` was 3 UTC days ago
- **THEN** `days_until_replace` is `-3`

#### Scenario: Unknown replace-by

- **WHEN** prediction quality is `no_data` and `replace_by` is unknown
- **THEN** the `days_until_replace` attribute is not present

### Requirement: Per-battery due-next-quarter binary companion

For every tracked battery, the integration SHALL create `binary_sensor.<src>_due_next_quarter` on the same companion device as the other per-source entities. It SHALL be `on` when the battery is tracked (`tracking_enabled` true), prediction quality is not `no_data`, `replace_by` is set, and `replace_by` is on or before the next-quarter end (same cutoff as the summary sensor). It SHALL be `off` otherwise.

#### Scenario: Battery due within next quarter

- **WHEN** the current UTC date is 1 March 2026, a battery is tracked with `replace_by` on 15 June 2026, and confidence is `medium`
- **THEN** `binary_sensor.<src>_due_next_quarter` is `on`

#### Scenario: Battery due after next quarter

- **WHEN** the current UTC date is 1 March 2026 and a battery has `replace_by` on 15 August 2026
- **THEN** `binary_sensor.<src>_due_next_quarter` is `off`

#### Scenario: Untracked battery is off

- **WHEN** `switch.<src>_tracking_enabled` is `off`
- **THEN** `binary_sensor.<src>_due_next_quarter` is `off` regardless of `replace_by`

#### Scenario: No-data battery is off

- **WHEN** prediction quality is `no_data`
- **THEN** `binary_sensor.<src>_due_next_quarter` is `off`

### Requirement: Per-battery companion entity set includes due-next-quarter binary

The per-battery companion entity set SHALL include `binary_sensor.<src>_due_next_quarter` in addition to the existing eight companions. The binary sensor MUST share the same companion device and deterministic unique-id scheme as the other per-source entities.

#### Scenario: New battery discovery creates binary companion

- **WHEN** a new eligible battery source is discovered and companion entities are created
- **THEN** `binary_sensor.<src>_due_next_quarter` exists alongside the other per-source companions within the next coordinator update
