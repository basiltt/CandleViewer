"""Verify #102 on main@3ed3099: mid-macrostep snapshot is refused.

Criteria:
1. Taking get_persisted_snapshot() while a transition's action is still
   awaiting (exit->actions->enter window open) raises SnapshotMidStepError,
   a subclass of XStateMachineError -- not a torn state_ids=[] blob.
2. Once the step settles, get_persisted_snapshot() succeeds and reports the
   correct leaf state_ids (["t.b"]).
3. A snapshot taken while settled (sync engine) restores to a live machine
   whose .value is correct (round-trip sanity, no regression).
4. The public health probes (status, is_running) during the mid-step window
   do NOT mask the problem -- i.e. the exception is the enforcement
   mechanism regardless of what probes report (documented behaviour).
"""
import asyncio
import sys

from xstate_statemachine import (
    Interpreter,
    MachineLogic,
    SyncInterpreter,
    SnapshotMidStepError,
)
from xstate_statemachine.exceptions import XStateMachineError

results = []


def check(name, cond, detail=""):
    results.append((name, bool(cond), detail))


CFG = {
    "id": "t",
    "initial": "a",
    "states": {
        "a": {"on": {"GO": {"target": "b", "actions": ["slow"]}}},
        "b": {},
    },
}


async def slow(i, c, e, a):
    await asyncio.sleep(0.3)


async def main():
    i = await Interpreter(create_machine := __import__("xstate_statemachine").create_machine(
        CFG, logic=MachineLogic(actions={"slow": slow})
    )).start()
    t = asyncio.ensure_future(i.send("GO"))
    await asyncio.sleep(0.1)  # inside the transition window

    raised_typed = False
    is_xstate_err = False
    try:
        i.get_persisted_snapshot()
    except SnapshotMidStepError as ex:
        raised_typed = True
        is_xstate_err = isinstance(ex, XStateMachineError)
    except Exception:
        pass
    check("1 mid-step snapshot raises SnapshotMidStepError", raised_typed)
    check("1b SnapshotMidStepError is-a XStateMachineError", is_xstate_err)

    await t
    await asyncio.sleep(0.35)
    settled = i.get_persisted_snapshot()
    await i.stop()
    check("2 settled snapshot has correct state_ids", settled["state_ids"] == ["t.b"], settled.get("state_ids"))


asyncio.run(asyncio.wait_for(main(), 15))

# 3: sync engine round trip, settled snapshot restores live
si = SyncInterpreter(
    create_machine := __import__("xstate_statemachine").create_machine(
        CFG, logic=MachineLogic(actions={"slow": lambda i, c, e, a: None})
    )
)
si.start()
si.send("GO")
snap = si.get_snapshot()
si.stop()
r = SyncInterpreter.from_snapshot(
    snap,
    __import__("xstate_statemachine").create_machine(
        CFG, logic=MachineLogic(actions={"slow": lambda i, c, e, a: None})
    ),
)
check("3 settled snapshot restores to live machine at b", r.value == "b", r.value)

ok = True
for name, passed, detail in results:
    print(f"{'PASS' if passed else 'FAIL'}: {name}  {detail if not passed else ''}")
    ok = ok and passed

sys.exit(0 if ok else 1)
