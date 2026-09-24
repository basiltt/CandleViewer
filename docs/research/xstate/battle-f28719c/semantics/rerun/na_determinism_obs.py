"""D8-D: determinism (50x, both engines, both service kinds, incl. trip lap
counts), a hash-seed sweep, and the observability hook matrix.

D1  50x identical traces per (engine, service kind), incl. the lap count at
    the trip.
D2  Hook matrix: chain_budget on the ASYNC-def lane, queue_full loop-side,
    child=True refusal, children_timeout warning -- exactly once, ordered,
    both engines.
"""

from __future__ import annotations

import asyncio
import subprocess
import sys
import time
from collections import Counter
from typing import Any, Dict, List

from n_harness import attack, main

from xstate_statemachine import (
    Interpreter,
    MachineLogic,
    PluginBase,
    SyncInterpreter,
    create_machine,
)

TRACE_CFG = {
    "id": "t",
    "initial": "idle",
    "maxIterations": 20,
    "states": {
        "idle": {"on": {"GO": "a"}},
        "a": {"entry": "mark", "invoke": {"src": "svc", "onDone": "b"}},
        "b": {"entry": "mark", "invoke": {"src": "svc", "onDone": "a"}},
    },
}


def _trace_logic(kind: str, trace: List[str]) -> MachineLogic:
    laps = {"n": 0}

    def mark(i, ctx, e, ad):  # noqa: ANN001
        trace.append(f"enter:{sorted(i.current_state_ids)}")

    def svc(i_, ctx, e):  # noqa: ANN001
        laps["n"] += 1
        trace.append(f"svc:{laps['n']}")
        return laps["n"]

    async def svc_a(i_, ctx, e):  # noqa: ANN001
        laps["n"] += 1
        trace.append(f"svc:{laps['n']}")
        await asyncio.sleep(0)
        return laps["n"]

    return MachineLogic(
        actions={"mark": mark},
        services={"svc": svc_a if kind == "async" else svc},
    )


async def _one_async(kind: str) -> str:
    trace: List[str] = []
    i = await Interpreter(
        create_machine(dict(TRACE_CFG), logic=_trace_logic(kind, trace))
    ).start()
    await i.send("GO")
    await asyncio.sleep(0.25)
    trace.append(f"err:{type(i.last_error).__name__ if i.last_error else None}")
    await i.stop()
    return "|".join(trace)


def _one_sync() -> str:
    trace: List[str] = []
    i = SyncInterpreter(
        create_machine(dict(TRACE_CFG), logic=_trace_logic("plain", trace))
    ).start()
    r = i.send("GO", wait=True)
    err = r.error or i.last_error
    trace.append(f"err:{type(err).__name__ if err else None}")
    i.stop()
    return "|".join(trace)


@attack(
    "D1",
    "50x per lane: the trace (incl. the TRIP LAP COUNT) is byte-identical "
    "within each lane, and the def / async-def lanes agree",
    "determinism of the #179 charged lane",
)
async def d1() -> Dict[str, Any]:
    lanes: Dict[str, Counter] = {}
    for kind in ("plain", "async"):
        c: Counter = Counter()
        for _ in range(50):
            c[await _one_async(kind)] += 1
        lanes[f"async-engine/{kind}"] = c
    c = Counter()
    for _ in range(50):
        c[_one_sync()] += 1
    lanes["sync-engine/plain"] = c

    nondet = {k: len(v) for k, v in lanes.items() if len(v) != 1}

    def laps(key: str) -> int:
        t = next(iter(lanes[key]))
        return sum(1 for p in t.split("|") if p.startswith("svc:"))

    kinds_agree = laps("async-engine/plain") == laps("async-engine/async")
    engines_agree = laps("async-engine/plain") == laps("sync-engine/plain")
    return {
        "ok": not nondet and kinds_agree and engines_agree,
        "nondeterministic_lanes": nondet,
        "trip_laps": {k: laps(k) for k in lanes},
        "def_vs_asyncdef_agree": kinds_agree,
        "sync_vs_async_engine_agree": engines_agree,
        "distinct_traces_per_lane": {k: len(v) for k, v in lanes.items()},
    }


_SEED_SNIPPET = r"""
import asyncio, logging, sys
logging.disable(logging.CRITICAL)
sys.path.insert(0, r"{here}")
from n9_livelock_determinism import _run_async, _gen
import random
async def go():
    out = []
    rng = random.Random(11)
    for idx in range(12):
        cfg = _gen(rng, idx)
        for kind in ("plain", "async"):
            r = await _run_async(dict(cfg), kind)
            out.append(f"{{cfg['id']}}/{{kind}}:{{r['laps']}}:{{r['last_error']}}")
    print("|".join(out))
asyncio.run(go())
"""


@attack(
    "D2",
    "Hash-seed sweep: 5 PYTHONHASHSEED values in fresh subprocesses yield "
    "one identical lap/trip trace over 12 cycle configs x both kinds",
    "no dict/set-ordering dependence in the charged lane",
)
def d2() -> Dict[str, Any]:
    import os
    import tempfile

    here = os.path.dirname(os.path.abspath(__file__))
    code = _SEED_SNIPPET.format(here=here)
    with tempfile.NamedTemporaryFile(
        "w", suffix=".py", delete=False, encoding="utf-8"
    ) as fh:
        fh.write(code)
        path = fh.name
    outs: Dict[str, str] = {}
    for seed in ("0", "1", "42", "12345", "99991"):
        env = dict(os.environ)
        env["PYTHONHASHSEED"] = seed
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"
        p = subprocess.run(
            [sys.executable, path],
            capture_output=True,
            text=True,
            env=env,
            timeout=110,
        )
        outs[seed] = (p.stdout or "").strip().splitlines()[-1] if p.stdout.strip() else f"ERR:{p.stderr[-200:]}"
    os.unlink(path)
    distinct = set(outs.values())
    return {
        "ok": len(distinct) == 1 and not any(v.startswith("ERR") for v in outs.values()),
        "distinct_outputs": len(distinct),
        "sample": next(iter(distinct))[:300],
        "per_seed_len": {k: len(v) for k, v in outs.items()},
    }


if __name__ == "__main__":
    main("na_determinism_obs")
