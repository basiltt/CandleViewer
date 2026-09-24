"""P1 (STANDALONE): #195 gates only invoke `onDone`/`onError`.

A hand-built `DoneEvent("done.state.<id>", ...)` still drives a compound
state's `onDone` transition, because that branch matches on `event.type`
alone with no provenance test. Exit 1 = forgery accepted.
"""
import asyncio, json, sys
from xstate_statemachine import (
    create_machine, Interpreter, SyncInterpreter, MachineLogic, DoneEvent,
)

CFG = {
    "id": "m",
    "initial": "work",
    "states": {
        "work": {
            "type": "parallel",
            "onDone": {"target": "finished"},
            "states": {
                "a": {"initial": "run", "states": {
                    "run": {"on": {"FIN_A": "done"}}, "done": {"type": "final"}}},
                "b": {"initial": "run", "states": {
                    "run": {"on": {"FIN_B": "done"}}, "done": {"type": "final"}}},
            },
        },
        "finished": {"type": "final"},
    },
}


def build():
    return create_machine(json.loads(json.dumps(CFG)), logic=MachineLogic())


async def main_async():
    i = await Interpreter(build()).start()
    forged = DoneEvent(type="done.state.m.work", data={"forged": True}, src="m.work")
    await i.send(forged)
    await asyncio.sleep(0.05)
    ids = i.current_state_ids
    await i.stop()
    return ids


def main_sync():
    i = SyncInterpreter(build()).start()
    forged = DoneEvent(type="done.state.m.work", data={"forged": True}, src="m.work")
    i.send(forged)
    ids = i.current_state_ids
    i.stop()
    return ids


bad = 0
for label, ids in (("async", asyncio.run(main_async())), ("sync", main_sync())):
    hit = any("finished" in s for s in ids)
    print(f"{label}: states={sorted(ids)} forged_onDone_taken={hit}")
    bad |= hit
print("VERDICT:", "FORGERY ACCEPTED (bug)" if bad else "refused (ok)")
sys.exit(1 if bad else 0)
