"""Standalone verify #239: drain_pending drains both lanes, priority first,
and fails a wait=True receipt on a drained event with InterpreterStoppedError.
Run from neutral cwd <home>.
"""
import asyncio
from xstate_statemachine import create_machine, Interpreter
from xstate_statemachine.exceptions import InterpreterStoppedError

CFG = {"id": "m", "initial": "a", "states": {"a": {"on": {"GO": "b"}}, "b": {}}}


async def main():
    machine = create_machine(CFG)
    interp = Interpreter(machine)
    await interp.start()
    # No `await` occurs between these calls, so the cooperative run-loop
    # task never gets a turn to process anything before drain_pending().
    interp.send("PLAIN1", wait=False)
    receipt_fut = asyncio.ensure_future(interp.send_priority("PRIO_WAIT", wait=True))
    interp.send("PLAIN2", wait=False)

    drained = await interp.drain_pending()
    names = [getattr(ev, "type", None) or ev[0] for ev in drained]
    print("drained:", names)
    assert "PRIO_WAIT" in names, f"priority lane not drained: {names}"
    assert len(interp._priority_queue) == 0, "priority queue not cleared"
    assert names.index("PRIO_WAIT") < names.index("PLAIN1"), "priority not first"

    try:
        receipt = await asyncio.wait_for(receipt_fut, timeout=5)
    except InterpreterStoppedError:
        print("OK: wait=True receipt future raised InterpreterStoppedError")
    else:
        assert isinstance(receipt.error, InterpreterStoppedError), (
            f"FAIL: receipt.error is {receipt.error!r}, expected InterpreterStoppedError"
        )
        print("OK: wait=True receipt resolved with Receipt.error=InterpreterStoppedError")
    await interp.stop()
    print("PASS #239")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
