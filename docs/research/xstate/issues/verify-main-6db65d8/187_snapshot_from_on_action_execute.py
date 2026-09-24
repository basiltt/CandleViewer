"""Verify #187: on_action_execute is inside the mid-step snapshot refusal
window on BOTH engines, def and async def actions."""
import asyncio
from xstate_statemachine import (
    create_machine,
    Interpreter,
    SyncInterpreter,
    PluginBase,
    MachineLogic,
)
from xstate_statemachine.exceptions import SnapshotMidStepError

CONFIG = {
    "id": "m",
    "initial": "a",
    "context": {},
    "states": {
        "a": {"on": {"GO": {"target": "b", "actions": ["act"]}}},
        "b": {"type": "final"},
    },
}


def sync_act(interp, event):
    pass


async def async_act(interp, event):
    pass


class Capture(PluginBase):
    def __init__(self):
        self.result = None

    def on_action_execute(self, interp, action_def):
        try:
            interp.get_persisted_snapshot()
            self.result = "accepted"
        except SnapshotMidStepError:
            self.result = "refused"


def run_sync(action_fn):
    logic = MachineLogic(actions={"act": action_fn})
    machine = create_machine(CONFIG, logic=logic)
    interp = SyncInterpreter(machine)
    cap = Capture()
    interp.use(cap)
    interp.start()
    interp.send("GO")
    return cap.result


async def run_async(action_fn):
    logic = MachineLogic(actions={"act": action_fn})
    machine = create_machine(CONFIG, logic=logic)
    interp = Interpreter(machine)
    cap = Capture()
    interp.use(cap)
    await interp.start()
    await interp.send("GO", wait=True)
    return cap.result


def main():
    cells = {}
    cells["SyncInterpreter/def-action"] = run_sync(sync_act)
    # SyncInterpreter does not support async def actions (NotSupportedError) -
    # that's an orthogonal, expected restriction, not part of #187.
    cells["Interpreter/def-action"] = asyncio.run(run_async(sync_act))
    cells["Interpreter/async-def-action"] = asyncio.run(run_async(async_act))

    ok = all(v == "refused" for v in cells.values())
    print("cell table:")
    for k, v in cells.items():
        print(f"  {k}: {v}")
    print("ALL PASS" if ok else "FAIL")
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
