"""P4 (STANDALONE): #196 turns events an `always` used to absorb into
UNHANDLED events.

Before #196 an eventless transition was an eligible candidate for a named
event, so a chart of the shape

    s1: { always: {target: s2, cond: g} }   # g false for now
    (no `on` handler for PING anywhere)

had `PING` "handled" (a transition was selected and evaluated), and
`onUnhandled: "error"` / `strict` never fired. Now the always is eligible
only in the settle pass, so the same PING is an unhandled event.

Prints whether the policy fires. Exit 1 if the policy fires (behaviour
change vs 6db65d8 that the changelog does not call out as a compat note).
"""
import asyncio, json, sys
from xstate_statemachine import (
    create_machine, Interpreter, SyncInterpreter, MachineLogic,
    UnhandledEventError,
)

CFG = {
    "id": "m",
    "initial": "s1",
    "onUnhandled": "error",
    "states": {
        "s1": {"always": [{"target": "s2", "cond": "ready"}]},
        "s2": {},
    },
}


def build():
    return create_machine(
        json.loads(json.dumps(CFG)),
        logic=MachineLogic(guards={"ready": lambda c, e: False}),
    )


async def run_async():
    i = await Interpreter(build()).start()
    try:
        await i.send("PING")
        await asyncio.sleep(0.05)
        err = type(i.last_error).__name__ if i.last_error else None
    finally:
        await i.stop()
    return err


def run_sync():
    i = SyncInterpreter(build()).start()
    try:
        i.send("PING")
        return None
    except UnhandledEventError as exc:
        return type(exc).__name__
    finally:
        i.stop()


a, s = asyncio.run(run_async()), run_sync()
print(f"async last_error={a}")
print(f"sync raised={s}")
bad = bool(a or s)
print("VERDICT:", "UNHANDLED NOW FIRES (behaviour change)" if bad else "absorbed (ok)")
sys.exit(1 if bad else 0)
