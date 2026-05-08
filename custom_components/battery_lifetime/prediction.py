"""Drain modelling and prediction for the Battery Lifetime integration.

Pure-logic module: no Home Assistant imports here so we can unit-test the
maths without spinning up a HA instance. The coordinator builds a
:class:`BatteryState`, mutates it as readings arrive, and asks the helpers
in this module for the projected ``replace_by`` timestamp and the current
confidence value.

The drain rate is an exponentially-weighted moving average of ``%/day``,
seeded by an exponential decay anchored on a half-life. Increases in the
source reading without a confirmed replacement event do **not** feed the
EWMA -- they leave the rate unchanged so a small temperature-driven uptick
can't make a battery look like it's regenerating itself.

For lithium-profile batteries, while the most recent reading is at or
above the chemistry plateau the projector ignores the EWMA and reports
``replaced_on + default_lifetime`` instead. This stops a flat-for-a-year
lithium primary from extrapolating to ridiculous EOL dates.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from typing import Any

from .const import (
    CONFIDENCE_HIGH,
    CONFIDENCE_HIGH_DAYS,
    CONFIDENCE_HIGH_DRAIN_PCT,
    CONFIDENCE_LOW,
    CONFIDENCE_LOW_DAYS,
    CONFIDENCE_LOW_DRAIN_PCT,
    CONFIDENCE_MEDIUM,
    CONFIDENCE_MEDIUM_DAYS,
    CONFIDENCE_MEDIUM_DRAIN_PCT,
    CONFIDENCE_NO_DATA,
    CONFIDENCE_PROFILE_DEFAULT,
    CONFIDENCE_STALE,
    EWMA_HALF_LIFE_DAYS,
    EWMA_WINDOW_DAYS,
    PREDICTED_STATE_BELOW_THRESHOLD,
    PREDICTED_STATE_OK,
    PREDICTED_STATE_UNKNOWN,
    STALE_SOURCE_DAYS,
)
from .models import Profile, get_profile

UTC = timezone.utc


def _utcnow() -> datetime:
    return datetime.now(tz=UTC)


def _to_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


@dataclass(slots=True)
class EwmaState:
    """Exponentially-weighted moving average of ``%/day``.

    ``rate`` is the current EWMA estimate (or ``None`` when no drain has
    been observed yet). ``last_pct`` and ``last_at`` are the most recent
    sample fed into the EWMA. ``baseline_pct`` and ``baseline_at`` are the
    seed sample (set on replacement) so we can ask "how much have we
    drained since replacement?" without scanning a long history.
    """

    rate: float | None = None
    last_pct: float | None = None
    last_at: datetime | None = None
    baseline_pct: float | None = None
    baseline_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "rate": self.rate,
            "last_pct": self.last_pct,
            "last_at": self.last_at.isoformat() if self.last_at else None,
            "baseline_pct": self.baseline_pct,
            "baseline_at": (
                self.baseline_at.isoformat() if self.baseline_at else None
            ),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> EwmaState:
        if not data:
            return cls()
        last_at = data.get("last_at")
        baseline_at = data.get("baseline_at")
        return cls(
            rate=data.get("rate"),
            last_pct=data.get("last_pct"),
            last_at=datetime.fromisoformat(last_at) if last_at else None,
            baseline_pct=data.get("baseline_pct"),
            baseline_at=(
                datetime.fromisoformat(baseline_at) if baseline_at else None
            ),
        )


def reset_ewma_for_replacement(at_pct: float, at_time: datetime) -> EwmaState:
    """Return a fresh EWMA state seeded by the replacement sample."""
    at_time = _to_utc(at_time)
    return EwmaState(
        rate=None,
        last_pct=at_pct,
        last_at=at_time,
        baseline_pct=at_pct,
        baseline_at=at_time,
    )


def update_ewma(
    state: EwmaState,
    pct: float,
    at: datetime,
    *,
    half_life_days: float = EWMA_HALF_LIFE_DAYS,
    window_days: int = EWMA_WINDOW_DAYS,
) -> EwmaState:
    """Fold a new ``(pct, at)`` reading into ``state`` and return the new state.

    Increases vs the previous reading are ignored for the rate calculation
    but still update ``last_pct``/``last_at`` so subsequent decreases are
    measured against the most recent observation. Samples older than
    ``window_days`` past ``baseline_at`` simply replace ``last_*`` without
    influencing the rate -- this caps how far back a single still-current
    EWMA reflects.
    """
    at = _to_utc(at)
    if state.last_at is None or state.last_pct is None:
        return replace(state, last_pct=pct, last_at=at)

    delta_pct = state.last_pct - pct
    delta_days = (at - state.last_at).total_seconds() / 86400.0
    if delta_days <= 0:
        return replace(state, last_pct=pct, last_at=at)

    if state.baseline_at is not None:
        from_baseline_days = (at - state.baseline_at).total_seconds() / 86400.0
    else:
        from_baseline_days = 0.0

    if delta_pct <= 0 or from_baseline_days > window_days:
        return replace(state, last_pct=pct, last_at=at)

    sample_rate = delta_pct / delta_days
    if state.rate is None:
        new_rate = sample_rate
    else:
        weight = 1.0 - 0.5 ** (delta_days / max(half_life_days, 1e-6))
        weight = max(0.0, min(1.0, weight))
        new_rate = state.rate * (1.0 - weight) + sample_rate * weight

    return replace(state, rate=new_rate, last_pct=pct, last_at=at)


@dataclass(slots=True)
class BatteryState:
    """Everything the projector needs to compute ``replace_by`` for a battery."""

    profile_id: str
    replaced_on: datetime | None
    threshold_override: float | None
    last_reading_pct: float | None
    last_reading_at: datetime | None
    ewma: EwmaState = field(default_factory=EwmaState)

    @property
    def profile(self) -> Profile:
        return get_profile(self.profile_id)

    @property
    def threshold_pct(self) -> float:
        if self.threshold_override is not None:
            return float(self.threshold_override)
        return self.profile.default_threshold_pct

    @property
    def on_plateau(self) -> bool:
        plateau = self.profile.plateau_pct
        return (
            plateau is not None
            and self.last_reading_pct is not None
            and self.last_reading_pct >= plateau
        )

    def days_since_replaced(self, *, now: datetime | None = None) -> float | None:
        if self.replaced_on is None:
            return None
        ref = _to_utc(now) if now is not None else _utcnow()
        return (ref - _to_utc(self.replaced_on)).total_seconds() / 86400.0

    def observed_drain_pct(self) -> float | None:
        baseline = self.ewma.baseline_pct
        last = self.last_reading_pct if self.last_reading_pct is not None else self.ewma.last_pct
        if baseline is None or last is None:
            return None
        drain = baseline - last
        return drain if drain > 0 else 0.0

    def source_age_days(self, *, now: datetime | None = None) -> float | None:
        if self.last_reading_at is None:
            return None
        ref = _to_utc(now) if now is not None else _utcnow()
        return (ref - _to_utc(self.last_reading_at)).total_seconds() / 86400.0


def evaluate_confidence(
    state: BatteryState,
    *,
    now: datetime | None = None,
) -> str:
    """Return one of the confidence ladder values for the current state.

    The ``stale`` flag is orthogonal: when the source has produced no update
    in the last :data:`STALE_SOURCE_DAYS` days, we report ``stale`` regardless
    of the other gates. This matches the spec's "stale takes precedence" rule.
    """
    age = state.source_age_days(now=now)
    if age is not None and age >= STALE_SOURCE_DAYS:
        return CONFIDENCE_STALE
    if state.replaced_on is None:
        return CONFIDENCE_NO_DATA
    if state.on_plateau:
        return CONFIDENCE_PROFILE_DEFAULT

    days = state.days_since_replaced(now=now) or 0.0
    drain = state.observed_drain_pct() or 0.0

    if days >= CONFIDENCE_HIGH_DAYS and drain >= CONFIDENCE_HIGH_DRAIN_PCT:
        return CONFIDENCE_HIGH
    if days >= CONFIDENCE_MEDIUM_DAYS and drain >= CONFIDENCE_MEDIUM_DRAIN_PCT:
        return CONFIDENCE_MEDIUM
    if days >= CONFIDENCE_LOW_DAYS and drain >= CONFIDENCE_LOW_DRAIN_PCT:
        return CONFIDENCE_LOW
    return CONFIDENCE_PROFILE_DEFAULT


def _is_observed_confidence(confidence: str) -> bool:
    return confidence in (CONFIDENCE_LOW, CONFIDENCE_MEDIUM, CONFIDENCE_HIGH)


@dataclass(slots=True, frozen=True)
class Prediction:
    """The projector's output for a single battery at the current time."""

    replace_by: datetime | None
    confidence: str
    drain_rate_pct_day: float | None
    threshold_pct: float
    profile_id: str


