"""D6 -- cross-engine divergence on the SAME script: why do the two engines
disagree about how many times a service ran, and about `after` timers?

D1 (§cross-engine) found, on one 10 000-step script:
   async: raised=2215 svc_err=11 svc_ok=87 timers=2
   sync : raised=2231 svc_err=17 svc_ok=84 timers=0

Three distinct questions:
  Q1  Does `invoke` of a SYNC callable complete inside the entry macrostep on
      the sync engine but a loop-turn later on the async engine?
  Q2  Does an `after` timer that is cancelled by an earlier exit fire at all?
  Q3  Is the `raise` count difference explained by Q1 (a different number of
      `pending` entries)?

These are answered with minimal machines, no randomness, no wall clock.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys

sys.path.insert(
    0, "<workspace>/_ref/xstate-statemachine/src"
)
logging.disable(logging.CRITICAL)

from xstate_statemachine import (  # noqa: E402
    Interpreter,
    MachineLogic,
    PluginBase,
    SyncInterpreter,
    create_machine,
)
from xstate_statemachine.clock import SimulatedClock  # noqa: E402

# Q1/Q3 -- a state that invokes a SYNC service and also has an `after`.
CFG = {
    "id": "q",
    "initial": "idle",
    "context": {"ok": 0, "late": 0, "cancel": 0},
    "states": {
        "idle": {"on": {"GO": {"target": "busy"}}},
        "busy": {
            "invoke": {
                "id": "s",
                "src": "work",
                "onDone": {"target": "idle", "actions": ["ok"]},
            },
            "after": {"50": {"target": "idle", "actions": ["late"]}},
            "on": {"CANCEL": {"target": "idle", "actions": ["cancel"]}},
        },
    },
}


class Trace(PluginBase):
    def __init__(self, t):
        self.t = t

    def on_event_received(self, i, e):
        self.t.append(("recv", e.type))

    def on_transition(self, i, f, to, tr):
        self.t.append(("to", tuple(sorted(s.id for s in to if s.parent))))


def logic():
    def ok(i, c, e, a):
        c["ok"] += 1

    def late(i, c, e, a):
        c["late"] += 1

    def cancel(i, c, e, a):
        c["cancel"] += 1

    def work(i, c, e):  # plain sync -- both engines accept it
        return {"v": 1}

    return MachineLogic(
        actions={"ok": ok, "late": late, "cancel": cancel},
        services={"work": work},
    )


def build():
    return create_machine(CFG, logic=logic())


async def q_async(script, ticks):
    t = []
    clock = SimulatedClock()
    i = Interpreter(build(), clock=clock)
    i.use(Trace(t))
    await i.start()
    for step in script:
        if step[0] == "tick":
            await clock.increment(step[1])
        else:
            await i.send(step[1])
    for _ in range(3000):
        await asyncio.sleep(0)
    out = (t, dict(i.context), sorted(i.current_state_ids))
    await i.stop()
    return out


def q_sync(script, ticks):
    t = []
    clock = SimulatedClock()
    i = SyncInterpreter(build(), clock=clock)
    i.use(Trace(t))
    i.start()
    for step in script:
        if step[0] == "tick":
            clock.increment(step[1])
        else:
            i.send(step[1])
    out = (t, dict(i.context), sorted(i.current_state_ids))
    i.stop()
    return out


SCRIPTS = {
    "S1 GO then drain (service should complete)": [("send", "GO")],
    "S2 GO, then advance 100ms (after should be dead)": [
        ("send", "GO"),
        ("tick", 100),
    ],
    "S3 GO,GO,GO -- how many completions?": [
        ("send", "GO"),
        ("send", "GO"),
        ("send", "GO"),
    ],
    "S4 GO then CANCEL in the same breath": [
        ("send", "GO"),
        ("send", "CANCEL"),
    ],
    "S5 GO x10 with a tick between each": [
        s for _ in range(10) for s in (("send", "GO"), ("tick", 100))
    ],
}

if __name__ == "__main__":
    res = {}
    for name, script in SCRIPTS.items():
        at, actx, ast = asyncio.run(q_async(script, None))
        st, sctx, sst = q_sync(script, None)
        agree_ctx = actx == sctx
        agree_state = ast == sst
        agree_trace = at == st
        res[name] = {
            "async": {"ctx": actx, "state": ast, "trace": at},
            "sync": {"ctx": sctx, "state": sst, "trace": st},
            "agree": {
                "context": agree_ctx,
                "state": agree_state,
                "trace": agree_trace,
            },
        }
        print(f"\n--- {name} ---")
        print(f"  async ctx={actx} state={ast}")
        print(f"  sync  ctx={sctx} state={sst}")
        print(
            f"  agree: context={agree_ctx} state={agree_state} "
            f"trace={agree_trace}"
        )
        if not agree_trace:
            for k, (a, b) in enumerate(zip(at, st)):
                if a != b:
                    print(f"    trace first diff @ {k}: async={a!r} sync={b!r}")
                    break
            else:
                print(f"    trace lengths: async={len(at)} sync={len(st)}")
                print(f"      async tail: {at[len(st):][:4]}")
                print(f"      sync  tail: {st[len(at):][:4]}")

    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "d6_cross_engine.json"), "w", encoding="utf-8") as f:
        json.dump(res, f, indent=2, default=str)
    print("\nwrote out/d6_cross_engine.json")
