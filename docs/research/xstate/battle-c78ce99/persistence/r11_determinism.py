# -*- coding: utf-8 -*-
"""R11 -- determinism of the persisted blob: 50 identical runs per cell,
both engines where available, both service kinds, plus a PYTHONHASHSEED sweep.

A snapshot that differs run-to-run for the same input cannot be compared,
deduplicated or used as a checkpoint identity. Two properties:

  1. WITHIN a cell (engine x service kind), 50 runs of the same event
     sequence must produce exactly ONE distinct canonical blob.
  2. ACROSS service kinds on the same engine, the blob must be the same --
     #179's whole point is that `def` and `async def` completions now travel
     the same charged lane and trip at the same lap count, so the persisted
     result should no longer depend on which style the service was written in.

The `machine_hash` is also checked against a `PYTHONHASHSEED` sweep in a
subprocess: a structure hash derived from an unordered iteration would make
every blob written by one process unreadable by another.
"""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys

from xstate_statemachine import Interpreter, MachineLogic, SyncInterpreter, create_machine
from xstate_statemachine.clock import SimulatedClock

SPEC = {
    "id": "det",
    "type": "parallel",
    "states": {
        "r0": {
            "initial": "a",
            "states": {
                "a": {"entry": ["bump"],
                      "invoke": [{"id": "k", "src": "svc",
                                  "onDone": {"target": "b", "actions": ["bump"]}}],
                      "on": {"GO": "b"}},
                "b": {"entry": ["bump"], "on": {"BACK": "a"}},
            },
        },
        "r1": {
            "initial": "x",
            "states": {"x": {"on": {"GO": "y"}}, "y": {"on": {"BACK": "x"}}},
        },
    },
}

SEQ = ["GO", "BACK", "GO", "GO", "BACK"]


def _strip(o):
    if isinstance(o, dict):
        return {k: _strip(v) for k, v in o.items() if k != "taken_at"}
    if isinstance(o, list):
        return [_strip(x) for x in o]
    return o


def canon(b) -> str:
    return json.dumps(_strip(b), sort_keys=True, default=str)


def build(kind: str):
    def bump(i, c, e, a):  # noqa: ANN001
        c["n"] = c.get("n", 0) + 1

    def svc_def(i, c, e):  # noqa: ANN001
        return {"ok": 1}

    async def svc_async(i, c, e):  # noqa: ANN001
        await asyncio.sleep(0)
        return {"ok": 1}

    return create_machine(
        json.loads(json.dumps(SPEC)),
        logic=MachineLogic(
            actions={"bump": bump},
            services={"svc": svc_def if kind == "def" else svc_async},
        ),
    )


async def run_async(kind: str) -> str:
    i = Interpreter(build(kind), clock=SimulatedClock())
    await i.start(children_timeout=1.0)
    await asyncio.sleep(0.02)
    for ev in SEQ:
        await i.send(ev)
        await asyncio.sleep(0.01)
    b = i.get_persisted_snapshot()
    await i.stop()
    return canon(b)


def run_sync(kind: str) -> str:
    i = SyncInterpreter(build(kind))
    i.start()
    for ev in SEQ:
        i.send(ev)
    b = i.get_persisted_snapshot()
    i.stop()
    return canon(b)


async def main() -> None:
    if os.environ.get("R11_HASH_ONLY"):
        print(build("def").structure_hash)
        return

    N = 50
    print("=== 1. within-cell determinism: %d identical runs per cell" % N)
    cells: dict[tuple[str, str], set[str]] = {}
    SKIP = {("sync", "async")}   # SyncInterpreter refuses an async service
                                 # (NotSupportedError, documented) -- not a
                                 # determinism result, so it is excluded
                                 # rather than counted as a failure.
    for engine in ("async", "sync"):
        for kind in ("def", "async"):
            if (engine, kind) in SKIP:
                print("  %-6s engine / %-5s service : SKIPPED "
                      "(NotSupportedError: async service on the sync engine)"
                      % (engine, kind))
                continue
            seen = set()
            for _ in range(N):
                seen.add(await run_async(kind) if engine == "async"
                         else run_sync(kind))
            cells[(engine, kind)] = seen
            print("  %-6s engine / %-5s service : %d distinct blob(s)  %s"
                  % (engine, kind, len(seen),
                     "OK" if len(seen) == 1 else "<-- NON-DETERMINISTIC"))

    print("\n=== 2. service-kind parity on the same engine (#179)")
    bad = [k for k, v in cells.items() if len(v) != 1]
    for engine in ("async",):
        a = next(iter(cells[(engine, "def")]))
        b = next(iter(cells[(engine, "async")]))
        same = a == b
        print("  %-6s engine: def-blob == async-blob ? %s" % (engine, same))
        if not same:
            d = json.loads(a), json.loads(b)
            diff = sorted(k for k in set(d[0]) | set(d[1])
                          if d[0].get(k) != d[1].get(k))
            print("      differing keys: %s" % diff)
            for k in diff:
                print("        %-16s def=%r" % (k, d[0].get(k)))
                print("        %-16s asy=%r" % ("", d[1].get(k)))
            bad.append((engine, "kind-parity"))

    print("\n=== 3. engine parity")
    sa = next(iter(cells[("async", "async")]))
    ss = next(iter(cells[("sync", "def")]))
    print("  async-engine blob == sync-engine blob ? %s" % (sa == ss))

    print("\n=== 4. PYTHONHASHSEED sweep on machine_hash")
    env = dict(os.environ, R11_HASH_ONLY="1")
    hashes = {}
    for seed in ("0", "1", "12345", "random"):
        env["PYTHONHASHSEED"] = seed
        out = subprocess.run([sys.executable, __file__], env=env,
                             capture_output=True, text=True).stdout.strip()
        hashes[seed] = out
        print("  PYTHONHASHSEED=%-8s machine_hash=%s" % (seed, out))
    if len(set(hashes.values())) != 1:
        bad.append(("hashseed", sorted(set(hashes.values()))))

    print("\nnon-deterministic cells:", bad if bad else "none")
    print("VERDICT:", "FAIL" if bad else "PASS")


asyncio.run(main())
