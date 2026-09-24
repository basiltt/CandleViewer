"""Verify #244: dropped_receipts increments + on_receipt_dropped fires when a
send(wait=True) receipt issued inside an action is never awaited.
Standalone; run with `python -W error 244_dropped_receipts.py`? We instead
assert programmatically since -W error would crash on the RuntimeWarning
we WANT to observe as a warnings.catch_warnings record (deterministic
signal per docstring is dropped_receipts/hook; warning may be unraisable).
"""
import asyncio
import gc
from xstate_statemachine import create_machine, Interpreter, MachineLogic
from xstate_statemachine.plugins import PluginBase

CFG = {
    "id": "m",
    "initial": "s1",
    "states": {
        "s1": {"on": {"A": {"target": "s2", "actions": ["fireAndForget"]}}},
        "s2": {"on": {"B": "s3"}},
        "s3": {"type": "final"},
    },
}


class Recorder(PluginBase):
    def __init__(self):
        self.fired = 0

    def on_receipt_dropped(self, interpreter, event_type):
        self.fired += 1


async def main():
    rec = Recorder()

    def fire_and_forget(interp, ctx, event, action):
        # Sync def action: cannot await. Fire wait=True and drop it.
        interp.send("B", wait=True)  # receipt discarded

    machine = create_machine(
        CFG, logic=MachineLogic(actions={"fireAndForget": fire_and_forget})
    )
    interp = Interpreter(machine)
    interp.use(rec)
    await interp.start()
    await interp.send("A", wait=True)
    # Force GC to trigger __del__ on the dropped receipt object.
    await asyncio.sleep(0.02)
    gc.collect()
    await interp.stop()

    assert interp.dropped_receipts >= 1, interp.dropped_receipts
    assert rec.fired >= 1, rec.fired
    print("OK #244", interp.dropped_receipts, rec.fired)


if __name__ == "__main__":
    import warnings

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        asyncio.run(main())
