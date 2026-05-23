## 1. Quarter boundary helper

- [x] 1.1 Create `custom_components/battery_lifetime/quarters.py` with `next_quarter_end(now)` and `is_due_by_quarter_end(replace_by, now)`
- [x] 1.2 Add unit tests in `tests/test_quarters.py` covering month boundaries and year rollover (December → March)

## 2. Replace-by attribute and summary sensor

- [x] 2.1 Add `days_until_replace` to `ReplaceBySensor.extra_state_attributes` in `sensor.py`
- [x] 2.2 Add `DueNextQuarterSensor` summary entity (`sensor.battery_lifetime_due_next_quarter`) in `sensor.py`
- [x] 2.3 Add translation keys for the new summary sensor

## 3. Binary sensor platform

- [x] 3.1 Create `binary_sensor.py` with `DueNextQuarterBinarySensor` per tracked battery
- [x] 3.2 Register `binary_sensor` in `const.PLATFORMS` and ensure dynamic entity add on discovery matches other platforms
- [x] 3.3 Add translation keys for the binary companion

## 4. Tests and documentation

- [x] 4.1 Extend `tests/test_entities.py` for `days_until_replace`, summary count, and binary sensor on/off cases
- [x] 4.2 Update `tests/test_init.py` for new platform entities
- [x] 4.3 Update `README.md` companion table and summary sensor list (nine companions)
- [x] 4.4 Bump `manifest.json` version

## 5. Lovelace card

- [x] 5.1 Revise `examples/lovelace/quarterly-battery-maintenance-card.yaml` to filter `*_due_next_quarter` and use `days_until_replace` / summary sensor
