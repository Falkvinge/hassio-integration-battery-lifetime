"""Constants for the Battery Lifetime integration."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "battery_lifetime"
PLATFORMS: Final = ["sensor", "binary_sensor", "switch", "button", "date", "number"]

STORAGE_KEY: Final = "battery_lifetime"
STORAGE_VERSION: Final = 1

CONF_DEFAULT_PROFILE: Final = "default_profile"

PROFILE_ALKALINE: Final = "alkaline"
PROFILE_LITHIUM: Final = "lithium"
ALL_PROFILES: Final = (PROFILE_ALKALINE, PROFILE_LITHIUM)
DEFAULT_PROFILE: Final = PROFILE_LITHIUM

ALKALINE_THRESHOLD_PCT: Final = 15.0
ALKALINE_LIFETIME_DAYS: Final = 365
ALKALINE_PLATEAU_PCT: Final = None

LITHIUM_THRESHOLD_PCT: Final = 5.0
LITHIUM_LIFETIME_DAYS: Final = 1825
LITHIUM_PLATEAU_PCT: Final = 85.0

EWMA_WINDOW_DAYS: Final = 60
EWMA_HALF_LIFE_DAYS: Final = 14.0

CONFIDENCE_NO_DATA: Final = "no_data"
CONFIDENCE_PROFILE_DEFAULT: Final = "profile_default"
CONFIDENCE_LOW: Final = "low"
CONFIDENCE_MEDIUM: Final = "medium"
CONFIDENCE_HIGH: Final = "high"
CONFIDENCE_STALE: Final = "stale"

CONFIDENCE_LOW_DAYS: Final = 7
CONFIDENCE_LOW_DRAIN_PCT: Final = 1.0
CONFIDENCE_MEDIUM_DAYS: Final = 30
CONFIDENCE_MEDIUM_DRAIN_PCT: Final = 5.0
CONFIDENCE_HIGH_DAYS: Final = 60
CONFIDENCE_HIGH_DRAIN_PCT: Final = 10.0
STALE_SOURCE_DAYS: Final = 7

REPLACEMENT_DROP_THRESHOLD: Final = 80.0
REPLACEMENT_FULL_THRESHOLD: Final = 100.0
REPLACEMENT_PRIOR_MAX_AGE_DAYS: Final = 30
REPLACEMENT_CONFIRM_TIMEOUT_SECONDS: Final = 3600
REPLACEMENT_GLITCH_REVERT_PCT: Final = 95.0

REMOVED_SOURCE_RETENTION_DAYS: Final = 30

EVENT_REPLACEMENT_DETECTED: Final = "battery_lifetime_replacement_detected"

REPLACEMENT_SOURCE_AUTO: Final = "auto"
REPLACEMENT_SOURCE_MANUAL_BUTTON: Final = "manual_button"
REPLACEMENT_SOURCE_MANUAL_DATE_EDIT: Final = "manual_date_edit"
REPLACEMENT_SOURCE_COLD_START_BACKFILL: Final = "cold_start_backfill"
REPLACEMENT_SOURCE_STALE_CONFIRMED: Final = "stale_confirmed"

SERVICE_PREDICT_AT: Final = "predict_at"
SERVICE_CONFIRM_STALE_REPLACEMENT: Final = "confirm_stale_replacement"
SERVICE_DISMISS_STALE_REPLACEMENT: Final = "dismiss_stale_replacement"
SERVICE_EXCLUDE_STALE_REPLACEMENT: Final = "exclude_stale_replacement"

NOTIFICATION_STALE_PRIOR_PREFIX: Final = "battery_lifetime_stale_"

UPDATE_INTERVAL_SECONDS: Final = 600

UNIQUE_ID_PREFIX: Final = "battery_lifetime"

PREDICTED_STATE_OK: Final = "ok"
PREDICTED_STATE_BELOW_THRESHOLD: Final = "below_threshold"
PREDICTED_STATE_UNKNOWN: Final = "unknown"
