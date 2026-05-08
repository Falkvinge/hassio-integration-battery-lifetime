## ADDED Requirements

### Requirement: Per-battery companion entity set

For every tracked battery, the integration SHALL create the following companion entities, each with a unique ID derived from the source entity's `unique_id`:

- `sensor.<src>_replace_by` — `device_class: timestamp`, state is the predicted replacement datetime or `unknown`.
- `sensor.<src>_prediction_quality` — state is one of `no_data`, `profile_default`, `low`, `medium`, `high`, `stale`.
- `sensor.<src>_drain_rate` — state is the current EWMA drain rate in `%/day`, or `unknown`.
- `switch.<src>_profile_lithium` — `on` means lithium, `off` means alkaline. Default reflects the integration-level default profile.
- `switch.<src>_tracking_enabled` — `on` means tracked. Defaults to `on` when a battery is first discovered.
- `date.<src>_replaced_on` — manually editable replaced-on date, never in the future.
- `button.<src>_mark_replaced` — fires a manual replacement event when pressed.
- `number.<src>_threshold_override` — optional `%` override of the active profile's default threshold; blank means use the profile default.

#### Scenario: Companion entities created on discovery
- **WHEN** a battery is first discovered as eligible
- **THEN** all eight companion entities listed above MUST exist within the next coordinator update

#### Scenario: Companion entity unique IDs are stable
- **WHEN** Home Assistant restarts
- **THEN** each companion entity retains the same unique ID and is associated with the same persisted state for that source `unique_id`

### Requirement: Chemistry profiles

The integration SHALL provide exactly two chemistry profiles for v1: `alkaline` and `lithium`. Each profile defines a discharge-curve shape, a default replacement threshold (in `%`), and a default lifetime (in days). The default values SHALL be: `alkaline` with smooth-taper shape, threshold `15%`, default lifetime `365` days; `lithium` with plateau-then-cliff shape, threshold `5%`, default lifetime `1825` days. The active profile for a battery is determined by `switch.<src>_profile_lithium`.

#### Scenario: Default profile applied to a new battery
- **WHEN** a battery is discovered for the first time and the integration-level default profile is `lithium`
- **THEN** `switch.<src>_profile_lithium` is `on` for that battery and the lithium profile is used

#### Scenario: User flips profile per battery
- **WHEN** the user toggles `switch.<src>_profile_lithium` from `on` to `off`
- **THEN** that battery's active profile becomes `alkaline`, the EWMA state is preserved, and the next coordinator update recomputes `sensor.<src>_replace_by` against the alkaline threshold and shape

#### Scenario: Threshold override takes precedence over profile default
- **WHEN** the user sets `number.<src>_threshold_override` to a non-blank value `T`
- **THEN** all extrapolation and prediction for that battery uses `T` as the threshold instead of the active profile's default

### Requirement: EWMA drain-rate computation

The integration SHALL compute drain rate for each tracked battery as an exponentially-weighted moving average of `%/day` over the readings observed since the most recent `replaced_on`, with the window capped at the most recent 60 days of post-replacement data, weighting more recent samples higher than older samples. The integration SHALL update the EWMA on every source-state update that produces a non-increasing reading and SHALL NOT include increases in the EWMA except through full reset on a confirmed replacement.

#### Scenario: Drain rate updates on a normal decrease
- **WHEN** a tracked battery's source reading decreases by `0.4%` over a 24-hour interval since the previous reading
- **THEN** the integration ingests that decrease into the EWMA and updates `sensor.<src>_drain_rate`

#### Scenario: Replacement fully resets EWMA state
- **WHEN** a confirmed replacement is committed for a tracked battery
- **THEN** the EWMA state for that battery is cleared and recomputed only from post-replacement readings

#### Scenario: Increases without replacement do not pollute the EWMA
- **WHEN** a tracked battery's source reading increases by `2%` (e.g. due to a small temperature-driven uptick) without triggering replacement detection
- **THEN** the increase is excluded from the EWMA and `sensor.<src>_drain_rate` is held at its prior value

### Requirement: Lithium plateau handling

While a battery's active profile is `lithium` and its source reading is greater than or equal to `85%`, the integration SHALL treat the battery as on the chemistry plateau: `sensor.<src>_replace_by` SHALL be reported as `replaced_on + profile.default_lifetime`, `sensor.<src>_prediction_quality` SHALL remain at `profile_default` regardless of elapsed time, and the EWMA state SHALL be ignored for the purpose of producing `sensor.<src>_replace_by`. Once the source reading drops below `85%`, the integration SHALL switch to EWMA-based extrapolation against the active threshold.

#### Scenario: Lithium battery on plateau
- **WHEN** a lithium-profile battery's source reads `99%` and `replaced_on` was 200 days ago
- **THEN** `sensor.<src>_replace_by` reports `replaced_on + 1825 days` and `sensor.<src>_prediction_quality` reports `profile_default`

