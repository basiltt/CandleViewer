# -*- coding: utf-8 -*-
"""W1: B16-B20 control charts (+ B11 R13-15) end-to-end on xstate-statemachine 0.9.1.

STANDALONE: stdlib + xstate_statemachine only; helpers inline; neutral cwd.
Run:  CV_SVC_STYLE=async|def  python -W error::RuntimeWarning w1_contracts.py
Chart JSON is read from this file's directory (data only).
"""
from __future__ import annotations
import asyncio, copy, json, os, pathlib, sys

HERE = pathlib.Path(__file__).resolve().parent
os.chdir("<home>")
from xstate_statemachine import (Interpreter, SyncInterpreter, MachineLogic,  # noqa
                                 OverflowPolicy, create_machine, InterpreterStoppedError)
from xstate_statemachine.actions import is_builtin  # noqa
from xstate_statemachine.clock import SimulatedClock  # noqa
from xstate_statemachine.plugins import PluginBase  # noqa

STYLE = os.environ.get("CV_SVC_STYLE", "async")
RES = {}


def rec(k, ok, note=""):
    RES["[%s]%s" % (STYLE, k)] = {"pass": bool(ok), "note": str(note)[:300]}
    print(("PASS " if ok else "FAIL ") + "[%s]%s | %s" % (STYLE, k, note), flush=True)


def cfg(b):
    c = json.loads((HERE / (b + ".machine.json")).read_text(encoding="utf-8"))
    c["strictConfig"] = True
    return c


def names(c):
    A, G, S = set(), set(), set()

    def a(v):
        if isinstance(v, str): A.add(v)
        elif isinstance(v, dict) and isinstance(v.get("type"), str): A.add(v["type"])
        elif isinstance(v, list): [a(x) for x in v]

    def t(v):
        if isinstance(v, list): [t(x) for x in v]
        elif isinstance(v, dict):
            a(v.get("actions"))
            if isinstance(v.get("guard"), str): G.add(v["guard"])

    def w(n):
        a(n.get("entry")); a(n.get("exit")); t(n.get("always"))
        for v in (n.get("on") or {}).values(): t(v)
        inv = n.get("invoke")
        for i in (inv if isinstance(inv, list) else [inv] if inv else []):
            S.add(i["src"]); t(i.get("onDone")); t(i.get("onError"))
        for s in (n.get("states") or {}).values(): w(s)
    w(c)
    return A, G, S


class Stub:
    def __init__(self, c, guards=None, acts=None, raising=(), graise=()):
        self.A, self.G, self.S = names(c)
        self.gv, self.ai = dict(guards or {}), dict(acts or {})
        self.raising, self.graise, self.trace = set(raising), set(graise), []

    def logic(self):
        def ma(n):
            def f(i, ctx, e, ad):
                self.trace.append(n)
                if n in self.raising: raise RuntimeError("boom:" + n)
                if n in self.ai: self.ai[n](ctx, e)
            return f

        def mg(n):
            def g(ctx, e):
                if n in self.graise: raise RuntimeError("guard:" + n)
                v = self.gv.get(n, False)
                return bool(v(ctx, e)) if callable(v) else bool(v)
            return g

        def ms(n):
            if STYLE == "def":
                def s(i, ctx, e): return {"ok": n}
            else:
                async def s(i, ctx, e): return {"ok": n}
            return s
        return MachineLogic(
            actions={n: ma(n) for n in self.A if not is_builtin(n)},
            guards={n: mg(n) for n in self.G},
            services={n: ms(n) for n in self.S}, strict=True)


class Hooks(PluginBase):
    def __init__(self):
        self.starts, self.restored, self.recv, self.dropped = 0, [], [], []
        self.guard_err, self.act_err = [], []

    def on_interpreter_start(self, i):
        self.starts += 1; self.restored.append(i.restored_from_snapshot)

    def on_event_received(self, i, e): self.recv.append(getattr(e, "type", e))
    def on_receipt_dropped(self, i, t): self.dropped.append(t)
    def on_guard_error(self, i, *a): self.guard_err.append(repr(a[-1]))
    def on_action_error(self, i, a, e): self.act_err.append(repr(e))


