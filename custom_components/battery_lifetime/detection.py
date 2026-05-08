"""Replacement-detection logic for the Battery Lifetime integration.

The auto-detection rule is:

  prev_pct < 80
  AND new_pct >= 100
  AND (new_at - prev_at) <= 30 days
  AND the 100% reading is confirmed by either:
    (a) a subsequent update at >= 100%, OR
    (b) one continuous hour with no contradicting reading (< 95%)
  AND the battery is currently tracked (tracking_enabled is True)

Glitch protection: if a candidate 100% reading drops below 95% within an
hour, the candidate is discarded.

Stale-prior protection: if the most recent prior reading is older than 30
days, the rule never auto-commits. Instead, the integration raises a
persistent HA notification offering Confirm / Dismiss / Exclude.

This module keeps two layers:

* Pure-logic helpers (``classify_reading``, ``classify_followup``) that
  return enums describing what should happen, with no HA imports. These are
  the unit-tested heart of the rule.
* :class:`ReplacementDetector` -- the HA-aware wrapper that holds candidate
  state per ``unique_id``, arms 1-hour confirmation timers via
  :func:`async_call_later`, raises persistent notifications, and emits the
  ``battery_lifetime_replacement_detected`` HA event on commit.

Cold-start backfill lives in :class:`ColdStartBackfiller`, which queries
HA long-term statistics (preferred) and the recorder (fallback) for the
most recent qualifying jump.
"""

from __future__ import annotations

import enum
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from homeassistant.components import persistent_notification
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.event import async_call_later

from .const import (
    DOMAIN,
    EVENT_REPLACEMENT_DETECTED,
    NOTIFICATION_STALE_PRIOR_PREFIX,
    REPLACEMENT_CONFIRM_TIMEOUT_SECONDS,
    REPLACEMENT_DROP_THRESHOLD,
    REPLACEMENT_FULL_THRESHOLD,
    REPLACEMENT_GLITCH_REVERT_PCT,
    REPLACEMENT_PRIOR_MAX_AGE_DAYS,
    REPLACEMENT_SOURCE_AUTO,
    REPLACEMENT_SOURCE_COLD_START_BACKFILL,
    REPLACEMENT_SOURCE_STALE_CONFIRMED,
)

_LOGGER = logging.getLogger(__name__)
UTC = timezone.utc


def _to_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


class ReadingClassification(enum.Enum):
    """What to do with an incoming reading from the source sensor."""

    NO_EVENT = "no_event"
    NEW_CANDIDATE = "new_candidate"
    STALE_PRIOR_NOTIFICATION = "stale_prior_notification"


class FollowupClassification(enum.Enum):
    """What to do with a follow-up reading while a candidate is pending."""

    HOLD = "hold"
    CONFIRM = "confirm"
    GLITCH = "glitch"


@dataclass(slots=True, frozen=True)
class Candidate:
    """An unconfirmed 100% reading awaiting confirmation or expiry."""

    new_pct: float
    new_at: datetime
    prior_pct: float
    prior_at: datetime


def classify_reading(
    *,
    prev_pct: float | None,
    prev_at: datetime | None,
    new_pct: float,
    new_at: datetime,
    drop_threshold: float = REPLACEMENT_DROP_THRESHOLD,
    full_threshold: float = REPLACEMENT_FULL_THRESHOLD,
    prior_max_age_days: int = REPLACEMENT_PRIOR_MAX_AGE_DAYS,
) -> ReadingClassification:
    """Decide whether a fresh reading triggers candidacy or a notification."""
    if prev_pct is None or prev_at is None:
        return ReadingClassification.NO_EVENT
    if new_pct < full_threshold:
        return ReadingClassification.NO_EVENT
    if prev_pct >= drop_threshold:
        return ReadingClassification.NO_EVENT
    age_days = (_to_utc(new_at) - _to_utc(prev_at)).total_seconds() / 86400.0
    if age_days > prior_max_age_days:
        return ReadingClassification.STALE_PRIOR_NOTIFICATION
    return ReadingClassification.NEW_CANDIDATE


