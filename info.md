# Battery Lifetime

A Home Assistant integration that turns raw battery percentage sensors into actionable
predicted-replacement-date sensors. Built for the operator who wants to answer
"which batteries do I need to replace this month?" or "which batteries should I
proactively replace before leaving the cottage for four months?".

For every Home Assistant entity with `device_class: battery` and unit `%`, the
integration creates a companion `*_replace_by` datetime sensor, a confidence
sensor, an observed drain rate sensor, and a small set of switches/buttons that
let you tell it about the chemistry, mark a battery as replaced manually, or
opt the battery out of tracking.

Replacement events are auto-detected from the source sensor's value (a
`<80% → ≥100%` jump within the last 30 days), with glitch and stale-prior
protections, and emit a Home Assistant event your automations can listen for.
A `battery_lifetime.predict_at` service forward-simulates every tracked
battery to a future date so dashboards can answer the cottage-departure question.

See `README.md` for the full feature list, profile defaults, and the documented
non-goals (rechargeables, voltage-only and categorical battery sensors,
multi-cell awareness).
