"""N4 — DETERMINISM: 50x byte-identical traces on both engines, including
the new inline plain-sync invoke semantics (#116), across hash seeds.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import subprocess
import sys
from typing import Any, Dict, List

from n_harness import attack, main

from xstate_statemachine import (
    Interpreter,
    MachineLogic,
    PluginBase,
    SimulatedClock,
    SyncInterpreter,
    create_machine,
)

# A machine with parallel regions, guards, always-hops, a plain-sync invoke
# and an `after` -- every ordering-sensitive surface at once.
CFG: Dict[str, Any] = {
    "id": "d",
    "type": "parallel",
    "context": {"n": 0},
    "states": {
        "P": {
            "initial": "idle",
            "states": {
                "idle": {"entry": ["e_idle"], "on": {"GO": "work"}},
                "work": {
                    "entry": ["e_work"],
                    "invoke": {"id": "w", "src": "svc"},
                    "on": {
                        "done.invoke.w": {"target": "hop", "actions": ["a_done"]},
                        "CANCEL": {"target": "idle", "actions": ["a_cancel"]},
                    },
                },
                "hop": {"entry": ["e_hop"], "always": "idle"},
            },
        },
        "Q": {
            "initial": "q1",
            "states": {
                "q1": {
                    "entry": ["e_q1"],
                    "on": {"GO": {"target": "q2", "actions": ["a_q"]}},
                },
                "q2": {"entry": ["e_q2"], "on": {"CANCEL": "q1"}},
            },
        },
    },
}

SCRIPT = ["GO", "CANCEL", "GO", "GO", "CANCEL", "NOPE", "GO", "CANCEL"]
NAMES = ["e_idle", "e_work", "e_hop", "e_q1", "e_q2", "a_done", "a_cancel", "a_q"]


class Trace(PluginBase):
    """Records an ordered, engine-neutral trace of every transition."""

    def __init__(self) -> None:
        self.log: List[str] = []

    def on_transition(self, interpreter, from_states, to_states, transition):  # noqa: ANN001
        self.log.append("T:" + ",".join(sorted(s.id for s in to_states)))


def _logic(log: List[str]) -> MachineLogic:
    def mk(name: str):
        def fn(i, ctx, e, am):  # noqa: ANN001
            log.append(name)

        return fn

    def svc(i, ctx, e):  # plain sync service: inline on BOTH engines (#116)
        return {"v": 1}

    return MachineLogic(
        actions={n: mk(n) for n in NAMES}, services={"svc": svc}
    )


def _sync_trace() -> str:
    log: List[str] = []
    t = Trace()
    s = SyncInterpreter(create_machine(CFG, logic=_logic(log)))
    s.use(t)
    s.start()
    for ev in SCRIPT:
        s.send(ev)
        s.tick()
    out = json.dumps({"actions": log, "transitions": t.log,
                      "ids": sorted(s.current_state_ids)}, sort_keys=True)
    s.stop()
    return out


async def _async_trace() -> str:
    log: List[str] = []
    t = Trace()
    i = Interpreter(create_machine(CFG, logic=_logic(log)))
    i.use(t)
    await i.start()
    for ev in SCRIPT:
        await i.send(ev, wait=True)
    await asyncio.sleep(0.05)
    out = json.dumps({"actions": log, "transitions": t.log,
                      "ids": sorted(i.current_state_ids)}, sort_keys=True)
    await i.stop()
    return out


@attack(
    "N4-01",
    "50x identical script on SyncInterpreter yields ONE byte-identical trace",
    "a replayed order script must be bit-reproducible or audit/replay is impossible",
)
async def n4_01() -> Dict[str, Any]:
    traces = {_sync_trace() for _ in range(50)}
    return {
        "ok": len(traces) == 1,
        "runs": 50,
        "distinct": len(traces),
        "sample": sorted(traces)[0][:300],
    }


@attack(
    "N4-02",
    "50x identical script on Interpreter (async) yields ONE byte-identical trace",
    "async scheduling must not leak into the observable action/transition order",
)
async def n4_02() -> Dict[str, Any]:
    traces = set()
    for _ in range(50):
        traces.add(await _async_trace())
    return {
        "ok": len(traces) == 1,
        "runs": 50,
        "distinct": len(traces),
        "sample": sorted(traces)[0][:300],
    }


@attack(
    "N4-03",
    "The async and sync traces for the same script are IDENTICAL (#116 parity)",
    "engine choice must not change what an OMS did; a divergence is a correctness fork",
)
async def n4_03() -> Dict[str, Any]:
    a = await _async_trace()
    s = _sync_trace()
    return {
        "ok": a == s,
        "async": json.loads(a),
        "sync": json.loads(s),
    }


@attack(
    "N4-04",
    "The trace is stable across 5 PYTHONHASHSEED values (subprocess, sync engine)",
    "a hash-seed-dependent order would be a nondeterminism, not a deviation",
)
async def n4_04() -> Dict[str, Any]:
    here = os.path.dirname(os.path.abspath(__file__))
    prog = (
        "import sys;sys.path.insert(0,r'%s');"
        "import n4_determinism as M;print(M._sync_trace())" % here
    )
    digests = {}
    for seed in ("0", "1", "42", "12345", "99999"):
        env = dict(os.environ, PYTHONHASHSEED=seed, PYTHONIOENCODING="utf-8",
                   PYTHONUTF8="1")
        r = subprocess.run([sys.executable, "-c", prog], capture_output=True,
                           text=True, env=env, timeout=90)
        digests[seed] = hashlib.sha256(r.stdout.strip().encode()).hexdigest()[:16]
    return {"ok": len(set(digests.values())) == 1, "digests": digests}


@attack(
    "N4-05",
    "A SimulatedClock timer ladder is replay-identical 30x on both engines",
    "deterministic time replay is the basis of any OMS backtest",
)
async def n4_05() -> Dict[str, Any]:
    cfg = {
        "id": "L",
        "initial": "s1",
        "states": {
            "s1": {"after": {100: "s2"}},
            "s2": {"after": {100: "s3"}},
            "s3": {"after": {100: "s4"}},
            "s4": {"type": "final"},
        },
    }
    mk = lambda: create_machine(cfg, logic=MachineLogic())  # noqa: E731

    async def one_async() -> str:
        c = SimulatedClock()
        i = await Interpreter(mk(), clock=c).start()
        seq = [sorted(i.current_state_ids)]
        for _ in range(3):
            await c.increment(100)
            seq.append(sorted(i.current_state_ids))
        await i.stop()
        return json.dumps(seq)

    def one_sync() -> str:
        c = SimulatedClock()
        s = SyncInterpreter(mk(), clock=c).start()
        seq = [sorted(s.current_state_ids)]
        for _ in range(3):
            c.increment(100)
            seq.append(sorted(s.current_state_ids))
        s.stop()
        return json.dumps(seq)

    a = set()
    for _ in range(30):
        a.add(await one_async())
    # 🧵 D5-semantics-2: SimulatedClock.increment() returns an un-awaited
    #    _MustAwait if ANY loop is running on this thread, even when it is
    #    driving a SyncInterpreter. Run the sync lane off-loop.
    sy = await asyncio.to_thread(lambda: {one_sync() for _ in range(30)})
    return {
        "ok": len(a) == 1 and len(sy) == 1 and a == sy,
        "async_distinct": len(a),
        "sync_distinct": len(sy),
        "async": sorted(a)[0],
        "sync": sorted(sy)[0],
    }


if __name__ == "__main__":
    main("n4_determinism")