def classify_followup(
    candidate: Candidate,
    *,
    new_pct: float,
    new_at: datetime,
    full_threshold: float = REPLACEMENT_FULL_THRESHOLD,
    glitch_revert_pct: float = REPLACEMENT_GLITCH_REVERT_PCT,
    confirm_timeout_seconds: int = REPLACEMENT_CONFIRM_TIMEOUT_SECONDS,
) -> FollowupClassification:
    """Decide what to do with a follow-up reading while ``candidate`` is open."""
    age = (_to_utc(new_at) - _to_utc(candidate.new_at)).total_seconds()
    if age >= confirm_timeout_seconds:
        if new_pct < glitch_revert_pct:
            return FollowupClassification.GLITCH
        return FollowupClassification.CONFIRM
    if new_pct >= full_threshold:
        return FollowupClassification.CONFIRM
    if new_pct < glitch_revert_pct:
        return FollowupClassification.GLITCH
    return FollowupClassification.HOLD


CommitCallback = Callable[
    [str, datetime, dict[str, Any]],
    Awaitable[None],
]


class ReplacementDetector:
    """HA-aware wrapper around the pure-logic detection rules."""

    def __init__(
        self,
        hass: HomeAssistant,
        commit_callback: CommitCallback,
    ) -> None:
        self._hass = hass
        self._commit = commit_callback
        self._candidates: dict[str, Candidate] = {}
        self._timers: dict[str, CALLBACK_TYPE] = {}
        self._stale_pending: dict[str, Candidate] = {}

    @property
    def candidates(self) -> dict[str, Candidate]:
        return dict(self._candidates)

    @property
    def stale_pending(self) -> dict[str, Candidate]:
        return dict(self._stale_pending)

    async def process_reading(
        self,
        unique_id: str,
        entity_id: str,
        *,
        prev_pct: float | None,
        prev_at: datetime | None,
        new_pct: float,
        new_at: datetime,
        tracking_enabled: bool,
    ) -> bool:
        """Feed a new source reading into the detector.

        Returns ``True`` if a replacement was committed during this call.
        """
        if not tracking_enabled:
            self._cancel_timer(unique_id)
            self._candidates.pop(unique_id, None)
            return False

        candidate = self._candidates.get(unique_id)
        if candidate is not None:
            decision = classify_followup(
                candidate, new_pct=new_pct, new_at=new_at
            )
            if decision is FollowupClassification.CONFIRM:
                self._cancel_timer(unique_id)
                self._candidates.pop(unique_id, None)
                await self._commit_replacement(
                    unique_id,
                    entity_id,
                    candidate=candidate,
                    source=REPLACEMENT_SOURCE_AUTO,
                    confirmed=True,
                )
                return True
            if decision is FollowupClassification.GLITCH:
                self._cancel_timer(unique_id)
                self._candidates.pop(unique_id, None)
                _LOGGER.debug(
                    "battery_lifetime: %s candidate discarded as glitch "
                    "(reverted to %.1f%% within %s s)",
                    unique_id,
                    new_pct,
                    REPLACEMENT_CONFIRM_TIMEOUT_SECONDS,
                )
                return False

        decision = classify_reading(
            prev_pct=prev_pct,
            prev_at=prev_at,
            new_pct=new_pct,
            new_at=new_at,
        )
        if decision is ReadingClassification.NO_EVENT:
            return False
        if decision is ReadingClassification.STALE_PRIOR_NOTIFICATION:
            assert prev_pct is not None and prev_at is not None
            await self._raise_stale_notification(
                unique_id=unique_id,
                entity_id=entity_id,
                candidate=Candidate(
                    new_pct=new_pct,
                    new_at=_to_utc(new_at),
                    prior_pct=prev_pct,
                    prior_at=_to_utc(prev_at),
                ),
            )
            return False

        assert prev_pct is not None and prev_at is not None
        self._candidates[unique_id] = Candidate(
            new_pct=new_pct,
            new_at=_to_utc(new_at),
            prior_pct=prev_pct,
            prior_at=_to_utc(prev_at),
        )
        self._arm_timer(unique_id, entity_id)
        return False

    async def _commit_replacement(
        self,
        unique_id: str,
        entity_id: str,
        *,
        candidate: Candidate,
        source: str,
        confirmed: bool,
    ) -> None:
        # ``source`` MUST be one of the values enumerated in
        # ``replacement-detection/spec.md`` ("Replacement event payload"):
        # REPLACEMENT_SOURCE_AUTO, REPLACEMENT_SOURCE_MANUAL_BUTTON,
        # REPLACEMENT_SOURCE_MANUAL_DATE_EDIT,
        # REPLACEMENT_SOURCE_COLD_START_BACKFILL, or
        # REPLACEMENT_SOURCE_STALE_CONFIRMED. Dismissal does not commit and
        # therefore has no event source.
        prior_age = (
            candidate.new_at - candidate.prior_at
        ).total_seconds()
        payload: dict[str, Any] = {
            "entity_id": entity_id,
            "unique_id": unique_id,
            "previous_pct": candidate.prior_pct,
            "current_pct": candidate.new_pct,
            "prior_reading_age_seconds": prior_age,
            "replaced_on": candidate.new_at.isoformat(),
            "confirmed": confirmed,
            "source": source,
        }
        await self._commit(unique_id, candidate.new_at, payload)
        self._hass.bus.async_fire(EVENT_REPLACEMENT_DETECTED, payload)
        _LOGGER.info(
            "battery_lifetime: replacement committed for %s (%s) at %s",
            entity_id,
            source,
            candidate.new_at.isoformat(),
        )

    @callback
    def _cancel_timer(self, unique_id: str) -> None:
        timer = self._timers.pop(unique_id, None)
        if timer is not None:
            timer()

    def _arm_timer(self, unique_id: str, entity_id: str) -> None:
        self._cancel_timer(unique_id)

        async def _confirm_by_timer(_now: datetime) -> None:
            self._timers.pop(unique_id, None)
            candidate = self._candidates.pop(unique_id, None)
            if candidate is None:
                return
            await self._commit_replacement(
                unique_id,
                entity_id,
                candidate=candidate,
                source=REPLACEMENT_SOURCE_AUTO,
                confirmed=True,
            )

        self._timers[unique_id] = async_call_later(
            self._hass,
            REPLACEMENT_CONFIRM_TIMEOUT_SECONDS,
            _confirm_by_timer,
        )

    async def _raise_stale_notification(
        self,
        *,
        unique_id: str,
        entity_id: str,
        candidate: Candidate,
    ) -> None:
        self._stale_pending[unique_id] = candidate
        notification_id = f"{NOTIFICATION_STALE_PRIOR_PREFIX}{unique_id}"
        age_days = (candidate.new_at - candidate.prior_at).total_seconds() / 86400.0
        message = (
            f"Possible battery replacement detected for **{entity_id}**.\n\n"
            f"- Previous reading: **{candidate.prior_pct:.0f}%** "
            f"({age_days:.0f} days ago)\n"
            f"- New reading: **{candidate.new_pct:.0f}%**\n\n"
            "Take action by calling one of these services from "
            "**Developer Tools → Services** "
            f"(set `entity_id: {entity_id}`):\n\n"
            f"- `battery_lifetime.confirm_stale_replacement` — "
            "record the replacement at the candidate timestamp\n"
            f"- `battery_lifetime.dismiss_stale_replacement` — "
            "ignore this candidate and keep tracking\n"
            f"- `battery_lifetime.exclude_stale_replacement` — "
            "ignore this candidate and turn tracking off for this battery"
        )
        persistent_notification.async_create(
            self._hass,
            message,
            title="Battery Lifetime: confirm replacement?",
            notification_id=notification_id,
        )

    async def confirm_stale(self, unique_id: str, entity_id: str) -> bool:
        """User confirmed a stale-prior replacement notification.

        Returns ``True`` on commit, ``False`` if no candidate was pending.
        Sets ``replaced_on`` to the candidate's ``new_at`` (the first ``100%``
        reading observed during the stale episode), per
        ``replacement-detection/spec.md``.
        """
        candidate = self._stale_pending.pop(unique_id, None)
        if candidate is None:
            return False
        await self._commit_replacement(
            unique_id,
            entity_id,
            candidate=candidate,
            source=REPLACEMENT_SOURCE_STALE_CONFIRMED,
            confirmed=True,
        )
        persistent_notification.async_dismiss(
            self._hass, f"{NOTIFICATION_STALE_PRIOR_PREFIX}{unique_id}"
        )
        return True

    async def dismiss_stale(self, unique_id: str) -> bool:
        """User dismissed a stale-prior replacement notification.

        Returns ``True`` if a candidate was pending (and is now cleared),
        ``False`` otherwise. Tracking remains enabled.
        """
        had_pending = self._stale_pending.pop(unique_id, None) is not None
        persistent_notification.async_dismiss(
            self._hass, f"{NOTIFICATION_STALE_PRIOR_PREFIX}{unique_id}"
        )
        return had_pending

    async def exclude_stale(self, unique_id: str) -> bool:
        """User excluded the battery from a stale-prior notification.

        Clears the pending candidate and dismisses the notification. The
        caller (the service handler) is responsible for flipping
        ``tracking_enabled`` off on the corresponding battery record, since
        the detector deliberately has no coordinator dependency. Returns
        ``True`` if a candidate was pending.
        """
        return await self.dismiss_stale(unique_id)

    def shutdown(self) -> None:
        """Cancel all outstanding confirmation timers."""
        for cancel in list(self._timers.values()):
            cancel()
        self._timers.clear()