#### Scenario: Lithium battery leaves plateau
- **WHEN** a lithium-profile battery's source reading drops from `87%` to `82%`
- **THEN** the next coordinator update switches `sensor.<src>_replace_by` to EWMA-based extrapolation against the lithium threshold and the prediction quality is reassessed against the confidence ladder

#### Scenario: Alkaline battery is not treated as on a plateau
- **WHEN** an alkaline-profile battery's source reads `99%` and `replaced_on` was 5 days ago
- **THEN** the integration uses EWMA-based extrapolation as soon as enough drain is observed; the plateau rule does not apply

### Requirement: Confidence ladder

The integration SHALL set `sensor.<src>_prediction_quality` according to the following ladder, evaluated on every coordinator update:

- `no_data` — `replaced_on` is `unknown` and no qualifying drain has been observed yet.
- `profile_default` — `replaced_on` is known but the gating thresholds for `low` are not met, or the battery is on the lithium plateau.
- `low` — at least 7 days have elapsed since `replaced_on` and at least `1%` total drain has been observed.
- `medium` — at least 30 days have elapsed since `replaced_on` and at least `5%` total drain has been observed.
- `high` — at least 60 days have elapsed since `replaced_on` and at least `10%` total drain has been observed.
- `stale` — orthogonal flag, set when the source entity has produced no update in the last 7 days; this state SHALL take precedence over the others when active.

The same value SHALL be exposed as the `confidence` attribute on `sensor.<src>_replace_by`.

#### Scenario: Brand-new battery shows no_data when no history is available
- **WHEN** a battery is first discovered, no cold-start backfill found a replacement, and no drain has been observed yet
- **THEN** `sensor.<src>_prediction_quality` is `no_data` and `sensor.<src>_replace_by` is `unknown`

#### Scenario: Recently replaced battery shows profile_default
- **WHEN** a battery has `replaced_on` set to 2 days ago and 0% drain has been observed
- **THEN** `sensor.<src>_prediction_quality` is `profile_default` and `sensor.<src>_replace_by` reports `replaced_on + profile.default_lifetime`

#### Scenario: Confidence climbs as data accumulates
- **WHEN** an alkaline battery has `replaced_on` 35 days ago and the source has observed `7%` total drain
- **THEN** `sensor.<src>_prediction_quality` is `medium`

#### Scenario: Stale source overrides everything else
- **WHEN** any tracked battery's source has produced no update in the last 7 days
- **THEN** `sensor.<src>_prediction_quality` reports `stale` regardless of the other ladder gates, and `sensor.<src>_replace_by` retains its last computed value

### Requirement: Replacement-by computation

The integration SHALL compute `sensor.<src>_replace_by` for each tracked battery as follows: if the prediction quality is `no_data`, the state is `unknown`; if the prediction quality is `profile_default` (including lithium plateau), the state is `replaced_on + profile.default_lifetime`; otherwise, the state is the timestamp at which the source reading is projected to reach the active threshold given the current EWMA drain rate (linear projection from the most recent observed reading), and is reported as a Home Assistant `timestamp`-class sensor.

#### Scenario: Alkaline projection
- **WHEN** an alkaline-profile battery has `replaced_on` 60 days ago, the most recent reading is `78%`, the EWMA drain rate is `0.30 %/day`, and the active threshold is `15%`
- **THEN** `sensor.<src>_replace_by` reports a timestamp roughly `(78 - 15) / 0.30 = 210` days after the most recent reading

#### Scenario: Lithium projection after leaving plateau
- **WHEN** a lithium-profile battery has dropped to `40%`, the EWMA drain rate is `0.50 %/day`, and the active threshold is `5%`
- **THEN** `sensor.<src>_replace_by` reports a timestamp roughly `(40 - 5) / 0.50 = 70` days after the most recent reading

#### Scenario: Stale source freezes replace_by at last good value
- **WHEN** a battery's source has produced no update in the last 7 days
- **THEN** `sensor.<src>_replace_by` reports the last computed timestamp (not recomputed against the now-old EWMA), and the attribute `last_seen` reflects the time of the last update

### Requirement: Integration-level summary sensors

The integration SHALL provide two integration-level sensors that count tracked batteries projected to need replacement: `sensor.battery_lifetime_due_this_month` (count of tracked batteries whose `replace_by` is on or before the last day of the current local-time month) and `sensor.battery_lifetime_due_next_3_months` (count of tracked batteries whose `replace_by` is on or before the date three months from now). Disabled batteries MUST be excluded from these counts.

#### Scenario: Counts reflect current state
- **WHEN** at the time of computation 3 tracked batteries have `replace_by` within the current month and 7 have `replace_by` within the next three months
- **THEN** `sensor.battery_lifetime_due_this_month` is `3` and `sensor.battery_lifetime_due_next_3_months` is `7`

#### Scenario: Disabled batteries are excluded
- **WHEN** a battery whose `replace_by` is within the current month has `switch.<src>_tracking_enabled` set to `off`
- **THEN** that battery is NOT counted in either summary sensor
