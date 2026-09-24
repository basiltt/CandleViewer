# -*- coding: utf-8 -*-
"""Minimal repro, no project machine: onUnhandled='error' stops the interpreter
but the triggering send(wait=True) receipt is indistinguishable from a no-op
and `last_error` stays None."""
import asyncio, json
from xstate_statemachine import Interpreter, MachineLogic, create_machine

CFG = {
    "id": "m",
    "onUnhandled": "error",
    "initial": "a",
    "states": {
        "a": {"on": {"GO": {"target": "#m.b"}}},
        "b": {"on": {"BACK": {"target": "#m.a"}}},
    },
}


async def main():
    m = create_machine(CFG, logic=MachineLogic())
    it = Interpreter(m)
    await it.start()
    await it.send("GO", wait=True)
    await asyncio.sleep(0.05)
    out = {"state_after_GO": sorted(it.current_state_ids),
           "running_before": it.is_running}
    # GO is not handled in state b -> onUnhandled='error'
    rc = await it.send("GO", wait=True)
    await asyncio.sleep(0.05)
    out["receipt_of_fatal_event"] = {
        "changed": rc.changed, "error": repr(rc.error),
        "deferred": rc.deferred, "state_ids": sorted(rc.state_ids)}
    out["running_after"] = it.is_running
    out["status_after"] = it.status
    out["last_error_after"] = repr(it.last_error)
    out["interpreter_error_after"] = repr(it.error)
    rc2 = await it.send("BACK", wait=True)
    out["next_receipt"] = {"changed": rc2.changed, "error": repr(rc2.error)}
    out["verdict"] = (
        "CONFIRMED (narrow): the receipt for the very event that killed the "
        "machine reports error=None, changed=False, deferred=False -- "
        "indistinguishable from a benign no-op. last_error is also None. "
        "The error IS observable, but only via interpreter.error / .status, "
        "which a send(wait=True) caller has no reason to poll."
        if rc.error is None and it.last_error is None
        and it.status == "error" and it.error is not None
        else "not reproduced as described")
    print(json.dumps(out, indent=1))


asyncio.run(main())
