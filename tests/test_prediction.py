"""Tests for the prediction module: EWMA, projector, simulator, confidence."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from custom_components.battery_lifetime.const import (
    ALKALINE_LIFETIME_DAYS,
    ALKALINE_THRESHOLD_PCT,
    CONFIDENCE_HIGH,
    CONFIDENCE_LOW,
    CONFIDENCE_MEDIUM,
    CONFIDENCE_NO_DATA,
    CONFIDENCE_PROFILE_DEFAULT,
    CONFIDENCE_STALE,
    LITHIUM_LIFETIME_DAYS,
    PROFILE_ALKALINE,
    PROFILE_LITHIUM,
)
from custom_components.battery_lifetime.prediction import (
    BatteryState,
    EwmaState,
    evaluate_confidence,
    forward_simulate,
    project_replace_by,
    reset_ewma_for_replacement,
    update_ewma,
)

UTC = timezone.utc


def _dt(year: int, month: int, day: int, hour: int = 12) -> datetime:
    return datetime(year, month, day, hour, tzinfo=UTC)


def test_ewma_first_drain_seeds_rate() -> None:
    seed_at = _dt(2026, 4, 1)
    state = reset_ewma_for_replacement(100.0, seed_at)
    state = update_ewma(state, 99.6, seed_at + timedelta(days=2))
    assert state.rate == pytest.approx(0.2, rel=1e-6)


def test_ewma_ignores_increases() -> None:
    seed_at = _dt(2026, 4, 1)
    state = reset_ewma_for_replacement(100.0, seed_at)
    state = update_ewma(state, 99.0, seed_at + timedelta(days=2))
    rate_before = state.rate
    state = update_ewma(state, 99.5, seed_at + timedelta(days=3))
    assert state.rate == rate_before
    assert state.last_pct == 99.5


def test_ewma_window_cap_drops_old_samples() -> None:
    seed_at = _dt(2026, 1, 1)
    state = reset_ewma_for_replacement(100.0, seed_at)
    state = update_ewma(state, 95.0, seed_at + timedelta(days=10))
    rate_before = state.rate
    far_future = seed_at + timedelta(days=400)
    state = update_ewma(state, 90.0, far_future)
    assert state.rate == rate_before
    assert state.last_at == far_future


def test_reset_ewma_for_replacement_clears_rate() -> None:
    state = reset_ewma_for_replacement(100.0, _dt(2026, 4, 1))
    assert state.rate is None
    assert state.baseline_pct == 100.0
    assert state.last_pct == 100.0


def _battery(
    profile_id: str,
    *,
    replaced_on: datetime | None,
    last_pct: float | None,
    last_at: datetime | None,
    ewma_rate: float | None = None,
    baseline_pct: float | None = None,
    baseline_at: datetime | None = None,
    threshold_override: float | None = None,
) -> BatteryState:
    return BatteryState(
        profile_id=profile_id,
        replaced_on=replaced_on,
        threshold_override=threshold_override,
        last_reading_pct=last_pct,
        last_reading_at=last_at,
        ewma=EwmaState(
            rate=ewma_rate,
            last_pct=last_pct,
            last_at=last_at,
            baseline_pct=baseline_pct,
            baseline_at=baseline_at,
        ),
    )


def test_confidence_no_data_when_replaced_on_unknown() -> None:
    now = _dt(2026, 5, 1)
    state = _battery(
        PROFILE_ALKALINE,
        replaced_on=None,
        last_pct=80.0,
        last_at=now,
    )
    assert evaluate_confidence(state, now=now) == CONFIDENCE_NO_DATA


def test_confidence_profile_default_when_lithium_on_plateau() -> None:
    now = _dt(2026, 5, 1)
    replaced = _dt(2025, 1, 1)
    state = _battery(
        PROFILE_LITHIUM,
        replaced_on=replaced,
        last_pct=99.0,
        last_at=now,
        baseline_pct=100.0,
        baseline_at=replaced,
    )
    assert evaluate_confidence(state, now=now) == CONFIDENCE_PROFILE_DEFAULT


def test_confidence_climbs_with_data() -> None:
    now = _dt(2026, 5, 1)
    replaced = now - timedelta(days=35)
    state = _battery(
        PROFILE_ALKALINE,
        replaced_on=replaced,
        last_pct=93.0,
        last_at=now,
        baseline_pct=100.0,
        baseline_at=replaced,
        ewma_rate=0.2,
    )
    assert evaluate_confidence(state, now=now) == CONFIDENCE_MEDIUM


def test_confidence_high_with_60d_and_10pct_drain() -> None:
    now = _dt(2026, 5, 1)
    replaced = now - timedelta(days=70)
    state = _battery(
        PROFILE_ALKALINE,
        replaced_on=replaced,
        last_pct=85.0,
        last_at=now,
        baseline_pct=100.0,
        baseline_at=replaced,
        ewma_rate=0.21,
    )
    assert evaluate_confidence(state, now=now) == CONFIDENCE_HIGH


def test_confidence_low_with_just_enough_data() -> None:
    now = _dt(2026, 5, 1)
    replaced = now - timedelta(days=8)
    state = _battery(
        PROFILE_ALKALINE,
        replaced_on=replaced,
        last_pct=98.0,
        last_at=now,
        baseline_pct=100.0,
        baseline_at=replaced,
        ewma_rate=0.25,
    )
    assert evaluate_confidence(state, now=now) == CONFIDENCE_LOW


def test_confidence_stale_overrides_others() -> None:
    now = _dt(2026, 5, 1)
    replaced = now - timedelta(days=70)
    last_at = now - timedelta(days=10)
    state = _battery(
        PROFILE_ALKALINE,
        replaced_on=replaced,
        last_pct=85.0,
        last_at=last_at,
        baseline_pct=100.0,
        baseline_at=replaced,
        ewma_rate=0.21,
    )
    assert evaluate_confidence(state, now=now) == CONFIDENCE_STALE


def test_stale_overrides_high_confidence_explicit() -> None:
    """Same battery, two ``now`` values: HIGH while fresh, STALE once stale.

    Pinned to ``replacement-detection/spec.md`` "Stale source overrides
    everything else" — the ladder gates (60d / 10% drain) are met both times,
    but once ``now - last_at`` exceeds the 7-day staleness window the
    confidence MUST flip to ``stale`` regardless of the other gates.
    """
    last_at = _dt(2026, 5, 1)
    replaced = last_at - timedelta(days=70)
    state = _battery(
        PROFILE_ALKALINE,
        replaced_on=replaced,
        last_pct=85.0,
        last_at=last_at,
        baseline_pct=100.0,
        baseline_at=replaced,
        ewma_rate=0.21,
    )
    fresh_now = last_at + timedelta(hours=1)
    stale_now = last_at + timedelta(days=10)
    assert evaluate_confidence(state, now=fresh_now) == CONFIDENCE_HIGH
    assert evaluate_confidence(state, now=stale_now) == CONFIDENCE_STALE


def test_alkaline_projection_extrapolates_to_threshold() -> None:
    now = _dt(2026, 5, 1)
    replaced = now - timedelta(days=60)
    state = _battery(
        PROFILE_ALKALINE,
        replaced_on=replaced,
        last_pct=78.0,
        last_at=now,
        baseline_pct=100.0,
        baseline_at=replaced,
        ewma_rate=0.30,
    )
    pred = project_replace_by(state, now=now)
    assert pred.confidence == CONFIDENCE_HIGH
    assert pred.replace_by is not None
    days_to_threshold = (78.0 - ALKALINE_THRESHOLD_PCT) / 0.30
    expected = now + timedelta(days=days_to_threshold)
    assert abs((pred.replace_by - expected).total_seconds()) < 60


def test_lithium_plateau_holds_at_default_lifetime() -> None:
    now = _dt(2026, 5, 1)
    replaced = now - timedelta(days=200)
    state = _battery(
        PROFILE_LITHIUM,
        replaced_on=replaced,
        last_pct=99.0,
        last_at=now,
        baseline_pct=100.0,
        baseline_at=replaced,
        ewma_rate=0.001,
    )
    pred = project_replace_by(state, now=now)
    assert pred.confidence == CONFIDENCE_PROFILE_DEFAULT
    assert pred.replace_by is not None
    expected = replaced + timedelta(days=LITHIUM_LIFETIME_DAYS)
    assert abs((pred.replace_by - expected).total_seconds()) < 60


def test_lithium_after_plateau_extrapolates_with_cliff() -> None:
    now = _dt(2026, 5, 1)
    replaced = now - timedelta(days=400)
    state = _battery(
        PROFILE_LITHIUM,
        replaced_on=replaced,
        last_pct=40.0,
        last_at=now,
        baseline_pct=100.0,
        baseline_at=replaced,
        ewma_rate=0.5,
    )
    pred = project_replace_by(state, now=now)
    assert pred.confidence in (CONFIDENCE_HIGH, CONFIDENCE_MEDIUM, CONFIDENCE_LOW)
    assert pred.replace_by is not None
    expected_days = (40.0 - 5.0) / 0.5
    expected = now + timedelta(days=expected_days)
    assert abs((pred.replace_by - expected).total_seconds()) < 120


def test_threshold_override_is_used() -> None:
    now = _dt(2026, 5, 1)
    replaced = now - timedelta(days=70)
    state = _battery(
        PROFILE_ALKALINE,
        replaced_on=replaced,
        last_pct=80.0,
        last_at=now,
        baseline_pct=100.0,
        baseline_at=replaced,
        ewma_rate=0.20,
        threshold_override=25.0,
    )
    pred = project_replace_by(state, now=now)
    assert pred.threshold_pct == 25.0
    days_to_threshold = (80.0 - 25.0) / 0.20
    expected = now + timedelta(days=days_to_threshold)
    assert abs((pred.replace_by - expected).total_seconds()) < 60


def test_stale_returns_last_replace_by_fallback() -> None:
    now = _dt(2026, 5, 1)
    replaced = now - timedelta(days=70)
    last_at = now - timedelta(days=10)
    fallback = now + timedelta(days=200)
    state = _battery(
        PROFILE_ALKALINE,
        replaced_on=replaced,
        last_pct=85.0,
        last_at=last_at,
        baseline_pct=100.0,
        baseline_at=replaced,
        ewma_rate=0.21,
    )
    pred = project_replace_by(
        state, now=now, last_replace_by_fallback=fallback
    )
    assert pred.confidence == CONFIDENCE_STALE
    assert pred.replace_by == fallback


def test_forward_simulate_alkaline_below_threshold() -> None:
    now = _dt(2026, 5, 1)
    replaced = now - timedelta(days=70)
    state = _battery(
        PROFILE_ALKALINE,
        replaced_on=replaced,
        last_pct=40.0,
        last_at=now,
        baseline_pct=100.0,
        baseline_at=replaced,
        ewma_rate=0.5,
    )
    target = now + timedelta(days=80)
    result = forward_simulate(state, target_date=target, now=now)
    assert result["predicted_state"] == "below_threshold"
    assert result["predicted_pct_at_date"] == 0.0


def test_forward_simulate_lithium_holds_during_plateau() -> None:
    now = _dt(2026, 5, 1)
    replaced = now - timedelta(days=100)
    state = _battery(
        PROFILE_LITHIUM,
        replaced_on=replaced,
        last_pct=98.0,
        last_at=now,
        baseline_pct=100.0,
        baseline_at=replaced,
        ewma_rate=0.001,
    )
    target = now + timedelta(days=60)
    result = forward_simulate(state, target_date=target, now=now)
    assert result["predicted_state"] == "ok"
    assert result["predicted_pct_at_date"] == pytest.approx(98.0, abs=0.05)


def test_forward_simulate_unknown_when_no_data() -> None:
    now = _dt(2026, 5, 1)
    state = _battery(
        PROFILE_ALKALINE,
        replaced_on=None,
        last_pct=None,
        last_at=None,
    )
    result = forward_simulate(state, target_date=now + timedelta(days=10), now=now)
    assert result["predicted_state"] == "unknown"
    assert result["predicted_pct_at_date"] is None


def test_forward_simulate_margin_extends_evaluation_date() -> None:
    """Positive margin extends the projection further into the future.

    With the safety-margin semantic, applying a margin makes the
    ``actionable_only`` filter MORE inclusive: a battery that would still
    be above threshold at the target date can be projected as below
    threshold once the margin is applied. This is the conservative case the
    cottage-departure use case asks for.
    """
    now = _dt(2026, 5, 1)
    replaced = now - timedelta(days=70)
    state = _battery(
        PROFILE_ALKALINE,
        replaced_on=replaced,
        last_pct=30.0,
        last_at=now,
        baseline_pct=100.0,
        baseline_at=replaced,
        ewma_rate=1.0,
    )
    target = now + timedelta(days=10)
    no_margin = forward_simulate(state, target_date=target, now=now)
    with_margin = forward_simulate(
        state, target_date=target, margin_days=10, now=now
    )
    assert no_margin["predicted_state"] == "ok"
    assert with_margin["predicted_state"] == "below_threshold"
