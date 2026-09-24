# -*- coding: utf-8 -*-
"""Contract harness for B1-B5 on commit f28719c.

Async primary + sync parity, SimulatedClock, bounded RAISE inbox,
CvErrorHooks-equivalent plugin stub, snapshot/restore at every quiescence.
Library source is never imported-for-patching; read-only use only.
"""
from __future__ import annotations
import asyncio, copy, json, os, pathlib, time
from typing import Any, Dict, List, Optional, Tuple

from xstate_statemachine import (
    Interpreter, SyncInterpreter, MachineLogic, OverflowPolicy, create_machine,
)
from xstate_statemachine.actions import is_builtin
from xstate_statemachine.clock import SimulatedClock
from xstate_statemachine.plugins import PluginBase

HERE = pathlib.Path(__file__).parent
SETTLE = 0.05
RESULTS: Dict[str, Any] = {}
#: "async" (default, the recommended style) or "def". Every driver is run
#: twice: CV_SVC_STYLE=async then CV_SVC_STYLE=def.
STYLE = os.environ.get("CV_SVC_STYLE", "async")


def cfg(bid: str) -> Dict[str, Any]:
    return json.loads((HERE / (bid + ".machine.json")).read_text(encoding="utf-8"))


def rec(key: str, ok: bool, note: str = "") -> bool:
    key = "[%s]" % STYLE + key
    RESULTS[key] = {"pass": bool(ok), "note": note}
    print(("PASS " if ok else "FAIL ") + key + ("  | " + note if note else ""),
          flush=True)
    return bool(ok)


def dump(path: str) -> None:
    path = path.replace(".json", "." + STYLE + ".json")
    (HERE / path).write_text(json.dumps(RESULTS, indent=1, default=str),
                             encoding="utf-8")
    bad = [k for k, v in RESULTS.items() if not v["pass"]]
    print("\n--- %d checks, %d FAIL: %s" % (len(RESULTS), len(bad), bad), flush=True)


# ------------------------------------------------------------------ names --
def collect(c):
    acts, guards, svcs, delays, evts = set(), set(), set(), set(), set()

    def A(v):
        if v is None:
            return
        if isinstance(v, str):
            acts.add(v)
        elif isinstance(v, dict):
            if isinstance(v.get("type"), str):
                acts.add(v["type"])
        elif isinstance(v, list):
            for i in v:
                A(i)

    def G(v):
        if isinstance(v, str):
            guards.add(v)
        elif isinstance(v, dict):
            for k in ("and", "or", "not"):
                if k in v:
                    x = v[k]
                    for i in (x if isinstance(x, list) else [x]):
                        G(i)

    def T(v):
        if isinstance(v, list):
            for i in v:
                T(i)
        elif isinstance(v, dict):
            A(v.get("actions"))
            G(v.get("guard") or v.get("cond"))

    def walk(n):
        A(n.get("entry")); A(n.get("exit"))
        for k, v in (n.get("on") or {}).items():
            evts.add(k); T(v)
        T(n.get("always"))
        for d, v in (n.get("after") or {}).items():
            if not str(d).lstrip("-").isdigit():
                delays.add(str(d))
            T(v)
        inv = n.get("invoke")
        if inv:
            for i in (inv if isinstance(inv, list) else [inv]):
                if isinstance(i.get("src"), str):
                    svcs.add(i["src"])
                T(i.get("onDone")); T(i.get("onError"))
        for s in (n.get("states") or {}).values():
            walk(s)

    walk(c)
    return sorted(acts), sorted(guards), sorted(svcs), sorted(delays), sorted(evts)


