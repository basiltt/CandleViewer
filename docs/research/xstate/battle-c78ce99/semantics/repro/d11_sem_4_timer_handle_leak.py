"""D11-semantics-4: a `raise(delay=)` heartbeat leaks one timer handle PER
BEAT, unboundedly -- the liveness #212 legalises has no reclamation.

#212 made a delayed self-send a legal PERIODIC process: a heartbeat of any
period now runs for ever instead of dying at `maxIterations` beats. But the
handle bookkeeping was written for `after` timers, which are owned by a
STATE and reclaimed when that state is exited
(`interpreter.py:2557`, `_timer_handles.pop(state.id, [])`).
A delayed self-send is registered under `self.id`
(`interpreter.py:2354`, `_timer_handles.setdefault(self.id, []).append(handle)`)
-- the MACHINE, which is never exited while running -- and the entry is
never removed when the timer FIRES. `_armed_self_sends` and
`_scheduled_sends` are both correctly cleaned up; only `_timer_handles`
grows.

Before #212 this was invisible: the cycle tripped at `maxIterations` and
the list stopped growing. #212 removed the thing that was bounding it.

Contrast in this repro: an `after: 10` ping-pong retains ~1 handle after
900+ beats; a `raise(delay=10)` ping-pong retains ~900 -- one per beat.

Exit 1 == reproduced. Standalone: stdlib + xstate_statemachine only.
"""
from __future__ import annotations

import asyncio, copy, gc, json, logging, sys
from typing import Any, Dict

from xstate_statemachine import Interpreter, MachineLogic, create_machine

logging.disable(logging.CRITICAL)

RD = {"type": "raise", "params": {"event": "TICK", "delay": 10}}


def mk(shape: str) -> Dict[str, Any]:
    c: Dict[str, Any] = {"id": "hb", "initial": "a", "maxIterations": 20,
                         "states": {"a": {}, "b": {}}}
    for s, o in (("a", "b"), ("b", "a")):
        if shape == "raise_delay":
            c["states"][s] = {"entry": [copy.deepcopy(RD), "beat"],
                              "on": {"TICK": o}}
        else:
            c["states"][s] = {"entry": "beat", "after": {10: o}}
    return c


async def run(shape: str, kind: str, secs: float) -> Dict[str, Any]:
    n = {"v": 0}

    def beat(i, c, e, a):  # noqa: ANN001
        n["v"] += 1

    async def beat_a(i, c, e, a):  # noqa: ANN001
        n["v"] += 1

    lg = MachineLogic(actions={"beat": beat_a if kind == "async" else beat})
    it = Interpreter(create_machine(mk(shape), logic=lg))
    await it.start()
    await asyncio.sleep(secs)
    gc.collect()
    retained = sum(len(v) for v in it._timer_handles.values())
    res = {
        "beats": n["v"],
        "timer_handles_retained": retained,
        "armed_self_sends": len(it._armed_self_sends),
        "scheduled_sends": len(it._scheduled_sends),
        # 🎯 the invariant: retention must NOT scale with the beat count
        "retained_per_beat": round(retained / max(n["v"], 1), 3),
    }
    await it.stop()
    return res


async def main() -> int:
    out: Dict[str, Any] = {}
    for kind in ("plain", "async"):
        out[f"after/{kind}"] = await run("after", kind, 10.0)
        out[f"raise_delay/{kind}"] = await run("raise_delay", kind, 10.0)
    repro = [k for k, v in out.items()
             if k.startswith("raise_delay") and v["retained_per_beat"] > 0.5]
    out["REPRODUCED"] = bool(repro)
    out["leaking_cells"] = repro
    out["note"] = ("`after` reclaims its handles on state exit; a delayed "
                   "self-send is owned by the machine id and never reclaimed")
    print(json.dumps(out, indent=1))
    return 1 if repro else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
