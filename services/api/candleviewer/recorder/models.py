"""Domain models for the recorder module (M11) — E16-T02 recording policy.

`RecorderSetChanged` is the bus contract in `docs/plan/24-internal-schemas.md` §13.1.
"""

from __future__ import annotations

from typing import Final, Literal

from pydantic import BaseModel, ConfigDict

Reason = Literal["manual", "position_open", "chart_open"]

#: Precedence, highest first (ADR-0015 / E16-T02): manual > position_open > chart_open.
PRECEDENCE: Final[tuple[Reason, ...]] = ("manual", "position_open", "chart_open")

#: Eviction priority consumed by the E16-T07 ladder: higher survives longer.
PRIORITY: Final[dict[Reason, int]] = {"manual": 300, "position_open": 200, "chart_open": 100}


class EffectiveEntry(BaseModel):
    """One symbol in the effective recorded set."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    symbol: str
    reason: Reason
    reasons: tuple[Reason, ...]
    priority: int
    #: `False` for manual entries: exempt from the E16-T07 auto-eviction ladder.
    auto_evictable: bool
    #: In the stop grace window (B11 `lingering`): still recording.
    lingering: bool
    pinned: bool
    streams: tuple[str, ...] = ()
    depth: int | None = None


class RecorderSetChanged(BaseModel):
    """Published on `{env}.recorder.set_changed` when the effective set changes."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    symbol: str
    change: Literal["added", "removed", "reason_changed"]
    reason: Reason
    reasons: tuple[Reason, ...]
    priority: int
    auto_evictable: bool
    ts_event: int
