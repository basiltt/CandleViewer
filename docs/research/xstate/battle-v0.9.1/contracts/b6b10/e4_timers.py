# -*- coding: utf-8 -*-
"""q4 @ c78ce99 -- #212 / #213 timer obligations for the B6-B10 family.

FACT FIRST: our catalogued B6, B7, B8, B9 and B10 carry **no `after`
block and no `raise(delay=)`** (grep: 0 hits for "after" and "delay" in
all five .machine.json).  So there is nothing in the shipped contracts
these two findings can touch, and the obligations are discharged on
contract-SHAPED overlays that spell the two timers the OMS will add:

  T1  `after` on B6.armed -- slice pacing ("if no SLICE_DUE arrives in
      N ms, fire the next slice ourselves").
  T2  raise(delay=1) heartbeat between B10.armed and a polling state --
      retry/keepalive pacing.  Under #212 (which SUPERSEDES #206) this is
      a periodic process, NOT a runaway: it must run for many more beats
      than `maxIterations` without a RunawayChainError.
  T3  #213: an armed, UNFIRED delayed self-send must appear in the v3
      snapshot's `scheduled_sends` and be re-armed by start().

STANDALONE: stdlib + xstate_statemachine only.
Run: e4_timers.py [async|def]
"""
from __future__ import annotations
import asyncio, json, pathlib, sys

from xstate_statemachine import (
    Interpreter, MachineLogic, OverflowPolicy, SyncInterpreter, create_machine,
)
from xstate_statemachine.actions import is_builtin
from xstate_statemachine.clock import SimulatedClock

HERE = pathlib.Path(__file__).parent
STYLE = sys.argv[1] if len(sys.argv) > 1 else "async"
RES: dict = {}


def rec(k, ok, note=""):
    k = "[%s]%s" % (STYLE, k)
    RES[k] = {"pass": bool(ok), "note": note}
    print(("PASS " if ok else "FAIL ") + k
          + ("  | " + json.dumps(note, default=str) if note else ""),
          flush=True)
    return bool(ok)


def cfg(b):
    return json.loads((HERE / (b + ".machine.json")).read_text("utf-8"))


# ---------------------------------------------------------- name scanning --
def collect(c):
    acts, guards, svcs, delays = set(), set(), set(), set()

    def A(v):
        if isinstance(v, str):
            acts.add(v)
        elif isinstance(v, dict) and isinstance(v.get("type"), str):
            acts.add(v["type"])
        elif isinstance(v, list):
            for x in v:
                A(x)

    def T(v):
        if isinstance(v, list):
            for x in v:
                T(x)
        elif isinstance(v, dict):
            A(v.get("actions"))
            g = v.get("guard") or v.get("cond")
            if isinstance(g, str):
                guards.add(g)

    def walk(n):
        A(n.get("entry")); A(n.get("exit"))
        for _k, v in (n.get("on") or {}).items():
            T(v)
        T(n.get("always"))
        for d, v in (n.get("after") or {}).items():
            if not str(d).lstrip("-").isdigit():
                delays.add(str(d))
            T(v)
        inv = n.get("invoke")
        if inv:
            for x in (inv if isinstance(inv, list) else [inv]):
                if isinstance(x.get("src"), str):
                    svcs.add(x["src"])
                T(x.get("onDone")); T(x.get("onError"))
        for s in (n.get("states") or {}).values():
            walk(s)

    walk(c)
    return sorted(acts), sorted(guards), sorted(svcs), sorted(delays)


class Stub:
    def __init__(self, c, guard_vals=None, style=None):
        self.acts, self.guards, self.svcs, self.delays = collect(c)
        self.trace, self.svc_calls = [], []
        self.guard_vals = dict(guard_vals or {})
        self.style = style or STYLE

    def logic(self):
        def mk_a(n):
            def f(i, ctx, e, ad):
                self.trace.append(n)
            f.__name__ = n
            return f

        def mk_g(n):
            def g(ctx, e):
                return bool(self.guard_vals.get(n, False))
            g.__name__ = n
            return g

        def mk_s_a(n):
            async def s(i, ctx, e):
                self.svc_calls.append(n)
                return {"ok": True}
            s.__name__ = n
            return s

        def mk_s_d(n):
            def s(i, ctx, e):
                self.svc_calls.append(n)
                return {"ok": True}
            s.__name__ = n
            return s

        mk_s = mk_s_d if self.style == "def" else mk_s_a
        return MachineLogic(
            # ⚠️ never shadow a BUILT-IN action name (`raise`, `cancel`,
            # `log`, ...) -- doing so silently disarms the overlay's timer.
            actions={n: mk_a(n) for n in self.acts
                     if not is_builtin(n) and not n.startswith("spawn_")},
            guards={n: mk_g(n) for n in self.guards},
            services={n: mk_s(n) for n in self.svcs},
            delays={n: 50 for n in self.delays},
            strict=True,
        )


