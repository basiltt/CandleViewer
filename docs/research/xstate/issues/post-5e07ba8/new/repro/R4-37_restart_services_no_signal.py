"""R4-37: from_snapshot(restart_services=True) has no effect until start()
is called, with no signal in between.

Interpreter.from_snapshot(..., restart_services=True) only records the
intent (`_restart_services_on_start`); the actual re-invocation of dormant
services happens inside start(). In between those two calls, `status`
already reads "running" while `has_dormant_invocations` is still True --
a caller who checks dormancy before calling start() sees a contradictory
pair (status says running, but the dormant invoke has not actually been
restarted).

Exits 1 (defect present) if, immediately after from_snapshot(restart_services=True)
and before start(), status == "running" AND has_dormant_invocations is True.
Exits 0 once that ordering no longer produces a contradictory pair.
"""
import asyncio
import json
import sys

from xstate_statemachine import Interpreter, MachineLogic, create_machine


async def main() -> int:
    async def slow_service(interp, ctx, ev):
        await asyncio.sleep(100)
        return "done"

    cfg = {
        "id": "m_dormant",
        "initial": "a",
        "states": {"a": {"invoke": {"src": "slow_service", "id": "svc"}}},
    }
    logic = MachineLogic(services={"slow_service": slow_service})
    machine = create_machine(cfg, logic=logic)

    interp = Interpreter(machine)
    await interp.start()
    snap = json.dumps(interp.get_persisted_snapshot())
    await interp.stop()

    restored = Interpreter.from_snapshot(snap, machine, restart_services=True)

    status_before_start = restored.status
    dormant_before_start = restored.has_dormant_invocations

    print("OBSERVED (after from_snapshot(restart_services=True), before start()):")
    print(f"  status                    = {status_before_start!r}")
    print(f"  has_dormant_invocations   = {dormant_before_start!r}")

    print(
        "\nEXPECTED: status should not read 'running' while dormant "
        "invocations have not yet been restarted -- the two signals should "
        "not contradict each other before start() runs"
    )

    await restored.start()
    await asyncio.sleep(0.05)
    print(f"\nAfter start(): has_dormant_invocations = {restored.has_dormant_invocations}")
    await restored.stop()

    defect_present = (status_before_start == "running") and dormant_before_start
    if defect_present:
        print("\nRESULT: contradictory pair observed before start() -- defect present")
        return 1
    else:
        print("\nRESULT: no contradiction -- fixed")
        return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
