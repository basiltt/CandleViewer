# -*- coding: utf-8 -*-
"""T5 - genuinely freeze the run loop mid-macrostep, then crash.

An ACTION that never returns parks the run loop inside `_process_event`, so
subsequent `send()`s pile up in the inbox, unprocessed. That is the real
crash-mid-macrostep shape: some events accepted, one half-applied.

Q1: does `get_persisted_snapshot()` capture the piled-up inbox?
Q2: what does each `wait=True` awaiter get when the process dies?
Q3: after a restore, is the half-applied macrostep's context committed or
    rolled back, and are the queued events replayed?
"""
from __future__ import annotations

import asyncio
import json

from xstate_statemachine import Interpreter, MachineLogic, create_machine
from xstate_statemachine.clock import SimulatedClock

from harness import attach_clock

FREEZE = asyncio.Event()

CONFIG = {
    "id": "freeze",
    "initial": "a",
    "context": {"log": []},
    "states": {
        "a": {"on": {"GO": {"target": "b", "actions": ["first", "hang",
                                                       "second"]}}},
        "b": {"entry": ["entered_b"],
              "on": {"X": {"actions": ["noteX"]},
                     "Y": {"actions": ["noteY"]}}},
    },
}


def first(i, ctx, e, ad):  # noqa: ANN001
    ctx["log"].append("first")


async def hang(i, ctx, e, ad):  # noqa: ANN001
    ctx["log"].append("hang_enter")
    await FREEZE.wait()
    ctx["log"].append("hang_exit")


def second(i, ctx, e, ad):  # noqa: ANN001
    ctx["log"].append("second")


def entered_b(i, ctx, e, ad):  # noqa: ANN001
    ctx["log"].append("entered_b")


def noteX(i, ctx, e, ad):  # noqa: ANN001
    ctx["log"].append("X")


def noteY(i, ctx, e, ad):  # noqa: ANN001
    ctx["log"].append("Y")


def build(policy: str | None = None):
    cfg = json.loads(json.dumps(CONFIG))
    if policy:
        cfg["actionErrorPolicy"] = policy
    return create_machine(cfg, logic=MachineLogic(actions={
        "first": first, "hang": hang, "second": second,
        "entered_b": entered_b, "noteX": noteX, "noteY": noteY,
    }))


async def main() -> None:
    global FREEZE
    FREEZE = asyncio.Event()
    i = await Interpreter(build(), clock=SimulatedClock()).start()
    await asyncio.sleep(0.02)

    go = asyncio.ensure_future(i.send("GO", wait=True))
    await asyncio.sleep(0.05)          # now parked inside `hang`
    x = asyncio.ensure_future(i.send("X", wait=True))
    y = asyncio.ensure_future(i.send("Y", wait=True))
    await asyncio.sleep(0.05)

    print("frozen mid-macrostep:")
    print("  states      :", sorted(i.current_state_ids))
    print("  context.log :", i.context["log"])
    print("  pending     :", [e.type for e in i.pending_events])

    blob = i.get_snapshot()
    d = json.loads(blob)
    print("  SNAPSHOT states   :", d["state_ids"])
    print("  SNAPSHOT log      :", d["context"]["log"])
    print("  SNAPSHOT pending  :", [r["type"] for r in d["pending_events"]])

    await i.stop()   # 💥 process dies
    for name, t in (("GO", go), ("X", x), ("Y", y)):
        try:
            r = await asyncio.wait_for(t, timeout=1.0)
            print(f"  awaiter {name}: RESOLVED {r}")
        except asyncio.TimeoutError:
            print(f"  awaiter {name}: HUNG   <-- no resolution, no error")
        except Exception as e:  # noqa: BLE001
            print(f"  awaiter {name}: RAISED {type(e).__name__}: {e}")
    FREEZE.set()

    print("\nrestore & resume:")
    FREEZE = asyncio.Event()
    FREEZE.set()  # the restored process does not hang
    i2 = Interpreter.from_snapshot(blob, build())
    attach_clock(i2, SimulatedClock())
    await i2.start()
    await asyncio.sleep(0.15)
    print("  states :", sorted(i2.current_state_ids))
    print("  log    :", i2.context["log"])
    print("  pending:", [e.type for e in i2.pending_events])
    await i2.stop()

    print("\nreference (no crash):")
    FREEZE = asyncio.Event()
    FREEZE.set()
    i3 = await Interpreter(build(), clock=SimulatedClock()).start()
    await asyncio.sleep(0.02)
    for ev in ("GO", "X", "Y"):
        await i3.send(ev)
    await asyncio.sleep(0.1)
    print("  states :", sorted(i3.current_state_ids))
    print("  log    :", i3.context["log"])
    await i3.stop()


if __name__ == "__main__":
    asyncio.run(main())