G6 = {"slice_qty_below_min_roll_forward": False, "price_limit_breached": False,
      "failures_exhausted": False, "preflight_invalid": False,
      "abort_on_price_limit": False, "final_market_sweep_and_remaining": False,
      "on_disconnect_is_freeze": True}
G10 = {"in_storm_window": False, "all_channels_ok": True,
       "delivery_attempts_left": True, "severity_requires_ack": False}


def ids(i):
    return sorted(i.current_state_ids)


async def q(i, n=6):
    for _ in range(n):
        await asyncio.sleep(0.03)


async def new_async(c, st, maxq=256):
    m = create_machine(json.loads(json.dumps(c)), logic=st.logic(),
                       strict_config=True)
    i = Interpreter(m, clock=SimulatedClock(), max_queue_size=maxq,
                    overflow_policy=OverflowPolicy.RAISE)
    await i.start()
    await q(i, 3)
    return i


# ============================== T1: `after` on B6.armed (slice pacing) =====
def b6_after_overlay(ms=40):
    """OVERLAY: B6.armed gets an `after` that self-fires the next slice.

    This is NOT in the shipped contract (B6 has no `after`); it is the
    shape the OMS slice pacer will add, exercised here so #212/#213 have
    a contract-shaped target."""
    c = cfg("B6")
    c["states"]["armed"].setdefault("after", {})[ms] = {
        "target": "#twap.submitting_slice"}
    return c


async def t1_after():
    c = b6_after_overlay(40)
    st = Stub(c, guard_vals=dict(G6))
    i = await new_async(c, st)
    rec("T1/B6+after: starts in armed", ids(i) == ["twap.armed"], ids(i))
    for _ in range(6):                        # 6 pacing ticks
        await i.clock.increment(45)
        await q(i, 3)
    n = st.svc_calls.count("submit_child")
    rec("T1/B6+after: the pacer fires repeatedly (>=4 slices), no runaway",
        n >= 4 and i.last_error is None,
        {"submit_child": n, "state": ids(i),
         "last_error": repr(i.last_error)[:120]})
    await i.stop()


# ==================== T2: #212 -- a raise(delay=1) heartbeat is a timer ====
def b10_heartbeat_overlay(period=1):
    """OVERLAY on B10: a 1 ms raise(delay=) ping-pong between two polling
    states, entered from `armed` on POLL_START.  #212: this is a periodic
    process, not a chain -- it must NOT trip maxIterations."""
    c = cfg("B10")
    arm = {"type": "raise", "params": {"event": "BEAT", "delay": period}}
    c["maxIterations"] = 8
    c["context"]["beats"] = 0
    c["states"]["armed"].setdefault("on", {})["POLL_START"] = {
        "target": "#alert.poll_up"}
    c["states"]["poll_up"] = {"entry": [arm, "beat"],
                              "on": {"BEAT": {"target": "#alert.poll_down"}}}
    c["states"]["poll_down"] = {"entry": [arm, "beat"],
                                "on": {"BEAT": {"target": "#alert.poll_up"}}}
    return c


async def t2_heartbeat():
    c = b10_heartbeat_overlay(1)
    st = Stub(c, guard_vals=dict(G10))

    def beat(i, ctx, e, ad):
        ctx["beats"] = ctx.get("beats", 0) + 1
    logic = st.logic()
    logic.actions["beat"] = beat
    m = create_machine(json.loads(json.dumps(c)), logic=logic,
                       strict_config=True)
    i = Interpreter(m, clock=None, max_queue_size=512,
                    overflow_policy=OverflowPolicy.RAISE)
    await i.start()
    await q(i, 3)
    await i.send("POLL_START")
    await asyncio.sleep(1.2)                  # real clock: ~hundreds of beats
    beats = i.context.get("beats", 0)
    err = i.last_error
    state = ids(i)
    await i.stop()
    rec("T2/#212 1ms raise(delay=) ping-pong runs >> maxIterations(8) beats",
        beats >= 30 and err is None,
        {"beats": beats, "maxIterations": 8, "last_error": repr(err)[:140],
         "state": state})


# ====================== T3: #213 -- armed, unfired delayed send in v3 ======
def b6_delayed_selfsend_overlay(delay_ms=5000):
    """OVERLAY: entering B6.armed arms a long delayed self-send whose
    firing is the ONLY exit to a parked state.  Before #213 this record
    existed nowhere the snapshot could see."""
    c = cfg("B6")
    c["states"]["armed"].setdefault("entry", [])
    e = c["states"]["armed"]["entry"]
    if not isinstance(e, list):
        e = [e]
    e = list(e) + [{"type": "raise", "params": {"event": "PACE",
                                                "delay": delay_ms,
                                                "id": "pacer"}}]
    c["states"]["armed"]["entry"] = e
    c["states"]["armed"].setdefault("on", {})["PACE"] = {
        "target": "#twap.submitting_slice"}
    return c


