# Battery Lifetime

> A Home Assistant integration that turns raw `battery %` sensors into
> **actionable replacement-date predictions**, with auto-detected replacement
> events, two chemistry profiles (alkaline / lithium primary), and a forward-
> prediction service for "before I leave the cottage" planning.

Home Assistant gives you `sensor.foo_battery = 47%`. This integration adds
`sensor.foo_battery_replace_by = 2026-09-14`, plus the small set of
companion entities you need to tell it about chemistry, mark replacements
manually, and opt individual batteries out.

## Why this exists

The built-in HA battery percentage sensors are not actionable. You can't
sort batteries by "needs replacement soon", you can't ask HA "which of these
will fail before I'm back from the cottage?", and you can't tell HA which
batteries are which chemistry. This integration fills that gap, with
deliberately transparent extrapolation (no ML, no Bayesian magic — just a
rolling drain rate plus chemistry-aware projection).

## Installation

### HACS (recommended)

This integration is distributed as a HACS **custom integration**. The
canonical repository is hosted on `git.falkvinge.net`. To install via HACS:

1. In Home Assistant, open **HACS → Integrations → ⋮ → Custom repositories**.
2. Add `https://github.com/<mirror>/hassio-battery-lifetime-integration` (or
   whichever GitHub mirror you maintain) with category **Integration**.
   *(HACS requires GitHub-hosted repositories. The git.falkvinge.net repo
   is the source of truth; mirror it to GitHub for HACS distribution.)*
3. Search for **Battery Lifetime** in HACS, install, restart Home Assistant.
4. **Settings → Devices & Services → Add Integration → Battery Lifetime**.

### Manual

1. Copy `custom_components/battery_lifetime/` into your HA `config/custom_components/`.
2. Restart Home Assistant.
3. **Settings → Devices & Services → Add Integration → Battery Lifetime**.

## What gets discovered

The integration enumerates all entities in the entity registry with:

- `device_class: battery`
- `unit_of_measurement: %`
- a numeric current state in the range `[0, 100]`
- a stable `unique_id`

The following are **deliberately skipped** (logged at info level on first sight):

- categorical battery sensors (`low` / `normal` / `full`)
- boolean low-battery sensors (`binary_sensor.*_battery_low`, on/off)
- voltage-only battery sensors (`V` or `mV`)

If you want a sensor like that tracked, expose it as a `%` sensor via a
`template` integration.

## Per-battery companion entities

For every tracked battery `sensor.foo_battery`, the integration creates:

| Entity                                    | Type            | Meaning                                                      |
| ----------------------------------------- | --------------- | ------------------------------------------------------------ |
| `sensor.foo_battery_replace_by`           | `timestamp`     | Predicted replacement datetime, or `unknown`                 |
| `sensor.foo_battery_prediction_quality`   | enum            | `no_data` / `profile_default` / `low` / `medium` / `high` / `stale` |
| `sensor.foo_battery_drain_rate`           | `%/d`           | Observed EWMA drain rate                                     |
| `switch.foo_battery_profile_lithium`      | switch          | `on` = lithium, `off` = alkaline (icons differ per state)    |
| `switch.foo_battery_tracking_enabled`     | switch          | `on` = tracked. Toggle off to opt out without deleting.      |
| `date.foo_battery_replaced_on`            | date            | Manual override of replaced-on. Future dates rejected.       |
| `button.foo_battery_mark_replaced`        | button          | Sets `replaced_on` to now and resets the model.              |
| `number.foo_battery_threshold_override`   | number          | Optional `%` override. Blank means "use profile default."    |

And two integration-level summary sensors:

- `sensor.battery_lifetime_due_this_month`
- `sensor.battery_lifetime_due_next_3_months`

## Replacement detection

Replacements are detected automatically from the source sensor's value pattern.
A replacement is committed when **all** of the following hold:

1. The most recent prior reading was **strictly less than 80%**.
2. The new reading is **at least 100%**.
3. The prior reading is **at most 30 days old**.
4. The 100% reading **persists** across at least one more update from the
   source, or for one continuous hour, whichever comes first.
5. The battery is currently tracked (its `tracking_enabled` switch is on).

A 100% reading that drops below 95% within an hour is **discarded as a glitch**.

If the prior reading is older than 30 days, the integration does **not**
auto-commit. Instead, it raises a persistent HA notification asking you to
**Confirm**, **Dismiss**, or **Exclude** the battery. The notification names
the source entity; respond by calling one of these services from
**Developer Tools → Services** (or from a script/automation):

- `battery_lifetime.confirm_stale_replacement` — record the replacement at
  the candidate's first 100% reading.
- `battery_lifetime.dismiss_stale_replacement` — ignore this candidate;
  tracking stays on.
- `battery_lifetime.exclude_stale_replacement` — ignore this candidate
  *and* turn tracking off for the battery (sets
  `switch.<src>_tracking_enabled` to `off`).

All three take a single `entity_id` field — the source battery sensor, the
one named in the notification. This protects you from sensor gaps that
look like replacements.

