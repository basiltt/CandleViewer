# -*- coding: utf-8 -*-
"""NEW ATTACK: quiescent-point persistence invariant.

Property: for a 2k-event random-walk run against the soak machine, taking a
snapshot at every point the machine is quiescent (i.e. NOT mid-macrostep --
which in practice for this harness is "immediately after `send(...,
wait=True)` returns, since that's the only point we observe from outside")
must NEVER raise `SnapshotMidStepError`, and every such snapshot must
round-trip: `from_snapshot(json.dumps(get_persisted_snapshot()))` must
restore a byte-identical `state_ids` set (order-insensitive) and context.
"""
from __future__ import annotations

import asyncio
import json
import random
import sys

sys.path.insert(0, ".")
import soak_machine as sm  # noqa: E402
from xstate_statemachine import Interpreter, MachineLogic  # noqa: E402
from xstate_statemachine.exceptions import SnapshotMidStepError  # noqa: E402


async def main(n_events: int = 2000) -> None:
    rng = random.Random(7)
    m = sm.build(max_queue_size=256)
    interp = Interpreter(m)
    await interp.start()
    await interp.send({"type": "SUBMIT", "payload": {"qty": 5}}, wait=True)

    mid_step_errors = 0
    roundtrip_mismatches = []
    events = ["ACK", "REJECT", "NOPE", "RISK_OK", "RISK_HOLD", "TICK", "FAIL_HARD"]

    for i in range(n_events):
        ev = rng.choice(events)
        try:
            await asyncio.wait_for(interp.send(ev, wait=True), timeout=2.0)
        except asyncio.TimeoutError:
            print(f"UNEXPECTED: send timed out at i={i}")
            continue
        if interp.status not in ("running",):
            # terminal; recycle
            m2 = sm.build(max_queue_size=256)
            interp = Interpreter(m2)
            await interp.start()
            await interp.send({"type": "SUBMIT", "payload": {"qty": 5}}, wait=True)
            continue

        # Quiescent point: take a snapshot right here.
        try:
            snap = interp.get_persisted_snapshot()
        except SnapshotMidStepError as exc:
            mid_step_errors += 1
            print(f"SnapshotMidStepError AT QUIESCENCE (i={i}): {exc!r}")
            continue

        before_ids = frozenset(snap.get("state_ids", []))
        before_ctx = json.loads(json.dumps(snap.get("context", {}), default=repr))
        snap_str = json.dumps(snap, default=repr)

        new_m = sm.build(max_queue_size=256)
        restored = Interpreter.from_snapshot(snap_str, new_m)
        # `snap["state_ids"]` records LEAF states only; compare like for
        # like by taking the restored interpreter's own leaves.
        after_ids = frozenset(
            s.id for s in restored._active_state_nodes if not s.states
        )
        after_ctx = json.loads(json.dumps(restored.context, default=repr))
        if after_ids != before_ids or after_ctx != before_ctx:
            roundtrip_mismatches.append((i, before_ids, after_ids))

    print(f"events processed: {n_events}")
    print(f"SnapshotMidStepError-at-quiescence count: {mid_step_errors}")
    print(f"round-trip mismatches: {len(roundtrip_mismatches)}")
    if mid_step_errors:
        print("DEFECT: SnapshotMidStepError fired at an observably-quiescent point")
    if roundtrip_mismatches:
        print("DEFECT: snapshot round-trip did not preserve state_ids/context")
        for m_ in roundtrip_mismatches[:5]:
            print("  ", m_)
    if not mid_step_errors and not roundtrip_mismatches:
        print("PASS: no mid-step errors at quiescence; all snapshots round-tripped")


if __name__ == "__main__":
    asyncio.run(main())