async def t3_scheduled_sends():
    c = b6_delayed_selfsend_overlay(5000)
    st = Stub(c, guard_vals=dict(G6))
    clock = SimulatedClock()
    m = create_machine(json.loads(json.dumps(c)), logic=st.logic(),
                       strict_config=True)
    i = Interpreter(m, clock=clock, max_queue_size=256,
                    overflow_policy=OverflowPolicy.RAISE)
    await i.start()
    await q(i, 4)
    await clock.increment(1000)               # 1 s of the 5 s elapsed
    await q(i, 3)
    blob = i.get_persisted_snapshot()
    ss = blob.get("scheduled_sends")
    rec("T3/#213 v3 snapshot has scheduled_sends", isinstance(ss, list), str(ss))
    rec("T3/#213 the armed PACE send is recorded with its REMAINING delay",
        bool(ss) and ss[0].get("type") == "PACE"
        and 3500 <= float(ss[0].get("remaining_ms", 0)) <= 4600,
        json.dumps(ss, default=str)[:300])
    rec("T3/snapshot layout version == 3", blob.get("version") == 3,
        str(blob.get("version")))
    before = ids(i)
    await i.stop()

    # restore into a fresh machine and prove the timer still fires
    st2 = Stub(c, guard_vals=dict(G6))
    m2 = create_machine(json.loads(json.dumps(c)), logic=st2.logic(),
                        strict_config=True)
    clock2 = SimulatedClock()
    j = Interpreter.from_snapshot(json.dumps(blob), m2, clock=clock2,
                                  minimum_version=3)
    await j.start()
    await q(j, 3)
    rec("T3/restore lands in the same configuration", ids(j) == before,
        {"before": before, "after": ids(j)})
    await clock2.increment(1000)              # not yet due
    await q(j, 3)
    early = ids(j)
    early_svc = list(st2.svc_calls)
    await clock2.increment(3600)              # now past the remainder
    await q(j, 4)
    # PACE -> submitting_slice -> (onDone) -> armed, so the CONFIGURATION
    # returns to `armed`; the observable proof the timer fired is that the
    # slice service ran after the restore, and only after the remainder.
    rec("T3/#213 the restored delayed send FIRES (slice submitted only "
        "after the remaining delay elapsed)",
        early == before and early_svc == [] and st2.svc_calls == [
            "submit_child"],
        {"early": early, "early_svc": early_svc, "late": ids(j),
         "svc": st2.svc_calls})
    await j.stop()


def t3_sync():
    """Same obligation on the sync engine."""
    c = b6_delayed_selfsend_overlay(5000)
    st = Stub(c, guard_vals=dict(G6), style="def")
    clock = SimulatedClock()
    m = create_machine(json.loads(json.dumps(c)), logic=st.logic(),
                       strict_config=True)
    i = SyncInterpreter(m, clock=clock)
    i.start()
    clock.increment(1000)
    blob = i.get_persisted_snapshot()
    ss = blob.get("scheduled_sends")
    before = ids(i)
    i.stop()
    rec("T3/[SYNC] scheduled_sends carries the armed send",
        bool(ss) and ss[0].get("type") == "PACE",
        json.dumps(ss, default=str)[:260])
    st2 = Stub(c, guard_vals=dict(G6), style="def")
    m2 = create_machine(json.loads(json.dumps(c)), logic=st2.logic(),
                        strict_config=True)
    clock2 = SimulatedClock()
    j = SyncInterpreter.from_snapshot(json.dumps(blob), m2, clock=clock2,
                                      minimum_version=3)
    j.start()
    same = ids(j) == before
    early_svc = list(st2.svc_calls)
    clock2.increment(4600)
    rec("T3/[SYNC] restored delayed send fires",
        same and early_svc == [] and st2.svc_calls == ["submit_child"],
        {"before": before, "early_svc": early_svc, "after": ids(j),
         "svc": st2.svc_calls})
    try:
        j.stop()
    except Exception:
        pass


async def main():
    await t1_after()
    await t2_heartbeat()
    await t3_scheduled_sends()
    (HERE / ("e4_timers.%s.json" % STYLE)).write_text(
        json.dumps(RES, indent=1, default=str), encoding="utf-8")
    bad = [k for k, v in RES.items() if not v["pass"]]
    print("\n--- %d checks, %d FAIL: %s" % (len(RES), len(bad), bad), flush=True)
    return 1 if bad else 0


def _all():
    rc = asyncio.run(main())
    # 🧭 the sync engine's SimulatedClock must be driven OUTSIDE a running
    # event loop, so this runs after asyncio.run() returns.
    t3_sync()
    (HERE / ("e4_timers.%s.json" % STYLE)).write_text(
        json.dumps(RES, indent=1, default=str), encoding="utf-8")
    bad = [k for k, v in RES.items() if not v["pass"]]
    print("--- FINAL %d checks, %d FAIL: %s" % (len(RES), len(bad), bad),
          flush=True)
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(_all())
