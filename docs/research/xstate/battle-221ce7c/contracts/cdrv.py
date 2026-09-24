# -*- coding: utf-8 -*-
"""Driver helpers layered on charness: run / snapshot-every-macrostep / compare."""
from __future__ import annotations
import asyncio, json, copy
from typing import Any, Dict, List, Optional, Tuple

from xstate_statemachine import Interpreter, SyncInterpreter, OverflowPolicy
from xstate_statemachine.clock import SimulatedClock
from charness import Stub, TraceP, build, ids, SETTLE


def cfg_of(b: str) -> Dict[str, Any]:
    import pathlib
    p = pathlib.Path(__file__).parent
    fixed = p / f"{b}.machine.json"
    src = fixed if fixed.exists() else p / f"{b}.catalogue.json"
    return json.loads(src.read_text(encoding="utf-8"))


async def mk(b, stub_kw=None, **ikw):
    cfg = cfg_of(b)
    st = Stub(cfg, **(stub_kw or {}))
    m = build(cfg, st)
    clock = SimulatedClock()
    interp = Interpreter(m, clock=clock, **ikw)
    tp = TraceP(); interp.use(tp)
    await interp.start(); await asyncio.sleep(SETTLE)
    return interp, st, tp, clock, m


async def step(interp, clock, s):
    """One macrostep. s = 'EVT' | ('EVT', payload) | ('TICK', ms)."""
    if isinstance(s, tuple) and s[0] == "TICK":
        await clock.increment(s[1]); await asyncio.sleep(SETTLE); return None
    if isinstance(s, tuple):
        r = await interp.send(s[0], **(s[1] or {}), wait=True)
    else:
        r = await interp.send(s, wait=True)
    await asyncio.sleep(SETTLE)
    return r


def obs(interp, st, tp):
    return {
        "ids": ids(interp),
        "ctx": json.loads(json.dumps(interp.context, default=str)),
        "acts": list(st.trace),
        "status": interp.status,
        "deferred": interp.deferred_count,
        "transitions": list(tp.transitions),
    }


async def run_plain(b, seq, stub_kw=None, **ikw):
    interp, st, tp, clock, m = await mk(b, stub_kw, **ikw)
    receipts = []
    for s in seq:
        receipts.append(await step(interp, clock, s))
    o = obs(interp, st, tp)
    o["receipts"] = [None if r is None else
                     {"changed": r.changed, "error": type(r.error).__name__ if r.error else None,
                      "deferred": getattr(r, "deferred", None)} for r in receipts]
    await interp.stop()
    return o


async def run_snapshotted(b, seq, stub_kw=None, **ikw):
    """Snapshot at quiescence between EVERY macrostep, restore, resume.

    The same `Stub` object is carried across restores so the action trace
    accumulates exactly as in the plain run.
    """
    cfg = cfg_of(b)
    st = Stub(cfg, **(stub_kw or {}))
    m = build(cfg, st)
    clock = SimulatedClock()
    interp = Interpreter(m, clock=clock, **ikw)
    tp = TraceP(); interp.use(tp)
    await interp.start(); await asyncio.sleep(SETTLE)
    midstep: List[str] = []
    transitions: List[str] = list(tp.transitions)
    receipts = []
    for s in seq:
        try:
            blob = json.dumps(interp.get_persisted_snapshot())
        except Exception as e:                                  # noqa: BLE001
            midstep.append(f"before {s!r}: {type(e).__name__}: {str(e)[:160]}")
            raise
        await interp.stop()
        clock = SimulatedClock()
        interp = Interpreter.from_snapshot(
            blob, m, clock=clock, restart_services=True, restart_timers=True)
        tp = TraceP(); interp.use(tp)
        await interp.start(); await asyncio.sleep(SETTLE)
        receipts.append(await step(interp, clock, s))
        transitions.extend(tp.transitions)
    o = obs(interp, st, tp)
    o["transitions"] = transitions
    o["midstep_errors"] = midstep
    o["receipts"] = [None if r is None else
                     {"changed": r.changed, "error": type(r.error).__name__ if r.error else None,
                      "deferred": getattr(r, "deferred", None)} for r in receipts]
    await interp.stop()
    return o


def compare(a: Dict[str, Any], b: Dict[str, Any], fields=("ids", "ctx", "status")):
    diffs = {}
    for f in fields:
        if a.get(f) != b.get(f):
            diffs[f] = {"plain": a.get(f), "snap": b.get(f)}
    return diffs


def run_sync_parity(b, seq, stub_kw=None):
    """Sync-engine parity (informational)."""
    cfg = cfg_of(b)
    st = Stub(cfg, **(stub_kw or {}))
    m = build(cfg, st)
    clock = SimulatedClock()
    interp = SyncInterpreter(m, clock=clock)
    tp = TraceP(); interp.use(tp)
    try:
        interp.start()
        for s in seq:
            if isinstance(s, tuple) and s[0] == "TICK":
                clock.increment_sync(s[1]) if hasattr(clock, "increment_sync") else None
                interp.tick()
                continue
            if isinstance(s, tuple):
                interp.send(s[0], **(s[1] or {}))
            else:
                interp.send(s)
        out = {"ids": ids(interp),
               "ctx": json.loads(json.dumps(interp.context, default=str)),
               "acts": list(st.trace), "status": interp.status}
    except Exception as e:                                       # noqa: BLE001
        out = {"error": f"{type(e).__name__}: {str(e)[:200]}"}
    finally:
        try: interp.stop()
        except Exception: pass
    return out
