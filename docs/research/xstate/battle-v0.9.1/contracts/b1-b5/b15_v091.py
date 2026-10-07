# -*- coding: utf-8 -*-
"""B1-B5 contract machines end-to-end on xstate-statemachine 0.9.1.

STANDALONE: stdlib + xstate_statemachine only; helpers inline; cwd <home>.
Usage:  python -W error::RuntimeWarning b15_v091.py async|def
Mandatory config: strictConfig, rollback, defer, guard raise, strictTargets,
strict, bounded RAISE inbox, SimulatedClock, plugins= on every restore
asserting on_interpreter_start fires with restored_from_snapshot=True.
"""
from __future__ import annotations
import asyncio, copy, json, os, pathlib, sys

from xstate_statemachine import (Interpreter, SyncInterpreter, MachineLogic,
                                 OverflowPolicy, create_machine, __version__)
from xstate_statemachine.actions import is_builtin
from xstate_statemachine.clock import SimulatedClock
from xstate_statemachine.plugins import PluginBase

HERE = pathlib.Path(__file__).resolve().parent.parent   # contracts/ (JSON)
STYLE = sys.argv[1] if len(sys.argv) > 1 else "async"
os.chdir("<home>")
RES = {}


def rec(k, ok, note=""):
    k = "[%s]%s" % (STYLE, k)
    RES[k] = {"pass": bool(ok), "note": str(note)[:500]}
    print(("PASS " if ok else "FAIL ") + k + ("  | " + str(note)[:300] if note else ""), flush=True)


def cfg(b):
    c = json.loads((HERE / (b + ".machine.json")).read_text(encoding="utf-8"))
    c["strictConfig"] = True
    return c


def names(c):
    acts, guards, svcs = set(), set(), set()
    def A(v):
        for x in (v if isinstance(v, list) else [v] if v else []):
            if isinstance(x, str): acts.add(x)
            elif isinstance(x, dict) and isinstance(x.get("type"), str): acts.add(x["type"])
    def G(v):
        if isinstance(v, str): guards.add(v)
        elif isinstance(v, dict):
            for k in ("and", "or", "not"):
                if k in v:
                    for i in (v[k] if isinstance(v[k], list) else [v[k]]): G(i)
    def T(v):
        for x in (v if isinstance(v, list) else [v] if v else []):
            if isinstance(x, dict): A(x.get("actions")); G(x.get("guard"))
    def W(n):
        A(n.get("entry")); A(n.get("exit")); T(n.get("always")); T(n.get("onDone"))
        for v in (n.get("on") or {}).values(): T(v)
        for v in (n.get("after") or {}).values(): T(v)
        inv = n.get("invoke")
        for i in (inv if isinstance(inv, list) else [inv] if inv else []):
            svcs.add(i["src"]); T(i.get("onDone")); T(i.get("onError"))
        for s in (n.get("states") or {}).values(): W(s)
    W(c)
    return acts, guards, svcs


class Stub:
    def __init__(self, c, gv, raising=(), svc_err=()):
        self.a, self.g, self.s = names(c)
        self.gv, self.raising, self.svc_err = dict(gv), set(raising), set(svc_err)
        self.trace, self.svc_calls = [], []

    def logic(self):
        def mk_a(n):
            if STYLE == "async":
                async def f(i, ctx, e, ad):
                    self.trace.append(n)
                    if n in self.raising: raise RuntimeError("boom:" + n)
            else:
                def f(i, ctx, e, ad):
                    self.trace.append(n)
                    if n in self.raising: raise RuntimeError("boom:" + n)
            f.__name__ = n; return f
        def mk_g(n):
            def g(ctx, e):
                v = self.gv.get(n, False)
                return bool(v(ctx, e)) if callable(v) else bool(v)
            g.__name__ = n; return g
        def mk_s(n):
            def body():
                self.svc_calls.append(n)
                if n in self.svc_err: raise RuntimeError("svc:" + n)
                return {"ok": True}
            if STYLE == "async":
                async def s(i, ctx, e): return body()
            else:
                def s(i, ctx, e): return body()
            s.__name__ = n; return s
        return MachineLogic(
            actions={n: mk_a(n) for n in self.a if not is_builtin(n)},
            guards={n: mk_g(n) for n in self.g},
            services={n: mk_s(n) for n in self.s}, strict=True)


