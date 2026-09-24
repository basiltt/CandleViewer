# -*- coding: utf-8 -*-
"""Core harness: run / snapshot / restore / compare.

`run_plain(seq)`      -- uninterrupted reference run.
`run_interrupted(seq, k)` -- crash after event k, snapshot, restore into a
fresh interpreter, resume with the remaining events.

Both return an `Outcome` (state ids, context, action trace) that is compared
field by field.
"""
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from xstate_statemachine import Interpreter
from xstate_statemachine.clock import SimulatedClock
from xstate_statemachine.plugins import PluginBase

import order_machine


class TraceP(PluginBase):
    """Records every executed action and every transition."""

    def __init__(self) -> None:
        self.actions: List[str] = []
        self.transitions: List[str] = []
        self.dropped: List[Tuple[str, str]] = []
        self.unhandled: List[Tuple[str, str]] = []

    def on_action_execute(self, interp, action):  # noqa: ANN001
        self.actions.append(action.type)

    def on_transition(self, interp, frm, to, t):  # noqa: ANN001
        self.transitions.append(
            f"{t.event}->{sorted(n.id for n in to if not n.states)}"
        )

    def on_event_dropped(self, interp, event, reason):  # noqa: ANN001
        self.dropped.append((getattr(event, "type", "?"), reason))

    def on_unhandled_event(self, interp, event, ids, disposition):  # noqa: ANN001
        self.unhandled.append((event.type, disposition))


@dataclass
class Outcome:
    states: List[str] = field(default_factory=list)
    context: Dict[str, Any] = field(default_factory=dict)
    actions: List[str] = field(default_factory=list)
    status: str = ""
    deferred: int = 0
    pending: int = 0
    error: Optional[str] = None
    note: str = ""

    def key(self) -> Tuple[Any, ...]:
        return (
            tuple(self.states),
            json.dumps(self.context, sort_keys=True, default=str),
            tuple(self.actions),
            self.status,
        )


SETTLE = 0.02


def attach_clock(interp, clock: SimulatedClock) -> None:
    """Swap a restored interpreter's clock for *clock*.

    `from_snapshot()` takes no `clock=` argument, so a restored interpreter
    always gets a `RealClock`. Everything the engine does with time goes
    through `self.clock` and `self._clock_accepts_sync`, both set in
    `BaseInterpreter.__init__`, so re-deriving those two is a faithful
    substitution for a constructor argument that does not exist.
    """
    from xstate_statemachine.base_interpreter import _accepts_kwarg

    interp.clock = clock
    interp._clock_accepts_sync = _accepts_kwarg(clock.set_timeout, "sync")
    clock._attach(interp._settle_for_clock)


async def _apply(interp, ev: Dict[str, Any], clock: SimulatedClock) -> None:
    if ev["type"] == "__TICK__":
        await clock.increment(ev["ms"])
        return
    await interp.send(ev["type"], **(ev.get("payload") or {}))
    await asyncio.sleep(SETTLE)


def _snap(interp, plug: TraceP) -> Outcome:
    return Outcome(
        states=sorted(interp.current_state_ids),
        context=json.loads(json.dumps(interp.context, default=str)),
        actions=list(plug.actions),
        status=interp.status,
        deferred=interp.deferred_count,
        pending=len(interp.pending_events),
        error=None if interp.error is None else str(interp.error),
    )


async def run_plain(seq: List[Dict[str, Any]], **kw) -> Outcome:
    m = order_machine.build(**kw)
    clock = SimulatedClock()
    plug = TraceP()
    interp = Interpreter(m, clock=clock)
    interp.use(plug)
    await interp.start()
    await asyncio.sleep(SETTLE)
    for ev in seq:
        if interp.status != "running":
            break
        await _apply(interp, ev, clock)
    await asyncio.sleep(SETTLE)
    out = _snap(interp, plug)
    await interp.stop()
    return out


async def run_interrupted(
    seq: List[Dict[str, Any]], k: int, *, restart_services: bool = False, **kw
) -> Tuple[Outcome, str]:
    """Crash after `k` events; restore; resume with the rest."""
    m = order_machine.build(**kw)
    clock = SimulatedClock()
    plug = TraceP()
    interp = Interpreter(m, clock=clock)
    interp.use(plug)
    await interp.start()
    await asyncio.sleep(SETTLE)
    for ev in seq[:k]:
        if interp.status != "running":
            break
        await _apply(interp, ev, clock)
    await asyncio.sleep(SETTLE)
    blob = interp.get_snapshot()
    now = clock.now()
    # 💥 crash: the process dies. stop() is NOT the crash path, but we must
    #    release the loop; nothing after this point touches `interp`.
    interp._plugins = []
    await interp.stop()

    m2 = order_machine.build(**kw)
    clock2 = SimulatedClock()
    # Virtual time is carried across the restore. `set()` returns an
    # awaitable inside a loop and there are no timers yet, so assign.
    clock2._now = now
    plug2 = TraceP()
    plug2.actions = list(plug.actions)  # carry the pre-crash trace
    i2 = Interpreter.from_snapshot(
        blob, m2, restart_services=restart_services
    )
    # ⚠️ D-persistence-1: `from_snapshot` has no `clock=` parameter, so the
    #    restored interpreter is built with a RealClock. Injecting the
    #    simulated clock is the only way to keep virtual time across a
    #    restore; we do it here so the rest of the track can proceed.
    attach_clock(i2, clock2)
    i2.use(plug2)
    await i2.start()
    await asyncio.sleep(SETTLE)
    for ev in seq[k:]:
        if i2.status != "running":
            break
        await _apply(i2, ev, clock2)
    await asyncio.sleep(SETTLE)
    out = _snap(i2, plug2)
    await i2.stop()
    return out, blob
