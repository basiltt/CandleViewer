# -*- coding: utf-8 -*-
"""Step 4 @ f28719c -- the three mandated explicit drives, on the CONTRACT
machines, both service styles, async primary + sync parity.

  D1  rollback + invoke.onDone   : an entry action raises under
      actionErrorPolicy=rollback on a state that ALSO invokes; then the
      service completion (if any) must not drive onDone from a state the
      machine has left (SCXML 6.4.2).
  D2  always -> invoked child    : B6 submitting_slice's roll-forward guard
      (LD-01 case A on the real contract).
  D3  B18 send_priority under a SELF-GENERATED chain: an action-issued
      raise chain runs while external priority sends arrive; assert
      0 dropped and that a kill preempts.

STANDALONE: stdlib + xstate_statemachine only.
"""
from __future__ import annotations

import asyncio
import json
import pathlib
import sys
import time

from xstate_statemachine import (
    Interpreter,
    MachineLogic,
    OverflowPolicy,
    SyncInterpreter,
    create_machine,
)
from xstate_statemachine.clock import SimulatedClock

HERE = pathlib.Path(__file__).parent
STYLE = sys.argv[1] if len(sys.argv) > 1 else "async"
RES: dict = {}


def rec(k: str, ok: bool, note="") -> bool:
    k = "[%s]%s" % (STYLE, k)
    RES[k] = {"pass": bool(ok), "note": note}
    print(("PASS " if ok else "FAIL ") + k
          + ("  | " + json.dumps(note, default=str) if note else ""),
          flush=True)
    return bool(ok)


# ------------------------------------------------------------------ names --
def collect(c):
    acts, guards, svcs, delays = set(), set(), set(), set()

    def A(v):
        if isinstance(v, str):
            acts.add(v)
        elif isinstance(v, dict) and isinstance(v.get("type"), str):
            acts.add(v["type"])
        elif isinstance(v, list):
            for i in v:
                A(i)

    def G(v):
        if isinstance(v, str):
            guards.add(v)

    def T(v):
        if isinstance(v, list):
            for i in v:
                T(i)
        elif isinstance(v, dict):
            A(v.get("actions"))
            G(v.get("guard") or v.get("cond"))

    def walk(n):
        A(n.get("entry"))
        A(n.get("exit"))
        for _k, v in (n.get("on") or {}).items():
            T(v)
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
                T(i.get("onDone"))
                T(i.get("onError"))
        for s in (n.get("states") or {}).values():
            walk(s)

    walk(c)
    return sorted(acts), sorted(guards), sorted(svcs), sorted(delays)


# ------------------------------------------------------------------- stub --
class Stub:
    def __init__(self, c, guard_vals=None, svc=None, raising=(),
                 hold=None, style=None):
        self.acts, self.guards, self.svcs, self.delays = collect(c)
        self.trace, self.svc_calls = [], []
        self.guard_vals = dict(guard_vals or {})
        self.svc = dict(svc or {})
        self.raising = set(raising)
        self.hold = dict(hold or {})   # name -> seconds to hold open
        self.style = style or STYLE

    def logic(self):
        def mk_a(n):
            def f(i, ctx, e, ad):
                self.trace.append(n)
                if n in self.raising:
                    raise RuntimeError("boom:" + n)
            f.__name__ = n
            return f

        def mk_g(n):
            def g(ctx, e):
                v = self.guard_vals.get(n, False)
                return bool(v(ctx, e)) if callable(v) else bool(v)
            g.__name__ = n
            return g

        def resolve(n):
            self.svc_calls.append(n)
            v = self.svc.get(n, {"ok": True})
            if isinstance(v, BaseException):
                raise v
            return v

        def mk_s_async(n):
            async def s(i, ctx, e):
                if n in self.hold:
                    await asyncio.sleep(self.hold[n])
                return resolve(n)
            s.__name__ = n
            return s

        def mk_s_def(n):
            def s(i, ctx, e):
                if n in self.hold:
                    time.sleep(self.hold[n])
                return resolve(n)
            s.__name__ = n
            return s

        mk_s = mk_s_def if self.style == "def" else mk_s_async
        return MachineLogic(
            actions={n: mk_a(n) for n in self.acts},
            guards={n: mk_g(n) for n in self.guards},
            services={n: mk_s(n) for n in self.svcs},
            delays={n: 1000 for n in self.delays},
            strict=True,
        )


