# -*- coding: utf-8 -*-
"""Q3 -- restore+resume TRACE parity, and the PR #165/#176 shared-sentinel
aliasing check.

A. Trace parity: for every crash point k in a 10-event sequence, the action
   trace of (run 0..k, snapshot, restore, run k+1..n) must equal the plain
   run's trace, on BOTH engines, with `restart_services`/`restart_timers`
   left at their defaults for a machine with no services/timers (so any
   divergence is a persistence defect, not the documented timer default).

B. Sentinel aliasing: PRs #165/#176 introduced SHARED init/exit sentinel
   objects and `__slots__`. Two independently built machines are started,
   driven and snapshotted; a shared mutable sentinel would let one machine's
   snapshot see the other's. Checks: distinct sentinel identity is fine,
   but the observable snapshots must be independent, and mutating one
   interpreter must not change the other's blob.
"""
from __future__ import annotations

import asyncio
import json

from xstate_statemachine import (
    Interpreter,
    MachineLogic,
    SyncInterpreter,
    create_machine,
)
from xstate_statemachine.plugins import PluginBase

CFG = {
    "id": "tp",
    "initial": "a",
    "context": {"log": [], "n": 0},
    "states": {
        "a": {"entry": ["en_a"], "exit": ["ex_a"], "on": {"GO": "b"}},
        "b": {
            "entry": ["en_b"],
            "exit": ["ex_b"],
            "on": {"GO": "c", "BACK": "a"},
        },
        "c": {"entry": ["en_c"], "on": {"BACK": "b"}},
    },
}
SEQ = ["GO", "GO", "BACK", "BACK", "GO", "BACK", "GO", "GO", "BACK", "GO"]


def build():
    def mk(nm):
        def _a(i, ctx, ev, action_def=None):  # noqa: ANN001
            ctx["n"] = ctx.get("n", 0) + 1
            ctx.setdefault("log", []).append(nm)

        return _a

    names = ["en_a", "ex_a", "en_b", "ex_b", "en_c"]
    return create_machine(
        json.loads(json.dumps(CFG)),
        logic=MachineLogic(actions={n: mk(n) for n in names}),
    )


class T(PluginBase):
    def __init__(self):
        self.acts = []

    def on_action_execute(self, i, a):  # noqa: ANN001
        self.acts.append(a.type)


async def async_plain():
    p = T()
    i = Interpreter(build())
    i.use(p)
    await i.start()
    for e in SEQ:
        await i.send(e, wait=True)
    r = (sorted(n.id for n in i._active_state_nodes), dict(i.context), p.acts)
    await i.stop()
    return r


async def async_interrupted(k):
    p = T()
    i = Interpreter(build())
    i.use(p)
    await i.start()
    for e in SEQ[:k]:
        await i.send(e, wait=True)
    blob = i.get_persisted_snapshot()
    await i.stop()
    p2 = T()
    j = Interpreter.from_snapshot(json.dumps(blob), build())
    j.use(p2)
    await j.start()
    for e in SEQ[k:]:
        await j.send(e, wait=True)
    r = (
        sorted(n.id for n in j._active_state_nodes),
        dict(j.context),
        p.acts + p2.acts,
    )
    await j.stop()
    return r


def sync_plain():
    p = T()
    i = SyncInterpreter(build())
    i.use(p)
    i.start()
    for e in SEQ:
        i.send(e)
    r = (sorted(n.id for n in i._active_state_nodes), dict(i.context), p.acts)
    i.stop()
    return r


def sync_interrupted(k):
    p = T()
    i = SyncInterpreter(build())
    i.use(p)
    i.start()
    for e in SEQ[:k]:
        i.send(e)
    blob = i.get_persisted_snapshot()
    i.stop()
    p2 = T()
    j = SyncInterpreter.from_snapshot(json.dumps(blob), build())
    j.use(p2)
    j.start()
    for e in SEQ[k:]:
        j.send(e)
    r = (
        sorted(n.id for n in j._active_state_nodes),
        dict(j.context),
        p.acts + p2.acts,
    )
    j.stop()
    return r


async def part_b():
    """Two machines, shared init/exit sentinels (PR #165/#176) -- cross-talk?"""
    from xstate_statemachine import events as ev_mod

    names = [n for n in dir(ev_mod) if "SENTINEL" in n.upper()]
    print(f"  sentinel-looking names in events: {names}")

    i1 = Interpreter(build())
    i2 = Interpreter(build())
    await i1.start()
    await i2.start()
    await i1.send("GO", wait=True)
    await i1.send("GO", wait=True)  # i1 -> c, i2 stays at a
    b1 = i1.get_persisted_snapshot()
    b2 = i2.get_persisted_snapshot()
    ok_states = b1["state_ids"] == ["tp.c"] and b2["state_ids"] == ["tp.a"]
    ok_ctx = b1["context"]["n"] != b2["context"]["n"]
    # mutate i2 and re-read i1's blob: must be unchanged
    await i2.send("GO", wait=True)
    b1b = i1.get_persisted_snapshot()
    b1.pop("taken_at", None)
    b1b.pop("taken_at", None)
    ok_iso = b1 == b1b
    # context object identity must not be shared
    ok_ident = i1.context is not i2.context and (
        i1.context.get("log") is not i2.context.get("log")
    )
    await i1.stop()
    await i2.stop()
    print(f"  distinct state_ids          : {ok_states} "
          f"({b1['state_ids']} vs {b2['state_ids']})")
    print(f"  distinct context counters   : {ok_ctx}")
    print(f"  i1 blob unaffected by i2    : {ok_iso}")
    print(f"  context objects not aliased : {ok_ident}")
    return ok_states and ok_ctx and ok_iso and ok_ident


async def main():
    print("=== A. restore+resume trace parity, both engines")
    ap = await async_plain()
    sp = sync_plain()
    print(f"  async plain: states={ap[0]} n={ap[1]['n']} acts={len(ap[2])}")
    print(f"  sync  plain: states={sp[0]} n={sp[1]['n']} acts={len(sp[2])}")
    engine_parity = ap == sp
    print(f"  engine parity (plain)  : {engine_parity}")

    bad = []
    for k in range(1, len(SEQ)):
        ai = await async_interrupted(k)
        si = sync_interrupted(k)
        if ai != ap:
            bad.append(f"async k={k}: states/ctx/trace differ from plain")
        if si != sp:
            bad.append(f"sync  k={k}: states/ctx/trace differ from plain")
        if ai != si:
            bad.append(f"k={k}: async vs sync resumed result differs")
    print(f"  crash points tested    : {len(SEQ) - 1} x 2 engines")
    for b in bad[:10]:
        print("   DIVERGENCE:", b)
    ok_a = engine_parity and not bad

    print()
    print("=== B. perf-PR shared sentinel / __slots__ aliasing")
    ok_b = await part_b()

    print()
    print(f"A trace parity = {ok_a}   B no aliasing = {ok_b}")
    print("VERDICT:", "PASS" if ok_a and ok_b else "FAIL")


asyncio.run(main())
