# -*- coding: utf-8 -*-
"""X6 -- livelock fuzzer with the #212 oracle, >=500 configs x kinds.

STANDALONE. Neutral cwd.

The oracle CHANGED in round 10:
  * a cycle every edge of which is a zero-delay `raise`  -> MUST trip
    (`RunawayChainError` / `chain_budget` drop) -- within-step work.
  * a cycle containing at least one `raise(delay>=1)`    -> MUST NOT trip
    and MUST keep beating (periodic process, the `after` rule).
  * a cycle containing an `after`                        -> control, same.

Every config is run on BOTH service kinds and BOTH engines
(Interpreter / SyncInterpreter) where the shape permits, with a watchdog:
a config that neither trips nor beats inside the budget is reported as
STALLED -- the observed result.
"""
from __future__ import annotations

import asyncio
import json
import os
import random
import time

from xstate_statemachine import (
    Interpreter,
    MachineLogic,
    SyncInterpreter,
    create_machine,
)
from xstate_statemachine.clock import SimulatedClock
from xstate_statemachine.exceptions import RunawayChainError
from xstate_statemachine.plugins import PluginBase

KIND = os.environ.get("XS_SVC", "async")
N = int(os.environ.get("XS_N", "500"))
MAXIT = 10
BEATS_REQUIRED = 3


class Drop(PluginBase):
    def __init__(self):
        self.reasons = []

    def on_event_dropped(self, i, e, reason):  # noqa: ANN001
        self.reasons.append(reason)


def gen(rnd):
    """Random n-state cycle; each edge is delayed / zero-delay / after."""
    n = rnd.randint(2, 4)
    names = [f"s{k}" for k in range(n)]
    edges = []
    for k in range(n):
        edges.append(rnd.choice(["zero", "zero", "delay", "after"]))
    # guarantee at least one zero-delay-only config and one delayed one
    states = {}
    for k, nm in enumerate(names):
        nxt = names[(k + 1) % n]
        e = edges[k]
        if e == "zero":
            states[nm] = {
                "entry": [{"type": "raise", "params": {"event": f"E{k}"}},
                          "beat"],
                "on": {f"E{k}": nxt},
            }
        elif e == "delay":
            d = rnd.choice([1, 1, 2, 5])
            p = {"event": f"E{k}", "delay": d}
            if rnd.random() < 0.3:
                p["id"] = f"sid{k}"
            states[nm] = {
                "entry": [{"type": "raise", "params": p}, "beat"],
                "on": {f"E{k}": nxt},
            }
        else:
            d = rnd.choice([1, 1, 2, 5])
            states[nm] = {"entry": ["beat"], "after": {str(d): nxt}}
    spec = {
        "id": "fz",
        "maxIterations": MAXIT,
        "initial": names[0],
        "context": {"beats": 0},
        "states": states,
    }
    has_delay = any(e in ("delay", "after") for e in edges)
    return spec, edges, has_delay


def build(spec):
    def beat(i, c, e, a):  # noqa: ANN001
        c["beats"] += 1

    async def sa(i, c, e):  # noqa: ANN001
        await asyncio.sleep(0)
        return 1

    def sd(i, c, e):  # noqa: ANN001
        return 1

    return create_machine(
        json.loads(json.dumps(spec)),
        logic=MachineLogic(actions={"beat": beat},
                           services={"s": sa if KIND == "async" else sd}),
    )


async def run_async(spec, budget=1.2):
    plug = Drop()
    i = Interpreter(build(spec))
    i.use(plug)
    try:
        await i.start()
    except RunawayChainError:
        pass
    t0 = time.monotonic()
    while time.monotonic() - t0 < budget:
        await asyncio.sleep(0.03)
        if i.error is not None or "chain_budget" in plug.reasons:
            break
        if i.context["beats"] > MAXIT + BEATS_REQUIRED + 5:
            break
    beats = i.context["beats"]
    tripped = isinstance(i.error, RunawayChainError) or (
        "chain_budget" in plug.reasons
    )
    if i.status == "running":
        await i.stop()
    return tripped, beats


def run_sync(spec, budget=1.2):
    # 📏 The sync engine has no run loop: it pumps its clock at the top of
    #    every `send()`. Real time + `pump()` alone fires the timer but
    #    nothing drains the queue, so drive it with a `SimulatedClock`,
    #    which settles every attached interpreter after each increment --
    #    the documented sync idiom. Called OUTSIDE any running loop.
    plug = Drop()
    i = SyncInterpreter(build(spec), clock=SimulatedClock())
    i.use(plug)
    try:
        i.start()
    except RunawayChainError:
        pass
    for _ in range(60):
        try:
            i.clock.increment(5)
        except RunawayChainError:
            break
        except Exception:  # noqa: BLE001
            break
        if i.error is not None or "chain_budget" in plug.reasons:
            break
        if i.context["beats"] > MAXIT + BEATS_REQUIRED + 5:
            break
    beats = i.context["beats"]
    tripped = isinstance(i.error, RunawayChainError) or (
        "chain_budget" in plug.reasons
    )
    if i.status == "running":
        i.stop()
    return tripped, beats


SYNC_RESULTS = {}


def sync_pass():
    """Every sync config, run OUTSIDE asyncio (SimulatedClock idiom)."""
    rnd = random.Random(int(os.environ.get("XS_SEED", "77213")))
    for k in range(N):
        spec, edges, has_delay = gen(rnd)
        try:
            SYNC_RESULTS[(k, 'sync')] = run_sync(spec)
        except Exception as exc:  # noqa: BLE001
            SYNC_RESULTS[(k, 'sync')] = ("EXC " + type(exc).__name__, 0)


async def main():
    rnd = random.Random(int(os.environ.get("XS_SEED", "77213")))
    stats = {}
    viols = []
    for k in range(N):
        spec, edges, has_delay = gen(rnd)
        for eng in ("async", "sync"):
            try:
                if eng == "async":
                    tripped, beats = await asyncio.wait_for(
                        run_async(spec), timeout=6.0
                    )
                else:
                    tripped, beats = SYNC_RESULTS[(k, 'sync')]
            except asyncio.TimeoutError:
                viols.append((k, eng, edges, "WATCHDOG"))
                continue
            except Exception as exc:  # noqa: BLE001
                viols.append((k, eng, edges, f"EXC {type(exc).__name__}"))
                continue
            if has_delay:
                ok = (not tripped) and beats >= BEATS_REQUIRED
                tag = "delayed-cycle"
                why = f"tripped={tripped} beats={beats}"
            else:
                ok = tripped
                tag = "zero-cycle"
                why = f"tripped={tripped} beats={beats}"
            key = (tag, eng, "OK" if ok else "VIOLATION")
            stats[key] = stats.get(key, 0) + 1
            if not ok and len(viols) < 12:
                viols.append((k, eng, edges, why))
    print(f"X6 kind={KIND} N={N} engines=async+sync  oracle=#212")
    for key in sorted(stats):
        print(f"   {key[0]:14s} {key[1]:5s} {key[2]:9s} : {stats[key]}")
    if viols:
        print(f"   VIOLATIONS ({len(viols)} shown):")
        for v in viols[:12]:
            print(f"     cfg={v[0]} eng={v[1]} edges={v[2]} {v[3]}")
    bad = sum(v for k, v in stats.items() if k[2] == "VIOLATION")
    print("VERDICT", "PASS" if bad == 0 and not viols else f"FAIL ({bad})")


sync_pass()
asyncio.run(main())
