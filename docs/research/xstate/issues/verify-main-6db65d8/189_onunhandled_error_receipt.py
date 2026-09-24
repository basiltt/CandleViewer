"""Verify #189: onUnhandled:"error" kill is visible on the sender's Receipt
on both engines, with def and async def actions present in the chart."""
import asyncio
from xstate_statemachine import (
    create_machine,
    Interpreter,
    SyncInterpreter,
    MachineLogic,
)


def make_cfg():
    return {
        "id": "m",
        "initial": "a",
        "context": {},
        "onUnhandled": "error",
        "states": {"a": {"entry": ["act"]}},
    }


def sync_act(interp, event):
    pass


async def async_act(interp, event):
    pass


def run_sync(action_fn):
    logic = MachineLogic(actions={"act": action_fn})
    machine = create_machine(make_cfg(), logic=logic)
    interp = SyncInterpreter(machine)
    interp.start()
    before = interp.status == "running"
    receipt = interp.send("UNKNOWN_EVENT", wait=True)
    after = interp.status == "running"
    return before, after, receipt


async def run_async(action_fn):
    logic = MachineLogic(actions={"act": action_fn})
    machine = create_machine(make_cfg(), logic=logic)
    interp = Interpreter(machine)
    await interp.start()
    before = interp.status == "running"
    receipt = await interp.send("UNKNOWN_EVENT", wait=True)
    after = interp.status == "running"
    return before, after, receipt


def check(before, after, receipt):
    return (
        before is True
        and after is False
        and receipt.error is not None
        and "UNKNOWN_EVENT" in str(receipt.error)
    )


def main():
    cells = {}
    cells["SyncInterpreter/def-action"] = run_sync(sync_act)
    cells["Interpreter/def-action"] = asyncio.run(run_async(sync_act))
    cells["Interpreter/async-def-action"] = asyncio.run(run_async(async_act))
    # SyncInterpreter cannot run async def actions (NotSupportedError) -
    # orthogonal restriction, not part of #189.

    print("cell table:")
    all_ok = True
    for k, (before, after, receipt) in cells.items():
        ok = check(before, after, receipt)
        all_ok &= ok
        print(f"  {k}: before={before} after={after} receipt.error={receipt.error!r} -> {'PASS' if ok else 'FAIL'}")

    print("ALL PASS" if all_ok else "FAIL")
    raise SystemExit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
