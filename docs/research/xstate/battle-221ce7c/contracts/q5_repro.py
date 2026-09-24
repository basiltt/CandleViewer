# -*- coding: utf-8 -*-
"""CV-221-01 minimal repro + necessity ablations + recovery.

Shape: state A invokes a service; onDone -> B; B's entry action raises under
actionErrorPolicy "rollback" -> rolled back into A -> invoke re-armed -> loop.
"""
import asyncio, json, time
from xstate_statemachine import (Interpreter, MachineLogic, create_machine,
                                 SyncInterpreter, OverflowPolicy)
from xstate_statemachine.clock import SimulatedClock

CTL = dict(max_queue_size=64, overflow_policy=OverflowPolicy.RAISE)
R = {}


def cfg(policy="rollback", guarded=True, entry_raise=True):
    ondone = ([{"target": "#m.b", "guard": "never"}, {"target": "#m.c"}]
              if guarded else {"target": "#m.c"})
    return {
        "id": "m", "initial": "idle", "actionErrorPolicy": policy,
        "guardErrorPolicy": "raise", "onUnhandled": "error",
        "strictTargets": True, "strict": True, "context": {},
        "states": {
            "idle": {"on": {"GO": "a"}},
            "a": {"invoke": {"id": "s", "src": "svc", "onDone": ondone,
                             "onError": {"target": "#m.c"}}},
            "b": {},
            "c": {"entry": (["boom"] if entry_raise else ["ok"])},
        },
    }


def logic(calls, acts):
    async def svc(i, c, e):
        calls.append(1)
        return {"ok": True}

    def boom(i, c, e, a):
        acts.append("boom")
        raise RuntimeError("boom")

    def ok(i, c, e, a):
        acts.append("ok")

    return MachineLogic(actions={"boom": boom, "ok": ok},
                        guards={"never": lambda c, e: False},
                        services={"svc": svc}, strict=True)


async def run(c, watch=1.0, sync=False):
    calls, acts = [], []
    m = create_machine(json.loads(json.dumps(c)), logic=logic(calls, acts))
    if sync:
        it = SyncInterpreter(m, clock=SimulatedClock())
        try:
            it.start(); it.send("GO")
            o = {"ids": sorted(it.current_state_ids), "status": it.status}
        except Exception as ex:
            o = {"error": f"{type(ex).__name__}: {str(ex)[:120]}"}
        o.update(svc=len(calls), acts=len(acts), engine="sync")
        try: it.stop()
        except Exception: pass
        return o
    it = Interpreter(m, clock=SimulatedClock(), **CTL)
    await it.start(); await asyncio.sleep(0.03)
    t0 = time.perf_counter()
    try:
        r = await asyncio.wait_for(it.send("GO", wait=True), 10)
        rec = {"changed": r.changed,
               "error": type(r.error).__name__ if r.error else None}
    except asyncio.TimeoutError:
        rec = {"TIMEOUT": True}
    rec["send_wall"] = round(time.perf_counter() - t0, 3)
    await asyncio.sleep(watch)
    n1 = len(calls)
    await asyncio.sleep(watch)
    o = {"receipt": rec, "svc_at_t": n1, "svc_at_2t": len(calls),
         "acts": len(acts), "ids": sorted(it.current_state_ids),
         "status": it.status, "engine": "async",
         "last_error": type(getattr(it, "last_error", None)).__name__
         if getattr(it, "last_error", None) else None}
    try:
        await asyncio.wait_for(it.stop(), 5)
    except Exception as ex:
        o["stop_error"] = type(ex).__name__
    return o


async def main():
    R["repro_async"] = await run(cfg())
    R["repro_sync"] = await run(cfg(), sync=True)
    # ablations
    R["abl_policy_fail"] = await run(cfg(policy="fail"))
    R["abl_policy_continue"] = await run(cfg(policy="continue"))
    R["abl_unguarded_ondone"] = await run(cfg(guarded=False))
    R["abl_no_entry_raise"] = await run(cfg(entry_raise=False))
    # recovery: does an external event end the chain?
    calls, acts = [], []
    m = create_machine(cfg(), logic=logic(calls, acts))
    it = Interpreter(m, clock=SimulatedClock(), **CTL)
    await it.start(); await asyncio.sleep(0.03)
    await asyncio.wait_for(it.send("GO", wait=True), 10)
    await asyncio.sleep(0.5)
    n0 = len(calls)
    try:
        r = await asyncio.wait_for(it.send("NOPE", wait=True), 5)
        ext = {"changed": r.changed,
               "error": type(r.error).__name__ if r.error else None}
    except Exception as ex:
        ext = {"exc": type(ex).__name__}
    await asyncio.sleep(0.5)
    R["recovery_external_event"] = {
        "svc_before_ext": n0, "ext": ext,
        "svc_after_ext": len(calls) - n0, "status": it.status,
        "ids": sorted(it.current_state_ids)}
    try:
        await asyncio.wait_for(it.stop(), 5)
    except Exception:
        pass

asyncio.run(main())
json.dump(R, open("results/q5_repro.json", "w", encoding="utf-8"), indent=2,
          default=str)
for k, v in R.items():
    print(k, json.dumps(v, default=str))
