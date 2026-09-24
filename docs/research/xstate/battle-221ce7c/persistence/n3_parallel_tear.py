# -*- coding: utf-8 -*-
"""N3 -- the #102 guard is `any(leaf)`, not `one leaf per region`.

`d3_torn_snapshot.py` (D-persistence-3, the 5e07ba8 Blocker) is FIXED: a
snapshot taken with a globally empty configuration now raises
`SnapshotMidStepError`.

`d3b_partial_parallel.py` (D-persistence-3b) is NOT. The guard is

    base_interpreter.py:1112  _active_leaf_present()
        return any(not node.states or node.is_final
                   for node in self._active_state_nodes
                   if node is not self.machine)

`any`. In a PARALLEL state, a macrostep that is mid-way through entering or
leaving ONE region leaves the other region's leaf active -- so
`_active_leaf_present()` is True, the guard passes, and the snapshot records
a configuration with a whole region missing. That blob restores without
error (`check_shape` only tests "running implies a non-empty list") and the
restored machine silently defers every event belonging to the absent region.

This script is the quantified version of `t6_action_boundary.py`: take a
snapshot at each action boundary of many randomised runs and classify the
result into legal / refused / TORN-MISSING-REGION.

usage: n3_parallel_tear.py [N_RUNS]
"""
from __future__ import annotations

import asyncio
import json
import random
import sys

from xstate_statemachine import Interpreter
from xstate_statemachine.clock import SimulatedClock
from xstate_statemachine.exceptions import SnapshotMidStepError
from xstate_statemachine.plugins import PluginBase

import order_machine

POOL = ["SUBMIT", "RISK_OK", "RISK_BLOCK", "FILL", "DONE", "CANCEL",
        "ACK_OK", "STALE", "REJECT"]

# order.submitted is parallel with regions `exchange` and `risk`.
PARALLEL = "order.submitted"
REGIONS = ("order.submitted.exchange", "order.submitted.risk")


class SnapAtNth(PluginBase):
    """Snapshot at the n-th executed action (public hook, no monkeypatching)."""

    def __init__(self, n: int) -> None:
        self.n = n
        self.count = 0
        self.result: tuple[str, object] | None = None

    def on_action_execute(self, interp, action):  # noqa: ANN001
        self.count += 1
        if self.count != self.n or self.result is not None:
            return
        try:
            self.result = ("ok", interp.get_snapshot())
        except SnapshotMidStepError:
            self.result = ("refused", None)
        except Exception as exc:  # noqa: BLE001
            self.result = ("raised", f"{type(exc).__name__}: {exc}")


def classify(blob: str) -> str:
    d = json.loads(blob)
    cfg = set(d.get("configuration") or [])
    if not d["state_ids"]:
        return "EMPTY"
    if PARALLEL in cfg:
        missing = [r for r in REGIONS if r not in cfg]
        if missing:
            return "MISSING_REGION"
        # each region must contribute exactly one active leaf
        for r in REGIONS:
            leaves = [s for s in d["state_ids"] if s.startswith(r + ".")]
            if len(leaves) != 1:
                return "MISSING_REGION"
    return "legal"


async def one_run(rng: random.Random) -> str | None:
    seq = [rng.choice(POOL) for _ in range(rng.randint(2, 6))]
    seq.insert(0, "SUBMIT")
    plug = SnapAtNth(rng.randint(1, 8))
    i = Interpreter(order_machine.build(), clock=SimulatedClock())
    i.use(plug)
    await i.start()
    await asyncio.sleep(0.01)
    for t in seq:
        if i.status != "running":
            break
        kw = {"qty": 7} if t == "SUBMIT" else ({"n": 2} if t == "FILL" else {})
        try:
            await i.send(t, **kw)
        except Exception:  # noqa: BLE001
            pass
        await asyncio.sleep(0.015)
    if i.status == "running":
        await i.stop()
    if plug.result is None:
        return None
    kind, payload = plug.result
    if kind == "refused":
        return "refused"
    if kind == "raised":
        return "raised"
    return classify(payload)  # type: ignore[arg-type]


async def main() -> None:
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 300
    rng = random.Random(4242)
    tally: dict[str, int] = {}
    taken = 0
    for _ in range(n):
        r = await one_run(rng)
        if r is None:
            continue
        taken += 1
        tally[r] = tally.get(r, 0) + 1

    print(f"runs={n}  snapshots attempted={taken}")
    for k in ("legal", "refused", "EMPTY", "MISSING_REGION", "raised"):
        if k in tally:
            print(f"   {k:<16}: {tally[k]}")
    torn = tally.get("EMPTY", 0) + tally.get("MISSING_REGION", 0)
    pct = (100.0 * torn / taken) if taken else 0.0
    print(f"\n   TORN (accepted illegal configuration) = {torn}/{taken} "
          f"= {pct:.1f}%")
    print(f"   of which globally-empty (D-3, expected 0) = "
          f"{tally.get('EMPTY', 0)}")
    print(f"   of which missing-parallel-region (D-3b)   = "
          f"{tally.get('MISSING_REGION', 0)}")
    print(f"\nVERDICT: {'PASS (no tear)' if torn == 0 else 'FAIL - torn snapshots still accepted'}")


if __name__ == "__main__":
    asyncio.run(main())
