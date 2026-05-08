## ADDED Requirements

### Requirement: Automatic replacement detection rule

The integration SHALL detect a battery replacement automatically when ALL of the following conditions hold simultaneously: the most recent prior reading was strictly less than `80%`; the new reading is greater than or equal to `100%`; the prior reading is no more than 30 days old; the `100%` reading is confirmed by either a subsequent update from the same source or by remaining at `≥100%` for one continuous hour, whichever comes first; the battery's `switch.<src>_tracking_enabled` is `on`. When all conditions hold, the integration SHALL set `replaced_on` to the timestamp of the first `≥100%` reading.

#### Scenario: Standard auto-detected replacement
- **WHEN** a tracked battery reports `47%` then later reports `100%`, the prior reading was 5 days ago, and a subsequent update 20 minutes later still reports `100%`
- **THEN** the integration sets that battery's `replaced_on` to the timestamp of the first `100%` reading and emits the `battery_lifetime_replacement_detected` event with `confirmed: true`

#### Scenario: Jump from above 80 percent is not a replacement
- **WHEN** a tracked battery jumps from `85%` directly to `100%`
- **THEN** the integration does NOT register a replacement and does NOT change `replaced_on`

#### Scenario: Confirmation by elapsed time
- **WHEN** a tracked battery jumps from `40%` to `100%` and no further source update arrives in the next hour, but the source remains visible to HA and continues to report `100%` at the one-hour mark
- **THEN** the integration treats the replacement as confirmed at the one-hour mark and sets `replaced_on` to the timestamp of the first `100%` reading

### Requirement: Glitch protection on the 100 percent confirmation

The integration SHALL discard a candidate `≥100%` replacement event if the source reading drops below `95%` within one hour of the candidate `100%` reading without any intervening valid update.

#### Scenario: Single-sample spike to 100 is rejected
- **WHEN** a tracked battery briefly reports `100%` for a single update and the next update 10 minutes later reports `30%`
- **THEN** the integration logs the event at debug level, does NOT register a replacement, and does NOT change `replaced_on`

#### Scenario: Confirmed 100 followed by a normal drop hours later
- **WHEN** a tracked battery is confirmed at `100%` (per the confirmation rule) and several hours later the natural drain produces a reading of `99%`
- **THEN** the previously-recorded replacement remains in effect; the later `99%` reading is treated as normal post-replacement drain, not a glitch

### Requirement: Stale-prior protection

The integration SHALL NOT auto-commit a replacement when the most recent prior reading is more than 30 days old. Instead, it SHALL raise a persistent Home Assistant notification listing the source entity, the prior reading and its age, and the new reading, and instructing the user to call one of three Home Assistant services to confirm, dismiss, or exclude the battery: `battery_lifetime.confirm_stale_replacement`, `battery_lifetime.dismiss_stale_replacement`, or `battery_lifetime.exclude_stale_replacement`. Each service takes a single `entity_id` field naming the source battery sensor.

#### Scenario: Long offline gap then 100 percent
- **WHEN** a tracked battery's last reading was `72%` 47 days ago and the next reading is `100%`
- **THEN** the integration creates a persistent notification asking the user to call one of the three services, does NOT change `replaced_on` automatically, and emits `battery_lifetime_replacement_detected` only after the user calls `battery_lifetime.confirm_stale_replacement`

#### Scenario: User confirms a stale-prior detection
- **WHEN** the user calls `battery_lifetime.confirm_stale_replacement` with the affected source `entity_id`
- **THEN** the integration sets `replaced_on` to the timestamp of the first `100%` reading observed during the stale episode, dismisses the persistent notification, and emits `battery_lifetime_replacement_detected` with `confirmed: true` and `source: stale_confirmed`

#### Scenario: User dismisses a stale-prior detection
- **WHEN** the user calls `battery_lifetime.dismiss_stale_replacement` with the affected source `entity_id`
- **THEN** the integration discards the candidate, dismisses the persistent notification, leaves `replaced_on` unchanged, leaves `switch.<src>_tracking_enabled` unchanged, and does NOT emit a replacement event