class Hooks(PluginBase):
    def __init__(self):
        self.starts, self.done, self.errs, self.stranded = [], [], [], []
        self.tr, self.rdrop, self.dropped = [], [], []
    def on_interpreter_start(self, i): self.starts.append(i.restored_from_snapshot)
    def on_transition(self, i, f, t, tr): self.tr.append(tr.event)
    def on_action_error(self, i, a, e): self.errs.append("act:%s:%r" % (a.type, e))
    def on_guard_error(self, i, *a): self.errs.append("guard:%r" % (a[-1],))
    def on_service_error(self, i, *a): self.errs.append("svc:%r" % (a[-1],))
    def on_error(self, i, e): self.errs.append("err:%r" % (e,))
    def on_done(self, i, o): self.done.append(o)
    def on_invocation_stranded(self, i, *a): self.stranded.append(a)
    def on_receipt_dropped(self, i, t): self.rdrop.append(t)
    def on_event_dropped(self, i, e, r): self.dropped.append((getattr(e, "type", "?"), r))


def build(c, st):
    return create_machine(copy.deepcopy(c), logic=st.logic(), strict_config=True,
                          strict_targets=True)


def ids(i): return sorted(s for s in i.current_state_ids)


async def settle(n=8):
    for _ in range(n): await asyncio.sleep(0.01)


async def boot(c, st, maxq=64):
    i = Interpreter(build(c, st), clock=SimulatedClock(), max_queue_size=maxq,
                    overflow_policy=OverflowPolicy.RAISE)
    p = Hooks(); i.use(p)
    await i.start(); await settle()
    return i, p


async def restore(blob, c, st):
    p = Hooks()
    j = Interpreter.from_snapshot(blob, build(c, st), clock=SimulatedClock(),
                                  minimum_version=3, plugins=[p])
    await j.start(); await settle()
    return j, p


# ------------------------------------------------------------- scenarios --
SPEC = {
    # machine: (guards, happy script, expected leaf substrings at end)
    "B1": ({"passes_all_gates": True, "ret_code_ok": True, "exec_new_and_partial":
            lambda c, e: e.payload.get("partial", False),
            "exec_new_and_closes": lambda c, e: not e.payload.get("partial", False)},
           [("VALIDATE", {}), ("SEND", {}), ("FIRST_FILL", {}),
            ("EXEC", {"partial": True}), ("EXEC", {})],
           ["lifecycle.filled", "protection.sl_present"]),
    "B2": ({"all_non_skipped_open": lambda c, e: True},
           [("CONFIRM", {}), ("LEG_OPEN", {}), ("CLOSE_GROUP", {}), ("ALL_LEGS_FLAT", {})],
           ["trade_group.closed"]),
    "B3": ({"passes_preflight": True, "fully_filled": True},
           [("ORDER_OPEN", {}), ("EXEC", {}), ("EXEC", {}), ("CLOSE", {}), ("FLAT", {})],
           ["leg.closed"]),
    "B4": ({"other_leg_terminal": True},
           [("LEG_A_FILL", {}), ("CHILDREN_TERMINAL", {})], ["oco.completed"]),
    "B5": ({"remaining_is_zero": True},
           [("CHILD_FILLED", {}), ("CHILDREN_TERMINAL", {})], ["iceberg.completed"]),
}


async def happy(b):
    gv, script, want = SPEC[b]
    c = cfg(b); i, p = await boot(c, Stub(c, gv))
    bad = []
    for n, (ev, pl) in enumerate(script):
        r = await asyncio.wait_for(i.send(ev, wait=True, **pl), 5)
        if r.error is not None: bad.append("%s:%r" % (ev, r.error))
        await settle()
        # snapshot -> restore at every quiescence, plugin must see a resume start
        blob = i.get_persisted_snapshot()
        blob = blob if isinstance(blob, str) else json.dumps(blob)
        j, pj = await restore(blob, c, Stub(c, gv))
        if pj.starts != [True]: bad.append("t%d:starts=%r" % (n, pj.starts))
        if ids(j) != ids(i) or j.context != i.context: bad.append("t%d:drift" % n)
        if j.chain_trips != 0: bad.append("t%d:restored trips" % n)
        await j.stop()
    leaves = ids(i)
    rec(b + ".happy_reaches_end", all(any(s.endswith(w) for s in leaves) for w in want), leaves)
    rec(b + ".happy_restore_every_step", not bad, bad[:4])
    rec(b + ".happy_boot_start_hook_false", p.starts == [False], p.starts)
    rec(b + ".happy_chain_trips_0", i.chain_trips == 0, i.chain_trips)
    rec(b + ".happy_dropped_receipts_0", i.dropped_receipts == 0 and not p.rdrop,
        (i.dropped_receipts, p.rdrop))
    rec(b + ".happy_no_errors_stranded", not p.errs and not p.stranded, (p.errs[:3], p.stranded[:3]))
    await i.stop()


