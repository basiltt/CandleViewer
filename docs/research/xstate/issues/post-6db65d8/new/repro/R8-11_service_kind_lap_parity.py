# -*- coding: utf-8 -*-
"""Standalone repro for R8-11: #179's CHANGELOG claim "both service kinds
now trip at the same lap count as the sync engine" is false for `invoke`
ping-pong and rollback+`onDone`. Drives both shapes on sync, async-engine
`def`, and async-engine `async def`, and asserts equal trip/lap behaviour.
maxIterations=20. 20s watchdog per probe.

OBSERVED (6db65d8): ping-pong -- sync and `def` trip (different lap
counts), `async def` does not trip within the settle window. rollback --
only the async engine's `def` lane trips; sync and `async def` do not.
EXPECTED (per #179's CHANGELOG claim): all three lanes trip at the same
lap count for both shapes.
Exits 1 while the defect is present, 0 once fixed.
"""
from __future__ import annotations

import asyncio

from xstate_statemachine import Interpreter, MachineLogic, SyncInterpreter, create_machine
from xstate_statemachine.clock import SimulatedClock
from xstate_statemachine.plugins import PluginBase

MAXIT = 20
FAIL: list[str] = []

PINGPONG = {
    "id": "lv", "initial": "ver", "maxIterations": MAXIT,
    "states": {
        "ver": {"entry": ["bump"], "invoke": [{"id": "k", "src": "svc", "onDone": {"target": "arm"}}]},
        "arm": {"entry": ["bump"], "invoke": [{"id": "k2", "src": "svc", "onDone": {"target": "ver"}}]},
    },
}
ROLLBACK = {
    "id": "lv", "initial": "a", "maxIterations": MAXIT, "actionErrorPolicy": "rollback",
    "states": {
        "a": {"invoke": [{"id": "k", "src": "svc", "onDone": {"target": "b", "actions": ["blow"]}}]},
        "b": {"entry": ["bump"], "always": {"target": "a"}},
    },
}


class Watch(PluginBase):
    def __init__(self):
        self.dropped = []

    def on_event_dropped(self, interp, event, reason):  # noqa: ANN001
        self.dropped.append((getattr(event, "type", "?"), reason))


def logic(kind: str) -> MachineLogic:
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

    return MachineLogic(actions={"bump": bump, "blow": blow},
                         services={"svc": svc_def if kind == "def" else svc_async})


async def probe(name: str, spec: dict, kind: str):
    m = create_machine(spec, logic=logic(kind))
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
        return False, 0, False
    except Exception as exc:  # noqa: BLE001
        err = exc
    laps1 = (i.context or {}).get("n", 0)
    tripped = bool(err) or i.error is not None or bool(w.dropped)
    await asyncio.sleep(1.0)  # keep the loop turning for a further 1s real time
    laps2 = (i.context or {}).get("n", 0)
    late = (i.error is not None) or bool(w.dropped)
    if not tripped and laps2 > laps1 and not late:
        FAIL.append(f"{name}/{kind}: chain ran {laps2} laps with NO signal ever")
    print("  [%-15s %-5s] tripped=%-5s laps=%-4d after+1s=%-5d still=%-5s"
          % (name, kind, tripped, laps1, laps2, laps2 > laps1))
    try:
        await asyncio.wait_for(i.stop(), timeout=5)
    except Exception:  # noqa: BLE001
        pass
    return tripped, laps1, laps2 > laps1


def probe_sync(name: str, spec: dict):
    m = create_machine(spec, logic=logic("def"))
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
    print("  [%-15s sync ] tripped=%-5s laps=%-4d" % (name, tripped, laps))
    try:
        i.stop()
    except Exception:  # noqa: BLE001
        pass
    return tripped, laps


async def main() -> int:
    print("maxIterations=%d; only diff between async-engine rows is `def` vs `async def`.\n" % MAXIT)
    for name, spec in (("invoke_pingpong", PINGPONG), ("rollback_ondone", ROLLBACK)):
        print("=== %s" % name)
        ts, ls = probe_sync(name, dict(spec))
        td, ld, _ = await probe(name, dict(spec), "def")
        ta, la, _ = await probe(name, dict(spec), "async")
        print()
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
    return 1 if FAIL else 0


if __name__ == "__main__":
    try:
        code = asyncio.run(asyncio.wait_for(main(), timeout=80))
    except asyncio.TimeoutError:
        print("FAIL: overall watchdog timeout (80s)")
        code = 1
    raise SystemExit(code)