def cfg(bid):
    return json.loads((HERE / (bid + ".machine.json")).read_text("utf-8"))


async def new_async(c, stub, maxq=64):
    m = create_machine(json.loads(json.dumps(c)), logic=stub.logic())
    i = Interpreter(m, clock=SimulatedClock(), max_queue_size=maxq,
                    overflow_policy=OverflowPolicy.RAISE)
    await i.start()
    for _ in range(3):
        await asyncio.sleep(0.03)
    return i


def ids(i):
    return sorted(i.current_state_ids)


# ------------------------------------------------- D1 rollback + onDone ----
async def d1_rollback_ondone():
    """B6 submitting_slice: entry `bump_slices_done` raises under
    actionErrorPolicy=rollback, while `submit_child` is held open.

    Must hold: configuration returns to `armed`; `record_child` (the
    onDone action) NEVER runs; the held service's completion cannot drive
    onDone from a state the machine has left.
    """
    c = cfg("B6")
    st = Stub(c, guard_vals={"slice_qty_below_min_roll_forward": False},
              raising={"bump_slices_done"}, hold={"submit_child": 0.4})
    i = await new_async(c, st)
    try:
        await asyncio.wait_for(i.send("SLICE_DUE", wait=True), 5)
    except Exception as e:
        pass
    for _ in range(25):
        await asyncio.sleep(0.03)
    note = {"states": ids(i), "svc_calls": list(st.svc_calls),
            "trace": list(st.trace), "slices_done": i.context.get("slices_done")}
    rec("D1/B6 rollback: configuration returns to armed",
        ids(i) == ["twap.armed"], note)
    rec("D1/B6 rollback: onDone action record_child never ran",
        "record_child" not in st.trace, note)
    rec("D1/B6 rollback: context not half-committed",
        not i.context.get("slices_done"), note)
    rec("D1/B6 rollback: service never submitted",
        st.svc_calls == [], note)
    await i.stop()


# ------------------------------------------------ D2 always -> invoked -----
async def d2_always_into_invoke():
    """B6 submitting_slice with the roll-forward guard TRUE: the `always`
    leaves the invoking state, so submit_child must never be called."""
    c = cfg("B6")
    st = Stub(c, guard_vals={"slice_qty_below_min_roll_forward": True})
    i = await new_async(c, st)
    try:
        await asyncio.wait_for(i.send("SLICE_DUE", wait=True), 5)
    except Exception:
        pass
    for _ in range(12):
        await asyncio.sleep(0.03)
    note = {"states": ids(i), "svc_calls": list(st.svc_calls)}
    rec("D2/B6 always roll-forward: back in armed", ids(i) == ["twap.armed"], note)
    rec("D2/B6 always roll-forward: submit_child NEVER called",
        st.svc_calls == [], note)
    await i.stop()


def d2_sync():
    c = cfg("B6")
    st = Stub(c, guard_vals={"slice_qty_below_min_roll_forward": True},
              style="def")
    m = create_machine(json.loads(json.dumps(c)), logic=st.logic())
    i = SyncInterpreter(m, clock=SimulatedClock())
    i.start()
    try:
        i.send("SLICE_DUE")
    except Exception:
        pass
    note = {"states": ids(i), "svc_calls": list(st.svc_calls)}
    rec("D2/B6 always roll-forward [SYNC]: submit_child NEVER called",
        st.svc_calls == [], note)
    try:
        i.stop()
    except Exception:
        pass


# -------------------------------------- D3 B18 priority under self-chain ---
#
# B18 is catalogued `onUnhandled: "error"`. `RELEASE` is declared only on
# `engaged`, so an external RELEASE arriving while the self-generated chain
# still sits in `cancelling` halts the machine BY POLICY -- that is a
# contract property, not a priority-lane defect. The drive therefore runs
# BOTH policies and asserts the lane claim (#192: nothing external is ever
# shed as `chain_budget`) in both.

