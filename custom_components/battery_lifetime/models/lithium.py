"""Lithium primary chemistry profile.

Re-exported here so the ``models`` package mirrors the design doc's "one
module per profile" structure even though the actual ``Profile`` instance
is constructed in :mod:`models.__init__`.
"""

from __future__ import annotations

from . import LITHIUM

__all__ = ("LITHIUM",)
