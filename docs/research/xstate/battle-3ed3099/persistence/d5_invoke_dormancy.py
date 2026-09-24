# -*- coding: utf-8 -*-
"""D-persistence-5: `has_dormant_invocations` is False on a LIVE machine
whose invoke is genuinely in flight, but True on the SAME machine restored
before `start()` -- and the restored value is right for the wrong reason.

More importantly: after `start()` with the default static restore, the
invoke stays dormant forever with NO further signal, and after
`restart_services=True` the service is re-run from scratch -- which for the
order path means a second exchange submission unless the caller supplies an
idempotency key.

This script documents the exact observable surface at each step, because
CV-C07 (reconcile invokes on restore) has to be built on it.
"""
from __future__ import annotations

import asyncio
import json

from xstate_statemachine import Interpreter
from xstate_statemachine.clock import SimulatedClock

import order_machine
from harness import attach_clock


async def main() -> None:
    gate = asyncio.Event()
    calls: list[str] = []

    async def gated(interp, ctx, event):  # noqa: ANN001
        calls.append("invoked")
        await gate.wait()
        return {"ack": len(calls)}

    i = await Interpreter(
        order_machine.build(ack=gated), clock=SimulatedClock()
    ).start()
    await asyncio.sleep(0.02)
    await i.send("SUBMIT", qty=1)
    await asyncio.sleep(0.05)
    print("LIVE, invoke genuinely in flight:")
    print("   states                 =", sorted(i.current_state_ids))
    print("   status                 =", i.status)
    print("   has_dormant_invocations=", i.has_dormant_invocations)
    print("   pending_invocations    =", i.pending_invocations())
    print("   service calls          =", len(calls))
    blob = i.get_snapshot()
    d = json.loads(blob)
    print("   snapshot records the invoke? ->",
          [k for k in d if "invo" in k.lower()] or "NO KEY FOR INVOKES")
    await i.stop()

    for restart in (False, True):
        print(f"\nRESTORED restart_services={restart}:")
        i2 = Interpreter.from_snapshot(
            blob, order_machine.build(ack=gated), restart_services=restart
        )
        attach_clock(i2, SimulatedClock())
        print("   pre-start  dormant =", i2.has_dormant_invocations,
              "pending =", [tuple(p) for p in i2.pending_invocations()])
        await i2.start()
        await asyncio.sleep(0.05)
        print("   post-start dormant =", i2.has_dormant_invocations,
              "status =", i2.status,
              "service calls =", len(calls))
        if not restart:
            # the order sits here forever with no signal beyond the boolean
            await asyncio.sleep(0.1)
            print("   after 100 ms idle: states =",
                  sorted(i2.current_state_ids),
                  "dormant =", i2.has_dormant_invocations)
        await i2.stop()
    gate.set()
    print("\n   NOTE: restart_services=True re-ran the exchange call "
          "(calls went up).")
    print("   The library documents this; CV-C07 must carry an idempotency "
          "key.")


if __name__ == "__main__":
    asyncio.run(main())
