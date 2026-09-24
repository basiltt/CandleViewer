"""R11-05 refutation probe: is the `raise(delay=tiny)` escape distinct from
the long-standing `after` exemption? STANDALONE (stdlib + xstate_statemachine).

For each action kind (def/async def), run four shapes at maxIterations=10:
  A1 after:1      + zero-delay raise per period   (pre-existing exempt shape)
  A2 after:0.0001 + zero-delay raise per period
  B1 pure after:1      ping-pong
  B2 pure after:0.0001 ping-pong
If after: behaves the same as raise(delay=), the #212 rule introduced no new
escape: it made raise(delay=) equal to after, which was never bounded.
"""

import asyncio, time
from typing import Any, Dict
from xstate_statemachine import Interpreter, MachineLogic, create_machine

LIMIT = 10


def _mk(cfg):
    def bump(i, c, e, a): c["n"] += 1
    async def abump(i, c, e, a): c["n"] += 1
    return create_machine(cfg, logic=MachineLogic(actions={"beat": bump, "abeat": abump}))


def mixed_after(act, d):
    return {"id": "mix", "initial": "A", "maxIterations": LIMIT, "context": {"n": 0},
            "states": {
                "A": {"entry": [act], "after": {d: "B"}},
                "B": {"entry": [{"type": "raise", "params": {"event": "GO"}}, act],
                      "on": {"GO": "A"}}}}


def pure_after(act, d):
    return {"id": "hb", "initial": "up", "maxIterations": LIMIT, "context": {"n": 0},
            "states": {"up": {"entry": [act], "after": {d: "down"}},
                       "down": {"entry": [act], "after": {d: "up"}}}}


async def run(cfg, w):
    i = await Interpreter(_mk(cfg)).start()
    t0 = time.perf_counter()
    await asyncio.sleep(w)
    el = time.perf_counter() - t0
    n, err = i.context["n"], type(i.last_error).__name__ if i.last_error else None
    await i.stop()
    return n, err, round(n / el, 1)


async def main():
    for act in ("beat", "abeat"):
        print(f"--- action kind: {act} ---")
        for label, cfg, w in (
            ("A1 after:1 + zero-delay raise", mixed_after(act, 1), 1.0),
            ("A2 after:0.0001 + zero-delay raise", mixed_after(act, 0.0001), 0.5),
            ("B1 pure after:1 ping-pong", pure_after(act, 1), 1.0),
            ("B2 pure after:0.0001 ping-pong", pure_after(act, 0.0001), 0.5),
        ):
            n, err, r = await run(cfg, w)
            print(f"  {label:38s} beats={n:6d} err={err} rate={r}/s (limit={LIMIT})")


if __name__ == "__main__":
    asyncio.run(main())
