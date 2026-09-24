"""G-10: teardown of invoked children on (a) parent stop(), (b) rollback of
the transition that entered the invoking state."""
import asyncio, gc
from xstate_statemachine import MachineLogic, create_machine
from xstate_statemachine.interpreter import Interpreter

LONG_CHILD = {"id": "c", "initial": "w", "states": {"w": {"after": {100000: "fin"}}, "fin": {"type": "final"}}}

async def main():
    # (a) parent stop() while a child is live
    child = create_machine(LONG_CHILD, logic=MachineLogic())
    m = create_machine({"id": "p", "initial": "w", "states": {
        "w": {"invoke": {"src": "kid", "id": "kid"}}}},
        logic=MachineLogic(services={"kid": child}))
    it = await Interpreter(m).start()
    await asyncio.sleep(0.1)
    kids = list(it._actors.values())
    print("a) live children:", len(kids), "tasks:", len(asyncio.all_tasks()))
    await it.stop()
    await asyncio.sleep(0.1); gc.collect()
    print("a) after parent stop(): child statuses", [k.status for k in kids],
          "tasks:", len(asyncio.all_tasks()), "(expect 1 = main)")

    # (b) rollback of the entering transition
    def boom(i, c, e): raise ValueError("entry action boom")
    child2 = create_machine(LONG_CHILD, logic=MachineLogic())
    m2 = create_machine({"id": "q", "actionErrorPolicy": "rollback",
        "initial": "idle", "states": {
            "idle": {"on": {"GO": "w"}},
            "w": {"entry": ["boom"], "invoke": {"src": "kid", "id": "kid"}}}},
        logic=MachineLogic(services={"kid": child2}, actions={"boom": boom}))
    it2 = await Interpreter(m2).start()
    base = len(asyncio.all_tasks())
    await it2.send("GO"); await asyncio.sleep(0.2); gc.collect()
    print(f"b) after rolled-back GO: state={set(it2.current_state_ids)} "
          f"_actors={len(it2._actors)} _invoked_children={dict((k,len(v)) for k,v in it2._invoked_children.items())} "
          f"tasks={len(asyncio.all_tasks())} (base {base})")
    for aid, a in it2._actors.items():
        print("   ORPHAN actor:", aid, a.status)
    await it2.stop()

asyncio.run(main())