async def shutdown_recipe(b):
    """drain_pending() -> persist -> stop() -> restore -> start -> replay:
    every drained event delivered exactly once; a wait=True receipt on a
    drained event resolves with InterpreterStoppedError (no hang)."""
    gv, script, want = SPEC[b]
    c = cfg(b); st = Stub(c, gv); i, p = await boot(c, st)
    # Advance to a state where the next two script events are live.
    first = script[0]
    await asyncio.wait_for(i.send(first[0], wait=True, **first[1]), 5); await settle()
    rest = script[1:]
    # Park: enqueue without yielding to the loop, mix lanes.
    i.send(rest[0][0], wait=False, **rest[0][1])
    nq = 2
    if len(rest) > 1:
        i.send_priority(rest[1][0], wait=False, **rest[1][1]); nq = 3
    # send() enqueues synchronously and returns a Future; no yield happens
    # between these sends and drain_pending(), so nothing is processed.
    waiter = i.send(first[0], wait=True)  # a stale extra, receipt pending
    view = [e.type for e in i.pending_events]
    drained = await i.drain_pending()
    dtypes = [e.type for e in drained]
    try:
        r = await asyncio.wait_for(waiter, 3)
        wok = type(r.error).__name__ == "InterpreterStoppedError"
        wnote = repr(r.error)
    except Exception as e:
        wok, wnote = False, "waiter:%r" % (e,)
    blob = i.get_persisted_snapshot()
    blob = blob if isinstance(blob, str) else json.dumps(blob)
    persisted_pending = len(json.loads(blob).get("pending_events") or [])
    before = ids(i)
    await asyncio.wait_for(i.stop(), 5)
    rec(b + ".drain_covers_both_lanes", dtypes == view and len(dtypes) == nq, (view, dtypes))
    rec(b + ".drain_wait_true_receipt_fails_not_hangs", wok, wnote)
    rec(b + ".persist_after_drain_has_no_pending", persisted_pending == 0, persisted_pending)
    rec(b + ".stop_did_not_process_drained", before == ids(i), (before, ids(i)))
    # restore and replay the journal (the drained list) exactly once
    st2 = Stub(c, gv); j, pj = await restore(blob, c, st2)
    rec(b + ".restore_start_hook_true", pj.starts == [True], pj.starts)
    seen0 = len(pj.tr)
    for ev in drained:
        if ev.type == first[0]:
            continue  # the stale extra; journal policy drops failed-receipt dupes
        await asyncio.wait_for(j.send(ev, wait=True), 5); await settle()
    replayed = pj.tr[seen0:]
    exp = [t for t in dtypes if t != first[0]]
    from collections import Counter
    got = Counter(t for t in replayed if t in exp)
    rec(b + ".replay_each_drained_once", got == Counter(exp),
        (exp, replayed))
    # finish the remaining script and reach the end state
    for ev, pl in script[3:] if len(rest) > 1 else []:
        await asyncio.wait_for(j.send(ev, wait=True, **pl), 5); await settle()
    leaves = ids(j)
    rec(b + ".replay_reaches_end", all(any(s.endswith(w) for s in leaves) for w in want), leaves)
    rec(b + ".replay_chain_trips_0_dropped_0",
        j.chain_trips == 0 and j.dropped_receipts == 0 and i.dropped_receipts == 0,
        (j.chain_trips, j.dropped_receipts, i.dropped_receipts))
    await j.stop()


