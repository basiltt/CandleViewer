"""G4 — the in-flight flag covers start()'s initial descent (targets
R7-05/#182/#187). A snapshot attempt from inside the initial entry action
(both engines) must be REFUSED with SnapshotMidStepError, matching sync's
long-standing behavior -- not silently accepted and torn."""
from __future__ import annotations
import asyncio, logging, sys
logging.disable(logging.CRITICAL)
LIB = "<workspace>/_ref/xstate-statemachine/src"
if LIB not in sys.path:
    sys.path.insert(0, LIB)
from xstate_statemachine import Interpreter, SyncInterpreter, MachineLogic, create_machine  # noqa: E402
from xstate_statemachine.exceptions import SnapshotMidStepError  # noqa: E402

CFG = {
    "id": "init",
    "initial": "s",
    "context": {"qty": 0},
    "states": {"s": {"entry": ["fill_then_snap"]}},
}


def make_action(interp_holder, results, key):
    def action(i, c, e, a=None):
        c["qty"] = 1
        try:
            snap = interp_holder["i"].get_persisted_snapshot()
            results[key] = ("ACCEPTED", snap)
        except SnapshotMidStepError:
            results[key] = ("REFUSED", None)
        except Exception as ex:
            results[key] = ("OTHER_EXC:" + type(ex).__name__, None)
        c["qty"] = 999
    return action


async def run_async():
    holder = {}
    results = {}
    action = make_action(holder, results, "async")
    logic = MachineLogic(actions={"fill_then_snap": action})
    machine = create_machine(CFG, logic=logic)
    interp = Interpreter(machine)
    holder["i"] = interp
    await interp.start()
    await interp.stop()
    return results["async"][0], interp.context["qty"]


def run_sync():
    holder = {}
    results = {}
    action = make_action(holder, results, "sync")
    logic = MachineLogic(actions={"fill_then_snap": action})
    machine = create_machine(CFG, logic=logic)
    interp = SyncInterpreter(machine)
    holder["i"] = interp
    interp.start()
    interp.stop()
    return results["sync"][0], interp.context["qty"]


async def main():
    r_async, q_async = await run_async()
    r_sync, q_sync = run_sync()
    print("async initial-entry snapshot attempt:", r_async, "final qty:", q_async)
    print("sync  initial-entry snapshot attempt:", r_sync, "final qty:", q_sync)
    print("parity(both refused, both qty=999):", r_async == "REFUSED" and r_sync == "REFUSED" and q_async == 999 and q_sync == 999)


if __name__ == "__main__":
    asyncio.run(main())
