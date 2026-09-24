"""Standalone verify #240: on_interpreter_start fires on every start() path
(fresh + restored) for both Interpreter and SyncInterpreter, and
interp.restored_from_snapshot reflects the correct bool."""
import asyncio
from xstate_statemachine import create_machine, Interpreter, SyncInterpreter

CFG = {"id": "m", "initial": "a", "states": {"a": {"on": {"GO": "b"}}, "b": {}}}


class Recorder:
    def __init__(self):
        self.calls = []

    def on_interpreter_start(self, interp):
        self.calls.append(interp.restored_from_snapshot)


async def check_async():
    machine = create_machine(CFG)
    rec = Recorder()
    interp = Interpreter(machine)
    interp.use(rec)
    await interp.start()
    assert rec.calls == [False], f"fresh async: {rec.calls}"
    snap = interp.get_snapshot()
    await interp.stop()

    rec2 = Recorder()
    restored = Interpreter.from_snapshot(snap, machine, plugins=[rec2])
    await restored.start()
    assert rec2.calls == [True], f"restored async: {rec2.calls}"
    assert restored.restored_from_snapshot is True
    await restored.stop()

    # .use() path on a restored interpreter too
    rec3 = Recorder()
    restored2 = Interpreter.from_snapshot(snap, machine)
    restored2.use(rec3)
    await restored2.start()
    assert rec3.calls == [True], f".use() restored: {rec3.calls}"
    await restored2.stop()
    print("PASS async #240")


def check_sync():
    machine = create_machine(CFG)
    rec = Recorder()
    interp = SyncInterpreter(machine)
    interp.use(rec)
    interp.start()
    assert rec.calls == [False], f"fresh sync: {rec.calls}"
    snap = interp.get_snapshot()
    interp.stop()

    rec2 = Recorder()
    restored = SyncInterpreter.from_snapshot(snap, machine, plugins=[rec2])
    restored.start()
    assert rec2.calls == [True], f"restored sync: {rec2.calls}"
    assert restored.restored_from_snapshot is True
    restored.stop()
    print("PASS sync #240")


if __name__ == "__main__":
    asyncio.run(check_async())
    check_sync()
    print("PASS #240")
