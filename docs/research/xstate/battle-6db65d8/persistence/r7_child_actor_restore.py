# -*- coding: utf-8 -*-
"""R7 -- MINIMAL: an invoked CHILD MACHINE is persisted but silently dropped
on restore; the blob does not round-trip.

`get_persisted_snapshot()`'s own docstring is explicit about why the actor
hierarchy is recorded:

    "child actors were previously omitted entirely. A parent with live
     children serialised to just {status, context, state_ids} and restoring
     produced an actor with zero children -- silent, unrecoverable data loss
     for anyone persisting a workflow."  (base_interpreter.py:1368)

The WRITE side does record them. The READ side does not rebuild them, with or
without `restart_services=True`, so the loss the docstring names still
happens -- one restore later, in a place where a round-trip check is the
natural way to detect it and *fails*.

Measured: blob1 (live) vs blob2 (after one restore), on both service kinds,
and again after `start()` on the restored interpreter.
"""
from __future__ import annotations

import asyncio
import json

from xstate_statemachine import Interpreter, MachineLogic, create_machine
from xstate_statemachine.clock import SimulatedClock


def canon(b):
    b = dict(b)
    b.pop("taken_at", None)
    return json.dumps(b, sort_keys=True, default=str)


def build(kind: str):
    def ke(i, c, e, a):  # noqa: ANN001
        c["v"] = c.get("v", 0) + 1

    async def ke_a(i, c, e, a):  # noqa: ANN001
        await asyncio.sleep(0)
        c["v"] = c.get("v", 0) + 1

    kid = create_machine(
        {"id": "kid", "initial": "s",
         "states": {"s": {"entry": ["ke"], "on": {"BUMP": "s2"}}, "s2": {}}},
        logic=MachineLogic(actions={"ke": ke if kind == "def" else ke_a}),
    )
    par = {
        "id": "par",
        "initial": "up",
        "states": {"up": {"invoke": [{"id": "kid", "src": "kid"}]}},
    }
    return create_machine(par, logic=MachineLogic(services={"kid": kid}))


async def one(kind: str, restart: bool) -> None:
    m = build(kind)
    i = Interpreter(m, clock=SimulatedClock())
    await i.start(children_timeout=1.0)
    await asyncio.sleep(0.05)
    # drive the child so it holds state worth persisting
    for a in list(i._actors.values()):
        await a.send("BUMP")
    await asyncio.sleep(0.05)
    blob1 = i.get_persisted_snapshot()
    live_actors = sorted((blob1.get("actors") or {}).keys())
    child_state = [
        (k, v.get("snapshot", {}).get("state_ids"),
         v.get("snapshot", {}).get("context"))
        for k, v in (blob1.get("actors") or {}).items()
        if isinstance(v, dict)
    ]
    await i.stop()

    r = Interpreter.from_snapshot(
        json.dumps(blob1, default=str), build(kind),
        restart_services=restart,
    )
    blob2 = r.get_persisted_snapshot()
    pre = sorted((blob2.get("actors") or {}).keys())
    await r.start(children_timeout=1.0)
    await asyncio.sleep(0.1)
    blob3 = r.get_persisted_snapshot()
    post = sorted((blob3.get("actors") or {}).keys())
    post_state = [
        (k, v.get("snapshot", {}).get("state_ids"),
         v.get("snapshot", {}).get("context"))
        for k, v in (blob3.get("actors") or {}).items()
        if isinstance(v, dict)
    ]
    print("  [%-5s restart_services=%-5s]" % (kind, restart))
    print("      persisted actors      : %s %s" % (live_actors, child_state))
    print("      after from_snapshot   : %s   round-trip equal=%s"
          % (pre, canon(blob1) == canon(blob2)))
    print("      after start()         : %s %s" % (post, post_state))
    await r.stop()


async def main() -> None:
    print("=== invoked child machine across a restore")
    for kind in ("def", "async"):
        for restart in (False, True):
            await one(kind, restart)


asyncio.run(main())


# ---- exact field-level diff of the actors record across one restore ----
async def diff_actors(kind: str = "def") -> None:
    m = build(kind)
    i = Interpreter(m, clock=SimulatedClock())
    await i.start(children_timeout=1.0)
    await asyncio.sleep(0.05)
    b1 = i.get_persisted_snapshot()
    await i.stop()
    r = Interpreter.from_snapshot(json.dumps(b1, default=str), build(kind))
    b2 = r.get_persisted_snapshot()
    a1 = (b1.get("actors") or {}).get("par:kid", {})
    a2 = (b2.get("actors") or {}).get("par:kid", {})
    print("\n=== field diff of actors['par:kid'] across one restore [%s]" % kind)
    for k in sorted(set(a1) | set(a2)):
        v1, v2 = a1.get(k, "<absent>"), a2.get(k, "<absent>")
        if k == "snapshot" and isinstance(v1, dict) and isinstance(v2, dict):
            for kk in sorted(set(v1) | set(v2)):
                s1, s2 = v1.get(kk, "<absent>"), v2.get(kk, "<absent>")
                if kk == "taken_at":
                    continue
                flag = "" if s1 == s2 else "   <-- DIFFERS"
                print("   snapshot.%-16s %r -> %r%s" % (kk, s1, s2, flag))
            continue
        flag = "" if v1 == v2 else "   <-- DIFFERS"
        print("   %-25s %r -> %r%s" % (k, v1, v2, flag))
    # and the top-level keys
    print("   top-level differing keys:",
          sorted(k for k in set(b1) | set(b2)
                 if k != "taken_at" and b1.get(k) != b2.get(k)))
    await r.stop()


asyncio.run(diff_actors("def"))
asyncio.run(diff_actors("async"))
