"""R5-10 repro: under `guardErrorPolicy: "raise"`, a guard that raises on an
ENGINE-DRIVEN transition (`invoke.onDone`) also cancels every LOWER-PRIORITY
candidate in the same array, so an unguarded fallback is never taken and the
completion event is dropped with no retry. Control: the identical machine
under the default `"false"` takes the fallback. The region is NOT wedged and
the failure IS observable; the defect is the lost fallback branch, which
`docs/_guide/guards.md` does not document.

Exits 1 while present, 0 once fixed. Stdlib + xstate_statemachine only.
"""

import asyncio
import logging
import sys

from xstate_statemachine import Interpreter, MachineLogic, create_machine


def gboom(c, e):
    raise RuntimeError("guardboom")


async def svc(i, c, e):
    return {"ok": True}


def cfg(policy: str):
    return {
        "id": "ld", "initial": "verifying",
        # mandatory config block
        "actionErrorPolicy": "rollback", "guardErrorPolicy": policy,
        "onUnhandled": "ignore", "strictTargets": True, "strict": False,
        "spawnBlockingTimeout": 5.0,
        "states": {
            "verifying": {"invoke": {"id": "ver", "src": "svc", "onDone": [
                {"target": "accepted", "guard": "risk_ok"},
                {"target": "rejected"},  # unguarded fallback
            ]}},
            "accepted": {}, "rejected": {},
        },
    }


async def run(policy: str):
    i = Interpreter(
        create_machine(
            cfg(policy),
            logic=MachineLogic(services={"svc": svc}, guards={"risk_ok": gboom}),
        )
    )
    await i.start()
    await asyncio.sleep(0.3)
    out = (sorted(i.current_state_ids), i.status, i.last_transition_ok,
           i.has_dormant_invocations)
    await i.stop()
    return out


async def main() -> int:
    r_ids, r_status, r_ok, r_dormant = await run("raise")
    f_ids, _, f_ok, f_dormant = await run("false")

    print("OBSERVED:")
    print('  guardErrorPolicy="raise"  ids=%s status=%s last_ok=%s dormant=%s'
          % (r_ids, r_status, r_ok, r_dormant))
    print('  guardErrorPolicy="false"  ids=%s last_ok=%s dormant=%s  (control)'
          % (f_ids, f_ok, f_dormant))
    print("EXPECTED:")
    print("  a raising guard makes ITS candidate unselectable; the next")
    print("  candidate is still evaluated, so both policies reach")
    print("  ['ld.rejected'] (or `raise`'s cancellation of the remaining")
    print("  candidates is documented in guards.md).")

    if r_ids == ["ld.verifying"] and f_ids == ["ld.rejected"]:
        print("RESULT: FAIL - `raise` cancelled the unguarded fallback "
              "candidate and dropped the completion event")
        return 1
    print("RESULT: PASS")
    return 0


if __name__ == "__main__":
    logging.disable(logging.CRITICAL)
    sys.exit(asyncio.run(main()))
