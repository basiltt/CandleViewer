# -*- coding: utf-8 -*-
"""r8 driver: run / snapshot-every-macrostep / compare / sync parity."""
from __future__ import annotations
import asyncio, json
from typing import Any, Dict, List

from xstate_statemachine import Interpreter, SyncInterpreter, OverflowPolicy
from xstate_statemachine.clock import SimulatedClock
from h import Stub, TraceP, build, ids, cfg_of, SETTLE

CTL = dict(max_queue_size=64, overflow_policy=OverflowPolicy.RAISE)


async def mk(b, kind="async", stub_kw=None, **ikw):
    cfg = cfg_of(b)
    st = Stub(cfg, kind=kind, **(stub_kw or {}))
    m = build(cfg, st)
    clock = SimulatedClock()
    interp = Interpreter(m, clock=clock, **ikw)
    tp = TraceP(); interp.use(tp)
    await interp.start(); await asyncio.sleep(SETTLE)
    return interp, st, tp, clock, m


async def step(interp, clock, s):
    if isinstance(s, tuple) and s[0] == "TICK":
        await clock.increment(s[1]); await asyncio.sleep(SETTLE); return None
    r = await interp.send(s, wait=True)
    await asyncio.sleep(SETTLE)
    return r


def rec(r):
    if r is None:
        return None
    return {"changed": r.changed,
            "error": type(r.error).__name__ if r.error else None,
            "deferred": getattr(r, "deferred", None),
            "denied": getattr(r, "denied", "ABSENT")}


def obs(interp, st, tp):
    return {"ids": ids(interp),
            "ctx": json.loads(json.dumps(interp.context, default=str)),
            "acts": list(st.trace),
            "svc": list(st.svc_calls),
            "status": interp.status,
            "deferred": interp.deferred_count,
            "transitions": list(tp.transitions),
            "unhandled": tp.unhandled,
            "dropped": tp.dropped,
            "last_error": type(getattr(interp, "last_error", None)).__name__}


async def run_plain(b, seq, kind="async", stub_kw=None, **ikw):
    ikw = dict(CTL, **ikw)
    interp, st, tp, clock, m = await mk(b, kind, stub_kw, **ikw)
    receipts, errs = [], []
    for s in seq:
        try:
            receipts.append(await asyncio.wait_for(step(interp, clock, s), 10))
        except Exception as e:                                   # noqa: BLE001
            receipts.append(None)
            errs.append(f"{s}: {type(e).__name__}: {str(e)[:160]}")
            break
    o = obs(interp, st, tp)
    o["receipts"] = [rec(r) for r in receipts]
    o["raised"] = errs
    try:
        await interp.stop()
    except Exception:
        pass
    return o


async def run_snapshotted(b, seq, kind="async", stub_kw=None, **ikw):
    ikw = dict(CTL, **ikw)
    cfg = cfg_of(b)
    st = Stub(cfg, kind=kind, **(stub_kw or {}))
    m = build(cfg, st)
    clock = SimulatedClock()
    interp = Interpreter(m, clock=clock, **ikw)
    tp = TraceP(); interp.use(tp)
    await interp.start(); await asyncio.sleep(SETTLE)
    midstep: List[str] = []
    transitions = list(tp.transitions)
    receipts, errs = [], []
    for s in seq:
        try:
            blob = json.dumps(interp.get_persisted_snapshot())
        except Exception as e:                                   # noqa: BLE001
            midstep.append(f"before {s!r}: {type(e).__name__}: {str(e)[:160]}")
            break
        await interp.stop()
        clock = SimulatedClock()
        interp = Interpreter.from_snapshot(
            blob, m, clock=clock, restart_services=True, restart_timers=True)
        tp = TraceP(); interp.use(tp)
        await interp.start(); await asyncio.sleep(SETTLE)
        try:
            receipts.append(await asyncio.wait_for(step(interp, clock, s), 10))
        except Exception as e:                                   # noqa: BLE001
            receipts.append(None)
            errs.append(f"{s}: {type(e).__name__}: {str(e)[:160]}")
            break
        transitions.extend(tp.transitions)
    o = obs(interp, st, tp)
    o["transitions"] = transitions
    o["midstep_errors"] = midstep
    o["receipts"] = [rec(r) for r in receipts]
    o["raised"] = errs
    try:
        await interp.stop()
    except Exception:
        pass
    return o


def compare(a, b, fields=("ids", "ctx", "status")):
    return {f: {"plain": a.get(f), "snap": b.get(f)}
            for f in fields if a.get(f) != b.get(f)}


def run_sync_parity(b, seq, kind="async", stub_kw=None):
    cfg = cfg_of(b)
    st = Stub(cfg, kind=kind, **(stub_kw or {}))
    m = build(cfg, st)
    interp = SyncInterpreter(m, clock=SimulatedClock())
    tp = TraceP(); interp.use(tp)
    try:
        interp.start()
        for s in seq:
            if isinstance(s, tuple):
                continue
            interp.send(s)
        out = {"ids": ids(interp),
               "ctx": json.loads(json.dumps(interp.context, default=str)),
               "acts": list(st.trace), "svc": list(st.svc_calls),
               "status": interp.status,
               "last_error": type(getattr(interp, "last_error", None)).__name__}
    except Exception as e:                                       # noqa: BLE001
        out = {"error": f"{type(e).__name__}: {str(e)[:200]}",
               "acts": list(st.trace), "svc": list(st.svc_calls)}
    finally:
        try:
            interp.stop()
        except Exception:
            pass
    return out


async def both(fn, *a, **kw):
    """Run an async coroutine factory for both service kinds."""
    return {k: await fn(*a, kind=k, **kw) for k in ("async", "sync")}
