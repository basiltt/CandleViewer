"""`RecordingPolicy` — the effective recorded set (ADR-0015 decision 1, E16-T02).

effective set = manual list + symbols with a chart open >= `autostart_delay_s`
                + symbols with an open position (immediately)
                + symbols in the stop grace window (B11 `lingering`).

The per-symbol lifecycle is B11 `recording`, built only via `statechart.build` and
driven only via `statechart.gateway`. This class is the synchronous enforcer
(C-2.21): it owns the trigger refs, the start delay and the grace deadline (checked
by `tick()`, a 1 s evaluation driven by the caller — no per-symbol sleeps, no chart
timers, so a restart re-derives deadlines). The chart only records.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Final, Literal, Protocol

import structlog

import candleviewer.statechart.bindings.b11_recording as b11
from candleviewer.bus.models import Topic
from candleviewer.recorder.errors import InvalidRecordedSymbolError, RecorderSymbolLimitError
from candleviewer.recorder.models import (
    PRECEDENCE,
    PRIORITY,
    EffectiveEntry,
    Reason,
    RecorderSetChanged,
)
from candleviewer.statechart import build
from candleviewer.statechart.factory import default_clock
from candleviewer.statechart.factory import restore as restore_chart
from candleviewer.statechart.gateway import Gateway
from candleviewer.statechart.persistence import MachineKey, Restorer, SealedSnapshot

MACHINE: Final = "recording"
LANE: Final = "platform"
_ACTIVE: Final = frozenset({"starting", "recording", "degraded", "lingering"})
_SYMBOL_RE: Final = re.compile(r"^[A-Z0-9]{2,30}$")
_SETTLE_YIELDS: Final = 64
Change = Literal["added", "removed", "reason_changed"]


def logger() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


class BusPublisher(Protocol):
    async def publish(self, topic: Topic, event: Any) -> None: ...


class AuditSink(Protocol):
    """`AuditWriter.emit` shape, injected (M11 may not import `audit`, C-3.3)."""

    async def emit(self, action: str, **kwargs: Any) -> None: ...


@dataclass(frozen=True, slots=True)
class PolicyConfig:
    """`CV_RECORDER_*` keys (20-architecture.md §7.2)."""

    autostart_delay_s: float = 60.0
    autostop_grace_s: float = 1800.0
    #: Gates chart-open convenience recording only; never position/manual recording.
    autorecord_enabled: bool = True
    max_symbols: int = 20


class _Refusals:
    def __init__(self) -> None:
        self.counts: dict[str, int] = {}

    def record_send_refused(self, reason: str) -> None:
        self.counts[reason] = self.counts.get(reason, 0) + 1


@dataclass
class _Sym:
    charts: dict[str, float] = field(default_factory=dict)  # chart_id -> opened_at
    positions: set[str] = field(default_factory=set)
    manual: dict[str, Any] | None = None
    pinned: bool = False
    linger_deadline: float | None = None
    actor: str = "system"
    trigger_ref: str | None = None
    started_reasons: set[Reason] = field(default_factory=set)  # reasons sent to B11


#: Upper bound on symbols with any tracked trigger (bounded memory, C-2.18).
MAX_TRACKED: Final = 1024


class RecordingPolicy:
    def __init__(
        self,
        *,
        bus: BusPublisher,
        audit: AuditSink,
        env: str,
        now: Callable[[], float],
        config: PolicyConfig | None = None,
    ) -> None:
        self._bus, self._audit, self._env, self._now = bus, audit, env, now
        self._cfg = config or PolicyConfig()
        self._syms: dict[str, _Sym] = {}
        self._charts: dict[str, Any] = {}
        self._published: dict[str, Reason] = {}
        self._gateway = Gateway()
        self.refusals = _Refusals()
        self._lock = asyncio.Lock()
        self._topic = Topic(env=env, domain="recorder", detail="set_changed")
        b11.set_hook(self._hook)

    # --- public triggers ---------------------------------------------------------------

    async def on_chart_opened(self, symbol: str, chart_id: str) -> None:
        self._sym(symbol).charts.setdefault(chart_id, self._now())
        await self._reconcile(symbol)

    async def on_chart_closed(self, symbol: str, chart_id: str) -> None:
        self._sym(symbol).charts.pop(chart_id, None)
        await self._reconcile(symbol)

    async def on_position_opened(self, symbol: str, position_id: str) -> None:
        s = self._sym(symbol)
        s.positions.add(position_id)
        s.trigger_ref = position_id
        await self._reconcile(symbol)

    async def on_position_closed(self, symbol: str, position_id: str) -> None:
        self._sym(symbol).positions.discard(position_id)
        await self._reconcile(symbol)

    async def add_manual(
        self, symbol: str, user_id: str, streams: tuple[str, ...] = (), depth: int | None = None
    ) -> None:
        s = self._sym(symbol)
        if s.manual is None and symbol not in self._active() and self._at_cap():
            raise RecorderSymbolLimitError(f"max {self._cfg.max_symbols} recorded symbols")
        s.manual = {"streams": tuple(streams), "depth": depth}
        s.actor, s.trigger_ref = user_id, f"manual:{user_id}"
        await self._reconcile(symbol)

    async def remove_manual(self, symbol: str) -> None:
        self._sym(symbol).manual = None
        await self._reconcile(symbol)

    async def set_pin(self, symbol: str, pinned: bool) -> None:
        self._sym(symbol).pinned = pinned

    # --- evaluation --------------------------------------------------------------------

    def _sym(self, symbol: str) -> _Sym:
        if not _SYMBOL_RE.match(symbol):
            raise InvalidRecordedSymbolError("symbol must match [A-Z0-9]{2,30}")
        s = self._syms.get(symbol)
        if s is None:
            if len(self._syms) >= MAX_TRACKED:
                raise InvalidRecordedSymbolError(f"more than {MAX_TRACKED} tracked symbols")
            s = self._syms[symbol] = _Sym()
        return s

    def _desired(self, s: _Sym) -> set[Reason]:
        out: set[Reason] = set()
        if s.manual is not None:
            out.add("manual")
        if s.positions:
            out.add("position_open")
        delay, now = self._cfg.autostart_delay_s, self._now()
        if self._cfg.autorecord_enabled and any(now - t >= delay for t in s.charts.values()):
            out.add("chart_open")
        return out

    def leaf(self, symbol: str) -> str | None:
        interp = self._charts.get(symbol)
        return None if interp is None else str(next(iter(interp.current_state_ids))).split(".")[1]

    def _active(self) -> set[str]:
        return {sym for sym in self._charts if self.leaf(sym) in _ACTIVE}

    def _at_cap(self) -> bool:
        return len(self._active()) >= self._cfg.max_symbols

    async def tick(self) -> None:
        """The 1 s evaluation tick: start delays and grace deadlines (fake clock in tests)."""
        for symbol in list(self._syms):
            await self._reconcile(symbol)

    async def _reconcile(self, symbol: str) -> None:
        async with self._lock:
            s = self._syms[symbol]
            want = self._desired(s)
            if self._cfg.autorecord_enabled and s.charts and self.leaf(symbol) == "lingering":
                want.add("chart_open")  # continuing an existing session is not a new start
            for reason in sorted(want - s.started_reasons, key=PRECEDENCE.index):
                await self._add(symbol, s, reason)
            for reason in sorted(s.started_reasons - want, key=PRECEDENCE.index):
                await self._remove(symbol, s, reason)
            leaf = self.leaf(symbol)
            if leaf == "lingering" and s.linger_deadline is not None:
                if self._now() >= s.linger_deadline:
                    await self._send_recording(
                        symbol, "LINGER_DUE", position_open=bool(s.positions)
                    )
            await self._settle(symbol)
            if not s.started_reasons and self.leaf(symbol) in ("recording", "degraded"):
                await self._linger_orphan(symbol, s)  # last reason left while `starting`
            if self.leaf(symbol) in ("stopped", None) and not want and not s.pinned:
                if not s.charts and not s.positions and s.manual is None:
                    self._syms.pop(symbol, None)
            await self._publish(symbol)

    async def _add(self, symbol: str, s: _Sym, reason: Reason) -> None:
        if symbol not in self._charts:
            if reason != "manual" and self._at_cap():
                logger().warning("recorder_autostart_refused", symbol=symbol, reason=reason)
                return
            interp = (await build(MACHINE, clock=default_clock(), lane=LANE)).interpreter
            self._register(symbol, interp)
        streams = list((s.manual or {}).get("streams") or ())
        if await self._send_recording(
            symbol, "REASON_ADDED", reason=reason, symbol=symbol, streams=streams
        ):
            s.started_reasons.add(reason)
            s.linger_deadline = None

    async def _remove(self, symbol: str, s: _Sym, reason: Reason) -> None:
        deadline = self._now() + self._cfg.autostop_grace_s
        if await self._send_recording(
            symbol, "REASON_REMOVED", reason=reason, linger_until_us=int(deadline * 1e6)
        ):
            s.started_reasons.discard(reason)
            if self.leaf(symbol) == "lingering" and s.linger_deadline is None:
                s.linger_deadline = deadline

    async def _linger_orphan(self, symbol: str, s: _Sym) -> None:
        deadline = self._now() + self._cfg.autostop_grace_s
        if await self._send_recording(
            symbol, "REASON_REMOVED", linger_until_us=int(deadline * 1e6)
        ):
            s.linger_deadline = deadline

    def _register(self, symbol: str, interp: Any) -> None:
        self._gateway.register(symbol, interp, kind="recording", lane=LANE, metrics=self.refusals)
        self._charts[symbol] = interp

    async def _send_recording(self, symbol: str, event: str, /, **payload: Any) -> bool:
        """Refuse (never park on `onUnhandled: defer`, CV-C06) what the leaf cannot take."""
        interp = self._charts.get(symbol)
        ev: dict[str, Any] = {"type": event, **payload}
        if interp is None or not interp.can(ev):
            self.refusals.record_send_refused("unhandled")
            return False
        await self._gateway.send(symbol, {"type": event, **payload})
        await self._settle(symbol)
        return True

    async def _settle(self, symbol: str) -> None:
        """Let an invoked service (pure hand-off) reach its outcome; bounded yields only."""
        interp = self._charts.get(symbol)
        if interp is None:
            return
        for _ in range(_SETTLE_YIELDS):
            busy = interp.pending_events or self.leaf(symbol) in ("starting", "stopping")
            if not busy:
                return
            await asyncio.sleep(0)

    # --- outputs -----------------------------------------------------------------------

    def _entry(self, symbol: str) -> EffectiveEntry | None:
        if self.leaf(symbol) not in _ACTIVE:
            return None
        s = self._syms.get(symbol) or _Sym()
        held = sorted(s.started_reasons, key=PRECEDENCE.index)
        lingering = self.leaf(symbol) == "lingering" or not held
        top: Reason = held[0] if held else self._last_reason(symbol)
        manual = s.manual or {}
        return EffectiveEntry(
            symbol=symbol,
            reason=top,
            reasons=tuple(held),
            priority=PRIORITY[top],
            auto_evictable=top != "manual",
            lingering=lingering,
            pinned=s.pinned,
            streams=tuple(manual.get("streams") or ()),
            depth=manual.get("depth"),
        )

    def _last_reason(self, symbol: str) -> Reason:
        return self._published.get(symbol, "chart_open")

    def effective_set(self) -> dict[str, EffectiveEntry]:
        out = {sym: self._entry(sym) for sym in self._charts}
        return {sym: e for sym, e in out.items() if e is not None}

    async def _publish(self, symbol: str) -> None:
        entry, prev = self._entry(symbol), self._published.get(symbol)
        if entry is None and prev is None:
            return
        if entry is not None and entry.reason == prev:
            return
        change: Change = (
            "removed" if entry is None else "added" if prev is None else "reason_changed"
        )
        reason: Reason = entry.reason if entry is not None else prev or "chart_open"
        event = RecorderSetChanged(
            symbol=symbol,
            change=change,
            reason=reason,
            reasons=entry.reasons if entry is not None else (),
            priority=PRIORITY[reason],
            auto_evictable=reason != "manual",
            ts_event=int(self._now() * 1e6),
        )
        if entry is None:
            self._published.pop(symbol, None)
        else:
            self._published[symbol] = entry.reason
        await self._bus.publish(self._topic, event)

    async def _hook(self, name: str, context: dict[str, Any]) -> None:
        """B11 side effects. Audit is write-ahead and raises if unavailable (C-2.9)."""
        symbol = str(context.get("symbol") or "")
        if name not in ("subscribe", "unsubscribe"):
            logger().info("recorder_b11_event", hook=name, symbol=symbol)
            return
        s = self._syms.get(symbol) or _Sym()
        reasons = list(context.get("reasons") or ())
        reason = reasons[0] if reasons else self._published.get(symbol, "chart_open")
        await self._audit.emit(
            "recorder.start" if name == "subscribe" else "recorder.stop",
            actor_label=s.actor if reason == "manual" else "system",
            object_kind="recorded_symbol",
            object_id=symbol,
            reason=str(reason),
            after_state={
                "symbol": symbol,
                "reason": reason,
                "actor": s.actor,
                "trigger_ref": s.trigger_ref,
            },
        )

    # --- lifecycle ---------------------------------------------------------------------

    async def restore(self, restorer: Restorer, key: MachineKey, env: SealedSnapshot) -> None:
        """Rehydrate one symbol's chart via `statechart.persistence` only. Reasons already
        recorded in the snapshot are adopted, so no duplicate session (REASON_ADDED from
        idle/stopped) is opened for a symbol that was recording or lingering."""
        res = await restore_chart(restorer, key, env)
        symbol = key.entity_id
        self._register(symbol, res.interpreter)
        s = self._sym(symbol)
        s.started_reasons = {r for r in res.interpreter.context.get("reasons") or ()}
        if self.leaf(symbol) == "lingering":
            until = res.interpreter.context.get("linger_until_us")
            s.linger_deadline = None if until is None else until / 1e6
        if self.leaf(symbol) in _ACTIVE:
            top = sorted(s.started_reasons, key=PRECEDENCE.index)
            self._published[symbol] = top[0] if top else "chart_open"

    async def stop(self) -> None:
        for symbol in list(self._charts):
            interp = self._charts.pop(symbol)
            self._gateway.unregister(symbol)
            await interp.stop()
        b11.set_hook(None)
