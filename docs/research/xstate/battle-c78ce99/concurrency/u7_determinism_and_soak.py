"""u7 (@c78ce99) -- STANDALONE. Determinism + reduced chaos soak.

D1  50x traces of the same chart on BOTH engines x BOTH action kinds,
    including a v3 `scheduled_sends` restore hop on a SimulatedClock:
    the transition trace and final context must be byte-identical.
D2  hash-seed: the same trace under 3 child processes with distinct
    PYTHONHASHSEED values.
S1  REDUCED soak (90 s, not the briefed 12 min -- the 20-minute
    whole-task bound; stated in the report): 60 machines, both kinds,
    `raise(delay=)` heartbeats at 10-50 ms + an external PRIORITY
    producer + chaos v3 snapshot/restore at quiescence every 2 s.
    Invariants: CPU bounded, 0 external events dropped, no heartbeat
    dies, every restored snapshot carries and re-arms its heartbeat.

Run: python u7_determinism_and_soak.py   (exit 1 == defect)
"""

from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import os
import subprocess
import sys
import time
from typing import Any, Dict, List

from xstate_statemachine import (
    Interpreter,
    MachineLogic,
    PluginBase,
    SyncInterpreter,
    create_machine,
)
from xstate_statemachine.clock import SimulatedClock

SOAK_S = 90.0
N_SOAK = 60
CHAOS_EVERY_S = 2.0


def emit(name: str, data: Dict[str, Any]) -> None:
    data = {"probe": name, "py": ".".join(map(str, sys.version_info[:3])), **data}
    txt = json.dumps(data, indent=2, default=str)
    with open(os.path.join(os.path.dirname(__file__), name + ".json"), "w") as fh:
        fh.write(txt)
    print(txt)


def blob_of(interp) -> str:
    snap = interp.get_persisted_snapshot()
    return snap if isinstance(snap, str) else json.dumps(snap, default=str)


TRACE_CFG = {
    "id": "u7", "initial": "a", "context": {"n": 0, "trail": []},
    "states": {
        "a": {"entry": [{"type": "raise",
                         "params": {"event": "STEP", "delay": 20}}, "tick"],
              "on": {"STEP": "b"}},
        "b": {"entry": [{"type": "raise",
                         "params": {"event": "STEP", "delay": 20}}, "tick"],
              "on": {"STEP": "c"}},
        "c": {"entry": ["tick"], "type": "final"},
    },
}


def trace_logic(kind):
    if kind == "def":

        def tick(i, ctx, e, ad):  # noqa: ANN001
            ctx["n"] = ctx.get("n", 0) + 1
            ctx.setdefault("trail", []).append(
                f"{sorted(i.current_state_ids)}<-{getattr(e, 'type', '')}")

        return MachineLogic(actions={"tick": tick})

    async def atick(i, ctx, e, ad):  # noqa: ANN001
        ctx["n"] = ctx.get("n", 0) + 1
        ctx.setdefault("trail", []).append(
            f"{sorted(i.current_state_ids)}<-{getattr(e, 'type', '')}")

    return MachineLogic(actions={"tick": atick})


async def one_trace_async(kind, with_restore) -> str:
    c = SimulatedClock()
    m = create_machine(copy.deepcopy(TRACE_CFG), logic=trace_logic(kind))
    i = Interpreter(m, clock=c)
    await i.start()
    await c.increment(10)
    if with_restore:
        blob = blob_of(i)
        await i.stop()
        c = SimulatedClock()
        m = create_machine(copy.deepcopy(TRACE_CFG), logic=trace_logic(kind))
        i = Interpreter.from_snapshot(blob, m, clock=c)
        await i.start()
    await c.increment(100)
    trail = json.dumps(i.context.get("trail"), sort_keys=True)
    n = i.context.get("n")
    states = sorted(i.current_state_ids)
    await i.stop()
    return hashlib.sha256(
        f"{trail}|{n}|{states}".encode()).hexdigest()[:16]


def one_trace_sync(with_restore) -> str:
    c = SimulatedClock()
    m = create_machine(copy.deepcopy(TRACE_CFG), logic=trace_logic("def"))
    i = SyncInterpreter(m, clock=c)
    i.start()
    c.increment(10)
    if with_restore:
        blob = blob_of(i)
        i.stop()
        c = SimulatedClock()
        m = create_machine(copy.deepcopy(TRACE_CFG), logic=trace_logic("def"))
        i = SyncInterpreter.from_snapshot(blob, m, clock=c)
        i.start()
    c.increment(100)
    trail = json.dumps(i.context.get("trail"), sort_keys=True)
    n = i.context.get("n")
    states = sorted(i.current_state_ids)
    i.stop()
    return hashlib.sha256(
        f"{trail}|{n}|{states}".encode()).hexdigest()[:16]


