## Why

On installs with many battery-powered devices (the user's live install: 70 batteries → 554 companion entities), pressing **Submit** in the config dialog locks the UI for several minutes before setup completes. The root cause is `_scan_initial_entities` in `coordinator.py`: it iterates every eligible source entity sequentially and `await`s `_attempt_cold_start_backfill` for each, which dispatches one or two recorder/LTS executor-thread queries per battery. The recorder is single-threaded by design, so 70 batteries means up to 140 serialized queries on the await path of `async_setup`, and the integration cannot return control to Home Assistant until they all complete.

v0.1.1 added a bold/all-caps "this will freeze for several minutes" warning to the config dialog as a stop-gap. v0.1.2 optimized the heartbeat path but did not touch setup. This change removes the freeze entirely by deferring cold-start backfill to background tasks scheduled after `async_setup` returns, and replaces the freeze warning with an accurate background-backfill note plus a one-shot persistent notification when the initial backfill batch completes.

## What Changes

- Cold-start backfill SHALL NOT block `async_setup`. `_scan_initial_entities` schedules `_attempt_cold_start_backfill` per record via `hass.async_create_task` instead of awaiting it.
- The coordinator SHALL track the set of `unique_id`s with in-flight initial backfills and, when the set drains to empty, fire exactly one `persistent_notification` ("Battery Lifetime cold-start backfill complete") so the user knows the initial population phase finished.
- The config-dialog warning in `strings.json` and `translations/en.json` SHALL be replaced with a softer note explaining that setup completes immediately, that background backfill of historical `replaced_on` may take several minutes for installs with many batteries, and that a notification will appear when it is complete.
- New tests in `tests/test_coordinator.py` cover the non-blocking setup contract, the completion notification, and the no-pending-no-notification path.

Out of scope: the `replacement-detection` cold-start contract itself (LTS-then-recorder fallback, qualifying-jump rules, event payload) is unchanged. Only the *scheduling* of backfill changes.

## Capabilities

### New Capabilities

(none)

### Modified Capabilities

- `coordinator-scheduling`: adds a "Cold-start backfill is non-blocking and announced on completion" requirement governing when backfill runs relative to `async_setup` and how the integration signals completion of the initial batch.

## Impact

- `custom_components/battery_lifetime/coordinator.py`: small additive change — new `_pending_backfills` set, `_run_backfill_with_tracking` wrapper, `_announce_backfill_complete` helper, and a one-line swap in `_ensure_record` from `await` to `hass.async_create_task`.
- `custom_components/battery_lifetime/strings.json` + `translations/en.json`: rewrite the `config.step.user.description` string.
- `custom_components/battery_lifetime/manifest.json`: version bump to `0.1.3`.
- `tests/test_coordinator.py`: three new test functions.
- `README.md`, `info.md`: release notes for v0.1.3.
- No new runtime dependencies. No schema migration. No public service or event payload changes. No breaking changes for existing installs (persistent state in `.storage/battery_lifetime` is untouched).
