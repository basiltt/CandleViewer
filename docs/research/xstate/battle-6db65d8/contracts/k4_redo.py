# -*- coding: utf-8 -*-
"""Redo of the probes that needed a genuinely gated service, plus CV-C32."""
import asyncio, json, time
from cdrv import run_plain, mk, step, cfg_of
from charness import Stub, build, TraceP, ids, SETTLE
from xstate_statemachine import Interpreter, MachineLogic, OverflowPolicy, create_machine
from xstate_statemachine.clock import SimulatedClock

R = {}
CTL = dict(max_queue_size=64, overflow_policy=OverflowPolicy.RAISE)
GATE = {}

def gated(name):
    async def s(i, c, e):
        ev = GATE.setdefault(name, asyncio.Event())
        await ev.wait()
        return {"ok": True}
    return s


async def mk2(b, svc_gates, stub_kw=None, **ikw):
    """Like cdrv.mk but installs genuinely awaited gated services."""
    cfg = cfg_of(b)
    st = Stub(cfg, **(stub_kw or {}))
    logic = st.logic()
    for name, gate in svc_gates.items():
        logic.services[name] = gated(gate)
    m = create_machine(json.loads(json.dumps(cfg)), logic=logic)
    clock = SimulatedClock()
    it = Interpreter(m, clock=clock, **ikw)
    tp = TraceP(); it.use(tp)
    await it.start(); await asyncio.sleep(SETTLE)
    return it, st, tp, clock, m

def rcpt(r):
    return None if r is None else {
        "changed": r.changed, "denied": getattr(r, "denied", "ABSENT"),
        "deferred": getattr(r, "deferred", None),
        "error": type(r.error).__name__ if r.error else None}

async def main():
    GATE.clear()
    # ---- B18: RELEASE while genuinely cancelling (undeclared there) ----
    GOK = {"cancel_working_requested": True, "flatten_requested": False,
           "all_accounts_flat": True, "owner_and_elevated": True,
           "owner_and_elevated_and_acknowledged_residual": True}
    interp, st, tp, clock, m = await mk2(
        "B18", {"cancel_all_working_orders": "cx"}, {"guard_vals": GOK}, **CTL)
    await step(interp, clock, "ENGAGE")
    mid = ids(interp)
    err = None; r = None
    try:
        r = await asyncio.wait_for(interp.send("RELEASE", wait=True), 3)
    except Exception as e:
        err = f"{type(e).__name__}: {str(e)[:160]}"
    await asyncio.sleep(SETTLE)
    R["b18_release_while_cancelling"] = {
        "ids_mid": mid, "ids_after": ids(interp), "status": interp.status,
        "raised": err, "receipt": rcpt(r), "unhandled": tp.unhandled,
        "dropped": tp.dropped}
    GATE.setdefault("cx", asyncio.Event()).set()
    try: await interp.stop()
    except Exception: pass

    # ---- B19: UNKNOWN_ORDER during an actual sweep ----
    GATE.clear()
    interp, st, tp, clock, m = await mk2(
        "B19", {"fetch_exchange_state": "f"},
        {"guard_vals": {"auto_remediate_allowed": True}}, **CTL)
    await step(interp, clock, "SWEEP_DUE")
    mid = ids(interp)
    r = await asyncio.wait_for(interp.send("UNKNOWN_ORDER", wait=True), 3)
    await asyncio.sleep(SETTLE)
    held = {"ids": ids(interp), "deferred": interp.deferred_count, "receipt": rcpt(r),
            "unhandled": tp.unhandled, "dropped": tp.dropped}
    GATE.setdefault("f", asyncio.Event()).set()
    await asyncio.sleep(SETTLE * 4)
    held["ids_after_release"] = ids(interp)
    held["deferred_after"] = interp.deferred_count
    held["acts_after"] = list(st.trace)
    held["ids_mid"] = mid
    R["b19_unknown_during_sweep"] = held
    try: await interp.stop()
    except Exception: pass

    # ---- B19: CANCEL during an actual sweep ----
    GATE.clear()
    interp, st, tp, clock, m = await mk2(
        "B19", {"fetch_exchange_state": "f"}, {"guard_vals": {}}, **CTL)
    await step(interp, clock, "SWEEP_DUE")
    r = await asyncio.wait_for(interp.send("CANCEL", wait=True), 3)
    await asyncio.sleep(SETTLE)
    R["b19_cancel_during_sweep"] = {"ids": ids(interp), "receipt": rcpt(r),
                                    "deferred": interp.deferred_count}
    GATE.setdefault("f", asyncio.Event()).set()
    try: await interp.stop()
    except Exception: pass

    # ---- B19 stale_lockout: failures_exhausted -> stale_lockout, then flap ----
    for ev in ["RECONNECTED", "OPERATOR_RESOLVED", "SWEEP_DUE"]:
        out = await run_plain(
            "B19", ["SWEEP_DUE", ev],
            stub_kw={"guard_vals": {"failures_exhausted": True},
                     "svc": {"fetch_exchange_state": RuntimeError("net")}}, **CTL)
        R["b19_stale_" + ev] = {k: out[k] for k in ("ids", "acts", "deferred", "receipts")}

    R["b19_stale_entry"] = {k: (await run_plain(
        "B19", ["SWEEP_DUE"],
        stub_kw={"guard_vals": {"failures_exhausted": True},
                 "svc": {"fetch_exchange_state": RuntimeError("net")}}, **CTL))[k]
        for k in ("ids", "acts")}

    # ---- CV-C32: does service_executor make plain-def services usable? ----
    cfg = cfg_of("B18")
    st2 = Stub(cfg, guard_vals=GOK)
    logic = st2.logic()
    mark = []
    def sync_cancel(interp, ctx, evt):
        mark.append(("start", time.monotonic()))
        time.sleep(0.25)
        mark.append(("end", time.monotonic()))
        return {"ok": True}
    logic.services["cancel_all_working_orders"] = sync_cancel
    mm = create_machine(json.loads(json.dumps(cfg)), logic=logic)
    clock = SimulatedClock()
    it = Interpreter(mm, clock=clock, **CTL)
    tp2 = TraceP(); it.use(tp2)
    await it.start(); await asyncio.sleep(SETTLE)
    ticks = []
    async def ticker():
        while True:
            ticks.append(time.monotonic()); await asyncio.sleep(0.02)
    t = asyncio.create_task(ticker())
    t0 = time.monotonic()
    await it.send("ENGAGE", wait=True)
    await asyncio.sleep(SETTLE * 3)
    t.cancel()
    if mark:
        during = [x for x in ticks if mark[0][1] < x < mark[1][1]]
    else:
        during = []
    R["cvc32_plain_def_service"] = {
        "ran": bool(mark), "ids": ids(it), "status": it.status,
        "loop_ticks_during_blocking_service": len(during),
        "service_wall_s": round(mark[1][1] - mark[0][1], 3) if mark else None,
        "has_service_executor_param": "service_executor" in
            Interpreter.__init__.__code__.co_varnames,
    }
    await it.stop()

asyncio.run(main())
json.dump(R, open("results/k4_redo.json", "w", encoding="utf-8"), indent=2, default=str)
print(json.dumps(R, indent=1, default=str)[:4500])