def project_replace_by(
    state: BatteryState,
    *,
    now: datetime | None = None,
    last_replace_by_fallback: datetime | None = None,
) -> Prediction:
    """Compute the predicted-replacement timestamp for a battery.

    ``last_replace_by_fallback`` is used when ``confidence`` is ``stale``;
    in that case we keep the previously-computed ``replace_by`` instead of
    re-extrapolating against an old EWMA.
    """
    confidence = evaluate_confidence(state, now=now)
    profile = state.profile
    threshold = state.threshold_pct
    rate = state.ewma.rate

    if confidence == CONFIDENCE_NO_DATA:
        return Prediction(
            replace_by=None,
            confidence=confidence,
            drain_rate_pct_day=rate,
            threshold_pct=threshold,
            profile_id=profile.id,
        )

    if confidence == CONFIDENCE_STALE:
        return Prediction(
            replace_by=last_replace_by_fallback,
            confidence=confidence,
            drain_rate_pct_day=rate,
            threshold_pct=threshold,
            profile_id=profile.id,
        )

    if confidence == CONFIDENCE_PROFILE_DEFAULT:
        if state.replaced_on is None:
            return Prediction(
                replace_by=None,
                confidence=confidence,
                drain_rate_pct_day=rate,
                threshold_pct=threshold,
                profile_id=profile.id,
            )
        replace_by = _to_utc(state.replaced_on) + timedelta(
            days=profile.default_lifetime_days
        )
        return Prediction(
            replace_by=replace_by,
            confidence=confidence,
            drain_rate_pct_day=rate,
            threshold_pct=threshold,
            profile_id=profile.id,
        )

    last_pct = state.last_reading_pct
    last_at = state.last_reading_at
    if last_pct is not None and last_at is not None and last_pct <= threshold:
        return Prediction(
            replace_by=_to_utc(last_at),
            confidence=confidence,
            drain_rate_pct_day=rate,
            threshold_pct=threshold,
            profile_id=profile.id,
        )
    if (
        rate is None
        or rate <= 0
        or last_pct is None
        or last_at is None
    ):
        if state.replaced_on is None:
            replace_by = None
        else:
            replace_by = _to_utc(state.replaced_on) + timedelta(
                days=profile.default_lifetime_days
            )
        return Prediction(
            replace_by=replace_by,
            confidence=confidence,
            drain_rate_pct_day=rate,
            threshold_pct=threshold,
            profile_id=profile.id,
        )

    days_to_threshold = (last_pct - threshold) / rate
    days_to_threshold = max(0.0, min(days_to_threshold, 365 * 50))
    replace_by = _to_utc(last_at) + timedelta(days=days_to_threshold)
    return Prediction(
        replace_by=replace_by,
        confidence=confidence,
        drain_rate_pct_day=rate,
        threshold_pct=threshold,
        profile_id=profile.id,
    )


