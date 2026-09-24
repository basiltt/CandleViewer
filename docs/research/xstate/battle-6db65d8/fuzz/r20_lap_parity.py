"""R20 -- is the r11 LAP-PARITY mismatch a real contract break or a harness
artefact?

r11 found 129/500 configs where the sync and async engines processed a
different number of events for the SAME chart with a `plain def` service
(`nested_invoke` 93, `rollback_ondone` 36).  #179 claims "Both service kinds
now trip at the same lap count as the sync engine."

Two candidate explanations:
  (A) a real divergence in the trip point;
  (B) the harness's global `_process_event` counter also counts the SYNC
      engine's `always`/transient micro-steps differently, or counts events
      from the previous run because the counter is global and the async run
      is still draining when it is read.

This script removes (B): one config at a time, a FRESH counter per run,
quiescence-polled, and it reports the exact event-TYPE histogram for each
engine so a difference can be attributed to a specific event rather than a
total.
"""
import asyncio, collections, copy, json, logging, sys, time, warnings
warnings.simplefilter("ignore"); logging.disable(logging.CRITICAL)
import xstate_statemachine.base_interpreter as bi
from xstate_statemachine import (
    Interpreter,
    SyncInterpreter,
    MachineLogic,
    create_machine,
)

C = collections.Counter()
_o = bi.BaseInterpreter._process_event


async def _p(self, e):
    C[e.type] += 1
    return await _o(self, e)


bi.BaseInterpreter._process_event = _p


def p_svc(i, c, e):
    return {"ok": 1}


def bump(i, c, e, a):
    c["n"] = c.get("n", 0) + 1


def L():
    return MachineLogic(
        services={"svc": p_svc},
        actions={"bump": bump},
        guards={"g": lambda c, e: True},
    )


def nested_invoke(i, mi):
    c = {"id": f"m{i}", "initial": "a", "context": {"n": 0}}
    if mi is not None:
        c["maxIterations"] = mi
    c["states"] = {
        "a": {
            "initial": "a",
            "invoke": {"id": "i1", "src": "svc", "onDone": {"target": f"#m{i}.a"}},
            "states": {
                "a": {
                    "invoke": {
                        "id": "i2",
                        "src": "svc",
                        "onDone": {"target": f"#m{i}.a"},
                    }
                }
            },
        }
    }
    return c


def rollback_ondone(i, mi):
    c = {"id": f"m{i}", "initial": "a", "context": {"n": 0}}
    if mi is not None:
        c["maxIterations"] = mi
    c["states"] = {
        "a": {"invoke": {"id": "i1", "src": "svc", "onDone": {"target": "b"}}},
        "b": {"always": {"target": "a", "guard": "g", "actions": ["bump"]}},
    }
    return c


def run_sync(cfg):
    C.clear()
    it = SyncInterpreter(create_machine(copy.deepcopy(cfg), logic=L()))
    it.start()
    h = dict(C)
    err = type(it.last_error).__name__ if it.last_error else None
    ids = sorted(it.current_state_ids)
    it.stop()
    return sum(h.values()), h, err, ids


async def run_async(cfg, watch=8.0):
    C.clear()
    it = Interpreter(create_machine(copy.deepcopy(cfg), logic=L()))
    await asyncio.wait_for(it.start(), 15)
    prev, stable, t0 = -1, 0, time.time()
    while time.time() - t0 < watch:
        await asyncio.sleep(0.1)
        cur = sum(C.values())
        stable = stable + 1 if cur == prev else 0
        prev = cur
        if stable >= 5:
            break
    h = dict(C)
    err = type(it.last_error).__name__ if it.last_error else None
    ids = sorted(it.current_state_ids)
    await it.stop()
    return sum(h.values()), h, err, ids


async def main():
    print("Per-config lap parity, fresh counter, quiescence-polled, plain def svc\n")
    bad = 0
    tot = 0
    for name, mk in (("nested_invoke", nested_invoke), ("rollback_ondone", rollback_ondone)):
        for mi in (1, 5, 20, 1000, None):
            cfg = mk(0, mi)
            sn, sh, se, si = run_sync(cfg)
            an, ah, ae, ai = await run_async(cfg)
            tot += 1
            same = sn == an
            bad += 0 if same else 1
            print(
                f"  {name:<16} mi={str(mi):<5} sync laps={sn:<5} async laps={an:<5} "
                f"{'SAME' if same else 'DIFFER'}"
            )
            print(
                f"      sync  err={se} ids={si} hist={ {k: v for k, v in sorted(sh.items())} }"
            )
            print(
                f"      async err={ae} ids={ai} hist={ {k: v for k, v in sorted(ah.items())} }"
            )
    print(f"\n  configs={tot} lap-parity mismatches={bad}")


asyncio.run(main())
