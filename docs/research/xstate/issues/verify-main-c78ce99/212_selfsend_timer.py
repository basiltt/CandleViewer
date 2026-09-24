"""R10-03 (STANDALONE): #206's chain charge for a self re-armed delayed send is
time-blind, so a `raise(delay=)` self-paced heartbeat dies at `maxIterations`
beats regardless of the beat period.

`Interpreter._schedule_send` (interpreter.py:2206-2247) treats a delayed send to
self issued from an action as a debt of the arming step (`_chain_owed_sends`,
`_armed_this_step += 1`) and charges its firing as engine work
(`_deliver_priority(..., engine_completion=self_armed)`), incrementing
`_raise_depth`. Nothing in that path is time-aware: the chain clears only on
"raised nothing, armed nothing, owes nothing", and a heartbeat re-arms in its
own entry action, so that test is false on every lap. Wall-clock time between
beats never ends the chain.

Control: the DOCUMENTED heartbeat idiom (`after`) is unaffected.

Exit 0 = both spellings survive the window (defect fixed).
Exit 1 = `raise(delay=)` is cut while `after` is not (defect present).

Stdlib + xstate_statemachine only. Runs from any cwd. Watchdog 40 s.
"""
from __future__ import annotations

import asyncio
import json
import sys

from xstate_statemachine import create_machine, Interpreter, MachineLogic

MAXIT = 8
PERIODS_MS = (30, 100, 250)
WINDOW_S = 3.0


def _raise_cfg(period_ms: int) -> dict:
    arm = {"type": "raise", "params": {"event": "BEAT", "delay": period_ms}}
    return {
        "id": "hb",
        "initial": "up",
        "maxIterations": MAXIT,
        "states": {
            "up": {"entry": [arm, "beat"], "on": {"BEAT": "down"}},
            "down": {"entry": [arm, "beat"], "on": {"BEAT": "up"}},
        },
    }


def _after_cfg(period_ms: int) -> dict:
    return {
        "id": "hb",
        "initial": "up",
        "maxIterations": MAXIT,
        "states": {
            "up": {"entry": ["beat"], "after": {period_ms: "down"}},
            "down": {"entry": ["beat"], "after": {period_ms: "up"}},
        },
    }


async def run(cfg: dict, kind: str) -> dict:
    beats = {"n": 0}
    drops: list = []

    def _beat(i, c, e, a=None):  # plain def
        beats["n"] += 1

    async def _beat_async(i, c, e, a=None):  # async def
        beats["n"] += 1

    fn = _beat if kind == "def" else _beat_async
    machine = create_machine(
        json.loads(json.dumps(cfg)), logic=MachineLogic(actions={"beat": fn})
    )
    interp = Interpreter(machine)
    try:
        interp.on_event_dropped = lambda *a, **k: drops.append(a)  # best effort
    except Exception:
        pass
    await interp.start()
    await asyncio.sleep(WINDOW_S)
    err = type(getattr(interp, "last_error", None)).__name__
    await interp.stop()
    return {"beats": beats["n"], "last_error": err}


async def main() -> int:
    bad = 0
    print(f"maxIterations={MAXIT}  window={WINDOW_S}s")
    print(f"{'spelling':<14}{'kind':<10}{'period':<9}{'beats':<8}last_error")
    for kind in ("def", "async def"):
        for p in PERIODS_MS:
            r = await run(_raise_cfg(p), kind)
            a = await run(_after_cfg(p), kind)
            print(f"{'raise(delay=)':<14}{kind:<10}{str(p)+'ms':<9}"
                  f"{r['beats']:<8}{r['last_error']}")
            print(f"{'after':<14}{kind:<10}{str(p)+'ms':<9}"
                  f"{a['beats']:<8}{a['last_error']}")
            # The defect: raise(delay=) is cut at ~maxIterations beats while the
            # documented `after` idiom keeps beating for the whole window.
            if r["beats"] <= MAXIT + 4 and a["beats"] > MAXIT + 4:
                bad += 1
    print()
    print("VERDICT:", "DEFECT PRESENT" if bad else "ok (bounded alike)",
          f"({bad}/{len(PERIODS_MS) * 2} cells cut)")
    return 1 if bad else 0


if __name__ == "__main__":
    try:
        rc = asyncio.run(asyncio.wait_for(main(), 40.0))
    except asyncio.TimeoutError:
        print("WATCHDOG TIMEOUT")
        rc = 1
    sys.exit(rc)