def forward_simulate(
    state: BatteryState,
    *,
    target_date: datetime,
    margin_days: int = 0,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Project a battery's state to ``target_date + margin_days`` (read-only).

    Returns a dict with ``predicted_pct_at_date`` (or ``None``) and a
    ``predicted_state`` of ``ok`` / ``below_threshold`` / ``unknown``,
    plus the active threshold and the confidence value at the time of the
    call.

    ``margin_days`` is a *safety margin* extending the evaluation window: a
    positive value asks "will this battery still be OK at ``target_date +
    margin_days`` if my drain estimate is a little optimistic?". With a
    positive margin, more batteries get flagged as below threshold.

    The simulation uses the active profile's curve shape: for lithium, while
    the projection has not yet left the plateau (i.e., the current reading is
    still on plateau and the elapsed days are within the chemistry-default
    lifetime), the projection holds at the most recent reading. For alkaline,
    or once a lithium battery has left plateau, the simulation linearly
    extrapolates with the EWMA drain rate.
    """
    now_dt = _to_utc(now) if now is not None else _utcnow()
    target = _to_utc(target_date) + timedelta(days=max(0, margin_days))
    confidence = evaluate_confidence(state, now=now_dt)
    threshold = state.threshold_pct

    if confidence == CONFIDENCE_NO_DATA or state.last_reading_pct is None:
        return {
            "predicted_pct_at_date": None,
            "predicted_state": PREDICTED_STATE_UNKNOWN,
            "threshold_pct": threshold,
            "confidence": confidence,
            "drain_rate_pct_day": state.ewma.rate,
            "profile": state.profile.id,
        }

    days_ahead = (target - now_dt).total_seconds() / 86400.0
    if days_ahead <= 0:
        projected_pct = state.last_reading_pct
    elif state.on_plateau and state.replaced_on is not None:
        plateau_end = _to_utc(state.replaced_on) + timedelta(
            days=state.profile.default_lifetime_days
        )
        if target <= plateau_end:
            projected_pct = state.last_reading_pct
        elif state.ewma.rate is not None and state.ewma.rate > 0:
            cliff_days = (target - plateau_end).total_seconds() / 86400.0
            projected_pct = state.last_reading_pct - cliff_days * state.ewma.rate
        else:
            projected_pct = threshold - 1.0
    elif state.ewma.rate is None or state.ewma.rate <= 0:
        projected_pct = state.last_reading_pct
    else:
        projected_pct = (
            state.last_reading_pct - days_ahead * state.ewma.rate
        )

    projected_pct = max(0.0, projected_pct)
    if math.isnan(projected_pct):
        projected_pct = 0.0

    if projected_pct <= threshold:
        predicted_state = PREDICTED_STATE_BELOW_THRESHOLD
    else:
        predicted_state = PREDICTED_STATE_OK

    return {
        "predicted_pct_at_date": round(projected_pct, 2),
        "predicted_state": predicted_state,
        "threshold_pct": threshold,
        "confidence": confidence,
        "drain_rate_pct_day": state.ewma.rate,
        "profile": state.profile.id,
    }
