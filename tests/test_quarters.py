"""Unit tests for calendar-quarter boundary helpers."""

from __future__ import annotations

from datetime import datetime, timezone

from custom_components.battery_lifetime.quarters import (
    days_until_replace,
    is_due_by_quarter_end,
    next_quarter_end,
)

UTC = timezone.utc


def test_next_quarter_end_from_q1() -> None:
    now = datetime(2026, 2, 10, 12, 0, 0, tzinfo=UTC)
    end = next_quarter_end(now)
    assert end == datetime(2026, 6, 30, 23, 59, 59, tzinfo=UTC)


def test_next_quarter_end_from_q2() -> None:
    now = datetime(2026, 5, 15, tzinfo=UTC)
    end = next_quarter_end(now)
    assert end == datetime(2026, 9, 30, 23, 59, 59, tzinfo=UTC)


def test_next_quarter_end_from_q4_rolls_to_march() -> None:
    now = datetime(2026, 12, 10, tzinfo=UTC)
    end = next_quarter_end(now)
    assert end == datetime(2027, 3, 31, 23, 59, 59, tzinfo=UTC)


def test_is_due_by_quarter_end() -> None:
    now = datetime(2026, 3, 1, tzinfo=UTC)
    due = datetime(2026, 6, 15, tzinfo=UTC)
    late = datetime(2026, 8, 1, tzinfo=UTC)
    assert is_due_by_quarter_end(due, now=now) is True
    assert is_due_by_quarter_end(late, now=now) is False
    assert is_due_by_quarter_end(None, now=now) is False


def test_days_until_replace_future_and_overdue() -> None:
    now = datetime(2026, 5, 1, 12, 0, 0, tzinfo=UTC)
    future = datetime(2026, 5, 11, 12, 0, 0, tzinfo=UTC)
    past = datetime(2026, 4, 28, 12, 0, 0, tzinfo=UTC)
    assert days_until_replace(future, now=now) == 10
    assert days_until_replace(past, now=now) == -3
    assert days_until_replace(None, now=now) is None
