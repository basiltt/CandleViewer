# -*- coding: utf-8 -*-
"""S7 -- does the async `invoke_pingpong` / `rollback_ondone` chain TRIP
at the same lap as the sync engine, given enough wall clock? (#201)

`r13_chain_parity_min.py` measures at a fixed deadline and reports
`tripped=False` for the async lanes; `r12_livelock_fuzz.py` at 200 configs
reports **0 lap-count mismatches and 0 silent trips**, which is only
consistent if the async lanes DO trip, just later than r13's window. #201
makes the distinction explicit and says what is NOT promised: on
`rollback + onDone` the sync engine stops after the first rollback with a
`RuntimeError` instead of re-arming, while both async lanes trip
`RunawayChainError` at the same lap.

This probe settles the question by polling until the machine stops turning
(bounded 20 s) rather than sampling once, and prints, per lane:
trip / lap count / final status.

STANDALONE.
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

MAXIT = 25
FAIL: list[str] = []


class Watch(PluginBase):
    def __init__(self):
        self.dropped = []

    def on_event_dropped(self, interp, event, reason):  # noqa: ANN001
        self.dropped.append((getattr(event, "type", "?"), reason))


PINGPONG = {
    "id": "lv", "initial": "ver", "maxIterations": MAXIT,
    "states": {
        "ver": {"entry": ["bump"],
                "invoke": [{"id": "k", "src": "svc",
                            "onDone": {"target": "arm"}}]},
        "arm": {"entry": ["bump"],
                "invoke": [{"id": "k2", "src": "svc",
                            "onDone": {"target": "ver"}}]},
    },
}

ROLLBACK = {
    "id": "lv", "initial": "a", "maxIterations": MAXIT,
    "actionErrorPolicy": "rollback",
    "states": {
        "a": {"invoke": [{"id": "k", "src": "svc",
                          "onDone": {"target": "b", "actions": ["blow"]}}]},
        "b": {"entry": ["bump"], "always": {"target": "a"}},
    },
}


def mk(spec, kind):
    n = {"v": 0}

    def bump(interp, ctx, ev, act):
        n["v"] += 1

    def blow(interp, ctx, ev, act):
        raise RuntimeError("rollback")

    async def svc_a(interp, ctx, ev):
        return 1

    def svc_d(interp, ctx, ev):
        return 1

    logic = MachineLogic(
        actions={"bump": bump, "blow": blow},
        services={"svc": svc_a if kind == "async" else svc_d},
    )
    return create_machine(json.loads(json.dumps(spec)), logic=logic), n


async def run_async(spec, kind):
    m, n = mk(spec, kind)
    i = Interpreter(m)
    w = Watch()
    i.use(w)
    await i.start()
    last, stable = -1, 0
    for _ in range(200):  # <= 20 s
        await asyncio.sleep(0.1)
        if n["v"] == last:
            stable += 1
            if stable >= 5:
                break
        else:
            stable = 0
            last = n["v"]
    err = i.error
    await i.stop()
    tripped = err is not None or bool(w.dropped)
    return tripped, n["v"], type(err).__name__ if err else None, w.dropped


def run_sync(spec, kind):
    m, n = mk(spec, kind)
    i = SyncInterpreter(m)
    w = Watch()
    i.use(w)
    try:
        i.start()
    except Exception as exc:  # noqa: BLE001
        return True, n["v"], type(exc).__name__, w.dropped
    err = i.error
    try:
        i.stop()
    except Exception:  # noqa: BLE001
        pass
    return (err is not None or bool(w.dropped)), n["v"], \
        type(err).__name__ if err else None, w.dropped


async def main() -> None:
    print("=== S7 chain parity, settled (maxIterations=%d) ===" % MAXIT)
    for name, spec in (("invoke_pingpong", PINGPONG),
                       ("rollback_ondone", ROLLBACK)):
        print("\n--- %s" % name)
        rows = {}
        t, laps, err, dr = run_sync(spec, "def")
        rows["sync/def"] = (t, laps, err, dr)
        for kind in ("def", "async"):
            rows["async/%s" % kind] = await run_async(spec, kind)
        for lane, (t, laps, err, dr) in rows.items():
            print("  %-12s tripped=%-5s laps=%-4d err=%-20s drops=%d"
                  % (lane, t, laps, err, len(dr)))
        laps_a = {k: v[1] for k, v in rows.items() if k.startswith("async")}
        if len(set(laps_a.values())) > 1:
            FAIL.append("%s: the two async service kinds settled at "
                        "different lap counts %s" % (name, laps_a))
        if not all(v[0] for v in rows.values()):
            FAIL.append("%s: not every lane tripped: %s"
                        % (name, {k: v[0] for k, v in rows.items()}))

    print("\nFAILURES:", FAIL if FAIL else "none")
    print("VERDICT:", "FAIL" if FAIL else "PASS")


asyncio.run(main())
