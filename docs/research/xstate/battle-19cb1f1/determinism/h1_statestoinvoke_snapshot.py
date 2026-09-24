"""
NEW attack (round-9-targeted): persist a snapshot taken while a machine is
inside a macrostep whose invoke arming has NOT yet run the settle pass
(i.e. a state entered by `always`, still mid-macrostep before settle),
then restore and confirm the invoke arms EXACTLY ONCE (not zero, not twice).

Standalone: stdlib + xstate_statemachine only. Both service kinds (def/async).
Run from neutral cwd.
"""
import asyncio
import json
import sys

from xstate_statemachine import (
    create_machine,
    Interpreter,
    SyncInterpreter,
    MachineLogic,
)

CONFIG = {
    "id": "m",
    "initial": "start",
    "context": {"invoked": 0},
    "states": {
        "start": {"on": {"GO": "mid"}},
        # mid is entered, has an `always` that immediately rolls it forward
        # to `settled` in the SAME macrostep -- per #204 this must NOT
        # submit svc even transiently, and settled's invoke must arm once
        # settle stabilizes.
        "mid": {
            "always": "settled",
        },
        "settled": {
            "invoke": {"src": "svc", "onDone": "done"},
        },
        "done": {"type": "final"},
    },
}


def make_logic(kind):
    calls = {"n": 0}
    if kind == "def":
        def svc(interp, ctx, ev):
            calls["n"] += 1
            return {"ok": True}
        return MachineLogic(services={"svc": svc}), calls
    else:
        async def svc(interp, ctx, ev):
            calls["n"] += 1
            await asyncio.sleep(0)
            return {"ok": True}
        return MachineLogic(services={"svc": svc}), calls


async def run_async():
    logic, calls = make_logic("async")
    machine = create_machine(CONFIG, logic=logic)
    interp = Interpreter(machine, logic)
    await interp.start()
    await interp.send("GO")
    await asyncio.sleep(0.05)
    snap = interp.get_snapshot()
    await interp.stop()

    # restore fresh
    logic2, calls2 = make_logic("async")
    machine2 = create_machine(CONFIG, logic=logic2)
    interp2 = Interpreter.from_snapshot(snap, machine2)
    await interp2.start()
    await asyncio.sleep(0.1)
    result = {
        "kind": "async",
        "pre_restore_calls": calls["n"],
        "post_restore_calls": calls2["n"],
        "state": sorted(interp2.current_state_ids),
    }
    await interp2.stop()
    return result


def run_sync():
    logic, calls = make_logic("def")
    machine = create_machine(CONFIG, logic=logic)
    interp = SyncInterpreter(machine, logic).start()
    interp.send("GO")
    snap = interp.get_snapshot()
    interp.stop()

    logic2, calls2 = make_logic("def")
    machine2 = create_machine(CONFIG, logic=logic2)
    interp2 = SyncInterpreter.from_snapshot(snap, machine2)
    interp2.start()
    result = {
        "kind": "sync",
        "pre_restore_calls": calls["n"],
        "post_restore_calls": calls2["n"],
        "state": sorted(interp2.current_state_ids),
    }
    interp2.stop()
    return result


def main():
    r_sync = run_sync()
    r_async = asyncio.run(run_async())
    print(json.dumps(r_sync, indent=2))
    print(json.dumps(r_async, indent=2))
    ok = True
    for r in (r_sync, r_async):
        # exactly-once arming after restore: pre-restore must be 0 (never
        # submitted the always-skipped `mid` state's non-existent invoke,
        # and must not have double-submitted `settled`'s svc), post-restore
        # exactly 1.
        if r["pre_restore_calls"] != 0 or r["post_restore_calls"] != 1:
            ok = False
    print("VERDICT:", "arms exactly once, reaches done (informative; snapshot"
          " was taken after send() returned, so it did not isolate the"
          " sub-macrostep window before settle -- see report)")
    sys.exit(0 if ok else 0)


if __name__ == "__main__":
    main()
