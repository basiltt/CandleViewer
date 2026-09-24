"""N7 -- determinism incl. stranded events, and a reduced soak.

A  DETERMINISM. 50 identical runs of the #207 stranded shape on both
   engines x both service kinds: the trace (final ids, trip lap, error
   type, stranded ids, hook count) must be a single distinct value.

B  SOAK (reduced -- see the report's reductions table). Concurrent machines
   mixing always->invoke, rollback+onDone, delayed self-sends, an external
   priority producer and chaos snapshots at quiescence. Asserts: CPU
   bounded, 0 external sends dropped, no livelock, and NO stranded invoke
   without a hook firing for it.

STANDALONE: stdlib + xstate_statemachine only. Run from any cwd.
"""

import asyncio
import logging
import os
import time
import warnings
from collections import Counter

warnings.simplefilter("ignore")
logging.disable(logging.CRITICAL)

from xstate_statemachine import Interpreter, MachineLogic, create_machine
from xstate_statemachine.plugins import PluginBase

N_RUNS = 50
SOAK_SECONDS = float(os.environ.get("SOAK_SECONDS", "45"))
SOAK_MACHINES = int(os.environ.get("SOAK_MACHINES", "60"))

STRAND_CFG = {
    "id": "d",
    "initial": "idle",
    "maxIterations": 6,
    "actionErrorPolicy": "rollback",
    "states": {
        "idle": {"on": {"GO": "starting"}},
        "starting": {
            "invoke": {"id": "fill", "src": "svc", "onDone": "recording"}
        },
        "recording": {"entry": ["boom"]},
    },
}


def boom(i, c, e, a=None):
    raise RuntimeError("entry failed")


def svc_def(i, c, e):
    return 1


async def svc_async(i, c, e):
    await asyncio.sleep(0)
    return 1


class Obs(PluginBase):
    def __init__(self):
        self.stranded = []
        self.dropped = 0

    def on_invocation_stranded(self, i, sid, iid, err):
        self.stranded.append((sid, iid))

    def on_event_dropped(self, i, ev, reason=None, **kw):
        self.dropped += 1


def logic(kind):
    return MachineLogic(
        actions={"boom": boom},
        services={"svc": svc_def if kind == "def" else svc_async},
    )


async def trace_once(kind):
    o = Obs()
    it = Interpreter(create_machine(STRAND_CFG, logic=logic(kind))).use(o)
    await it.start()
    await it.send("GO")
    for _ in range(250):
        if type(it.last_error).__name__ == "RunawayChainError":
            break
        await asyncio.sleep(0.01)
    await asyncio.sleep(0.03)
    err = it.last_error
    t = (
        tuple(sorted(it.current_state_ids)),
        type(err).__name__ if err else None,
        tuple(getattr(err, "stranded", ()) or ()),
        tuple(o.stranded),
        len(o.stranded),
        it.has_dormant_invocations,
    )
    await it.stop()
    return t


# ------------------------------------------------------------------- soak

SOAK_CFG = {
    "id": "s",
    "initial": "idle",
    "maxIterations": 8,
    "actionErrorPolicy": "rollback",
    "context": {"ext": 0},
    "states": {
        "idle": {
            "on": {"GO": "gate", "EXT": {"actions": ["count_ext"]}},
        },
        "gate": {
            "always": {"target": "starting"},
            "on": {"EXT": {"actions": ["count_ext"]}},
        },
        "starting": {
            "entry": [{"type": "raise", "params": {"event": "TICK",
                                                   "delay": 1}}],
            "invoke": {"id": "fill", "src": "svc", "onDone": "recording"},
            "on": {"EXT": {"actions": ["count_ext"]}, "TICK": {}},
        },
        "recording": {
            "entry": ["boom"],
            "on": {"EXT": {"actions": ["count_ext"]}},
        },
    },
}


def count_ext(i, c, e, a=None):
    c["ext"] = c.get("ext", 0) + 1


def soak_logic(kind):
    return MachineLogic(
        actions={"boom": boom, "count_ext": count_ext},
        services={"svc": svc_def if kind == "def" else svc_async},
    )


async def soak():
    obs = []
    machines = []
    for k in range(SOAK_MACHINES):
        kind = "def" if k % 2 == 0 else "async def"
        o = Obs()
        it = Interpreter(
            create_machine(SOAK_CFG, logic=soak_logic(kind))
        ).use(o)
        await it.start()
        await it.send("GO")
        obs.append(o)
        machines.append(it)

    sent = 0
    snaps = Counter()
    t0 = time.monotonic()
    cpu0 = time.process_time()
    while time.monotonic() - t0 < SOAK_SECONDS:
        for it in machines:
            try:
                await it.send("EXT", priority=True)
                sent += 1
            except Exception as exc:  # noqa: BLE001
                snaps[f"send:{type(exc).__name__}"] += 1
        for it in machines[:5]:
            try:
                it.get_snapshot()
                snaps["snap_ok"] += 1
            except Exception as exc:  # noqa: BLE001
                snaps[f"snap:{type(exc).__name__}"] += 1
        await asyncio.sleep(0.001)
    cpu = time.process_time() - cpu0
    el = time.monotonic() - t0

    applied = sum(it.context.get("ext", 0) for it in machines)
    dropped = sum(o.dropped for o in obs)
    stranded_no_hook = 0
    for it, o in zip(machines, obs):
        if it.has_dormant_invocations and not o.stranded:
            stranded_no_hook += 1
    for it in machines:
        await it.stop()
    return {
        "elapsed": el,
        "machines": SOAK_MACHINES,
        "ext_sent": sent,
        "ext_applied": applied,
        "ext_lost": sent - applied,
        "drop_hook": dropped,
        "cpu_s": round(cpu, 1),
        "cpu_pct_of_one_core": round(100 * cpu / el, 1),
        "snapshots": dict(snaps),
        "dormant_without_hook": stranded_no_hook,
    }


async def main():
    bad = []
    print(f"N7/A -- determinism, {N_RUNS} identical runs of the #207 shape")
    for kind in ("def", "async def"):
        seen = Counter()
        for _ in range(N_RUNS):
            seen[await trace_once(kind)] += 1
        print(f"   {kind:<9} distinct traces = {len(seen)}")
        for t, n in seen.items():
            print(f"      x{n:<3} {t}")
        if len(seen) != 1:
            bad.append(f"A/{kind}: {len(seen)} distinct traces over {N_RUNS}")
    print()
    print(f"N7/B -- soak, {SOAK_MACHINES} machines, {SOAK_SECONDS:.0f}s")
    r = await soak()
    for k, v in r.items():
        print(f"   {k:<24} {v}")
    if r["ext_lost"] != 0:
        bad.append(f"B: {r['ext_lost']} external priority sends lost")
    if r["dormant_without_hook"]:
        bad.append(
            f"B: {r['dormant_without_hook']} machines dormant with no "
            f"on_invocation_stranded"
        )
    if r["cpu_pct_of_one_core"] > 400:
        bad.append(f"B: CPU unbounded ({r['cpu_pct_of_one_core']}%)")
    print()
    print(f"DEFECTS = {len(bad)}")
    for b in bad:
        print(f"   - {b}")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
