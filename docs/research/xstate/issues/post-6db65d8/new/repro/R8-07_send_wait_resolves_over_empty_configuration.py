"""Standalone repro for R8-07: `await send(EV, wait=True)` can resolve
success-shaped (ok=True, err=None, status='running') at an instant when
`current_state_ids == []`, while `get_persisted_snapshot()` correctly refuses
at the same instant. Exits 1 while present, 0 once fixed.
"""
import asyncio
import logging
import os
import sys
import threading
import warnings

warnings.simplefilter("ignore")
logging.disable(logging.CRITICAL)

from xstate_statemachine import Interpreter, SyncInterpreter, MachineLogic, create_machine
from xstate_statemachine.exceptions import SnapshotMidStepError, SnapshotCorruptError
FAIL = []
CFG = {
    "id": "m", "initial": "a", "maxIterations": 38,
    "after": {"17": {"target": "#m.a.c"}},
    "states": {"a": {
        "initial": "a", "always": {"target": "#m.a.a.a"},
        "states": {
            "a": {"initial": "a", "invoke": {"id": "inv", "src": "svc"},
                  "states": {"a": {"type": "final"}}},
            "c": {},
        },
    }},
}


async def async_svc(i, c, e):
    return {"ok": 1}

def plain_svc(i, c, e):
    return {"ok": 1}

def mk(svc):
    import copy
    return create_machine(copy.deepcopy(CFG), logic=MachineLogic(services={"svc": svc}))

def snap(it):
    try:
        it.get_persisted_snapshot()
        return "PRODUCED"
    except (SnapshotMidStepError, SnapshotCorruptError) as e:
        return f"REFUSED:{type(e).__name__}"

async def trial(svc):
    it = Interpreter(mk(svc))
    await asyncio.wait_for(it.start(), 10)
    for ev in ("GO", "GO", "PING", "NOPE"):
        try:
            await asyncio.wait_for(it.send(ev, wait=True), 8)
        except (asyncio.TimeoutError, Exception):
            continue
        if not list(it.current_state_ids):
            row = ("EMPTY", it.last_transition_ok, it.last_error, it.status, snap(it))
            await it.stop()
            return row
    await it.stop()
    return ("ok",)

def run_sync():
    it = SyncInterpreter(mk(plain_svc))
    it.start()
    empty = not it.current_state_ids
    for ev in ("GO", "GO", "PING", "NOPE"):
        try:
            it.send(ev)
        except Exception:
            pass
        empty = empty or not it.current_state_ids
    it.stop()
    return empty

async def main(n=15):
    print("EXPECTED: await send(EV, wait=True) never resolves ok=True/err=None while\n"
          "current_state_ids == [] (or the snapshot side agrees it's mid-step).\nOBSERVED:")
    sync_empty = run_sync()
    print(f"  sync engine, plain def svc: ever EMPTY config = {sync_empty}")
    if sync_empty:
        FAIL.append("sync engine produced an empty configuration")

    for name, svc in (("async def", async_svc), ("plain def", plain_svc)):
        hits, sample = 0, None
        for _ in range(n):
            r = await trial(svc)
            if r[0] == "EMPTY":
                hits += 1
                sample = sample or r
        print(f"  async engine, {name:<9} svc: EMPTY config {hits}/{n}")
        if sample:
            _, ok, err, status, snapshot = sample
            print(f"    ok={ok} err={err} status={status} snapshot={snapshot}")
            if ok is True and err is None and snapshot.startswith("REFUSED"):
                FAIL.append(f"{name}: receipt success-shaped (ok=True,err=None) "
                             f"while snapshot refused ({snapshot}) over empty configuration")

    print("\nFAILURES:", FAIL if FAIL else "none")
    if FAIL:
        print("VERDICT: FAIL (defect present)")
        sys.exit(1)
    print("VERDICT: PASS (defect fixed)")
    sys.exit(0)

def _watchdog(timeout=60.0):
    def _kill():
        print("WATCHDOG: repro hung; aborting", file=sys.stderr)
        os._exit(2)
    t = threading.Timer(timeout, _kill)
    t.daemon = True
    t.start()


if __name__ == "__main__":
    _watchdog(60.0)
    asyncio.run(main())
