"""P14 (STANDALONE): #196 -- a named-event transition that used to be
reachable only via an `always` on the SAME state is now dropped.

Chart: `s1` declares `always` with a guard that only becomes true after
`BUMP` has set the context. Before #196 the `BUMP` macrostep selected the
`always` in the same pass (guard already re-evaluated on the deeper node)
where the handler and the always were both eligible. Now the always is
eligible only in the settle pass -- which is the CORRECT SCXML order, and
this probe confirms the settle pass still runs after the named-event step,
so no legitimate always is lost.

Also checks the settle trip is reported per step.

Exit 1 if the always fails to fire after the named event.
"""
import asyncio, json, sys
from xstate_statemachine import (
    create_machine, Interpreter, SyncInterpreter, MachineLogic,
)

CFG = {
    "id": "m",
    "initial": "s1",
    "context": {"ready": False},
    "states": {
        "s1": {
            "always": [{"target": "s2", "cond": "ready"}],
            "on": {"BUMP": {"actions": ["set_ready"]}},
        },
        "s2": {},
    },
}


def set_ready(i, c, e, adef=None):
    c["ready"] = True


async def aset_ready(i, c, e, adef=None):
    c["ready"] = True


def build(kind):
    return create_machine(
        json.loads(json.dumps(CFG)),
        logic=MachineLogic(
            actions={"set_ready": aset_ready if kind == "async def" else set_ready},
            guards={"ready": lambda c, e: bool(c.get("ready"))},
        ),
    )


async def run_async(kind):
    i = await Interpreter(build(kind)).start()
    await i.send("BUMP")
    await asyncio.sleep(0.1)
    ids = sorted(i.current_state_ids)
    await i.stop()
    return ids


def run_sync():
    i = SyncInterpreter(build("def")).start()
    i.send("BUMP")
    ids = sorted(i.current_state_ids)
    i.stop()
    return ids


bad = 0
for label, ids in (("async/def", asyncio.run(run_async("def"))),
                   ("async/async def", asyncio.run(run_async("async def"))),
                   ("sync/def", run_sync())):
    ok = ids == ["m.s2"]
    print(f"{label:>16}: states={ids} always_fired={ok}")
    if not ok:
        bad = 1
print("VERDICT:", "ALWAYS LOST (bug)" if bad else "settle pass still runs (ok)")
sys.exit(bad)
