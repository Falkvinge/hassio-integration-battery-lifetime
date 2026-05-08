"""Chemistry profiles for the Battery Lifetime integration.

Each profile defines a discharge-curve shape, a default replacement threshold,
and a default lifetime. v1 ships exactly two profiles: ``alkaline`` and
``lithium`` (primary). Future profiles (NiMH rechargeable, lead-acid, etc.)
plug in by adding a new module here and registering it in ``ALL_PROFILES``.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..const import (
    ALKALINE_LIFETIME_DAYS,
    ALKALINE_PLATEAU_PCT,
    ALKALINE_THRESHOLD_PCT,
    LITHIUM_LIFETIME_DAYS,
    LITHIUM_PLATEAU_PCT,
    LITHIUM_THRESHOLD_PCT,
    PROFILE_ALKALINE,
    PROFILE_LITHIUM,
)


@dataclass(frozen=True, slots=True)
class Profile:
    """A chemistry profile.

    ``plateau_pct`` is the percent threshold above which the battery is
    treated as on the chemistry plateau: while the source reading is
    ``>= plateau_pct``, the projector returns ``replaced_on +
    default_lifetime_days`` and the confidence ladder stays at
    ``profile_default``. ``None`` disables the plateau gate (alkaline).
    """

    id: str
    description: str
    default_threshold_pct: float
    default_lifetime_days: int
    plateau_pct: float | None


ALKALINE = Profile(
    id=PROFILE_ALKALINE,
    description=(
        "Alkaline (Zn-MnO\u2082) primary cells. Smooth-taper discharge, "
        "EWMA extrapolation from day one."
    ),
    default_threshold_pct=ALKALINE_THRESHOLD_PCT,
    default_lifetime_days=ALKALINE_LIFETIME_DAYS,
    plateau_pct=ALKALINE_PLATEAU_PCT,
)

LITHIUM = Profile(
    id=PROFILE_LITHIUM,
    description=(
        "Lithium primary cells (Li-FeS\u2082, LiMnO\u2082). Plateau then "
        "cliff: while the source reads >= 85% the prediction is "
        "replaced_on + default_lifetime_days; below that, EWMA-extrapolate."
    ),
    default_threshold_pct=LITHIUM_THRESHOLD_PCT,
    default_lifetime_days=LITHIUM_LIFETIME_DAYS,
    plateau_pct=LITHIUM_PLATEAU_PCT,
)


_PROFILES: dict[str, Profile] = {p.id: p for p in (ALKALINE, LITHIUM)}


def get_profile(profile_id: str) -> Profile:
    """Look up a profile by its id, falling back to alkaline if unknown."""
    return _PROFILES.get(profile_id, ALKALINE)


def all_profiles() -> tuple[Profile, ...]:
    return tuple(_PROFILES.values())


__all__ = ("ALKALINE", "LITHIUM", "Profile", "all_profiles", "get_profile")
