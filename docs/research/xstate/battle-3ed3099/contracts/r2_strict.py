# -*- coding: utf-8 -*-
"""R2 -- does `"strict": true` in the machine config reject an undeclared
event at the call site?

§1.3b makes `strict: true` normative on all twenty contracts, on the stated
grounds that "undeclared event names raise at the call site". B6 carries it.
We also test the `strict=` interpreter kwarg, and a machine WITHOUT the
inline `"*"` handler -- because `known_events` treats a bare `"*"` as
"every event is known".
"""
from __future__ import annotations

import asyncio
import copy
import json

import cvlib
from cvlib import Rig


def strip_star(cfg):
    c = copy.deepcopy(cfg)

    def walk(n):
        (n.get("on") or {}).pop("*", None)
        for ch in (n.get("states") or {}).values():
            walk(ch)

    walk(c)
    return c


async def probe(cfg, label, strict_kw=None):
    rig = Rig()
    m = cvlib.build(cfg, rig)
    from xstate_statemachine import Interpreter, OverflowPolicy
    from xstate_statemachine.clock import SimulatedClock

    kw = {} if strict_kw is None else {"strict": strict_kw}
    interp = Interpreter(m, clock=SimulatedClock(), **kw)
    plug = cvlib.TraceP()
    interp.use(plug)
    await interp.start()
    await asyncio.sleep(cvlib.SETTLE)
    res = {}
    for name in ("SLICE_DUE_TYPO", "after.party", "done.invoke.NEVER",
                 "xstate.forged", "___xstate_forged"):
        try:
            await interp.send(name, wait=True)
            res[name] = "ACCEPTED"
        except Exception as exc:  # noqa: BLE001
            res[name] = type(exc).__name__
    await interp.stop()
    return {
        "label": label,
        "machine.strict": m.strict,
        "known_events_has_star": "*" in m.known_events,
        "n_known": len(m.known_events),
        "sends": res,
    }


async def main():
    cfg = cvlib.load("B6")
    rows = [
        await probe(cfg, "as-catalogued (config strict:true + inline '*')"),
        await probe(strip_star(cfg), "strict:true, '*' scaffolding stripped"),
        await probe(strip_star(cfg), "strict:true stripped + strict= kwarg",
                    strict_kw=True),
    ]
    print(json.dumps(rows, indent=2))


asyncio.run(main())