# ------------------------------------------------------------------- stub --
class Stub:
    """Deterministic stub logic. Sync services are plain defs for the sync
    engine; async services are coroutines for the async engine."""

    def __init__(self, c, guard_vals=None, svc=None, act_impl=None,
                 raising=(), guard_raise=(), sync=False,
                 svc_style=None):
        self.acts, self.guards, self.svcs, self.delays, self.events = collect(c)
        self.trace: List[str] = []
        self.guard_calls: List[str] = []
        self.svc_calls: List[str] = []
        self.guard_vals = dict(guard_vals or {})
        self.svc = dict(svc or {})
        self.act_impl = dict(act_impl or {})
        self.raising = set(raising)
        self.guard_raise = set(guard_raise)
        self.sync = sync
        #: "async" -> every service is an `async def`; "def" -> plain def.
        #: Independent of which engine runs it (the async engine accepts
        #: both).  Defaults to "def" on the sync engine, "async" otherwise.
        self.svc_style = svc_style or ("def" if sync else STYLE)

    def logic(self):
        def mk_a(n):
            def f(interp, ctx, evt, ad):
                self.trace.append(n)
                if n in self.raising:
                    raise RuntimeError("boom:" + n)
                impl = self.act_impl.get(n)
                if impl:
                    return impl(interp, ctx, evt, ad)
            f.__name__ = n
            return f

        def mk_g(n):
            def g(ctx, evt):
                self.guard_calls.append(n)
                if n in self.guard_raise:
                    raise RuntimeError("guard:" + n)
                v = self.guard_vals.get(n, False)
                return bool(v(ctx, evt)) if callable(v) else bool(v)
            g.__name__ = n
            return g

        def resolve(n, interp, ctx, evt):
            self.svc_calls.append(n)
            v = self.svc.get(n, {"ok": True})
            if callable(v):
                v = v(interp, ctx, evt)
            if isinstance(v, BaseException):
                raise v
            return v

        def mk_s_async(n):
            async def s(interp, ctx, evt):
                v = resolve(n, interp, ctx, evt)
                if asyncio.iscoroutine(v):
                    v = await v
                return v
            s.__name__ = n
            return s

        def mk_s_sync(n):
            def s(interp, ctx, evt):
                return resolve(n, interp, ctx, evt)
            s.__name__ = n
            return s

        mk_s = mk_s_sync if self.svc_style == "def" else mk_s_async
        return MachineLogic(
            actions={n: mk_a(n) for n in self.acts
                     if not is_builtin(n) and not n.startswith("spawn_")},
            guards={n: mk_g(n) for n in self.guards},
            services={n: mk_s(n) for n in self.svcs},
            delays={n: 1000 for n in self.delays},
            strict=True,
        )


def build(c, stub, **kw):
    return create_machine(copy.deepcopy(c), logic=stub.logic(),
                          strict_targets=c.get("strictTargets", True), **kw)


# ----------------------------------------------------- CvErrorHooks stub ---
class CvHooks(PluginBase):
    """Stand-in for the project's CvErrorHooks: records every observability
    hook the OMS would route to alerting / journals."""

    def __init__(self):
        self.actions: List[str] = []
        self.transitions: List[str] = []
        self.dropped: List[Tuple[str, str]] = []
        self.unhandled: List[Tuple[str, str]] = []
        self.action_errors: List[str] = []
        self.transition_failed: List[str] = []
        self.guard_errors: List[str] = []
        self.service_errors: List[str] = []
        self.snapshot_errors: List[str] = []
        self.errors: List[str] = []
        self.done: List[Any] = []
        self.started = 0
        self.stopped = 0

    def on_interpreter_start(self, i): self.started += 1
    def on_interpreter_stop(self, i): self.stopped += 1
    def on_action_execute(self, i, a): self.actions.append(a.type)
    def on_transition(self, i, frm, to, t):
        self.transitions.append("%s->%s" % (
            t.event, sorted(n.id for n in to if not n.states)))
    def on_action_error(self, i, a, e): self.action_errors.append("%s:%r" % (a.type, e))
    def on_transition_failed(self, i, *a):
        self.transition_failed.append(repr(a[-1]))
    def on_guard_error(self, i, *a): self.guard_errors.append(repr(a[-1]))
    def on_service_error(self, i, *a): self.service_errors.append(repr(a[-1]))
    def on_snapshot_error(self, i, *a): self.snapshot_errors.append(repr(a[-1]))
    def on_event_dropped(self, i, e, reason):
        self.dropped.append((getattr(e, "type", "?"), reason))
    def on_unhandled_event(self, i, e, ids, disposition):
        self.unhandled.append((e.type, disposition))
    def on_error(self, i, e): self.errors.append(repr(e))
    def on_done(self, i, output): self.done.append(output)


def ids(i):
    return sorted(i.current_state_ids)


async def quiesce(i, n=6):
    for _ in range(n):
        await asyncio.sleep(SETTLE)


async def new_async(c, stub, maxq=64, **kw):
    m = build(c, stub)
    i = Interpreter(m, clock=SimulatedClock(), max_queue_size=maxq,
                    overflow_policy=OverflowPolicy.RAISE, **kw)
    p = CvHooks()
    i.use(p)
    await i.start()
    await quiesce(i, 3)
    return m, i, p


def new_sync(c, stub, maxq=64):
    m = build(c, stub)
    # NOTE: SyncInterpreter on 221ce7c accepts no max_queue_size /
    # overflow_policy - the bounded RAISE inbox is async-only (see report).
    i = SyncInterpreter(m, clock=SimulatedClock())
    p = CvHooks()
    i.use(p)
    i.start()
    return m, i, p


async def send(i, name, wait=True, timeout=5.0, **payload):
    """Send with a hard watchdog; a timeout IS the observed result."""
    t0 = time.perf_counter()
    try:
        r = await asyncio.wait_for(
            i.send(name, wait=wait, **payload), timeout)
        return {"ok": True, "receipt": r, "sec": time.perf_counter() - t0}
    except asyncio.TimeoutError:
        return {"ok": False, "timeout": True, "sec": time.perf_counter() - t0}
    except Exception as e:
        return {"ok": False, "exc": repr(e), "sec": time.perf_counter() - t0}


