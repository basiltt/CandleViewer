"""Alert gating pipeline, bar keys and storm suppressor (E40-T03). Pure, synchronous code.

Hot-path exclusion (C-2.20): every candidate fire runs through `gate()`; no statechart is
queried here. The order of `GATE_ORDER` is normative (ticket "Gating pipeline") and the
`checked` trail lets tests prove ORDER, not just outcome (e.g. a snoozed alert never
reaches — and so never consumes — its cooldown).
"""

from __future__ import annotations

from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Final, Literal

Gate = Literal[
    "enabled", "deleted", "expired", "snoozed", "muted", "trigger_mode", "cooldown", "storm"
]
GATE_ORDER: Final[tuple[Gate, ...]] = (
    "enabled", "deleted", "expired", "snoozed", "muted", "trigger_mode", "cooldown", "storm",
)  # fmt: skip

_MIN: Final = 60_000
TIMEFRAME_MS: Final[dict[str, int]] = {
    "1m": _MIN, "3m": 3 * _MIN, "5m": 5 * _MIN, "15m": 15 * _MIN, "30m": 30 * _MIN,
    "1h": 60 * _MIN, "2h": 120 * _MIN, "4h": 240 * _MIN, "6h": 360 * _MIN,
    "12h": 720 * _MIN, "1d": 1440 * _MIN, "1w": 10080 * _MIN,
}  # fmt: skip
#: 1970-01-01 was a Thursday; weekly bars anchor to Monday 00:00 UTC (ADR-0032 Q4).
_WEEK_ANCHOR_MS: Final = 4 * 1440 * _MIN
#: Provisional storm threshold (ADR-0032 Q3, pending E40-D01): >20 deliveries/user/60 s.
STORM_MAX_DELIVERIES: Final = 20
STORM_WINDOW_MS: Final = 60_000
#: Per-alert `once_per_bar` keys kept in memory (older bars are restored from `last_fired_at`).
MAX_BAR_KEYS: Final = 64


def bar_open_ms(ts_ms: int, timeframe: str) -> int:
    """`floor(ts / tf) * tf` on exchange event time; `1w` anchored to Monday."""
    tf = TIMEFRAME_MS[timeframe]
    anchor = _WEEK_ANCHOR_MS if timeframe == "1w" else 0
    return (ts_ms - anchor) // tf * tf + anchor


@dataclass(slots=True)
class AlertState:
    """In-memory mirror of one live `alerts` row plus its trigger-mode memory."""

    id: str
    owner_user_id: str
    name: str
    symbol: str | None
    condition_hash: str
    trigger_mode: str
    cooldown_seconds: int
    severity: str
    channels: tuple[str, ...]
    message_template: str
    timeframe: str | None
    enabled: bool = True
    deleted: bool = False
    expires_at_ms: int | None = None
    snoozed_until_ms: int | None = None
    last_fired_ms: int | None = None
    fired_bars: dict[int, None] = field(default_factory=dict)

    def remember_bar(self, bar_open: int) -> None:
        self.fired_bars[bar_open] = None
        while len(self.fired_bars) > MAX_BAR_KEYS:
            del self.fired_bars[min(self.fired_bars)]


def to_ms(d: datetime | None) -> int | None:
    return None if d is None else int(d.timestamp() * 1000)


@dataclass(frozen=True, slots=True)
class GateResult:
    passed: bool
    reason: Gate | None
    checked: tuple[Gate, ...]
    storm: bool = False  # passed every gate but the storm suppressor: record as suppressed
    bar_open: int | None = None


Muted = Callable[[AlertState], bool]


class StormSuppressor:
    """Per-USER sliding window: at most `limit` normal deliveries per `window_ms`.

    Window arithmetic: a delivery at `t` counts while `now - t < window_ms`. With the
    default 20/60 s the 20th firing in a window is delivered, the 21st is suppressed."""

    def __init__(self, limit: int = STORM_MAX_DELIVERIES, window_ms: int = STORM_WINDOW_MS):
        self.limit, self.window_ms = limit, window_ms
        self._sent: dict[str, deque[int]] = {}

    def _window(self, user: str, now_ms: int) -> deque[int]:
        q = self._sent.setdefault(user, deque())
        while q and now_ms - q[0] >= self.window_ms:
            q.popleft()
        return q

    def in_storm(self, user: str, now_ms: int) -> bool:
        return len(self._window(user, now_ms)) >= self.limit

    def record(self, user: str, now_ms: int) -> None:
        self._window(user, now_ms).append(now_ms)

    def window_end(self, user: str, now_ms: int) -> int:
        """When the current storm window lets the oldest counted delivery fall out."""
        q = self._window(user, now_ms)
        return (q[0] if q else now_ms) + self.window_ms


def gate(
    a: AlertState,
    now_ms: int,
    event_ts_ms: int,
    storm: StormSuppressor,
    *,
    muted: Muted,
    critical_override: Muted,
) -> GateResult:
    """Evaluate one candidate fire through `GATE_ORDER`; stop at the first closed gate.

    Pure apart from reading `storm` (it records only on an actual dispatch, in the
    evaluator's firing transaction). `checked` lists every gate consulted, in order."""
    checked: list[Gate] = []
    bar: int | None = None

    def stop(g: Gate) -> GateResult:
        return GateResult(False, g, tuple(checked), bar_open=bar)

    for g in GATE_ORDER:
        checked.append(g)
        if g == "enabled" and not a.enabled:
            return stop(g)
        if g == "deleted" and a.deleted:
            return stop(g)
        if g == "expired" and a.expires_at_ms is not None and now_ms >= a.expires_at_ms:
            return stop(g)
        if g == "snoozed" and a.snoozed_until_ms is not None and now_ms < a.snoozed_until_ms:
            return stop(g)
        if g == "muted" and muted(a) and not critical_override(a):
            return stop(g)
        if g == "trigger_mode" and a.trigger_mode == "once_per_bar":
            bar = bar_open_ms(event_ts_ms, a.timeframe or "1m")
            if bar in a.fired_bars:
                return stop(g)  # late revision of an already-fired bar never re-opens it
        if (
            g == "cooldown"
            and a.trigger_mode == "every_time"
            and a.last_fired_ms is not None
            and now_ms - a.last_fired_ms < a.cooldown_seconds * 1000
        ):
            return stop(g)
        if g == "storm" and storm.in_storm(a.owner_user_id, now_ms):
            return GateResult(False, g, tuple(checked), storm=True, bar_open=bar)
    return GateResult(True, None, tuple(checked), bar_open=bar)
