# -*- coding: utf-8 -*-
"""B13 follow-up: what exactly does onUnhandled='error' + strict=True do?"""
import asyncio, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import g3_harness as H
from g3_harness import scenario, run_all, ids, quiesce
from xstate_statemachine import Interpreter, MachineLogic, create_machine
from xstate_statemachine.clock import SimulatedClock
from g3_b13 import mk, to_live


@scenario("B13-unh-2", "onUnhandled=error", "unhandled event KILLS the interpreter; caller sees a clean receipt")
async def kills():
    it, st, tp = mk()
    await it.start()
    await to_live(it)
    before = it.is_running
    rc = await it.send("CONNECT", wait=True)
    await quiesce(it)
    after = it.is_running
    # can the machine still do its job?
    followup = {}
    try:
        rc2 = await it.send("PONG", us=1, wait=True)
        await quiesce(it)
        followup["PONG"] = "receipt=%r stamped=%s" % (rc2, it.context["last_pong_us"])
    except Exception as e:
        followup["PONG"] = "%s: %s" % (type(e).__name__, str(e)[:120])
    return {"ok": after is True,
            "running_before": before, "running_after_unhandled": after,
            "receipt": repr(rc), "last_error": repr(it.last_error),
            "status": getattr(it, "status", "?"),
            "followup_after_death": followup,
            "hook": tp.unhandled}


@scenario("B13-strict-2", "strict=true", "config strict=True does NOT gate event names; only Interpreter(strict=) does")
async def strictness():
    cfg = H.load("B13")
    st = H.Stub(cfg, guard_vals={"is_private": False, "connection_budget_exhausted": False})
    m = H.build(cfg, st)
    out = {"machine_strict_attr": m.strict}
    # A: default interpreter (config strict only)
    it = Interpreter(m, clock=SimulatedClock())
    await it.start()
    try:
        await it.send("TOTALLY_MADE_UP", wait=True)
        out["A_config_strict_only"] = "ACCEPTED running=%s" % it.is_running
    except Exception as e:
        out["A_config_strict_only"] = "%s: %s" % (type(e).__name__, str(e)[:120])
    await it.stop()
    # B: explicit Interpreter(strict=True)
    st2 = H.Stub(cfg, guard_vals={"is_private": False, "connection_budget_exhausted": False})
    it2 = Interpreter(H.build(cfg, st2), clock=SimulatedClock(), strict=True)
    await it2.start()
    try:
        await it2.send("TOTALLY_MADE_UP", wait=True)
        out["B_interpreter_strict"] = "ACCEPTED running=%s" % it2.is_running
    except Exception as e:
        out["B_interpreter_strict"] = "%s: %s" % (type(e).__name__, str(e)[:120])
    await it2.stop()
    return {"ok": "Error" in out["A_config_strict_only"], "detail": out}


@scenario("B13-unh-3", "onUnhandled=error", "does the same event survive as a legal no-op on onUnhandled=defer?")
async def compare_defer():
    cfg = H.load("B13")
    cfg["onUnhandled"] = "defer"
    st = H.Stub(cfg, guard_vals={"is_private": False, "connection_budget_exhausted": False})
    tp = H.TraceP()
    it = Interpreter(H.build(cfg, st), clock=SimulatedClock())
    it.use(tp)
    await it.start()
    await it.send("CONNECT", wait=True)
    await quiesce(it)
    live = ids(it)
    rc = await it.send("CONNECT", wait=True)
    await quiesce(it)
    r = {"ok": it.is_running,
         "live": live, "running": it.is_running, "receipt": repr(rc),
         "deferred": it.deferred_count, "hook": tp.unhandled}
    await it.stop()
    return r


if __name__ == "__main__":
    sys.exit(run_all("b13_unh"))
