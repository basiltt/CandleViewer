# -*- coding: utf-8 -*-
"""R10-C4 refutation: is the kill-switch hold a library defect or a
contract-modelling error? Standalone; stdlib + xstate_statemachine only.

A: kill handler ONLY on sibling states (the catalogue shape)  -> deferred
B: kill handler on the PARENT (standard XState kill-switch idiom) -> ?
C: kill handler on the invoking state                             -> ?
Both service styles. Polls to convergence; never samples early.
"""
from __future__ import annotations
import asyncio, copy, json, os, sys, time
from xstate_statemachine import Interpreter, MachineLogic, create_machine

STYLE = os.environ.get("CV_SVC_STYLE", "async")
HOLD = 1.5

BASE = {
  "id": "twap", "initial": "armed", "onUnhandled": "defer",
  "states": {
    "armed": {"on": {"SLICE_DUE": {"target": "submitting_slice"},
                     "USER_CANCEL": {"target": "cancelled"}}},
    "submitting_slice": {
      "invoke": {"src": "submit_child", "onDone": {"target": "armed"},
                 "onError": {"target": "cancelled"}}},
    "cancelling": {"on": {"DONE": {"target": "cancelled"}}},
    "cancelled": {"type": "final"},
  },
}

def svc():
    if STYLE == "async":
        async def held(*_a):
            await asyncio.sleep(HOLD); return {"ok": True}
        async def s(i, c, e): return await held()
        return s
    import time as _t
    def s(i, c, e):
        _t.sleep(HOLD); return {"ok": True}
    return s

def logic():
    return MachineLogic(services={"submit_child": svc()}, strict=True)

async def run(cfg, label):
    m = create_machine(copy.deepcopy(cfg), logic=logic())
    i = Interpreter(m)
    await i.start(); await asyncio.sleep(0.05)
    await asyncio.wait_for(i.send("SLICE_DUE", wait=True), 8)
    await asyncio.sleep(0.05)
    inflight = sorted(i.current_state_ids)
    t0 = time.perf_counter()
    await asyncio.wait_for(i.send("USER_CANCEL", wait=True, priority=True), 20)
    applied = None
    dl = time.perf_counter() + HOLD + 5
    while time.perf_counter() < dl:                 # poll to convergence
        if sorted(i.current_state_ids) != inflight:
            applied = time.perf_counter() - t0; break
        await asyncio.sleep(0.005)
    await asyncio.sleep(0.2)
    out = {"label": label, "style": STYLE, "inflight": inflight,
           "final": sorted(i.current_state_ids),
           "applied_s": None if applied is None else round(applied, 3),
           "deferred_count": i.deferred_count}
    try: await asyncio.wait_for(i.stop(), 5)
    except Exception: pass
    return out

async def main():
    A = copy.deepcopy(BASE)
    B = copy.deepcopy(BASE); B["on"] = {"USER_CANCEL": {"target": ".cancelled"}}
    C = copy.deepcopy(BASE)
    C["states"]["submitting_slice"]["on"] = {"USER_CANCEL": {"target": "cancelled"}}
    rows = []
    for cfg, lbl in ((A, "A sibling-only (catalogue)"), (B, "B parent handler"),
                     (C, "C handler on invoking state")):
        try: rows.append(await run(cfg, lbl))
        except Exception as e:
            import traceback; traceback.print_exc(); rows.append({"label": lbl, "exc": repr(e)})
    for r in rows: print(json.dumps(r), flush=True)

asyncio.run(main())
