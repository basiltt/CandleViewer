# -*- coding: utf-8 -*-
"""Verify #105 on 3ed3099: external `send()` during an in-flight step must
not be charged to the self-raised chain budget (maxIterations).

Acceptance criteria (from issue #105 body + CHANGELOG [Unreleased]):
  1. An external `await interp.send(...)` issued while a macrostep from a
     slow action is in flight must be delivered/applied, not silently
     dropped for "chain_budget" reasons, even when the burst count exceeds
     `maxIterations`.
  2. No `on_event_dropped(reason="chain_budget")` fires for these external
     sends.
  3. An action calling `await i.send(...)` on ITS OWN interpreter (a true
     self-send / self-feeding loop) must still be budgeted/bounded --
     the fix must not remove the runaway-chain protection entirely.

Exits 0 only if all criteria pass.
"""
from __future__ import annotations

import asyncio
import logging
import sys

from xstate_statemachine import Interpreter, MachineLogic, create_machine
from xstate_statemachine.plugins import PluginBase

logging.disable(logging.CRITICAL)


class DropSpy(PluginBase):
    def __init__(self):
        self.drops = []

    def on_event_dropped(self, interp, event, reason):
        self.drops.append((getattr(event, "type", event), reason))


async def criterion_1_and_2(burst: int) -> tuple[bool, bool, int, int]:
    cfg = {
        "id": "m",
        "initial": "a",
        "context": {"n": 0},
        "maxIterations": 10,  # deliberately tiny; must not affect external traffic
        "states": {
            "a": {
                "on": {
                    "SLOW": {"actions": ["slow"]},
                    "T": {"actions": ["inc"]},
                }
            }
        },
    }

    def inc(i, c, e, a):
        c["n"] += 1

    async def slow(i, c, e, a):
        await asyncio.sleep(0.3)

    spy = DropSpy()
    machine = create_machine(cfg, logic=MachineLogic(actions={"inc": inc, "slow": slow}))
    interp = Interpreter(machine)
    interp.use(spy)
    await interp.start()

    t = asyncio.ensure_future(interp.send("SLOW"))
    await asyncio.sleep(0.03)
    for _ in range(burst):
        await interp.send("T")
    await t
    await asyncio.sleep(0.5)

    applied = interp.context["n"]
    chain_budget_drops = [r for _, r in spy.drops if r == "chain_budget"]
    await interp.stop()
    return applied == burst, len(chain_budget_drops) == 0, applied, len(chain_budget_drops)


async def criterion_3_self_send_still_budgeted() -> tuple[bool, int]:
    cfg = {
        "id": "m2",
        "initial": "a",
        "context": {"n": 0},
        "maxIterations": 20,
        "states": {"a": {"on": {"LOOP": {"actions": ["ss"]}}}},
    }

    async def ss(i, c, e, a):
        c["n"] += 1
        await i.send("LOOP")

    interp = await Interpreter(
        create_machine(cfg, logic=MachineLogic(actions={"ss": ss}))
    ).start()
    await interp.send("LOOP")
    await asyncio.sleep(0.5)
    n = interp.context["n"]
    await interp.stop()
    # A genuine self-feeding loop must still be bounded (well under
    # unbounded growth); allow generous slack above maxIterations.
    return n <= 40, n


async def main() -> int:
    failures = []

    for burst in (999, 1500, 3000):
        ok_applied, ok_no_drop, applied, drops = await criterion_1_and_2(burst)
        print(
            f"[criterion 1/2] burst={burst:<5} applied={applied:<5} "
            f"chain_budget_drops={drops:<3} -> "
            f"{'OK' if (ok_applied and ok_no_drop) else 'FAIL'}"
        )
        if not ok_applied:
            failures.append(f"burst={burst}: applied {applied} != {burst} (events lost)")
        if not ok_no_drop:
            failures.append(f"burst={burst}: chain_budget drops={drops} (expected 0)")

    ok3, n3 = await criterion_3_self_send_still_budgeted()
    print(f"[criterion 3] self-send loop n={n3} -> {'OK' if ok3 else 'FAIL'}")
    if not ok3:
        failures.append(f"self-send loop not bounded: n={n3}")

    if failures:
        print("FAILURES:")
        for f in failures:
            print(" -", f)
        return 1
    print("ALL CRITERIA PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
