"""P2 (STANDALONE): #195 does not gate `after` transitions.

A hand-built `AfterEvent("after.60000.m.waiting")` fires the timer
transition instantly on both engines: the `after` branch of the selection
loop matches `isinstance(event, AfterEvent)` + name, with no provenance
test. Exit 1 = forged timer accepted.
"""
import asyncio, json, sys
from xstate_statemachine import (
    create_machine, Interpreter, SyncInterpreter, MachineLogic, AfterEvent,
)

CFG = {
    "id": "m",
    "initial": "waiting",
    "states": {
        "waiting": {"after": {"60000": {"target": "expired"}}},
        "expired": {},
    },
}


def build():
    return create_machine(json.loads(json.dumps(CFG)), logic=MachineLogic())


def forged():
    return AfterEvent(type="after.60000.m.waiting", scheduled_for=None, fired_at=None)


async def run_async():
    i = await Interpreter(build()).start()
    await i.send(forged())
    await asyncio.sleep(0.05)
    ids = set(i.current_state_ids)
    await i.stop()
    return ids


def run_sync():
    i = SyncInterpreter(build()).start()
    i.send(forged())
    ids = set(i.current_state_ids)
    i.stop()
    return ids


bad = 0
for label, ids in (("async", asyncio.run(run_async())), ("sync", run_sync())):
    hit = "m.expired" in ids
    print(f"{label}: states={sorted(ids)} forged_timer_fired={hit}")
    bad |= hit
print("VERDICT:", "FORGED TIMER ACCEPTED (bug)" if bad else "refused (ok)")
sys.exit(1 if bad else 0)
