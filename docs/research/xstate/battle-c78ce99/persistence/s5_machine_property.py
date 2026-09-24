# -*- coding: utf-8 -*-
"""S5 -- property: >=300 random machines, snapshot/restore at every window.

Generates N random charts (parallel regions, nested compounds, `always`
transitions, `after` timers, an invoked `def` or `async def` service or an
invoked CHILD MACHINE) and, for each, attempts a snapshot at every hook
window. Accept criteria, per attempt:

  1. NO TORN BLOB -- a snapshot the writer produced must be accepted by
     `from_snapshot`, or the write must have been refused.
  2. Restoring reproduces the exact `state_ids` the blob declared.
  3. The restored blob round-trips byte-identically (modulo `taken_at`,
     recursively, and `output`/`error` which the restore re-derives).
  4. No RAW builtin leaks into `pending_events` (every record typed).
  5. A restored child actor is never caught half-written.

Usage:  python s5_machine_property.py [N] [seed]
STANDALONE. XS_SVC=def|async selects the service kind.
"""
from __future__ import annotations

import asyncio
import json
import os
import random
import sys

from xstate_statemachine import Interpreter, MachineLogic, create_machine
from xstate_statemachine.plugins import PluginBase

N = int(sys.argv[1]) if len(sys.argv) > 1 else 300
SEED = int(sys.argv[2]) if len(sys.argv) > 2 else 11
KIND = os.environ.get("XS_SVC", "async")

STATS = {
    "machines": 0, "attempts": 0, "refused": 0, "accepted": 0,
    "torn": 0, "mismatch": 0, "raw": 0, "halfwritten": 0, "raises": 0,
}
DETAILS: list[str] = []
WINDOWS: dict[str, int] = {}


def strip(o):
    """Drop volatile keys recursively for the round-trip comparison."""
    if isinstance(o, dict):
        return {k: strip(v) for k, v in o.items()
                if k not in ("taken_at", "value", "output", "error")}
    if isinstance(o, list):
        return [strip(x) for x in o]
    return o


CHILD = {
    "id": "kid",
    "initial": "s1",
    "states": {"s1": {"entry": ["half"], "on": {"P": "s2"}}, "s2": {}},
}


def gen(rng):
    """Build one random machine spec."""
    regions = rng.randint(1, 3)
    spec = {"id": "g", "type": "parallel", "states": {}}
    if rng.random() < 0.35:
        spec["onUnhandled"] = rng.choice(["ignore", "defer"])
    for r in range(regions):
        leaf = {"on": {"E%d" % r: "z%d" % r}}
        if rng.random() < 0.4:
            leaf["after"] = {rng.choice([20, 50]): {"target": "z%d" % r}}
        if rng.random() < 0.45:
            leaf["invoke"] = [{
                "id": "inv%d" % r,
                "src": rng.choice(["svc", "kidsvc"]),
                "onDone": {"target": "z%d" % r},
                "onError": {"target": "z%d" % r},
            }]
        states = {"a%d" % r: leaf, "z%d" % r: {}}
        if rng.random() < 0.35:
            # nested compound with an `always`
            states["a%d" % r] = {
                "initial": "i",
                "states": {
                    "i": {"always": [{"target": "j",
                                      "guard": "gtrue"}]},
                    "j": leaf,
                },
            }
        spec["states"]["r%d" % r] = {"initial": "a%d" % r, "states": states}
    return spec


def logic(rng, bag):
    async def svc_async(interp, ctx, ev):
        await asyncio.sleep(rng.choice([0.0, 0.01]))
        return {"ok": 1}

    def svc_def(interp, ctx, ev):
        return {"ok": 1}

    def half(interp, ctx, ev, act):
        ctx["a"] = 1
        ctx["b"] = 1  # both keys, always -- a snapshot seeing only `a` is torn

    return MachineLogic(
        actions={"half": half},
        guards={"gtrue": lambda ctx, ev: True},
        services={
            "svc": svc_async if KIND == "async" else svc_def,
            "kidsvc": create_machine(
                CHILD, logic=MachineLogic(actions={"half": half})
            ),
        },
    )


class Snap(PluginBase):
    def __init__(self, spec):
        self.spec = spec

    def _try(self, interp, window):
        STATS["attempts"] += 1
        WINDOWS[window] = WINDOWS.get(window, 0) + 1
        try:
            blob = interp.get_persisted_snapshot()
        except Exception:  # noqa: BLE001
            STATS["refused"] += 1
            return
        STATS["accepted"] += 1
        # 4. raw records
        for rec in blob.get("pending_events") or []:
            if not isinstance(rec, dict) or "type" not in rec:
                STATS["raw"] += 1
                DETAILS.append("%s: raw record %r" % (window, rec))
        # 5. half-written child
        for actor in (blob.get("actors") or {}).values():
            ctx = (actor or {}).get("context") or {}
            if "a" in ctx and "b" not in ctx:
                STATS["halfwritten"] += 1
                DETAILS.append("%s: half-written child %r" % (window, ctx))
        # 1/2/3. round-trip
        rng = random.Random(0)
        try:
            j = Interpreter.from_snapshot(
                json.dumps(blob),
                create_machine(json.loads(json.dumps(self.spec)),
                               logic=logic(rng, {})),
            )
        except Exception as exc:  # noqa: BLE001
            STATS["torn"] += 1
            DETAILS.append("%s: TORN %s: %s"
                           % (window, type(exc).__name__, str(exc)[:70]))
            return
        if sorted(j.current_state_ids) != sorted(blob["state_ids"]):
            STATS["mismatch"] += 1
            DETAILS.append("%s: leaves %s != declared %s"
                           % (window, sorted(j.current_state_ids),
                              sorted(blob["state_ids"])))
            return
        again = j.get_persisted_snapshot()
        if strip(again) != strip(blob):
            STATS["mismatch"] += 1
            DETAILS.append("%s: round-trip differs" % window)

    def on_interpreter_start(self, interp):  # noqa: ANN001
        self._try(interp, "start")

    def on_transition(self, interp, frm, to, t):  # noqa: ANN001
        self._try(interp, "transition")

    def on_unhandled_event(self, interp, event, ids, disposition):  # noqa: ANN001,E501
        self._try(interp, "unhandled")


async def one(rng):
    spec = gen(rng)
    STATS["machines"] += 1
    m = create_machine(json.loads(json.dumps(spec)), logic=logic(rng, {}))
    i = Interpreter(m)
    plug = Snap(spec)
    i.use(plug)
    try:
        await i.start()
        for _ in range(rng.randint(1, 3)):
            i.send(rng.choice(["E0", "E1", "E2", "NOPE"]))
        await asyncio.sleep(0.03)
        plug._try(i, "quiescent")
    except Exception as exc:  # noqa: BLE001
        STATS["raises"] += 1
        DETAILS.append("run raise %s: %s" % (type(exc).__name__,
                                             str(exc)[:70]))
    finally:
        try:
            await i.stop()
        except Exception:  # noqa: BLE001
            pass


async def main() -> None:
    print("=== S5 machine property [%s] N=%d seed=%d ===" % (KIND, N, SEED))
    rng = random.Random(SEED)
    for _ in range(N):
        await one(rng)
    for k, v in STATS.items():
        print("  %-12s %d" % (k, v))
    print("  windows     ", WINDOWS)
    for d in DETAILS[:12]:
        print("   !", d)
    bad = STATS["torn"] + STATS["mismatch"] + STATS["raw"] \
        + STATS["halfwritten"] + STATS["raises"]
    print("VERDICT:", "FAIL" if bad else "PASS")


asyncio.run(main())
