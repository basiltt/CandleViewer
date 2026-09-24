"""N4 — DETERMINISM attacks: 50x identical traces on both engines including
executor-backed plain-def services (ordering vs #116), and a hash-seed sweep.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from typing import Any, Dict, List

from n_harness import attack, main

from xstate_statemachine import (
    Interpreter,
    MachineLogic,
    SyncInterpreter,
    create_machine,
)

SCRIPT = ["GO", "X", "GO", "DONE", "GO", "X", "GO"]

CFG: Dict[str, Any] = {
    "id": "d",
    "initial": "idle",
    "context": {"n": 0},
    "states": {
        "idle": {"on": {"GO": {"target": "work", "actions": ["log_go"]}}},
        "work": {
            "invoke": {"src": "calc", "onDone": {"target": "idle", "actions": ["log_done"]}},
            "on": {"X": {"actions": ["log_x"]}},
        },
    },
}


def _trace_logic(trace: List[str]) -> MachineLogic:
    def calc(i_, ctx, e):  # noqa: ANN001
        # plain `def` -> runs on the service_executor (#149)
        trace.append("svc:calc")
        return {"v": 1}

    def log_go(i_, ctx, e, am):  # noqa: ANN001
        ctx["n"] = ctx.get("n", 0) + 1
        trace.append(f"go:{ctx['n']}")

    def log_x(i_, ctx, e, am):  # noqa: ANN001
        trace.append("x")

    def log_done(i_, ctx, e, am):  # noqa: ANN001
        trace.append("done")

    return MachineLogic(
        actions={"log_go": log_go, "log_x": log_x, "log_done": log_done},
        services={"calc": calc},
    )


def _sync_trace() -> List[str]:
    trace: List[str] = []
    i = SyncInterpreter(create_machine(CFG, logic=_trace_logic(trace))).start()
    for ev in SCRIPT:
        i.send(ev)
        trace.append("|" + ",".join(sorted(i.current_state_ids)))
    i.stop()
    return trace


async def _async_trace() -> List[str]:
    trace: List[str] = []
    i = await Interpreter(create_machine(CFG, logic=_trace_logic(trace))).start()
    for ev in SCRIPT:
        await i.send(ev, wait=True)
        # ⚠️ `current_state_ids` is a SET; compare sorted lists. `wait=True`
        #    already settles the macrostep incl. the executor hop, so this
        #    poll is a belt-and-braces bound, not the mechanism.
        for _ in range(200):
            if sorted(i.current_state_ids) == ["d.idle"]:
                break
            await asyncio.sleep(0.002)
        trace.append("|" + ",".join(sorted(i.current_state_ids)))
    await i.stop()
    return trace


@attack(
    "N4-01",
    "50x the same script on SyncInterpreter (executor-backed service) yields ONE byte-identical trace",
    "determinism is the precondition for replay-based reconciliation",
)
def n4_01() -> Dict[str, Any]:
    seen = {json.dumps(_sync_trace()) for _ in range(50)}
    return {"ok": len(seen) == 1, "distinct_traces": len(seen), "trace": list(seen)[0][:300]}


@attack(
    "N4-02",
    "50x the same script on Interpreter (async, service on the executor) yields ONE byte-identical trace",
    "#149 moved services to a thread pool — the ORDER of their completion must not float",
)
async def n4_02() -> Dict[str, Any]:
    seen = set()
    for _ in range(50):
        seen.add(json.dumps(await _async_trace()))
    return {"ok": len(seen) == 1, "distinct_traces": len(seen), "trace": list(seen)[0][:300]}


@attack(
    "N4-03",
    "#116 parity survives #149: the async trace EQUALS the sync trace with an executor service",
    "the executor hop must not reorder a completion relative to a user event",
)
async def n4_03() -> Dict[str, Any]:
    s = _sync_trace()
    a = await _async_trace()
    return {"ok": s == a, "sync": s, "async": a}


@attack(
    "N4-04",
    "The trace is stable across 5 PYTHONHASHSEED values (fresh subprocess each)",
    "dict/set iteration order must never reach transition selection",
)
def n4_04() -> Dict[str, Any]:
    here = os.path.dirname(os.path.abspath(__file__))
    prog = (
        "import json,sys;sys.path.insert(0,r'%s');"
        "import n4_determinism as N;print(json.dumps(N._sync_trace()))" % here
    )
    outs: List[str] = []
    for seed in ("0", "1", "42", "12345", "99991"):
        env = dict(os.environ, PYTHONHASHSEED=seed, PYTHONIOENCODING="utf-8")
        r = subprocess.run(
            [sys.executable, "-c", prog],
            capture_output=True,
            text=True,
            env=env,
            timeout=60,
        )
        outs.append(r.stdout.strip().splitlines()[-1] if r.stdout.strip() else f"ERR:{r.stderr[-200:]}")
    return {"ok": len(set(outs)) == 1, "distinct": len(set(outs)), "sample": outs[0][:250]}


@attack(
    "N4-05",
    "A PARALLEL machine's region-entry and action order is identical 50x on both engines",
    "parallel region ordering is where a set-iteration leak would show first",
)
async def n4_05() -> Dict[str, Any]:
    cfg = {
        "id": "p",
        "type": "parallel",
        "context": {},
        "states": {
            "r0": {
                "initial": "a",
                "states": {"a": {"entry": ["e_r0a"], "on": {"T": "b"}}, "b": {"entry": ["e_r0b"]}},
            },
            "r1": {
                "initial": "a",
                "states": {"a": {"entry": ["e_r1a"], "on": {"T": "b"}}, "b": {"entry": ["e_r1b"]}},
            },
            "r2": {
                "initial": "a",
                "states": {"a": {"entry": ["e_r2a"], "on": {"T": "b"}}, "b": {"entry": ["e_r2b"]}},
            },
        },
    }

    def mk(trace: List[str]):
        names = [f"e_r{r}{s}" for r in range(3) for s in ("a", "b")]
        acts = {n: (lambda n_: (lambda i_, c, e, a: trace.append(n_)))(n) for n in names}
        return create_machine(cfg, logic=MachineLogic(actions=acts))

    sync_seen = set()
    for _ in range(50):
        t: List[str] = []
        i = SyncInterpreter(mk(t)).start()
        i.send("T")
        t.append("|" + ",".join(sorted(i.current_state_ids)))
        i.stop()
        sync_seen.add(json.dumps(t))
    async_seen = set()
    for _ in range(50):
        t = []
        i = await Interpreter(mk(t)).start()
        await i.send("T", wait=True)
        t.append("|" + ",".join(sorted(i.current_state_ids)))
        await i.stop()
        async_seen.add(json.dumps(t))
    same = sync_seen == async_seen
    return {
        "ok": len(sync_seen) == 1 and len(async_seen) == 1 and same,
        "sync_distinct": len(sync_seen),
        "async_distinct": len(async_seen),
        "engines_agree": same,
        "trace": list(sync_seen)[0][:300],
    }


if __name__ == "__main__":
    main("n4_determinism")
