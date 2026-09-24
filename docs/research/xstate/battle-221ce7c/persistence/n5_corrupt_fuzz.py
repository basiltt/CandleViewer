# -*- coding: utf-8 -*-
"""N5 -- SnapshotCorruptError coverage over a mutation fuzz (#110, #131).

D-persistence-4 on 5e07ba8: `from_snapshot()` silently accepted three
classes of malformed blob (`status: "banana"`, `context: 42`, a pending
record with an unknown `kind`) and leaked a raw builtin (`KeyError`,
`TypeError`, `AttributeError`) for seven more -- defeating
`except XStateMachineError`, the library's own documented catch-all.

#110 added `persistence.check_shape()`. This fuzzes it: N random structural
mutations of a real snapshot, each restored, and the outcome bucketed as

  TYPED    -- an XStateMachineError subclass (the contract)
  RAW      -- any other exception (contract violation)
  ACCEPTED -- restored without complaint; then probed for whether the
              resulting interpreter is actually sane (status in the four
              documented values, context a dict, sends still work)

A mutation that changes nothing semantically is allowed to be ACCEPTED, so
ACCEPTED is only reported as a defect when the restored object is unusable
or carries a value the library says it cannot carry.

usage: n5_corrupt_fuzz.py [N_MUTATIONS]
"""
from __future__ import annotations

import asyncio
import json
import random
import sys

from xstate_statemachine import Interpreter
from xstate_statemachine.clock import SimulatedClock
from xstate_statemachine.exceptions import XStateMachineError

import order_machine

VALID_STATUS = {"running", "done", "error", "stopped", "uninitialized"}

GARBAGE = [None, 42, -1, 0, 3.5, "", "banana", True, [], {}, [1, 2],
           {"a": 1}, "null", 1e308, "\x00", "🙂", "wat"]


def mutate(d: dict, rng: random.Random) -> str:
    """Apply one random structural mutation in place; return a label."""
    op = rng.choice(["set", "del", "settype", "nested", "listelem"])
    keys = sorted(d.keys())
    k = rng.choice(keys)
    if op == "del":
        d.pop(k, None)
        return f"del {k}"
    if op == "set":
        v = rng.choice(GARBAGE)
        d[k] = v
        return f"{k}={v!r}"
    if op == "settype":
        d[k] = rng.choice([[], {}, "s", 7, None])
        return f"{k}:type->{type(d[k]).__name__}"
    if op == "nested":
        for key in ("pending_events", "deferred"):
            if isinstance(d.get(key), list) and d[key]:
                rec = d[key][rng.randrange(len(d[key]))]
                if isinstance(rec, dict) and rec:
                    rk = rng.choice(sorted(rec.keys()))
                    if rng.random() < 0.5:
                        rec.pop(rk, None)
                        return f"{key}[].del {rk}"
                    rec[rk] = rng.choice(GARBAGE)
                    return f"{key}[].{rk}={rec[rk]!r}"
        d[k] = rng.choice(GARBAGE)
        return f"{k}={d[k]!r} (fallback)"
    # listelem
    for key in ("state_ids", "configuration"):
        if isinstance(d.get(key), list) and d[key]:
            idx = rng.randrange(len(d[key]))
            if rng.random() < 0.5:
                d[key][idx] = rng.choice(GARBAGE)
                return f"{key}[{idx}]={d[key][idx]!r}"
            d[key].pop(idx)
            return f"{key}[{idx}] removed"
    d[k] = None
    return f"{k}=None (fallback)"


async def base_blob() -> str:
    i = Interpreter(order_machine.build(), clock=SimulatedClock())
    await i.start()
    await asyncio.sleep(0.02)
    await i.send("SUBMIT", qty=3)
    await asyncio.sleep(0.05)
    await i.send("FILL", n=2)
    await asyncio.sleep(0.05)
    blob = i.get_snapshot()
    await i.stop()
    return blob


async def probe(interp) -> str | None:
    """Return a defect description if the restored interpreter is unsound."""
    if interp.status not in VALID_STATUS:
        return f"status={interp.status!r} not a documented value"
    if not isinstance(interp.context, dict):
        return f"context is {type(interp.context).__name__}, not a dict"
    try:
        await interp.start()
        await asyncio.sleep(0.02)
        await interp.send("FILL", n=1)
        await asyncio.sleep(0.02)
    except Exception as exc:  # noqa: BLE001
        return f"restored but unusable: {type(exc).__name__}: {exc}"
    finally:
        try:
            if interp.status == "running":
                await interp.stop()
        except Exception:  # noqa: BLE001
            pass
    return None


async def main() -> None:
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 5000
    blob = await base_blob()
    rng = random.Random(97531)

    typed: dict[str, int] = {}
    raw: dict[str, list[str]] = {}
    accepted = 0
    unsound: list[str] = []

    for _ in range(n):
        d = json.loads(blob)
        label = mutate(d, rng)
        if rng.random() < 0.25:          # sometimes stack two mutations
            label += " ; " + mutate(d, rng)
        s = json.dumps(d)
        try:
            i2 = Interpreter.from_snapshot(
                s, order_machine.build(), clock=SimulatedClock(),
                verify_machine_hash=False)
        except XStateMachineError as exc:
            typed[type(exc).__name__] = typed.get(type(exc).__name__, 0) + 1
            continue
        except Exception as exc:  # noqa: BLE001
            raw.setdefault(type(exc).__name__, []).append(
                f"{label}  ->  {exc}")
            continue
        accepted += 1
        bad = await probe(i2)
        if bad:
            unsound.append(f"{label}  ->  {bad}")

    print(f"mutations           : {n}")
    print(f"TYPED (XStateMachineError) : {sum(typed.values())}")
    for k, v in sorted(typed.items(), key=lambda x: -x[1]):
        print(f"     {k:<26}: {v}")
    print(f"RAW builtin leaks          : {sum(len(v) for v in raw.values())}"
          "   <- must be 0")
    for k, v in sorted(raw.items(), key=lambda x: -len(x[1])):
        print(f"     {k:<26}: {len(v)}")
        for line in v[:3]:
            print(f"         e.g. {line[:140]}")
    print(f"ACCEPTED                   : {accepted}")
    print(f"  of which UNSOUND         : {len(unsound)}   <- must be 0")
    seen = set()
    for line in unsound:
        key = line.split("->")[-1][:60]
        if key in seen:
            continue
        seen.add(key)
        print(f"     {line[:160]}")
    ok = not raw and not unsound
    print(f"\nVERDICT: {'PASS' if ok else 'FAIL'}")


if __name__ == "__main__":
    asyncio.run(main())