@dataclass(slots=True, frozen=True)
class ColdStartHit:
    """Result of a cold-start backfill query."""

    replaced_on: datetime
    previous_pct: float
    current_pct: float
    prior_at: datetime


class ColdStartBackfiller:
    """Find the most recent qualifying jump for a battery on first attach."""

    def __init__(self, hass: HomeAssistant) -> None:
        self._hass = hass

    async def find_most_recent_jump(
        self,
        entity_id: str,
        *,
        lookback_days: int = 365 * 5,
    ) -> ColdStartHit | None:
        """Return the most recent <80% -> >=100% jump for ``entity_id``."""
        try:
            from homeassistant.components.recorder import (  # noqa: PLC0415
                get_instance,
                history,
                statistics,
            )
        except ImportError:
            _LOGGER.debug(
                "battery_lifetime: recorder not available; skipping cold-start"
            )
            return None

        end = datetime.now(tz=UTC)
        start = end - timedelta(days=lookback_days)
        try:
            recorder = get_instance(self._hass)
        except (KeyError, RuntimeError):
            _LOGGER.debug(
                "battery_lifetime: recorder not yet running; skipping "
                "cold-start backfill for %s",
                entity_id,
            )
            return None

        lts_hit = await recorder.async_add_executor_job(
            self._find_jump_in_lts,
            statistics,
            self._hass,
            start,
            end,
            entity_id,
        )
        if lts_hit is not None:
            return lts_hit

        recorder_start = end - timedelta(days=min(lookback_days, 60))
        history_hit = await recorder.async_add_executor_job(
            self._find_jump_in_history,
            history,
            self._hass,
            recorder_start,
            end,
            entity_id,
        )
        return history_hit

    @staticmethod
    def _find_jump_in_lts(
        statistics_module: Any,
        hass: HomeAssistant,
        start: datetime,
        end: datetime,
        entity_id: str,
    ) -> ColdStartHit | None:
        try:
            data = statistics_module.statistics_during_period(
                hass,
                start,
                end,
                statistic_ids={entity_id},
                period="hour",
                units=None,
                types={"mean"},
            )
        except Exception as err:  # pragma: no cover - defensive
            _LOGGER.debug(
                "battery_lifetime: LTS lookup failed for %s: %s", entity_id, err
            )
            return None
        rows = data.get(entity_id) or []
        samples: list[tuple[datetime, float]] = []
        for row in rows:
            mean = row.get("mean")
            ts = row.get("start")
            if mean is None or ts is None:
                continue
            if isinstance(ts, (int, float)):
                ts = datetime.fromtimestamp(float(ts), tz=UTC)
            samples.append((ts, float(mean)))
        return _scan_for_jump(samples)

    @staticmethod
    def _find_jump_in_history(
        history_module: Any,
        hass: HomeAssistant,
        start: datetime,
        end: datetime,
        entity_id: str,
    ) -> ColdStartHit | None:
        try:
            data = history_module.state_changes_during_period(
                hass, start, end, entity_id=entity_id
            )
        except Exception as err:  # pragma: no cover - defensive
            _LOGGER.debug(
                "battery_lifetime: recorder lookup failed for %s: %s",
                entity_id,
                err,
            )
            return None
        states = data.get(entity_id) or []
        samples: list[tuple[datetime, float]] = []
        for state in states:
            try:
                pct = float(state.state)
            except (TypeError, ValueError):
                continue
            ts = state.last_updated
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=UTC)
            samples.append((ts, pct))
        return _scan_for_jump(samples)


