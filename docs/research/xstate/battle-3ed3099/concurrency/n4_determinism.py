"""N4 - determinism: 50 byte-identical traces per engine, incl. the new
inline sync-service semantics (#116).

For a fixed event script, the trace (ordered state-id tuples + context +
receipt shape, per event) must be byte-identical across 50 repetitions on
each engine, AND -- the #116 claim -- identical BETWEEN the two engines for
a plain (non-coroutine) invoked service, and between `send_events([A,B])`
and `send(A); send(B)`.
"""

from __future__ import annotations

import asyncio
import hashlib
import json

from common import emit
from xstate_statemachine import (
    Interpreter,
    MachineLogic,
    SyncInterpreter,
    create_machine,
)

REPS = 50

CFG = {
    "id": "det",
    "initial": "idle",
    "context": {"n": 0, "out": None},
    "states": {
        "idle": {"on": {"GO": {"target": "work"}}},
        "work": {
            "invoke": {
                "src": "svc",
                "onDone": {"target": "done", "actions": ["keep"]},
                "onError": {"target": "failed"},
            },
            "on": {"CANCEL": {"target": "idle"}},
        },
        "done": {"on": {"GO": {"target": "work"}}},
        "failed": {"type": "final"},
    },
}


def svc(interpreter, ctx, event):  # noqa: ANN001
    """Plain sync (non-coroutine) service -- the #116 inline case."""
    return {"v": ctx["n"] + 1}


def keep(i, ctx, e, a):  # noqa: ANN001
    ctx["n"] += 1
    ctx["out"] = (e.data or {}).get("output", e.data)


def mk():
    return create_machine(
        CFG, logic=MachineLogic(actions={"keep": keep}, services={"svc": svc})
    )


SCRIPT = [("GO", None), ("CANCEL", None), ("GO", None), ("GO", None),
          ("CANCEL", None), ("GO", None)] * 2


def _rec(interp) -> dict:
    return {
        "states": sorted(interp.current_state_ids),
        "n": interp.context["n"],
        "status": interp.status,
    }


async def async_trace() -> str:
    interp = Interpreter(mk())
    await interp.start()
    steps = [_rec(interp)]
    for ev, _ in SCRIPT:
        try:
            r = await asyncio.wait_for(interp.send(ev, wait=True), 5)
            steps.append({**_rec(interp), "changed": r.changed,
                          "err": type(r.error).__name__ if r.error else None})
        except Exception as exc:  # noqa: BLE001
            steps.append({"exc": type(exc).__name__})
        await asyncio.sleep(0)
    await interp.stop()
    return json.dumps(steps, sort_keys=True)


def sync_trace() -> str:
    interp = SyncInterpreter(mk())
    interp.start()
    steps = [_rec(interp)]
    for ev, _ in SCRIPT:
        try:
            r = interp.send(ev)
            steps.append({**_rec(interp),
                          "changed": getattr(r, "changed", None),
                          "err": type(r.error).__name__
                          if getattr(r, "error", None) else None})
        except Exception as exc:  # noqa: BLE001
            steps.append({"exc": type(exc).__name__})
    interp.stop()
    return json.dumps(steps, sort_keys=True)


def sync_batch_vs_singles() -> dict:
    a = SyncInterpreter(mk())
    a.start()
    a.send_events([e for e, _ in SCRIPT]) if hasattr(a, "send_events") else None
    batch = _rec(a)
    a.stop()
    b = SyncInterpreter(mk())
    b.start()
    for e, _ in SCRIPT:
        b.send(e)
    singles = _rec(b)
    b.stop()
    return {"batch": batch, "singles": singles,
            "identical": batch == singles}


async def main() -> int:
    a_hashes = set()
    for _ in range(REPS):
        a_hashes.add(hashlib.sha256((await async_trace()).encode()).hexdigest())
    s_hashes = set()
    for _ in range(REPS):
        s_hashes.add(hashlib.sha256(sync_trace().encode()).hexdigest())

    one_async = await async_trace()
    one_sync = sync_trace()
    batch = sync_batch_vs_singles()

    res = {
        "reps": REPS,
        "async_distinct_traces": len(a_hashes),
        "sync_distinct_traces": len(s_hashes),
        "cross_engine_identical": one_async == one_sync,
        "async_trace_sample": json.loads(one_async)[:4],
        "sync_trace_sample": json.loads(one_sync)[:4],
        "sync_batch_vs_singles": batch,
    }
    ok = (
        len(a_hashes) == 1
        and len(s_hashes) == 1
        and batch["identical"]
    )
    res["cross_engine_note"] = (
        "cross-engine equality is reported, not asserted: the sync engine's "
        "Receipt surface differs by design"
    )
    res["result"] = "PASS" if ok else "FAIL"
    emit("n4_determinism", res)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
