"""P3 (#206 follow-up): how far does the delayed-self-send charge reach?

P2 showed a 30 ms self re-arming heartbeat is cut at `maxIterations` on the
async engine at 19cb1f1 (and NOT on the sync engine). This pins the scope:

Q1: does a LONGER delay escape? 30 / 100 / 250 ms at maxIterations=4.
    If the lap count is the same at every delay, the charge is purely
    structural: idle wall-clock time never ends the chain, so ANY self
    re-arming timer dies after `maxIterations` beats regardless of period.
Q2: does `cancel(id)` settle the debt (no leak) -- re-arm under a stable
    send id, which supersedes, then confirm laps still bounded.
Q3: a single delayed self-send that is NOT a cycle (one hop, then rest):
    does the chain clear afterwards so later traffic is unaffected?

STANDALONE: stdlib + xstate_statemachine only. Run from any cwd.
"""

import asyncio
import json
import sys

SRC = sys.argv[1] if len(sys.argv) > 1 else (
    r"<workspace>/_ref"
    r"/xstate-statemachine/src"
)
sys.path.insert(0, SRC)

from xstate_statemachine import (  # noqa: E402
    Interpreter,
    MachineLogic,
    PluginBase,
    create_machine,
)


class _Drops(PluginBase):
    def __init__(self):
        self.dropped = []

    def on_event_dropped(self, interp, event, reason):
        self.dropped.append((event.type, reason))


def _ping_pong(delay_ms, limit, send_id=None):
    raise_act = {"type": "raise", "params": {"event": "TICK",
                                             "delay": delay_ms}}
    if send_id:
        raise_act["params"]["id"] = send_id
    return {
        "id": "hb",
        "initial": "up",
        "maxIterations": limit,
        "context": {"n": 0},
        "states": {
            "up": {
                "entry": ["beat", json.loads(json.dumps(raise_act))],
                "on": {"TICK": "down"},
            },
            "down": {
                "entry": ["beat", json.loads(json.dumps(raise_act))],
                "on": {"TICK": "up"},
            },
        },
    }


def _mk(cfg):
    return create_machine(
        cfg,
        logic=MachineLogic(
            actions={"beat": lambda i, c, e, a: c.__setitem__("n", c["n"] + 1)}
        ),
    )


async def _laps(cfg, budget_s):
    d = _Drops()
    i = Interpreter(_mk(cfg)).use(d)
    await i.start()
    loops = int(budget_s / 0.05)
    for _ in range(loops):
        await asyncio.sleep(0.05)
        if d.dropped:
            break
    out = (i.context["n"], bool(d.dropped))
    await i.stop()
    return out


async def q1():
    out = {}
    for delay in (30, 100, 250):
        out[delay] = await _laps(_ping_pong(delay, 4), budget_s=3.0)
    return out


async def q2():
    return await _laps(_ping_pong(30, 4, send_id="hb"), budget_s=3.0)


async def q3():
    # One delayed self-send, no cycle, then a burst of external traffic.
    cfg = {
        "id": "once",
        "initial": "a",
        "maxIterations": 3,
        "context": {"n": 0},
        "states": {
            "a": {
                "entry": [
                    {"type": "raise", "params": {"event": "GO", "delay": 30}}
                ],
                "on": {"GO": "b"},
            },
            "b": {"on": {"EV": {"actions": ["beat"]}}},
        },
    }
    d = _Drops()
    i = Interpreter(_mk(cfg)).use(d)
    await i.start()
    await asyncio.sleep(0.2)
    for _ in range(10):
        i.send("EV")
    await asyncio.sleep(0.3)
    out = (list(i.current_state_ids), i.context["n"],
           [r for _, r in d.dropped])
    await i.stop()
    return out


def _run(c):
    return asyncio.new_event_loop().run_until_complete(c)


if __name__ == "__main__":
    print("SRC:", SRC)
    print("Q1 laps by delay (n, cut?) :", _run(q1()))
    print("Q2 stable send id          :", _run(q2()))
    print("Q3 one hop then 10 externs :", _run(q3()))