Manual paths:

- **`button.foo_battery_mark_replaced`** — press it after swapping cells.
- **`date.foo_battery_replaced_on`** — directly set the date if you remember
  exactly when you swapped them. Future dates are rejected.

Every committed replacement (auto or manual) emits the
`battery_lifetime_replacement_detected` HA event with the source `entity_id`,
`unique_id`, before/after percentages, prior reading age, the committed
`replaced_on`, a `confirmed` flag, and a `source` field that names which path
committed it (`auto`, `manual_button`, `manual_date_edit`,
`cold_start_backfill`, `stale_confirmed`).

## Chemistry profiles

Two profiles ship in v1:

| Profile  | Default threshold | Default lifetime | Curve shape                    |
| -------- | ----------------: | ---------------: | ------------------------------ |
| alkaline |             `15%` |          365 d   | Smooth taper, EWMA from day 1  |
| lithium  |              `5%` |        1825 d    | Plateau (≥85%) then cliff      |

The integration-level **default profile** (settable in the options flow)
applies to newly discovered batteries. The default ships as `lithium`. Override
per battery with the `profile_lithium` switch on the device card (it's a
toggle: on = lithium, off = alkaline).

If you've got a battery whose firmware "linearizes" the lithium discharge
(rare), set its profile to **alkaline** — what the model cares about is curve
shape, not the chemistry label.

**Lithium plateau caveat.** While a lithium-profile battery's source reads
`≥85%`, the prediction is the chemistry-default lifetime anchored on
`replaced_on`, not extrapolation of the (misleadingly slow) observed drain.
Confidence stays at `profile_default` during the plateau regardless of how
much time has passed. Once the source drops below 85%, the model switches to
EWMA extrapolation.

## Confidence ladder

The `*_prediction_quality` sensor reflects how trustworthy the prediction is:

- `no_data` — no `replaced_on` known, no qualifying drain seen yet.
- `profile_default` — `replaced_on` known, but not enough drain observed yet, or
  the lithium battery is on its plateau.
- `low` — at least 7 days since `replaced_on` and at least 1% drain observed.
- `medium` — at least 30 days and at least 5% drain.
- `high` — at least 60 days and at least 10% drain.
- `stale` (orthogonal) — the source has produced no update in the last 7 days.
  Takes precedence over the others when active.

**Expect the first 30–60 days of any fresh install to sit at `low` or below.**
This is honest behaviour, not a bug. Lithium batteries on plateau will sit at
`profile_default` for many months until the chemistry actually starts to drop.

## Cold start

When a battery is first seen by the integration:

1. **Long-term statistics** are scanned for the most recent qualifying jump
   (`<80% → ≥100%` within the last few years). If found, that's `replaced_on`.
2. **Recorder** is scanned next as a fallback. Recorder default retention is
   ~10 days, so this rarely fires unless you've increased retention.
3. If neither yields a hit, the integration sits in `no_data` and continues
   listening. Once at least 7 days of post-attach data with at least 1% drain
   accumulate, it extrapolates backwards along the active profile to estimate
   `replaced_on` and updates accordingly.

The cold-start scan runs in the background after the integration finishes
setting up, so the **Settings → Devices & Services** dialog returns within
seconds even on installs with many batteries. On a 70-battery install the
background scan can take several minutes; the integration is fully
functional throughout, and a one-time persistent notification ("Battery
Lifetime: backfill complete") appears when the initial backfill batch is
done.

## The forward-prediction service

```yaml
service: battery_lifetime.predict_at
data:
  date: "2026-10-15"
  margin_days: 14         # optional, default 0
  actionable_only: false  # optional, default false
  include_excluded: false # optional, default false
```

The response contains a `results` list. Each entry is one battery:

```yaml
results:
  - entity_id: sensor.kitchen_motion_battery
    replace_by_entity: sensor.kitchen_motion_battery_replace_by
    unique_id: 0x00158d000123abcd-battery
    profile: lithium
    threshold_pct: 5
    drain_rate_pct_day: 0.18
    predicted_pct_at_date: 8
    predicted_state: below_threshold
    confidence: medium
    tracking_enabled: true
```

Use it from a script, automation, or template to power your own
"replace-this-month" or "before-the-cottage" dashboards.

## Non-goals (v1)

The integration **does not** model:

- Categorical (`low`/`normal`/`full`) or boolean low-battery sensors.
- Voltage-only (`V` / `mV`) battery sensors.
- Rechargeable batteries (NiMH eneloops, Li-ion packs, USB-backup devices,
  EcoFlow whole-house batteries). The auto-replacement rule will fire
  spuriously on every recharge cycle. **Exclude rechargeables** by toggling
  `tracking_enabled` off.
- "3×AA dies as a set" multi-cell awareness. Each entity is modeled
  independently.
- Custom Lovelace cards (left to a sibling project).
- Cross-device learning, Bayesian priors, or ML.

## License

MIT. See `LICENSE`.
