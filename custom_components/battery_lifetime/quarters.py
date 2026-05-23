"""Calendar-quarter helpers for dashboard and companion entities."""

from __future__ import annotations

from datetime import datetime, timezone

UTC = timezone.utc


def _to_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def next_quarter_end(now: datetime | None = None) -> datetime:
    """Return 23:59:59 UTC on the last day of the next calendar quarter."""
    now_dt = _to_utc(now) if now is not None else datetime.now(tz=UTC)
    year = now_dt.year
    month = now_dt.month
    if month <= 3:
        end_year, end_month, end_day = year, 6, 30
    elif month <= 6:
        end_year, end_month, end_day = year, 9, 30
    elif month <= 9:
        end_year, end_month, end_day = year, 12, 31
    else:
        end_year, end_month, end_day = year + 1, 3, 31
    return datetime(
        end_year,
        end_month,
        end_day,
        23,
        59,
        59,
        tzinfo=UTC,
    )


def is_due_by_quarter_end(
    replace_by: datetime | None,
    *,
    now: datetime | None = None,
) -> bool:
    """True when ``replace_by`` is on or before :func:`next_quarter_end`."""
    if replace_by is None:
        return False
    return _to_utc(replace_by) <= next_quarter_end(now)


def days_until_replace(
    replace_by: datetime | None,
    *,
    now: datetime | None = None,
) -> int | None:
    """Whole UTC days until ``replace_by`` (negative when overdue)."""
    if replace_by is None:
        return None
    now_dt = _to_utc(now) if now is not None else datetime.now(tz=UTC)
    return int((_to_utc(replace_by) - now_dt).total_seconds() / 86400.0)
