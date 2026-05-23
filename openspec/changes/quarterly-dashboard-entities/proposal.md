## Why

Quarterly battery-maintenance dashboards need calendar-aligned filters that the existing summary sensors (`due_this_month`, `due_next_3_months`) do not provide. Lovelace cards currently duplicate quarter-boundary math in Jinja templates and cannot filter companion entities with a simple include rule. Exposing `due_next_quarter` summary/count semantics, a `days_until_replace` attribute, and a per-battery `due_next_quarter` binary companion makes dashboard cards simpler, faster to author, and consistent with integration-level prediction data.

## What Changes

- Add integration-level sensor `sensor.battery_lifetime_due_next_quarter` counting tracked batteries whose `replace_by` is on or before the end of the calendar quarter immediately following the current one.
- Add `days_until_replace` attribute on each `sensor.<src>_replace_by` companion (signed integer days from now; negative when overdue; omitted when `replace_by` is unknown).
- Add per-battery binary companion `binary_sensor.<src>_due_next_quarter` that is `on` when the battery is tracked, has a computable `replace_by`, is not `no_data`, and that date falls on or before the next quarter end.
- Add shared quarter-boundary helper used by summary and binary companions (same cutoff semantics everywhere).
- Update the example quarterly maintenance Lovelace card to filter on `*_due_next_quarter` instead of inline timestamp math.
- Per-battery companion count increases from eight to nine; companion-device purge cascades automatically via existing device-registry removal.

## Capabilities

### New Capabilities

(none — behavior extends existing lifetime prediction surface)

### Modified Capabilities

- `lifetime-prediction`: adds next-quarter summary sensor, `days_until_replace` attribute on replace-by, and per-battery `due_next_quarter` binary companion.

## Impact

- `custom_components/battery_lifetime/quarters.py` (new): shared next-quarter-end calculation.
- `custom_components/battery_lifetime/sensor.py`: `days_until_replace` attribute; `DueNextQuarterSensor` summary.
- `custom_components/battery_lifetime/binary_sensor.py` (new platform): `DueNextQuarterBinarySensor` per battery.
- `custom_components/battery_lifetime/const.py`: add `binary_sensor` to `PLATFORMS`.
- `custom_components/battery_lifetime/translations/en.json`, `strings.json`: new entity strings.
- `examples/lovelace/quarterly-battery-maintenance-card.yaml`: simplified card using new entities.
- `README.md`: document new entities.
- Tests in `tests/test_entities.py`, `tests/test_init.py`, and new `tests/test_quarters.py`.
- `manifest.json`: version bump.
