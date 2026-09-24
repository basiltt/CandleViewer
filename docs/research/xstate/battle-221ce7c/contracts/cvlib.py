# -*- coding: utf-8 -*-
"""Shared harness for the CONTRACT MACHINES END-TO-END track (B6-B10).

Builds a stub `MachineLogic` for any catalogue contract by scanning the JSON
for every action / guard / service name, then drives it on the async engine
with a SimulatedClock, a trace plugin, and a snapshot/restore comparator.

Never imports or modifies library source; the library clone is read-only.
"""
from __future__ import annotations

import asyncio
import json
import pathlib
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from xstate_statemachine import (
    Interpreter,
    MachineLogic,
    OverflowPolicy,
    create_machine,
)
from xstate_statemachine.clock import SimulatedClock
from xstate_statemachine.plugins import PluginBase

HERE = pathlib.Path(__file__).parent
SETTLE = 0.02


# ---------------------------------------------------------------------------
# Name collection
# ---------------------------------------------------------------------------
def _as_list(x: Any) -> List[Any]:
    if x is None:
        return []
    return x if isinstance(x, list) else [x]


def collect_names(cfg: Dict[str, Any]) -> Tuple[Set[str], Set[str], Set[str]]:
    """Return (actions, guards, services) referenced anywhere in *cfg*."""
    acts: Set[str] = set()
    guards: Set[str] = set()
    svcs: Set[str] = set()

    def do_actions(v: Any) -> None:
        for a in _as_list(v):
            if isinstance(a, str):
                acts.add(a)
            elif isinstance(a, dict) and isinstance(a.get("type"), str):
                acts.add(a["type"])

    def do_trans(v: Any) -> None:
        for t in _as_list(v):
            if isinstance(t, dict):
                do_actions(t.get("actions"))
                g = t.get("guard") or t.get("cond")
                if isinstance(g, str):
                    guards.add(g)

    def walk(node: Dict[str, Any]) -> None:
        do_actions(node.get("entry"))
        do_actions(node.get("exit"))
        do_trans(node.get("always"))
        for _ev, tr in (node.get("on") or {}).items():
            do_trans(tr)
        for _ev, tr in (node.get("after") or {}).items():
            do_trans(tr)
        for inv in _as_list(node.get("invoke")):
            if isinstance(inv, dict):
                if isinstance(inv.get("src"), str):
                    svcs.add(inv["src"])
                do_trans(inv.get("onDone"))
                do_trans(inv.get("onError"))
        for child in (node.get("states") or {}).values():
            walk(child)

    walk(cfg)
    return acts, guards, svcs


def declared_events(cfg: Dict[str, Any]) -> Set[str]:
    out: Set[str] = set()

    def walk(node: Dict[str, Any]) -> None:
        out.update((node.get("on") or {}).keys())
        for child in (node.get("states") or {}).values():
            walk(child)

    walk(cfg)
    out.discard("*")
    return out


# ---------------------------------------------------------------------------
# Stub logic
# ---------------------------------------------------------------------------
@dataclass
class Rig:
    """Mutable knobs the scenario driver flips between runs."""

    guard_values: Dict[str, bool] = field(default_factory=dict)
    guard_raises: Set[str] = field(default_factory=set)
    action_raises: Set[str] = field(default_factory=set)
    service_mode: Dict[str, str] = field(default_factory=dict)  # ok|fail|hang
    service_output: Dict[str, Any] = field(default_factory=dict)
    action_hooks: Dict[str, Callable[..., None]] = field(default_factory=dict)
    calls: List[str] = field(default_factory=list)
    effects: List[str] = field(default_factory=list)
    #: name -> asyncio.Event; service_mode "gate" waits on it before
    #: resolving, so a scenario can hold a machine inside an invoking state.
    gates: Dict[str, Any] = field(default_factory=dict)

    def gate(self, name: str):
        ev = self.gates.get(name)
        if ev is None:
            ev = self.gates[name] = asyncio.Event()
        return ev