# ------------------------------------------------------- snapshot compare --
def obs(i):
    """Observable tuple used for snapshot/restore equivalence."""
    return {
        "states": ids(i),
        "context": json.loads(json.dumps(i.context, default=str)),
        "status": i.status,
        "deferred": i.deferred_count,
    }


async def snap_roundtrip(i, c, stub_factory, tag, notes):
    """Snapshot at quiescence, restore into a fresh machine, compare.

    Returns (ok, detail). Never raises."""
    try:
        blob = i.get_persisted_snapshot()
        if isinstance(blob, dict):
            blob = json.dumps(blob)
    except Exception as e:
        notes.append("%s:snapshot-refused:%r" % (tag, e))
        return False, "snapshot-refused"
    before = obs(i)
    try:
        st2 = stub_factory()
        m2 = build(c, st2)
        j2 = Interpreter.from_snapshot(blob, m2, clock=SimulatedClock())
        await j2.start()
        await quiesce(j2, 2)
        after = obs(j2)
        await j2.stop()
    except Exception as e:
        notes.append("%s:restore-raised:%r" % (tag, e))
        return False, "restore-raised:%r" % (e,)
    if before["states"] != after["states"] or before["context"] != after["context"]:
        notes.append("%s:drift before=%s after=%s" % (tag, before, after))
        return False, "drift"
    return True, "ok"


async def drive(c, stub, script, snapshots=True, maxq=64, **kw):
    """Run *script* (list of (EVENT, payload) or ('__TICK__', ms)) with a
    snapshot/restore round-trip at every quiescence point.

    Returns a dict of everything observable."""
    m, i, p = await new_async(c, stub, maxq=maxq, **kw)
    notes: List[str] = []
    snap_ok = True
    sends: List[Any] = []
    mk = lambda: Stub(c, guard_vals=stub.guard_vals, svc=stub.svc,
                      act_impl=stub.act_impl, raising=stub.raising,
                      guard_raise=stub.guard_raise,
                      svc_style=stub.svc_style)
    if snapshots:
        ok, d = await snap_roundtrip(i, c, mk, "t0", notes)
        snap_ok = snap_ok and ok
    for n, step in enumerate(script):
        if isinstance(step, tuple) and step[0] == "__TICK__":
            await i.clock.increment(step[1])
            await quiesce(i, 2)
            sends.append({"tick": step[1]})
        else:
            name, payload = (step, {}) if isinstance(step, str) else step
            r = await send(i, name, **payload)
            sends.append({"ev": name, **{k: v for k, v in r.items()
                                         if k != "receipt"}})
            if r.get("timeout"):
                notes.append("TIMEOUT on %s (step %d)" % (name, n))
                break
            await quiesce(i, 2)
        if snapshots:
            ok, d = await snap_roundtrip(i, c, mk, "t%d" % (n + 1,), notes)
            snap_ok = snap_ok and ok
    out = {
        "states": ids(i), "status": i.status,
        "context": json.loads(json.dumps(i.context, default=str)),
        "deferred": i.deferred_count,
        "error": None if i.error is None else repr(i.error),
        "actions": list(p.actions), "transitions": list(p.transitions),
        "dropped": list(p.dropped), "unhandled": list(p.unhandled),
        "action_errors": list(p.action_errors),
        "guard_errors": list(p.guard_errors),
        "service_errors": list(p.service_errors),
        "svc_calls": list(stub.svc_calls),
        "sends": sends, "snapshot_ok": snap_ok, "notes": notes,
    }
    try:
        await asyncio.wait_for(i.stop(), 5)
    except Exception as e:
        out["notes"].append("stop:%r" % (e,))
    return out


def drive_sync(c, stub, script, maxq=64):
    m, i, p = new_sync(c, stub, maxq=maxq)
    sends = []
    for step in script:
        if isinstance(step, tuple) and step[0] == "__TICK__":
            sends.append({"tick": step[1]})
            continue
        name, payload = (step, {}) if isinstance(step, str) else step
        try:
            i.send(name, **payload)
            sends.append({"ev": name, "ok": True})
        except Exception as e:
            sends.append({"ev": name, "ok": False, "exc": repr(e)})
    out = {"states": ids(i), "status": i.status,
           "context": json.loads(json.dumps(i.context, default=str)),
           "deferred": i.deferred_count,
           "error": None if i.error is None else repr(i.error),
           "actions": list(p.actions), "svc_calls": list(stub.svc_calls),
           "sends": sends}
    try:
        i.stop()
    except Exception:
        pass
    return out