def _scan_for_jump(samples: list[tuple[datetime, float]]) -> ColdStartHit | None:
    """Walk ``samples`` (in chronological order) and return the most recent jump."""
    samples = sorted(samples, key=lambda item: item[0])
    last_hit: ColdStartHit | None = None
    prev: tuple[datetime, float] | None = None
    for ts, pct in samples:
        if prev is None:
            prev = (ts, pct)
            continue
        prev_at, prev_pct = prev
        if (
            prev_pct < REPLACEMENT_DROP_THRESHOLD
            and pct >= REPLACEMENT_FULL_THRESHOLD
            and (ts - prev_at).total_seconds() / 86400.0
            <= REPLACEMENT_PRIOR_MAX_AGE_DAYS
        ):
            last_hit = ColdStartHit(
                replaced_on=ts,
                previous_pct=prev_pct,
                current_pct=pct,
                prior_at=prev_at,
            )
        prev = (ts, pct)
    return last_hit


async def commit_cold_start_hit(
    hass: HomeAssistant,
    *,
    entity_id: str,
    unique_id: str,
    hit: ColdStartHit,
    apply: Callable[[datetime], Awaitable[None]],
) -> None:
    """Apply a cold-start hit and emit the replacement event."""
    payload: dict[str, Any] = {
        "entity_id": entity_id,
        "unique_id": unique_id,
        "previous_pct": hit.previous_pct,
        "current_pct": hit.current_pct,
        "prior_reading_age_seconds": (
            hit.replaced_on - hit.prior_at
        ).total_seconds(),
        "replaced_on": hit.replaced_on.isoformat(),
        "confirmed": True,
        "source": REPLACEMENT_SOURCE_COLD_START_BACKFILL,
    }
    await apply(hit.replaced_on)
    hass.bus.async_fire(EVENT_REPLACEMENT_DETECTED, payload)
    _LOGGER.info(
        "battery_lifetime: cold-start backfill seeded %s with replaced_on=%s",
        entity_id,
        hit.replaced_on.isoformat(),
    )


def estimate_replaced_on_from_drain(
    *,
    last_pct: float,
    last_at: datetime,
    drain_rate_pct_day: float,
    starting_pct: float = 100.0,
) -> datetime | None:
    """Backwards-extrapolate ``replaced_on`` from a current drain rate.

    Returns ``None`` if extrapolation is not feasible (no rate, or the most
    recent reading is already at/above the assumed starting percent).
    """
    if drain_rate_pct_day <= 0:
        return None
    if last_pct >= starting_pct:
        return None
    days_since = (starting_pct - last_pct) / drain_rate_pct_day
    if days_since < 0:
        return None
    return _to_utc(last_at) - timedelta(days=days_since)


__all__ = (
    "Candidate",
    "ColdStartBackfiller",
    "ColdStartHit",
    "FollowupClassification",
    "ReadingClassification",
    "ReplacementDetector",
    "classify_followup",
    "classify_reading",
    "commit_cold_start_hit",
    "estimate_replaced_on_from_drain",
)
