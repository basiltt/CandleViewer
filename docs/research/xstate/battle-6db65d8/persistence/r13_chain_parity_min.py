# -*- coding: utf-8 -*-
"""R13 -- MINIMAL: the #179 "both service kinds trip at the same lap count"
parity does NOT hold for the invoke ping-pong (#168) and rollback+onDone
(#167) shapes.

#179 / reopened #167-#168 claim:

    "A step that armed a coroutine service keeps its chain open until the
     completion lands (`_chain_owed`) ... Both service kinds now trip at the
     same lap count as the sync engine."

`r12_livelock_fuzz.py` (500 configs) shows, with perfect consistency:

    invoke_pingpong  def -> TRIP (50/50)   async -> running (50/50)
    rollback_ondone  def -> TRIP (50/50)   async -> running (50/50)

This probe holds everything fixed except the ONE character that distinguishes
the two services (`def` vs `async def`) and reports, for each:

  * whether the machine tripped at all (`last_error` / receipt error / drop),
  * how many laps the cycle actually ran (the context counter), and
  * whether the cycle is still turning afterwards (laps measured again
    after a further second of wall clock) -- i.e. is "running" a bounded
    machine that stopped, or an unbounded one that never trips?

The last question is the one that matters: a cycle that never trips and never
stops is the livelock `maxIterations` exists to prevent.
"""
from __future__ import annotations

import asyncio
import json

from xstate_statemachine import Interpreter, MachineLogic, SyncInterpreter, create_machine
from xstate_statemachine.clock import SimulatedClock
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


def logic(kind: str):
    def bump(i, c, e, a):  # noqa: ANN001
        c["n"] = c.get("n", 0) + 1

    def blow(i, c, e, a):  # noqa: ANN001
        c["n"] = c.get("n", 0) + 1
        raise RuntimeError("rollback")

    def svc_def(i, c, e):  # noqa: ANN001
        return {"ok": 1}

    async def svc_async(i, c, e):  # noqa: ANN001
        await asyncio.sleep(0)
        return {"ok": 1}

    return MachineLogic(
        actions={"bump": bump, "blow": blow},
        services={"svc": svc_def if kind == "def" else svc_async},
    )


async def probe(name: str, spec: dict, kind: str) -> None:
    m = create_machine(json.loads(json.dumps(spec)), logic=logic(kind))
    w = Watch()
    i = Interpreter(m, clock=SimulatedClock())
    i.use(w)
    err = None
    try:
        await asyncio.wait_for(i.start(children_timeout=1.0), timeout=20)
        r = await asyncio.wait_for(i.send("PING", wait=True), timeout=20)
        err = getattr(r, "error", None)
    except asyncio.TimeoutError:
        print("  [%-15s %-5s] HANG (>20s)" % (name, kind))
        FAIL.append(f"{name}/{kind}: hang")
        return
    except Exception as exc:  # noqa: BLE001
        err = exc
    laps1 = (i.context or {}).get("n", 0)
    tripped = bool(err) or i.error is not None or bool(w.dropped)
    # keep the loop turning for a further second of real time
    await asyncio.sleep(1.0)
    laps2 = (i.context or {}).get("n", 0)
    still = laps2 > laps1
    # 🔎 Did the trip become observable LATER (last_error / a drop), even
    #    though the caller's receipt said ok?
    late = (i.error is not None) or bool(w.dropped)
    print("       late-observable after +1s: last_error=%s drops=%d"
          % (type(i.error).__name__ if i.error else None, len(w.dropped)))
    if not tripped and laps2 > laps1 and not late:
        FAIL.append(f"{name}/{kind}: chain ran {laps2} laps with NO signal ever")
    print("  [%-15s %-5s] tripped=%-5s laps=%-4d  after +1s laps=%-5d "
          "still_turning=%-5s status=%s err=%s"
          % (name, kind, tripped, laps1, laps2, still, i.status,
             type(err).__name__ if err else (type(i.error).__name__
                                             if i.error else None)))
    try:
        await asyncio.wait_for(i.stop(), timeout=5)
    except Exception:  # noqa: BLE001
        pass
    return tripped, laps1, still


def probe_sync(name: str, spec: dict) -> None:
    m = create_machine(json.loads(json.dumps(spec)), logic=logic("def"))
    w = Watch()
    i = SyncInterpreter(m)
    i.use(w)
    err = None
    try:
        i.start()
        r = i.send("PING")
        err = getattr(r, "error", None)
    except Exception as exc:  # noqa: BLE001
        err = exc
    laps = (i.context or {}).get("n", 0)
    tripped = bool(err) or i.error is not None or bool(w.dropped)
    print("  [%-15s sync ] tripped=%-5s laps=%-4d status=%s err=%s"
          % (name, tripped, laps, i.status,
             type(err).__name__ if err else None))
    try:
        i.stop()
    except Exception:  # noqa: BLE001
        pass
    return tripped, laps


async def main() -> None:
    print("maxIterations = %d; the ONLY difference between the two async-engine\n"
          "rows of each block is `def svc` vs `async def svc`.\n" % MAXIT)
    for name, spec in (("invoke_pingpong", PINGPONG),
                       ("rollback_ondone", ROLLBACK)):
        print("=== %s" % name)
        ts, ls = probe_sync(name, spec)
        res = {}
        for kind in ("def", "async"):
            res[kind] = await probe(name, spec, kind)
        print()
        td, ld, _ = res["def"]
        ta, la, still = res["async"]
        if td and not ta:
            FAIL.append(f"{name}: `def` trips, `async def` does not (#179)")
        if td and ta and ld != la:
            FAIL.append(f"{name}: lap counts differ def={ld} async={la}")
        if ts and td and ls != ld:
            FAIL.append(f"{name}: sync={ls} vs async-engine def={ld} laps")

    print("FAILURES:")
    for f in FAIL:
        print("  -", f)
    print("VERDICT:", "FAIL" if FAIL else "PASS")


asyncio.run(main())
