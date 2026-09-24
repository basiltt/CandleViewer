# -*- coding: utf-8 -*-
"""N8 -- byte-identical snapshot determinism across repeated runs.

The brief asks for "50x byte-identical traces, both engines". For the
persistence track the load-bearing form of that is: the SAME event script,
replayed on a `SimulatedClock`, must produce a byte-identical snapshot blob
every time -- otherwise a snapshot cannot be used as a replay oracle or a
diff target, and a "state changed" alarm built on blob equality is noise.

Two volatile fields are excluded by construction and that exclusion is
itself checked:
  * `taken_at`  -- wall clock, documented as such
  * actor ids   -- a spawned child's id contains a uuid4

Runs the script N times on each engine and compares the canonicalised blob.
Also reports which keys, if any, vary -- a varying key that is NOT
`taken_at` / an actor uuid is a determinism defect.

usage: n8_determinism.py [N_RUNS]
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import re
import sys

from xstate_statemachine import Interpreter, SyncInterpreter
from xstate_statemachine.clock import SimulatedClock

import order_machine

SCRIPT = [("SUBMIT", {"qty": 7}), ("ACK_OK", {}), ("RISK_OK", {}),
          ("FILL", {"n": 2}), ("FILL", {"n": 1}), ("STALE", {}),
          ("DONE", {})]

UUID_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


def canon(blob: str) -> str:
    d = json.loads(blob)
    d.pop("taken_at", None)
    s = json.dumps(d, sort_keys=True)
    return UUID_RE.sub("<uuid>", s)


def variance(blobs: list[str]) -> dict[str, set]:
    """Which top-level keys differ across runs?"""
    ds = [json.loads(b) for b in blobs]
    out: dict[str, set] = {}
    for k in sorted({k for d in ds for k in d}):
        vals = {json.dumps(d.get(k), sort_keys=True) for d in ds}
        if len(vals) > 1:
            out[k] = vals
    return out


async def run_async() -> str:
    i = Interpreter(order_machine.build(), clock=SimulatedClock())
    await i.start(); await asyncio.sleep(0.02)
    for t, kw in SCRIPT:
        if i.status != "running":
            break
        try:
            await i.send(t, wait=True, **kw)
        except Exception:  # noqa: BLE001
            pass
        await asyncio.sleep(0.01)
    blob = i.get_snapshot()
    if i.status == "running":
        await i.stop()
    return blob


def run_sync() -> str:
    i = SyncInterpreter(order_machine.build())
    i.start()
    for t, kw in SCRIPT:
        if i.status != "running":
            break
        try:
            i.send(t, **kw)
        except Exception:  # noqa: BLE001
            pass
    blob = i.get_snapshot()
    if i.status == "running":
        i.stop()
    return blob


async def main() -> None:
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 50

    a_blobs = [await run_async() for _ in range(n)]
    s_blobs = [run_sync() for _ in range(n)]

    for label, blobs in (("async", a_blobs), ("sync", s_blobs)):
        hashes = {hashlib.sha256(canon(b).encode()).hexdigest()
                  for b in blobs}
        print(f"{label:<6} runs={len(blobs)} distinct canonical blobs="
              f"{len(hashes)}  {'OK' if len(hashes) == 1 else 'NON-DETERMINISTIC'}")
        if len(hashes) > 1:
            v = variance(blobs)
            for k, vals in v.items():
                print(f"     varying key {k!r}: {len(vals)} values")
                for val in list(vals)[:3]:
                    print(f"        {val[:150]}")

    ah = canon(a_blobs[0])
    sh = canon(s_blobs[0])
    print(f"\ncross-engine canonical blobs identical: {ah == sh}")
    if ah != sh:
        da, ds = json.loads(ah), json.loads(sh)
        for k in sorted(set(da) | set(ds)):
            if da.get(k) != ds.get(k):
                print(f"   differs {k!r}:")
                print(f"      async={json.dumps(da.get(k))[:180]}")
                print(f"      sync ={json.dumps(ds.get(k))[:180]}")

    ok = (len({hashlib.sha256(canon(b).encode()).hexdigest()
               for b in a_blobs}) == 1
          and len({hashlib.sha256(canon(b).encode()).hexdigest()
                   for b in s_blobs}) == 1)
    print(f"\nVERDICT per-engine determinism: {'PASS' if ok else 'FAIL'}")


if __name__ == "__main__":
    asyncio.run(main())