def build(c, st):
    return create_machine(copy.deepcopy(c), logic=st.logic(), strict_targets=True,
                          strict_config=True)


def ids(i):
    s = i.current_state_ids
    s = s() if callable(s) else s
    return sorted(x.split(".", 1)[1] if "." in x else x for x in s)


async def settle(n=8):
    for _ in range(n): await asyncio.sleep(0.02)


async def new(c, st):
    i = Interpreter(build(c, st), clock=SimulatedClock(), max_queue_size=64,
                    overflow_policy=OverflowPolicy.RAISE)
    h = Hooks(); i.use(h); await i.start(); await settle()
    return i, h


async def run(c, st, script):
    i, h = await new(c, st)
    for ev in script:
        await i.send(ev); await settle()
    return i, h


async def shutdown_restore(tag, c, st, primer, pending, prio=None):
    """drain_pending -> persist -> stop -> from_snapshot(plugins=) -> start -> replay."""
    i, h = await run(c, st, primer)
    before = ids(i)
    for ev in pending:
        i.send(ev)                      # eager put, loop not yet run
    rcpt = i.send_priority(prio) if prio else None
    drained = await i.drain_pending()
    types = [e.type for e in drained]
    exp = ([prio] if prio else []) + list(pending)
    rec(tag + ".drain.both_lanes_priority_first", types == exp, "drained=%s" % types)
    if rcpt is not None:
        try:
            r = await asyncio.wait_for(rcpt, 5)   # documented: Receipt.error, not a raise
            ok = isinstance(r.error, InterpreterStoppedError); why = repr(r.error)
        except Exception as e:
            ok, why = False, repr(e)
        rec(tag + ".drain.wait_receipt_fails_stopped", ok, why)
    blob = i.get_snapshot()
    await i.stop()
    h2 = Hooks()
    j = Interpreter.from_snapshot(blob, build(c, st), clock=SimulatedClock(),
                                  plugins=[h2], minimum_version=3)
    await j.start(); await settle()
    rec(tag + ".restore.on_start_restored", h2.starts == 1 and h2.restored == [True],
        "starts=%d restored=%s" % (h2.starts, h2.restored))
    rec(tag + ".restore.state_equal", ids(j) == before, "%s vs %s" % (ids(j), before))
    pre = [t for t in h2.recv if t in set(exp)]      # nothing may leak in before replay
    rcpts = []
    for e in drained:
        rcpts.append(await j.send(e.type, wait=True, **(e.payload or {}))); await settle()
    # once per replayed send: one receipt each; `defer` re-offers are counted
    # separately (on_event_received fires per re-offer -- defer semantics).
    rec(tag + ".restore.drained_delivered_exactly_once",
        not pre and len(rcpts) == len(exp) and all(r is not None for r in rcpts),
        "pre=%s receipts=%d/%d recv=%s" % (pre, len(rcpts), len(exp),
                                          [t for t in h2.recv if t in set(exp)]))
    rec(tag + ".health", j.chain_trips == 0 and j.dropped_receipts == 0 and
        i.dropped_receipts == 0, "chain=%d dropped=%d/%d" % (j.chain_trips,
        i.dropped_receipts, j.dropped_receipts))
    await j.stop()
    return ids(j)


KILL = ["LOGOUT", "IDLE_DEADLINE", "ABSOLUTE_DEADLINE", "REVOKE"]


def fix_b16(c):
    c = copy.deepcopy(c); el = c["states"]["elevation"]
    el["states"]["dead"] = {"type": "final"}
    c.setdefault("on", {})
    for ev in KILL: c["on"][ev] = {"target": ".elevation.dead"}
    return c


def fix_b18(c):
    c = copy.deepcopy(c); c["onUnhandled"] = "defer"
    r = c["states"]["engaged"]["on"]["RELEASE"]
    c["states"]["engaged"]["on"]["RELEASE"] = [r, {"actions": ["audit_release_denied"]}]
    return c