def make_logic(cfg: Dict[str, Any], rig: Rig) -> MachineLogic:
    acts, guards, svcs = collect_names(cfg)
    A: Dict[str, Any] = {}
    G: Dict[str, Any] = {}
    S: Dict[str, Any] = {}

    def mk_action(n: str):
        def fn(interp, ctx, event, action_def):  # noqa: ANN001
            rig.calls.append("A:" + n)
            if n in rig.action_raises:
                raise RuntimeError("boom:" + n)
            hook = rig.action_hooks.get(n)
            if hook is not None:
                hook(interp, ctx, event)
            ctx.setdefault("_trace", []).append(n)

        fn.__name__ = n
        return fn

    def mk_guard(n: str):
        def fn(ctx, event):  # noqa: ANN001
            rig.calls.append("G:" + n)
            if n in rig.guard_raises:
                raise RuntimeError("guard-boom:" + n)
            return bool(rig.guard_values.get(n, False))

        fn.__name__ = n
        return fn

    def mk_service(n: str):
        async def fn(interp, ctx, event):  # noqa: ANN001
            rig.calls.append("S:" + n)
            mode = rig.service_mode.get(n, "ok")
            if mode == "hang":
                await asyncio.sleep(3600)
            if mode == "gate":
                await rig.gate(n).wait()
                mode = rig.service_mode.get(n, "ok")
            if mode == "fail":
                raise RuntimeError("svc-fail:" + n)
            return rig.service_output.get(n, {"svc": n})

        fn.__name__ = n
        return fn

    for name in sorted(acts):
        A[name] = mk_action(name)
    for name in sorted(guards):
        G[name] = mk_guard(name)
    for name in sorted(svcs):
        S[name] = mk_service(name)

    return MachineLogic(actions=A, guards=G, services=S, strict=True)


# ---------------------------------------------------------------------------
# Trace plugin
# ---------------------------------------------------------------------------
class TraceP(PluginBase):
    def __init__(self) -> None:
        self.actions: List[str] = []
        self.transitions: List[str] = []
        self.dropped: List[Tuple[str, str]] = []
        self.unhandled: List[Tuple[str, str]] = []

    def on_action_execute(self, interp, action):  # noqa: ANN001
        self.actions.append(action.type)

    def on_transition(self, interp, frm, to, t):  # noqa: ANN001
        leaves = ",".join(sorted(n.id for n in to if not n.states))
        self.transitions.append(str(t.event) + "->" + leaves)

    def on_event_dropped(self, interp, event, reason):  # noqa: ANN001
        self.dropped.append((getattr(event, "type", "?"), reason))

    def on_unhandled_event(self, interp, event, ids, disposition):  # noqa: ANN001
        self.unhandled.append((event.type, disposition))


@dataclass
class Outcome:
    states: List[str] = field(default_factory=list)
    context: Dict[str, Any] = field(default_factory=dict)
    actions: List[str] = field(default_factory=list)
    transitions: List[str] = field(default_factory=list)
    status: str = ""
    deferred: int = 0
    error: Optional[str] = None

    def key(self) -> Tuple[Any, ...]:
        return (
            tuple(self.states),
            json.dumps(self.context, sort_keys=True, default=str),
            tuple(self.actions),
            self.status,
        )


def snap(interp, plug: TraceP) -> Outcome:
    return Outcome(
        states=sorted(interp.current_state_ids),
        context=json.loads(json.dumps(interp.context, default=str)),
        actions=list(plug.actions),
        transitions=list(plug.transitions),
        status=interp.status,
        deferred=interp.deferred_count,
        error=None if interp.error is None else repr(interp.error),
    )


# ---------------------------------------------------------------------------
# Build / run
# ---------------------------------------------------------------------------
def load(bid: str) -> Dict[str, Any]:
    fixed = HERE / (bid + ".fixed.machine.json")
    p = fixed if fixed.exists() else HERE / (bid + ".machine.json")
    return json.loads(p.read_text(encoding="utf-8"))


def build(cfg: Dict[str, Any], rig: Rig):
    return create_machine(cfg, logic=make_logic(cfg, rig))


def new_interp(cfg, rig, clock=None, max_queue_size=64):
    m = build(cfg, rig)
    clock = clock or SimulatedClock()
    interp = Interpreter(
        m,
        clock=clock,
        max_queue_size=max_queue_size,
        overflow_policy=OverflowPolicy.RAISE,
    )
    plug = TraceP()
    interp.use(plug)
    return m, interp, plug, clock


def attach_clock(interp, clock: SimulatedClock) -> None:
    """Swap a restored interpreter clock for *clock* (from_snapshot(clock=)
    exists on this commit; kept for the legacy path)."""
    from xstate_statemachine.base_interpreter import _accepts_kwarg

    interp.clock = clock
    interp._clock_accepts_sync = _accepts_kwarg(clock.set_timeout, "sync")
    clock._attach(interp._settle_for_clock)


async def apply(interp, clock, ev) -> Any:
    """Apply one script step. ('__TICK__', ms) advances virtual time."""
    if isinstance(ev, tuple) and ev[0] == "__TICK__":
        await clock.increment(ev[1])
        await asyncio.sleep(SETTLE)
        return None
    if isinstance(ev, tuple):
        name, payload = ev[0], ev[1]
    else:
        name, payload = ev, {}
    r = await interp.send(name, **payload)
    await asyncio.sleep(SETTLE)
    return r