async def lanes():
    from xstate_statemachine import QueueOverflowError
    # --- rollback: raising transition action -> config restored, onDone still
    c = cfg("B1"); gv = SPEC["B1"][0]
    i, p = await boot(c, Stub(c, gv, raising={"stamp_validated"}))
    r = await asyncio.wait_for(i.send("VALIDATE", wait=True), 5); await settle()
    rec("B1.rollback_restores_draft", any(s.endswith("lifecycle.draft") for s in ids(i))
        and i.status == "running", (ids(i), i.status, repr(r.error)[:80]))
    rec("B1.rollback_reported", any(e.startswith("act:stamp_validated") for e in p.errs), p.errs[:2])
    await i.stop()
    # --- invoke onDone (place_order) + always -> invoked child (B5 pending->submitting_slice)
    c = cfg("B5"); st = Stub(c, {}); i, p = await boot(c, st)
    rec("B5.always_to_invoked_child_runs", "submit_child" in st.svc_calls
        and any(s.endswith("iceberg.working") for s in ids(i)), (st.svc_calls, ids(i)))
    await i.stop()
    c = cfg("B3"); st = Stub(c, {"passes_preflight": True}, svc_err={"x"})
    i, p = await boot(c, st)
    rec("B3.always_lands_submitting", any(s.endswith("leg.submitting") for s in ids(i)), ids(i))
    await i.stop()
    # --- onError path: service raises -> declared onError target, not stranded
    c = cfg("B1"); st = Stub(c, SPEC["B1"][0], svc_err={"place_order"}); i, p = await boot(c, st)
    for ev in ("VALIDATE", "SEND"):
        await asyncio.wait_for(i.send(ev, wait=True), 5); await settle()
    rec("B1.invoke_onError_to_unknown", any(s.endswith("lifecycle.unknown") for s in ids(i))
        and not p.stranded, (ids(i), p.stranded))
    await i.stop()
    # --- guard raise: reported, machine alive
    c = cfg("B1"); gv = dict(SPEC["B1"][0])
    def boom(ctx, e): raise RuntimeError("guard boom")
    gv["passes_all_gates"] = boom
    i, p = await boot(c, Stub(c, gv))
    r = await asyncio.wait_for(i.send("VALIDATE", wait=True), 5); await settle()
    rec("B1.guard_raise_reported_not_fatal", (r.error is not None or p.errs) and i.status == "running",
        (repr(r.error)[:80], p.errs[:2], i.status))
    await i.stop()
    # --- defer: out-of-order event parked, replayed when live
    c = cfg("B1"); i, p = await boot(c, Stub(c, SPEC["B1"][0]))
    r = await asyncio.wait_for(i.send("SEND", wait=True), 5); await settle()
    d1 = i.deferred_count
    await asyncio.wait_for(i.send("VALIDATE", wait=True), 5); await settle()
    rec("B1.defer_parks_then_replays", r.deferred and d1 == 1 and i.deferred_count == 0
        and any(s.endswith("lifecycle.submitted") for s in ids(i)), (r.deferred, d1, ids(i)))
    await i.stop()
    # --- bounded RAISE inbox on the order path
    c = cfg("B1"); i, p = await boot(c, Stub(c, SPEC["B1"][0]), maxq=4)
    over = None
    try:
        for _ in range(12): i.send("SL_LOST", wait=False)
    except QueueOverflowError as e: over = e
    await settle()
    rec("B1.bounded_raise_inbox", over is not None and i.status == "running",
        (repr(over)[:100], i.status, i.chain_trips))
    await i.stop()
    # --- send_priority overtakes a backlog (B18 shape on the order path)
    c = cfg("B1"); i, p = await boot(c, Stub(c, SPEC["B1"][0]), maxq=64)
    for _ in range(10): i.send("SL_LOST", wait=False)
    rp = await asyncio.wait_for(i.send_priority("VALIDATE"), 5)
    pos = p.tr.index("VALIDATE") if "VALIDATE" in p.tr else -1
    rec("B1.send_priority_overtakes_backlog", rp.error is None and 0 <= pos < 3
        and any(s.endswith("lifecycle.validated") for s in rp.state_ids), (pos, sorted(rp.state_ids)))
    await settle(); await i.stop()
    # --- sync engine parity (#245 kwargs) on each happy path
    for b in SPEC:
        gv, script, want = SPEC[b]; c = cfg(b)
        try:
            SyncInterpreter(build(c, Stub(c, gv)), max_queue_size=8); bad = "accepted"
        except ValueError: bad = None
        except Exception as e: bad = repr(e)
        if STYLE == "async":
            rec(b + ".sync_bounded_kw_is_ValueError", bad is None, bad); continue
        s = SyncInterpreter(build(c, Stub(c, gv)), clock=SimulatedClock(),
                            max_queue_size=None, overflow_policy=None)
        s.start()
        for ev, pl in script: s.send(ev, **pl)
        rec(b + ".sync_parity_end", all(any(x.endswith(w) for x in s.current_state_ids)
            for w in want), sorted(s.current_state_ids))
        rec(b + ".sync_bounded_kw_is_ValueError", bad is None, bad)
        s.stop()


async def main():
    rec("version", __version__ == "0.9.1", __version__)
    for b in SPEC:
        await happy(b)
        await shutdown_recipe(b)
    await lanes()
    out = pathlib.Path(__file__).with_name("res_b15_v091.%s.json" % STYLE)
    out.write_text(json.dumps(RES, indent=1), encoding="utf-8")
    bad = [k for k, v in RES.items() if not v["pass"]]
    print("--- %d checks, %d FAIL %s" % (len(RES), len(bad), bad))


asyncio.run(asyncio.wait_for(main(), 110))