async def b16():
    c = cfg("B16"); g = {"mfa_attempts_exhausted": False}
    i, h = await run(c, Stub(c, g), ["MFA_OK", "REQUEST", "STEP_UP_OK"])
    rec("B16.happy", ids(i) == ["auth.active", "elevation.elevated"], ids(i))
    await i.stop()
    open_ = []
    for ev in KILL:
        i, _ = await run(c, Stub(c, g), ["MFA_OK", "STEP_UP_OK", ev])
        if "elevation.elevated" in ids(i): open_.append(ev)
        await i.stop()
    rec("B16.C04.catalogue_still_open(expected)", len(open_) >= 3, "elevated after %s" % open_)
    f, bad = fix_b16(c), []
    for ev in KILL:
        i, _ = await run(f, Stub(f, g), ["MFA_OK", "STEP_UP_OK", ev])
        if "elevation.elevated" in ids(i): bad.append(ev)
        await i.stop()
    rec("B16.C04.config_fix_closes", not bad, "bad=%s" % bad)
    await shutdown_restore("B16.shutdown", c, Stub(c, g), ["MFA_OK"], ["REQUEST", "STEP_UP_OK"])


async def b17():
    c = cfg("B17"); g = {"all_evidence_present": True,
                         "owner_and_elevated_and_evidence_still_valid": True,
                         "owner_and_elevated": True}
    i, h = await run(c, Stub(c, g), ["EVIDENCE_RECORDED", "ENABLE_REQUESTED"])
    rec("B17.happy_enabled", ids(i) == ["enabled"], ids(i))
    await i.send("EMERGENCY_DISABLE"); await settle()
    rec("B17.emergency_locks", ids(i) == ["locked"], ids(i)); await i.stop()
    g2 = dict(g, owner_and_elevated_and_evidence_still_valid=False)
    i, h = await run(c, Stub(c, g2), ["EVIDENCE_RECORDED", "ENABLE_REQUESTED"])
    rec("B17.inv.denied_stays_eligible", ids(i) == ["eligible"], ids(i)); await i.stop()
    await shutdown_restore("B17.shutdown", c, Stub(c, g), [], ["EVIDENCE_RECORDED", "ENABLE_REQUESTED"],
                           prio="EMERGENCY_DISABLE")


async def b18():
    c = cfg("B18"); g = {"cancel_working_requested": True, "flatten_requested": True,
                         "all_accounts_flat": True, "owner_and_elevated": True}
    i, h = await run(c, Stub(c, g), [])
    r = await i.send_priority("ENGAGE"); await settle()
    rec("B18.always_to_invoked_child_chain", ids(i) == ["engaged"] and i.chain_trips == 0,
        "%s chain=%d receipt=%s" % (ids(i), i.chain_trips, type(r).__name__))
    await i.send("RELEASE"); await settle()
    rec("B18.release_clear", ids(i) == ["clear"], ids(i)); await i.stop()
    gd = dict(g, owner_and_elevated=False)
    i, h = await run(c, Stub(c, gd), ["ENGAGE", "RELEASE"])
    rec("B18.C07b.catalogue_still_bricks(expected)", i.status != "running",
        "status=%s" % i.status)
    await i.stop()
    f = fix_b18(c); st = Stub(f, gd)
    i, h = await run(f, st, ["ENGAGE", "RELEASE"])
    ok1 = i.status == "running" and ids(i) == ["engaged"]
    st.gv["owner_and_elevated"] = True
    await i.send("RELEASE"); await settle()
    rec("B18.C07b.config_fix_closes", ok1 and ids(i) == ["clear"] and i.chain_trips == 0,
        "denied_ok=%s final=%s" % (ok1, ids(i))); await i.stop()
    gi = dict(g, all_accounts_flat=False)
    i, h = await run(c, Stub(c, gi), ["ENGAGE"])
    rec("B18.flatten_incomplete", ids(i) == ["engaged_incomplete"], ids(i)); await i.stop()
    await shutdown_restore("B18.shutdown", f, Stub(f, g), ["ENGAGE"], ["RELEASE"], prio="RELEASE")


