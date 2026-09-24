"""#212 contract check: a `raise(delay=)` self-send is a TIMER, not a chain.

Post-#212 (CHANGELOG [Unreleased]): arming a delayed self-send ENDS the
step's chain; the firing is a clock event. A 1 ms `raise(delay=1)`
ping-pong is a legal periodic process and must NOT trip `maxIterations`,
exactly as an `after: 1` ping-pong never has. A ZERO-delay `raise`
ping-pong must still trip.

Standalone: stdlib + xstate_statemachine only, inline helpers, neutral cwd.
Exit 0 == #212 holds.  Exit 1 == violation (REPRODUCED).
"""
from __future__ import annotations

import asyncio, copy, json, logging, sys
from typing import Any, Dict, List

from xstate_statemachine import Interpreter, MachineLogic, create_machine
from xstate_statemachine.plugins import PluginBase

logging.disable(logging.CRITICAL)


def ping(delay: Any) -> Dict[str, Any]:
    """a <-> b ping-pong driven by `raise(P, delay=delay)` on entry."""
    r = {"type": "raise", "params": {"event": "P", "delay": delay}}
    return {
        "id": "pp", "initial": "a", "maxIterations": 10,
        "states": {
            "a": {"entry": [r, "beat"], "on": {"P": "b"}},
            "b": {"entry": [r, "beat"], "on": {"P": "a"}},
        },
    }


AFTER = {
    "id": "ap", "initial": "a", "maxIterations": 10,
    "states": {"a": {"entry": "beat", "after": {1: "b"}},
               "b": {"entry": "beat", "after": {1: "a"}}},
}


class Obs(PluginBase):
    def __init__(self) -> None:
        self.drops: List[Any] = []

    def on_event_dropped(self, i, e, r):  # noqa: ANN001
        self.drops.append((getattr(e, "type", None), r))


async def run(cfg: Dict[str, Any], kind: str, secs: float = 1.0) -> Dict[str, Any]:
    n = {"v": 0}

    def beat(i, c, e, a):  # noqa: ANN001
        n["v"] += 1

    async def beat_a(i, c, e, a):  # noqa: ANN001
        n["v"] += 1

    lg = MachineLogic(actions={"beat": beat_a if kind == "async" else beat})
    o = Obs()
    m = Interpreter(create_machine(copy.deepcopy(cfg), logic=lg)).use(o)
    await m.start()
    await asyncio.sleep(secs)
    mid = n["v"]
    await asyncio.sleep(0.5)
    res = {
        "beats": mid, "beats_later": n["v"], "still_beating": n["v"] > mid,
        "chain_budget_drops": sum(1 for _, r in o.drops if r == "chain_budget"),
        "last_error": type(m.last_error).__name__ if m.last_error else None,
    }
    await m.stop()
    return res


async def main() -> int:
    out: Dict[str, Any] = {}
    for kind in ("plain", "async"):
        out[f"after1/{kind}"] = await run(AFTER, kind)
        out[f"raise_delay1/{kind}"] = await run(ping(1), kind)
        out[f"raise_delay50/{kind}"] = await run(ping(50), kind)
        out[f"raise_delay0/{kind}"] = await run(ping(0), kind)
    bad: List[str] = []
    for k, v in out.items():
        if k.startswith(("after1", "raise_delay1", "raise_delay50")):
            if not v["still_beating"] or v["chain_budget_drops"] or v["last_error"]:
                bad.append(f"{k}: periodic process was cut")
        if k.startswith("raise_delay0"):
            if v["still_beating"] or not v["chain_budget_drops"]:
                bad.append(f"{k}: zero-delay cycle did NOT trip")
    out["VIOLATIONS"] = bad
    out["REPRODUCED"] = bool(bad)
    print(json.dumps(out, indent=1))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
