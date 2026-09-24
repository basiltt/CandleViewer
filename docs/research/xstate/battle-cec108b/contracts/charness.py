# -*- coding: utf-8 -*-
"""Contract harness: stub MachineLogic, trace plugin, snapshot/resume compare."""
from __future__ import annotations
import asyncio, json, copy
from dataclasses import dataclass, field
from typing import Any, Dict, List, Tuple, Optional

from xstate_statemachine import (Interpreter, MachineLogic, create_machine,
                                 SyncInterpreter, OverflowPolicy)
from xstate_statemachine.actions import is_builtin
from xstate_statemachine.clock import SimulatedClock
from xstate_statemachine.plugins import PluginBase

SETTLE = 0.03

# ---------------------------------------------------------------- names ----
def collect(cfg):
    acts, guards, svcs, delays, evts = set(), set(), set(), set(), set()
    def A(v):
        if v is None: return
        if isinstance(v, str): acts.add(v)
        elif isinstance(v, dict):
            t = v.get("type")
            if isinstance(t, str): acts.add(t)
        elif isinstance(v, list):
            for i in v: A(i)
    def G(v):
        if isinstance(v, str): guards.add(v)
        elif isinstance(v, dict):
            for k in ("and","or","not"):
                if k in v:
                    x=v[k]
                    if isinstance(x,list):
                        for i in x: G(i)
                    else: G(x)
    def T(v):
        if isinstance(v, list):
            for i in v:
                T(i)
            return
        if isinstance(v, dict):
            A(v.get("actions")); G(v.get("guard") or v.get("cond"))
        elif isinstance(v, str): pass
    def walk(node):
        A(node.get("entry")); A(node.get("exit"))
        for k, v in (node.get("on") or {}).items():
            evts.add(k); T(v)
        T(node.get("always"))
        for d, v in (node.get("after") or {}).items():
            if not str(d).lstrip("-").isdigit(): delays.add(str(d))
            T(v)
        inv = node.get("invoke")
        if inv:
            for i in (inv if isinstance(inv, list) else [inv]):
                if isinstance(i.get("src"), str): svcs.add(i["src"])
                T(i.get("onDone")); T(i.get("onError"))
        for s in (node.get("states") or {}).values(): walk(s)
    walk(cfg)
    return sorted(acts), sorted(guards), sorted(svcs), sorted(delays), sorted(evts)


class Stub:
    """Records every action call; guards/services driven by policy dicts."""
    def __init__(self, cfg, guard_vals=None, svc=None, act_impl=None,
                 raising=(), guard_raise=()):
        self.acts, self.guards, self.svcs, self.delays, self.events = collect(cfg)
        self.trace: List[str] = []
        self.guard_calls: List[str] = []
        self.svc_calls: List[str] = []
        self.guard_vals = dict(guard_vals or {})
        self.svc = dict(svc or {})            # name -> value | Exception | callable
        self.act_impl = dict(act_impl or {})  # name -> fn(interp, ctx, evt, ad)
        self.raising = set(raising)
        self.guard_raise = set(guard_raise)

    def logic(self):
        def mk_a(n):
            def f(interp, ctx, evt, ad):
                self.trace.append(n)
                if n in self.raising:
                    raise RuntimeError("boom:" + n)
                impl = self.act_impl.get(n)
                if impl: return impl(interp, ctx, evt, ad)
            f.__name__ = n
            return f
        def mk_g(n):
            def g(ctx, evt):
                self.guard_calls.append(n)
                if n in self.guard_raise: raise RuntimeError("guard:" + n)
                v = self.guard_vals.get(n, False)
                return v(ctx, evt) if callable(v) else bool(v)
            g.__name__ = n
            return g
        def mk_s(n):
            async def s(interp, ctx, evt):
                self.svc_calls.append(n)
                v = self.svc.get(n, {"ok": True})
                if callable(v): v = v(interp, ctx, evt)
                if isinstance(v, BaseException): raise v
                return v
            s.__name__ = n
            return s
        return MachineLogic(
            actions={n: mk_a(n) for n in self.acts
                     if not is_builtin(n) and not n.startswith("spawn_")},
            guards={n: mk_g(n) for n in self.guards},
            services={n: mk_s(n) for n in self.svcs},
            delays={n: 1000 for n in self.delays},
            strict=True,
        )


class TraceP(PluginBase):
    def __init__(self):
        self.actions: List[str] = []
        self.transitions: List[str] = []
        self.dropped: List[Tuple[str, str]] = []
        self.unhandled: List[Tuple[str, str]] = []
        self.plugin_errors: List[str] = []
    def on_action_execute(self, interp, action): self.actions.append(action.type)
    def on_transition(self, interp, frm, to, t):
        self.transitions.append(f"{t.event}->{sorted(n.id for n in to if not n.states)}")
    def on_event_dropped(self, interp, event, reason):
        self.dropped.append((getattr(event, "type", "?"), reason))
    def on_unhandled_event(self, interp, event, ids, disposition):
        self.unhandled.append((event.type, disposition))


def build(cfg, stub):
    return create_machine(copy.deepcopy(cfg), logic=stub.logic(),
                          strict_targets=cfg.get("strictTargets", True))


def ids(interp):
    return sorted(interp.current_state_ids)


async def quiesce(interp, n=6):
    for _ in range(n):
        await asyncio.sleep(SETTLE)


@dataclass
class Outcome:
    states: List[str] = field(default_factory=list)
    context: Dict[str, Any] = field(default_factory=dict)
    actions: List[str] = field(default_factory=list)
    transitions: List[str] = field(default_factory=list)
    status: str = ""
    deferred: int = 0
    err: Optional[str] = None
    def key(self):
        return (tuple(self.states),
                json.dumps(self.context, sort_keys=True, default=str),
                tuple(self.actions), self.status)


def snap(interp) -> Outcome:
    return Outcome(ids(interp),
                   json.loads(json.dumps(interp.context, default=str)),
                   [], [], interp.status, interp.deferred_count)