async def b19():
    c = cfg("B19"); g = {"divergences_found_and_auto_remediate": True,
                         "unresolved_divergences": False, "failures_exhausted": False}
    i, h = await run(c, Stub(c, g), ["SWEEP_DUE"])
    rec("B19.happy_roundtrip_idle", ids(i) == ["idle"] and i.chain_trips == 0, ids(i))
    await i.stop()
    st = Stub(c, g, raising=["store_exchange_state"])
    i, h = await run(c, st, ["SWEEP_DUE"])
    rec("B19.rollback_onDone_action_raises", i.status == "running" and ids(i) != ["diffing"],
        "status=%s ids=%s act_err=%d" % (i.status, ids(i), len(h.act_err)))
    await i.stop()
    st = Stub(c, g, graise=["divergences_found_and_auto_remediate"])
    i, h = await run(c, st, ["SWEEP_DUE"])
    rec("B19.guard_raise_surfaces", bool(h.guard_err) or i.status != "running",
        "status=%s guard_err=%s ids=%s" % (i.status, h.guard_err[:1], ids(i)))
    await i.stop()
    await shutdown_restore("B19.shutdown", c, Stub(c, g), [], ["STARTUP", "SWEEP_DUE"])


async def b20():
    c = cfg("B20"); g = {"breaches_daily_loss_cap": True, "until_mode_is_time_based": True,
                         "owner_and_elevated_and_override_permitted": False}
    i, h = await run(c, Stub(c, g), ["PNL_UPDATE"])
    rec("B20.breach_locks", ids(i) == ["locked"], ids(i))
    await i.send("OVERRIDE_REQUESTED"); await settle()
    rec("B20.inv.denied_override_stays_locked", ids(i) == ["locked"], ids(i))
    await i.send_priority("EXPIRY_DUE"); await settle()
    rec("B20.expiry_clears", ids(i) == ["clear"] and i.chain_trips == 0, ids(i)); await i.stop()
    await shutdown_restore("B20.shutdown", c, Stub(c, g), ["MANUAL_LOCK"], ["OVERRIDE_REQUESTED"],
                           prio="EXPIRY_DUE")


async def b11():
    c = cfg("B11")
    def mark(ctx, e): ctx["streams_healthy"][e.payload.get("stream", "trades")] = e.type == "STREAM_HEALTHY"
    acts = {"mark_stream_unhealthy": mark, "mark_stream_healthy": mark,
            "add_reason": lambda ctx, e: ctx["reasons"].append("r")}
    naive = {"all_streams_healthy": lambda ctx, e: all(ctx["streams_healthy"].values())}
    seq = ["REASON_ADDED", "STREAM_UNHEALTHY", "STREAM_HEALTHY"]
    i, _ = await run(c, Stub(c, naive, acts), seq)
    rec("B11.R1315.naive_guard_wedged(expected)", ids(i) == ["degraded"], ids(i)); await i.stop()
    aware = {"all_streams_healthy": lambda ctx, e: all(
        v for k, v in ctx["streams_healthy"].items() if k != e.payload.get("stream", "trades"))}
    i, _ = await run(c, Stub(c, aware, acts), seq)
    rec("B11.R1315.event_aware_guard_recovers", ids(i) == ["recording"], ids(i)); await i.stop()


async def main():
    for f in (b16, b17, b18, b19, b20, b11):
        try:
            await asyncio.wait_for(f(), 30)
        except Exception as e:
            rec(f.__name__ + ".CRASH", False, repr(e))
    try:
        SyncInterpreter(build(cfg("B18"), Stub(cfg("B18"))), max_queue_size=64)
        rec("sync.max_queue_size_rejected", False, "accepted")
    except ValueError as e:
        rec("sync.max_queue_size_rejected", True, "ValueError")
    bad = [k for k, v in RES.items() if not v["pass"]]
    (HERE / ("w1_results.%s.json" % STYLE)).write_text(json.dumps(RES, indent=1), encoding="utf-8")
    print("--- %d checks, %d FAIL %s" % (len(RES), len(bad), bad))
    sys.exit(1 if bad else 0)

asyncio.run(main())