#### Scenario: User excludes a battery from a stale-prior notification
- **WHEN** the user calls `battery_lifetime.exclude_stale_replacement` with the affected source `entity_id`
- **THEN** the integration discards the candidate, dismisses the persistent notification, sets `switch.<src>_tracking_enabled` to `off` for that battery, and does NOT emit a replacement event

### Requirement: Manual replacement controls

The integration SHALL expose `button.<src>_mark_replaced` to record an immediate replacement event using the current time as `replaced_on`, and `date.<src>_replaced_on` to manually set or correct `replaced_on` to any date not in the future. Both manual paths MUST emit `battery_lifetime_replacement_detected` with the appropriate timestamp.

#### Scenario: User presses mark-replaced
- **WHEN** the user presses `button.<src>_mark_replaced`
- **THEN** the integration sets that battery's `replaced_on` to the current Home Assistant time, resets the EWMA drain-rate state, and emits `battery_lifetime_replacement_detected` with `confirmed: true` and an event field indicating the source was manual

#### Scenario: User edits replaced-on directly
- **WHEN** the user sets `date.<src>_replaced_on` to a date in the past (not in the future)
- **THEN** the integration updates that battery's `replaced_on` to the chosen date, recomputes drain-rate state, and emits `battery_lifetime_replacement_detected` with the chosen date and an event field indicating manual edit

#### Scenario: Future date is rejected
- **WHEN** the user attempts to set `date.<src>_replaced_on` to a date in the future
- **THEN** the integration rejects the change, restores the previous value, and surfaces the validation error to the user

### Requirement: Cold-start replaced-on backfill

When a battery is first seen by the integration and has no persisted `replaced_on`, the integration SHALL search Home Assistant long-term statistics (preferred) and the recorder (fallback) for the most recent `<80% → ≥100%` jump that satisfies the staleness and glitch rules, and SHALL use that timestamp as `replaced_on` if found. If no qualifying jump is found, the integration SHALL set `replaced_on` to `unknown`, set the prediction quality to `no_data`, and continue listening; if at least 7 days of post-attach data with at least 1% observed drain accumulate, the integration SHALL extrapolate backwards along the active profile to estimate `replaced_on` and update accordingly.

#### Scenario: Long-term statistics yield a replacement
- **WHEN** an existing battery is first seen at integration install and long-term statistics contain a qualifying `<80% → ≥100%` jump 92 days ago
- **THEN** the integration sets `replaced_on` to that timestamp and emits `battery_lifetime_replacement_detected` with an event field indicating the source was cold-start backfill

#### Scenario: No history available
- **WHEN** an existing battery is first seen and neither long-term statistics nor the recorder contain a qualifying jump
- **THEN** the integration sets `replaced_on` to `unknown`, sets `sensor.<src>_prediction_quality` to `no_data`, and `sensor.<src>_replace_by` to `unknown`

#### Scenario: Backwards extrapolation after observation
- **WHEN** a battery has been in `no_data` state for 8 days and the source has observed a 2% drop with consistent updates
- **THEN** the integration extrapolates backward along the active profile to estimate `replaced_on`, sets the estimate as `replaced_on`, and updates `sensor.<src>_prediction_quality` to `low` or higher according to the confidence ladder

### Requirement: Replacement event payload

When the integration commits a replacement (auto, manual, cold-start backfill, or stale-prior confirmed), it SHALL emit the Home Assistant event `battery_lifetime_replacement_detected` whose payload includes the source `entity_id`, the source `unique_id`, `previous_pct`, `current_pct`, `prior_reading_age_seconds`, `replaced_on` (as ISO 8601), `confirmed` (boolean), and `source` (one of `auto`, `manual_button`, `manual_date_edit`, `cold_start_backfill`, `stale_confirmed`).

#### Scenario: Event payload completeness on auto-detection
- **WHEN** an auto-detected replacement is committed
- **THEN** the emitted event includes all required fields, `confirmed` is `true`, and `source` is `auto`

#### Scenario: Event payload on cold-start backfill
- **WHEN** a cold-start backfill commits a `replaced_on`
- **THEN** the emitted event has `source: cold_start_backfill`, `confirmed: true`, and `prior_reading_age_seconds` reflecting the gap between the inferred prior `<80%` reading and the inferred `100%` reading
