# -*- coding: utf-8 -*-
"""R5-01 refutation attempt: reach the torn snapshot WITHOUT calling
get_persisted_snapshot() from inside an action.

A plain asyncio monitoring task (the documented way to observe a running
actor) snapshots while a macrostep is in flight in ONE region of a parallel
state. No plugin hook, no action re-entrancy, no mandatory-config omission.
"""
import asyncio, json
from xstate_statemachine import create_machine, MachineLogic, Interpreter
from xstate_statemachine.exceptions import XStateMachineError

CFG = {
    "id": "oms", "type": "parallel",
    "states": {
        "exchange": {"initial": "idle", "states": {
            "idle": {"on": {"GO": "working"}},
            "working": {"entry": ["slow_book"], "on": {"FILL": "filled"}},
            "filled": {"type": "final"}}},
        "risk": {"initial": "ok", "states": {"ok": {}}},
    },
}

async def main():
    gate = asyncio.Event()
    async def slow_book(i, c, e, ad=None):
        c["booked"] = False
        gate.set()
        await asyncio.sleep(0.05)   # long entry action: step still in flight
        c["booked"] = True          # context completed only here

    m = create_machine(CFG, logic=MachineLogic(actions={"slow_book": slow_book}))
    i = await Interpreter(m).start()

    async def observer():
        await gate.wait()
        await asyncio.sleep(0.005)
        try:
            return ("ACCEPTED", i.get_persisted_snapshot())
        except XStateMachineError as ex:
            return ("REFUSED:" + type(ex).__name__, None)

    t = asyncio.create_task(observer())
    await i.send("GO", wait=True)
    verdict, snap = await t
    print("observer snapshot :", verdict)
    if snap:
        print("   state_ids      =", snap["state_ids"])
        print("   context        =", snap["context"])
    print("live after settle :", sorted(i.current_state_ids), i.context)
    await i.stop()

    if snap:
        r = Interpreter.from_snapshot(json.dumps(snap, default=str),
                                      create_machine(CFG, logic=MachineLogic(actions={"slow_book": slow_book})))
        await r.start(); await asyncio.sleep(0.02)
        print("restored          :", sorted(r.current_state_ids), r.context, "status=", r.status)
        await r.stop()

asyncio.run(main())
