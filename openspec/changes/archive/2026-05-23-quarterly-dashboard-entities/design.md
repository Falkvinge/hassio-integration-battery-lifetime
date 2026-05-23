## Context

The integration already exposes `sensor.<src>_replace_by` timestamps and two rolling summary counters. A quarterly maintenance card (visible during days 1–10 of March, June, September, and December) needs batteries due before the **end of the next calendar quarter** — e.g. on 15 May (Q2), the cutoff is 30 September (Q3 end). Today that logic lives entirely in Lovelace Jinja duplicated across header and filter blocks.

Existing summary sensors use UTC for cutoff boundaries (`due_this_month`, `due_next_3_months`). This change follows the same convention for consistency.

## Goals / Non-Goals

**Goals:**

- One canonical definition of “next quarter end” reused by summary count, binary companion, and card authors.
- Per-battery `binary_sensor.<src>_due_next_quarter` so `auto-entities` can use a trivial `state: "on"` include.
- `days_until_replace` on replace-by for row coloring and sorting without timestamp parsing in templates.
- Keep companion device purge unchanged — removing the device still cascades all entity-registry entries.

**Non-Goals:**

- Changing `battery_lifetime.predict_at` service schema.
- Local-time quarter boundaries (would diverge from existing summary sensors).
- A custom Lovelace card in this repository.
- Retroactive entity creation for installs until the next coordinator refresh / rediscovery (standard HA platform behaviour).

## Decisions

### Decision: Next quarter end is end of the calendar quarter after the current one

Given a reference datetime, map its month to a cutoff at 23:59:59 UTC on the last day of the next calendar quarter:

| Reference month | Next quarter end (UTC) |
| --------------- | ---------------------- |
| Jan–Mar         | 30 June                |
| Apr–Jun         | 30 September           |
| Jul–Sep         | 31 December            |
| Oct–Dec         | 31 March (following year) |

Alternative considered: align only during the Mar/Jun/Sep/Dec maintenance window. Rejected because integration entities should be meaningful year-round for automations and other dashboards.

### Decision: `days_until_replace` is a signed whole-day floor

Compute `floor((replace_by - now) / 86400)` in UTC. Negative values mean overdue. Omit the attribute when `replace_by` is `None` or confidence is `no_data`. Alternative considered: fractional days. Rejected — dashboards want integer labels (“12 days”).

### Decision: Binary companion is `off` for `no_data` and untracked batteries

`binary_sensor.<src>_due_next_quarter` is `on` only when `tracking_enabled`, `replace_by` is set, confidence is not `no_data`, and `replace_by <= next_quarter_end`. Stale batteries with a frozen `replace_by` still evaluate normally. Alternative considered: separate `unknown` state. Rejected — binary sensors are simpler as on/off for Lovelace filters.

### Decision: Shared helper module `quarters.py`

Pure functions `next_quarter_end(now)` and `is_due_by_quarter_end(replace_by, now)` keep sensor and binary_sensor platforms thin and unit-testable without HA imports in the core math.

## Risks / Trade-offs

- **Companion count 8 → 9** → README and stale docs referencing “eight companions” need updating; device purge still removes all entities on the device automatically.
- **UTC vs local quarter** → A battery due “today” in local time may differ by one day from UTC boundary; matches existing summary sensor trade-off.

## Migration Plan

Non-breaking additive change. On upgrade, HA loads the new `binary_sensor` platform and creates new entities on the next setup; existing stores and services unchanged. Users replace Lovelace template filters with `*_due_next_quarter` includes when ready.
