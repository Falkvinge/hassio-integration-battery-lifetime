"""Tests for replacement-detection logic.

The pure-logic helpers (`classify_reading`, `classify_followup`,
`_scan_for_jump`, `estimate_replaced_on_from_drain`) are exercised here
without spinning up Home Assistant; the HA-aware `ReplacementDetector`
gets a thin set of integration tests using the `hass` fixture.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from custom_components.battery_lifetime.detection import (
    Candidate,
    ColdStartHit,
    FollowupClassification,
    ReadingClassification,
    ReplacementDetector,
    _scan_for_jump,
    classify_followup,
    classify_reading,
    estimate_replaced_on_from_drain,
)

UTC = timezone.utc


def _dt(year: int, month: int, day: int, hour: int = 12) -> datetime:
    return datetime(year, month, day, hour, tzinfo=UTC)


def test_classify_reading_no_event_when_under_100() -> None:
    decision = classify_reading(
        prev_pct=70.0,
        prev_at=_dt(2026, 5, 1),
        new_pct=80.0,
        new_at=_dt(2026, 5, 2),
    )
    assert decision is ReadingClassification.NO_EVENT


def test_classify_reading_no_event_when_prev_above_80() -> None:
    decision = classify_reading(
        prev_pct=85.0,
        prev_at=_dt(2026, 5, 1),
        new_pct=100.0,
        new_at=_dt(2026, 5, 2),
    )
    assert decision is ReadingClassification.NO_EVENT


def test_classify_reading_new_candidate_within_window() -> None:
    decision = classify_reading(
        prev_pct=47.0,
        prev_at=_dt(2026, 5, 1),
        new_pct=100.0,
        new_at=_dt(2026, 5, 6),
    )
    assert decision is ReadingClassification.NEW_CANDIDATE


def test_classify_reading_stale_prior_outside_window() -> None:
    decision = classify_reading(
        prev_pct=72.0,
        prev_at=_dt(2026, 3, 1),
        new_pct=100.0,
        new_at=_dt(2026, 5, 1),
    )
    assert decision is ReadingClassification.STALE_PRIOR_NOTIFICATION


def test_classify_reading_no_event_without_prior() -> None:
    decision = classify_reading(
        prev_pct=None,
        prev_at=None,
        new_pct=100.0,
        new_at=_dt(2026, 5, 1),
    )
    assert decision is ReadingClassification.NO_EVENT


def _candidate() -> Candidate:
    return Candidate(
        new_pct=100.0,
        new_at=_dt(2026, 5, 6),
        prior_pct=47.0,
        prior_at=_dt(2026, 5, 1),
    )


def test_followup_confirms_on_second_full_reading() -> None:
    cand = _candidate()
    decision = classify_followup(
        cand, new_pct=100.0, new_at=cand.new_at + timedelta(minutes=20)
    )
    assert decision is FollowupClassification.CONFIRM


def test_followup_glitch_on_drop_below_95() -> None:
    cand = _candidate()
    decision = classify_followup(
        cand, new_pct=30.0, new_at=cand.new_at + timedelta(minutes=10)
    )
    assert decision is FollowupClassification.GLITCH


def test_followup_holds_in_95_to_100_band() -> None:
    cand = _candidate()
    decision = classify_followup(
        cand, new_pct=98.0, new_at=cand.new_at + timedelta(minutes=15)
    )
    assert decision is FollowupClassification.HOLD


def test_followup_confirms_after_one_hour_with_no_contradiction() -> None:
    cand = _candidate()
    decision = classify_followup(
        cand, new_pct=99.0, new_at=cand.new_at + timedelta(seconds=3600)
    )
    assert decision is FollowupClassification.CONFIRM


def test_followup_glitches_after_one_hour_with_low_reading() -> None:
    cand = _candidate()
    decision = classify_followup(
        cand, new_pct=20.0, new_at=cand.new_at + timedelta(seconds=3600)
    )
    assert decision is FollowupClassification.GLITCH


def test_scan_for_jump_finds_most_recent() -> None:
    samples = [
        (_dt(2025, 1, 10), 90.0),
        (_dt(2025, 1, 11), 80.0),
        (_dt(2025, 6, 1), 30.0),
        (_dt(2025, 6, 5), 100.0),
        (_dt(2025, 12, 1), 25.0),
        (_dt(2025, 12, 2), 100.0),
    ]
    hit = _scan_for_jump(samples)
    assert hit is not None
    assert hit.replaced_on == _dt(2025, 12, 2)
    assert hit.previous_pct == 25.0
    assert hit.current_pct == 100.0


def test_scan_for_jump_skips_when_prior_too_old() -> None:
    samples = [
        (_dt(2025, 1, 1), 50.0),
        (_dt(2026, 5, 1), 100.0),
    ]
    hit = _scan_for_jump(samples)
    assert hit is None


def test_scan_for_jump_returns_none_for_no_jumps() -> None:
    samples = [
        (_dt(2026, 5, 1), 70.0),
        (_dt(2026, 5, 2), 60.0),
        (_dt(2026, 5, 3), 50.0),
    ]
    assert _scan_for_jump(samples) is None


def test_estimate_replaced_on_from_drain() -> None:
    last_at = _dt(2026, 5, 1)
    estimated = estimate_replaced_on_from_drain(
        last_pct=92.0,
        last_at=last_at,
        drain_rate_pct_day=0.4,
        starting_pct=100.0,
    )
    assert estimated is not None
    expected = last_at - timedelta(days=20.0)
    assert abs((estimated - expected).total_seconds()) < 1.0


def test_estimate_replaced_on_returns_none_for_zero_drain() -> None:
    assert (
        estimate_replaced_on_from_drain(
            last_pct=92.0,
            last_at=_dt(2026, 5, 1),
            drain_rate_pct_day=0.0,
        )
        is None
    )


def test_estimate_replaced_on_returns_none_when_above_starting_pct() -> None:
    assert (
        estimate_replaced_on_from_drain(
            last_pct=100.0,
            last_at=_dt(2026, 5, 1),
            drain_rate_pct_day=0.5,
        )
        is None
    )


async def test_detector_commits_on_followup_confirmation(hass: Any) -> None:
    captured: list[tuple[str, datetime, dict[str, Any]]] = []

    async def commit(unique_id: str, replaced_on: datetime, payload: dict) -> None:
        captured.append((unique_id, replaced_on, payload))

    detector = ReplacementDetector(hass, commit)
    initial_at = _dt(2026, 5, 6)
    committed = await detector.process_reading(
        "uid-a",
        "sensor.foo_battery",
        prev_pct=47.0,
        prev_at=_dt(2026, 5, 1),
        new_pct=100.0,
        new_at=initial_at,
        tracking_enabled=True,
    )
    assert committed is False
    assert "uid-a" in detector.candidates

    committed = await detector.process_reading(
        "uid-a",
        "sensor.foo_battery",
        prev_pct=100.0,
        prev_at=initial_at,
        new_pct=100.0,
        new_at=initial_at + timedelta(minutes=20),
        tracking_enabled=True,
    )
    assert committed is True
    assert captured
    assert captured[0][2]["source"] == "auto"
    assert captured[0][2]["confirmed"] is True
    assert "uid-a" not in detector.candidates


async def test_detector_glitches_on_low_followup(hass: Any) -> None:
    detector = ReplacementDetector(hass, lambda *args, **kwargs: _noop())
    await detector.process_reading(
        "uid-a",
        "sensor.foo_battery",
        prev_pct=47.0,
        prev_at=_dt(2026, 5, 1),
        new_pct=100.0,
        new_at=_dt(2026, 5, 6),
        tracking_enabled=True,
    )
    assert "uid-a" in detector.candidates
    committed = await detector.process_reading(
        "uid-a",
        "sensor.foo_battery",
        prev_pct=100.0,
        prev_at=_dt(2026, 5, 6),
        new_pct=30.0,
        new_at=_dt(2026, 5, 6, 13),
        tracking_enabled=True,
    )
    assert committed is False
    assert "uid-a" not in detector.candidates


async def test_detector_raises_stale_notification(hass: Any) -> None:
    detector = ReplacementDetector(hass, lambda *args, **kwargs: _noop())
    committed = await detector.process_reading(
        "uid-a",
        "sensor.foo_battery",
        prev_pct=72.0,
        prev_at=_dt(2026, 3, 1),
        new_pct=100.0,
        new_at=_dt(2026, 5, 1),
        tracking_enabled=True,
    )
    assert committed is False
    assert "uid-a" in detector.stale_pending


async def test_detector_confirm_stale_commits(hass: Any) -> None:
    captured: list[tuple[str, datetime, dict[str, Any]]] = []

    async def commit(unique_id: str, replaced_on: datetime, payload: dict) -> None:
        captured.append((unique_id, replaced_on, payload))

    detector = ReplacementDetector(hass, commit)
    await detector.process_reading(
        "uid-a",
        "sensor.foo_battery",
        prev_pct=72.0,
        prev_at=_dt(2026, 3, 1),
        new_pct=100.0,
        new_at=_dt(2026, 5, 1),
        tracking_enabled=True,
    )
    confirmed = await detector.confirm_stale("uid-a", "sensor.foo_battery")
    assert confirmed is True
    assert captured
    assert captured[0][2]["source"] == "stale_confirmed"
    assert "uid-a" not in detector.stale_pending


async def test_detector_dismiss_stale_clears_state(hass: Any) -> None:
    detector = ReplacementDetector(hass, lambda *args, **kwargs: _noop())
    await detector.process_reading(
        "uid-a",
        "sensor.foo_battery",
        prev_pct=72.0,
        prev_at=_dt(2026, 3, 1),
        new_pct=100.0,
        new_at=_dt(2026, 5, 1),
        tracking_enabled=True,
    )
    had_pending = await detector.dismiss_stale("uid-a")
    assert had_pending is True
    assert "uid-a" not in detector.stale_pending


async def test_detector_exclude_stale_clears_state(hass: Any) -> None:
    """``exclude_stale`` clears the candidate; the caller flips tracking off."""
    captured: list[tuple[str, datetime, dict[str, Any]]] = []

    async def commit(
        unique_id: str, replaced_on: datetime, payload: dict
    ) -> None:
        captured.append((unique_id, replaced_on, payload))

    detector = ReplacementDetector(hass, commit)
    await detector.process_reading(
        "uid-a",
        "sensor.foo_battery",
        prev_pct=72.0,
        prev_at=_dt(2026, 3, 1),
        new_pct=100.0,
        new_at=_dt(2026, 5, 1),
        tracking_enabled=True,
    )
    excluded = await detector.exclude_stale("uid-a")
    assert excluded is True
    assert "uid-a" not in detector.stale_pending
    assert captured == []  # no replacement is committed by exclusion


async def test_detector_dismiss_returns_false_when_no_candidate(
    hass: Any,
) -> None:
    detector = ReplacementDetector(hass, lambda *args, **kwargs: _noop())
    had_pending = await detector.dismiss_stale("uid-never-existed")
    assert had_pending is False


async def test_detector_skips_when_tracking_disabled(hass: Any) -> None:
    detector = ReplacementDetector(hass, lambda *args, **kwargs: _noop())
    committed = await detector.process_reading(
        "uid-a",
        "sensor.foo_battery",
        prev_pct=47.0,
        prev_at=_dt(2026, 5, 1),
        new_pct=100.0,
        new_at=_dt(2026, 5, 6),
        tracking_enabled=False,
    )
    assert committed is False
    assert "uid-a" not in detector.candidates


async def _noop() -> None:
    return None