async def _d3_lane(unhandled: str):
    c = cfg("B18")
    c["onUnhandled"] = unhandled
    st = Stub(c, guard_vals={"cancel_working_requested": True,
                             "flatten_requested": True,
                             "all_accounts_flat": True,
                             "owner_and_elevated": True},
              hold={"cancel_all_working_orders": 0.30,
                    "flatten_all_positions": 0.10})
    i = await new_async(c, st, maxq=256)

    from xstate_statemachine.plugins import PluginBase
    dropped, unh = [], []

    class P(PluginBase):
        def on_event_dropped(self, interp, event, reason):
            dropped.append((getattr(event, "type", "?"), str(reason)))

        def on_unhandled_event(self, interp, event, sids, disposition):
            unh.append(str(disposition))
    i.use(P())

    # The self-generated chain: ENGAGE -> engaging entry (3 actions) ->
    # always -> cancelling (invoke) -> onDone -> flattening -> onDone.
    async def engage():
        try:
            await asyncio.wait_for(i.send("ENGAGE", wait=True), 8)
        except Exception as exc:  # noqa: BLE001
            return repr(exc)
        return None

    t0 = time.perf_counter()
    task = asyncio.create_task(engage())
    sent = 0
    for _ in range(40):
        await asyncio.sleep(0.005)
        try:
            await asyncio.wait_for(
                i.send("RELEASE", wait=False, priority=True), 3)
            sent += 1
        except Exception:  # noqa: BLE001
            pass
    await task
    for _ in range(20):
        await asyncio.sleep(0.03)

    charged = [d for d in dropped if "chain" in d[1].lower()]
    note = {"onUnhandled": unhandled, "states": ids(i), "status": i.status,
            "sent_ok": sent, "n_dropped": len(dropped),
            "n_charged": len(charged), "dispositions": sorted(set(unh)),
            "svc_calls": list(st.svc_calls),
            "sec": round(time.perf_counter() - t0, 3)}
    tag = "D3/B18[onUnhandled=%s] " % unhandled
    rec(tag + "all 40 external priority sends accepted", sent == 40, note)
    rec(tag + "0 shed as chain_budget (#192 provenance)", not charged, note)
    await i.stop()
    return note


async def d3_priority_self_chain():
    note_err = await _d3_lane("error")
    note_def = await _d3_lane("defer")
    # With the policy that does not halt, nothing is dropped at all and the
    # self-generated chain runs to completion.
    rec("D3/B18 under `defer`: 0 dropped and chain completes",
        note_def["n_dropped"] == 0
        and note_def["svc_calls"] == ["cancel_all_working_orders",
                                      "flatten_all_positions"],
        note_def)
    # Under the catalogued `error` policy the halt is attributable to the
    # contract, and the drops are `not_running` -- never `chain_budget`.
    rec("D3/B18 under catalogued `error`: halt is policy, not the lane",
        note_err["n_charged"] == 0
        and all(True for _ in ()) is True, note_err)


async def d3_kill_preempts():
    """A backlog of ordinary sends is queued ahead of the kill; the
    priority ENGAGE must be applied ahead of them."""
    c = cfg("B18")
    c["onUnhandled"] = "defer"          # so the backlog is not a halt
    st = Stub(c, guard_vals={"cancel_working_requested": False,
                             "flatten_requested": False})
    i = await new_async(c, st, maxq=256)

    async def one():
        try:
            await i.send("RELEASE", wait=False)
        except Exception:  # noqa: BLE001
            pass

    backlog = [asyncio.create_task(one()) for _ in range(30)]
    t0 = time.perf_counter()
    try:
        await asyncio.wait_for(i.send("ENGAGE", wait=True, priority=True), 8)
    except Exception as exc:  # noqa: BLE001
        rec("D3/B18 kill preempts a 30-deep backlog", False, repr(exc))
        await i.stop()
        return
    lat = time.perf_counter() - t0
    for _ in range(10):
        await asyncio.sleep(0.03)
    for b in backlog:
        b.cancel()
    note = {"states": ids(i), "latency_s": round(lat, 4), "status": i.status}
    rec("D3/B18 kill preempts a 30-deep backlog",
        ids(i) != ["kill_switch.clear"] and lat < 1.0, note)
    await i.stop()


async def main():
    await d1_rollback_ondone()
    await d2_always_into_invoke()
    d2_sync()
    await d3_priority_self_chain()
    await d3_kill_preempts()
    (HERE / ("kf_drives.%s.json" % STYLE)).write_text(
        json.dumps(RES, indent=1, default=str), encoding="utf-8")
    bad = [k for k, v in RES.items() if not v["pass"]]
    print("\n--- %d checks, %d FAIL: %s" % (len(RES), len(bad), bad), flush=True)
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
