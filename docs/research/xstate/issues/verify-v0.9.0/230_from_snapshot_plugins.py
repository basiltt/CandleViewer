"""Verify #230 on v0.9.0/main: from_snapshot(plugins=...) registered before
admission runs, on both Interpreter and SyncInterpreter.

STANDALONE: stdlib + xstate_statemachine only. Neutral cwd <home>.
"""
import sys as _xs_sys  # noqa: E402
from pathlib import Path as _XsPath  # noqa: E402
_xs_sys.path.insert(0, str(_XsPath(__file__).resolve().parents[2] / "gate"))
from _paths import REPO_ROOT as _REPO, XSTATE_SRC as _XS, upstream_main_python as _xs_main_py  # noqa: E402,F401
import sys, json, asyncio

sys.path.insert(
    0,
    str(_XS / 'src'),
)
from xstate_statemachine import (  # noqa: E402
    create_machine, MachineLogic, SyncInterpreter, Interpreter, PluginBase,
)

CFG = {
    "id": "m", "initial": "w", "strict": True,
    "states": {"w": {"on": {"GO": "done_state"}}, "done_state": {"type": "final"}},
}


class Spy(PluginBase):
    def __init__(self):
        self.invalid = []

    def on_invalid_event(self, interpreter, exc, raw):
        self.invalid.append((exc, raw))


def make_snapshot_sync():
    m = create_machine(CFG, logic=MachineLogic())
    interp = SyncInterpreter(m).start()
    snap = json.loads(interp.get_snapshot())
    snap["pending_events"] = [{"type": "UNDECLARED", "payload": {}}]
    return json.dumps(snap), m


failures = []


def check_sync():
    snap, m = make_snapshot_sync()
    spy = Spy()
    restored = SyncInterpreter.from_snapshot(snap, m, plugins=[spy])
    ok = len(spy.invalid) == 1 and restored.last_error is not None
    print("sync: hook fired:", spy.invalid, "last_error:", restored.last_error, "ok:", ok)
    if not ok:
        failures.append("sync from_snapshot plugins= did not observe refusal")
    # no plugins= -> unaffected
    snap2, m2 = make_snapshot_sync()
    restored2 = SyncInterpreter.from_snapshot(snap2, m2)
    print("sync: no plugins= still works, last_error:", restored2.last_error)
    if restored2.last_error is None:
        failures.append("sync from_snapshot without plugins= regressed")


async def check_async():
    m = create_machine(CFG, logic=MachineLogic())
    interp = Interpreter(m)
    await interp.start()
    snap = json.loads(interp.get_snapshot())
    snap["pending_events"] = [{"type": "UNDECLARED", "payload": {}}]
    snap_s = json.dumps(snap)

    spy = Spy()
    restored = Interpreter.from_snapshot(snap_s, m, plugins=[spy])
    ok = len(spy.invalid) == 1 and restored.last_error is not None
    print("async: hook fired:", spy.invalid, "last_error:", restored.last_error, "ok:", ok)
    if not ok:
        failures.append("async from_snapshot plugins= did not observe refusal")

    restored2 = Interpreter.from_snapshot(snap_s, m)
    print("async: no plugins= still works, last_error:", restored2.last_error)
    if restored2.last_error is None:
        failures.append("async from_snapshot without plugins= regressed")


check_sync()
asyncio.run(check_async())

print()
print("FAILURES:", failures if failures else "none")
sys.exit(1 if failures else 0)