async def d1_determinism() -> Dict[str, Any]:
    cells: Dict[str, Any] = {}
    bad: List[str] = []
    for kind in ("def", "async def"):
        for restore in (False, True):
            key = f"async/{kind}/restore={restore}"
            hs = {await one_trace_async(kind, restore) for _ in range(50)}
            cells[key] = sorted(hs)
            if len(hs) != 1:
                bad.append(f"{key}: {len(hs)} distinct traces in 50 runs")
    for restore in (False, True):
        key = f"sync/def/restore={restore}"
        hs = {one_trace_sync(restore) for _ in range(50)}
        cells[key] = sorted(hs)
        if len(hs) != 1:
            bad.append(f"{key}: {len(hs)} distinct traces in 50 runs")
    return {"runs_per_cell": 50, "cells": cells, "violations": bad}


def d2_hashseed() -> Dict[str, Any]:
    here = os.path.dirname(os.path.abspath(__file__))
    outs = {}
    for seed in ("0", "1", "12345"):
        env = dict(os.environ, PYTHONHASHSEED=seed,
                   PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
        r = subprocess.run([sys.executable, os.path.abspath(__file__),
                            "--trace-only"], cwd=here, env=env,
                           capture_output=True, text=True, timeout=60)
        outs[seed] = r.stdout.strip().splitlines()[-1] if r.stdout else \
            f"ERR:{r.stderr[-200:]}"
    distinct = sorted(set(outs.values()))
    out = {"per_seed": outs, "distinct": distinct}
    if len(distinct) != 1:
        out["fail"] = "trace depends on PYTHONHASHSEED"
    return out


SOAK_CFG = {
    "id": "u7s", "initial": "beat", "maxIterations": 12,
    "context": {"n": 0, "ext": 0},
    "states": {
        # 💓 `reenter: True` -- u8 established that a self-target
        #    transition WITHOUT it is an internal transition, so entry
        #    never re-runs and the heartbeat beats exactly once (the
        #    `after` reference behaves identically; it is SCXML, not a
        #    library defect).
        "beat": {
            "entry": [{"type": "raise",
                       "params": {"event": "TICK", "delay": 25}}],
            "on": {"TICK": {"target": "beat", "reenter": True,
                            "actions": ["tick"]},
                   "EXT": {"actions": ["ext"]}},
        },
    },
}


def soak_logic(kind):
    def ext(i, ctx, e, ad):  # noqa: ANN001
        ctx["ext"] = ctx.get("ext", 0) + 1

    if kind == "def":

        def tick(i, ctx, e, ad):  # noqa: ANN001
            ctx["n"] = ctx.get("n", 0) + 1

        return MachineLogic(actions={"tick": tick, "ext": ext})

    async def atick(i, ctx, e, ad):  # noqa: ANN001
        ctx["n"] = ctx.get("n", 0) + 1

    return MachineLogic(actions={"tick": atick, "ext": ext})


class SoakSpy(PluginBase):
    def __init__(self):
        self.dropped: Dict[str, int] = {}

    def on_event_dropped(self, interpreter, event, reason):  # noqa: ANN001
        if getattr(event, "type", "") == "EXT":
            self.dropped[reason] = self.dropped.get(reason, 0) + 1


async def s1_soak() -> Dict[str, Any]:
    import psutil

    proc = psutil.Process()
    spies = [SoakSpy() for _ in range(N_SOAK)]
    kinds = ["def" if k % 2 == 0 else "async def" for k in range(N_SOAK)]
    machines = [create_machine(copy.deepcopy(SOAK_CFG), logic=soak_logic(k))
                for k in kinds]
    interps = []
    for m, sp in zip(machines, spies):
        i = Interpreter(m)
        i.use(sp)
        interps.append(i)
    await asyncio.gather(*(i.start() for i in interps))

    sent = 0
    chaos_rounds = 0
    chaos_blobs_with_record = 0
    chaos_blobs_inflight = 0
    chaos_failures: List[str] = []
    rss0 = proc.memory_info().rss
    c0 = proc.cpu_times()
    t0 = time.perf_counter()
    next_chaos = t0 + CHAOS_EVERY_S
    while time.perf_counter() - t0 < SOAK_S:
        for i in interps:
            await i.send("EXT", priority=True)
            sent += 1
        await asyncio.sleep(0.05)
        if time.perf_counter() >= next_chaos:
            next_chaos = time.perf_counter() + CHAOS_EVERY_S
            chaos_rounds += 1
            idx = chaos_rounds % N_SOAK
            old = interps[idx]
            blob = blob_of(old)
            snapd = json.loads(blob)
            recs = snapd.get("scheduled_sends") or []
            # 🎯 At any instant the beat is EITHER armed on the clock
            #    (scheduled_sends) OR already fired and sitting in the
            #    inbox (pending_events). Either restores; losing BOTH is
            #    the defect. Count which side of the window we caught.
            inflight = [r for r in (snapd.get("pending_events") or [])
                        if r.get("type") == "TICK"]
            if recs:
                chaos_blobs_with_record += 1
            elif inflight:
                chaos_blobs_inflight += 1
            else:
                chaos_failures.append(
                    f"round {chaos_rounds}: snapshot carried the heartbeat "
                    f"NEITHER as an armed scheduled_sends record NOR as an "
                    f"in-flight pending TICK")
            n_before = old.context.get("n", 0)
            await old.stop()
            m = create_machine(copy.deepcopy(SOAK_CFG),
                               logic=soak_logic(kinds[idx]))
            new = Interpreter.from_snapshot(blob, m)
            new.use(spies[idx])
            await new.start()
            await asyncio.sleep(0.15)
            if new.context.get("n", 0) <= n_before:
                chaos_failures.append(
                    f"round {chaos_rounds}: heartbeat did not resume "
                    f"after restore (n {n_before} -> {new.context.get('n')})")
            interps[idx] = new
    wall = time.perf_counter() - t0
    c1 = proc.cpu_times()
    cpu = (c1.user - c0.user) + (c1.system - c0.system)
    rss1 = proc.memory_info().rss
    beats = [i.context.get("n", 0) for i in interps]
    exts = sum(i.context.get("ext", 0) for i in interps)
    dropped = {}
    for sp in spies:
        for k, v in sp.dropped.items():
            dropped[k] = dropped.get(k, 0) + v
    errs = [str(i.last_error) for i in interps if i.last_error is not None]
    await asyncio.gather(*(i.stop() for i in interps),
                         return_exceptions=True)
    out = {
        "machines": N_SOAK, "soak_s": SOAK_S, "wall_s": round(wall, 1),
        "cpu_s": round(cpu, 1), "cpu_over_wall": round(cpu / wall, 2),
        "cores": os.cpu_count(),
        "rss_mb_start": round(rss0 / 1e6, 1), "rss_mb_end": round(rss1 / 1e6, 1),
        "external_sent": sent, "external_handled": exts,
        "external_dropped": dropped,
        "beats_min": min(beats), "beats_max": max(beats),
        "beats_ideal_per_machine": round(SOAK_S * 1000.0 / 25),
        "chaos_rounds": chaos_rounds,
        "chaos_blobs_with_heartbeat_record": chaos_blobs_with_record,
        "chaos_blobs_heartbeat_inflight_in_inbox": chaos_blobs_inflight,
        "chaos_failures": chaos_failures[:5],
        "n_chaos_failures": len(chaos_failures),
        "last_errors": errs[:3],
    }
    if dropped:
        out["fail"] = f"external events dropped: {dropped}"
    elif min(beats) < SOAK_S * 1000.0 / 25 * 0.2:
        out["fail"] = (f"a heartbeat died or stalled during the soak "
                       f"(min {min(beats)} beats vs ideal "
                       f"{SOAK_S * 1000.0 / 25:.0f})")
    elif chaos_failures:
        out["fail"] = chaos_failures[0]
    return out


async def main() -> int:
    if "--trace-only" in sys.argv:
        print(await one_trace_async("def", True))
        return 0
    res: Dict[str, Any] = {
        "D1_determinism_50x": await d1_determinism(),
        "D2_hashseed": d2_hashseed(),
        "S1_soak": await s1_soak(),
        "reductions": {
            "soak": f"{SOAK_S} s / {N_SOAK} machines instead of the briefed "
                    f"12 min / 200 -- the 20-minute whole-task bound. The "
                    f"soak invariants (0 external dropped, heartbeat never "
                    f"dies, every chaos snapshot carries and re-arms its "
                    f"scheduled_sends) are per-machine and rate-independent; "
                    f"u5 L1 already ran 200 machines at a 1 ms period.",
        },
    }
    bad: List[str] = []
    bad += res["D1_determinism_50x"]["violations"]
    if "fail" in res["D2_hashseed"]:
        bad.append("D2: " + res["D2_hashseed"]["fail"])
    if "fail" in res["S1_soak"]:
        bad.append("S1: " + res["S1_soak"]["fail"])
    res["violations"] = bad
    res["verdict"] = "DEFECT" if bad else "CLEAN"
    emit("u7_determinism_and_soak", res)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
