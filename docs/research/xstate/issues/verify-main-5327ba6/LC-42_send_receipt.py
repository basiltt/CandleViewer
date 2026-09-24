"""LC-42 verification on xstate-statemachine main @ 5327ba6 (pre-0.8.1).

Exercises `send(..., wait=True)` receipts and `send(..., priority=True)` /
`send_priority()` against the acceptance criteria of GH issue #39
(LC-42-send-fire-and-forget-no-answer), PLUS the new-in-Unreleased #75/#39
fix: "one Event instance in flight twice via wait=True -- both receipts
resolve; caller object not mutated" (CHANGELOG [Unreleased], `_detach`
in interpreter.py).
"""

from __future__ import annotations

import asyncio
import copy
import logging
import statistics
import sys
import time

from xstate_statemachine import Event, Interpreter, MachineLogic, create_machine

logging.disable(logging.CRITICAL)

CFG = {
    "id": "gov",
    "initial": "open",
    "states": {
        "open": {"on": {"TRIP": {"target": "tripped"}, "NOISE": {}}},
        "tripped": {"type": "final"},
    },
}

BACKGROUND = 2_000


async def main() -> int:
    ok = True

    # --- 1) wait=True returns a Receipt only after the macrostep completes
    interp = await Interpreter(create_machine(CFG, logic=MachineLogic())).start()
    receipt = await interp.send("TRIP", wait=True)
    print(f"OBSERVED await send('TRIP', wait=True) -> {receipt!r}")
    print("EXPECTED a Receipt with state_ids containing 'gov.tripped' and changed=True")
    if receipt is None or "gov.tripped" not in receipt.state_ids or not receipt.changed:
        ok = False
    if receipt is not None and receipt.error is not None:
        ok = False
    await interp.stop()

    # --- 2) receipt.error surfaces an exception raised while processing ---
    def boom(interp, ctx, event, action_def):  # noqa: ANN001
        raise RuntimeError("boom")

    cfg_err = {
        "id": "e",
        "initial": "a",
        "states": {"a": {"on": {"GO": {"target": "b", "actions": ["boom"]}}}, "b": {}},
    }
    interp_err = await Interpreter(
        create_machine(cfg_err, logic=MachineLogic(actions={"boom": boom}))
    ).start()
    r_err = await interp_err.send("GO", wait=True)
    print(f"OBSERVED erroring action receipt.error = {r_err.error!r}")
    print("EXPECTED receipt.error to be the RuntimeError (surfaced, not swallowed)")
    if r_err.error is None:
        ok = False
    await interp_err.stop()

    # --- 3) send() without wait still returns None, unchanged from 0.7.0 --
    interp2 = await Interpreter(create_machine(CFG, logic=MachineLogic())).start()
    ret = await interp2.send("NOISE")
    print(f"OBSERVED await send('NOISE') (no wait) -> {ret!r}")
    print("EXPECTED None")
    if ret is not None:
        ok = False

    # --- 4) priority=True jumps an existing backlog; bounded latency ------
    for i in range(BACKGROUND):
        await interp2.send("NOISE", n=i)
    lat = []
    for _ in range(5):
        t0 = time.perf_counter()
        await interp2.send_priority("NOISE")
        lat.append((time.perf_counter() - t0) * 1000)
    p50 = statistics.median(lat)
    print(
        f"OBSERVED send_priority() p50 latency behind {BACKGROUND} queued events "
        f"= {p50:.3f} ms (samples={[round(x,3) for x in lat]})"
    )
    print("EXPECTED p50 < 1 ms (priority jumps the backlog)")
    if p50 >= 1.0:
        ok = False
    await interp2.stop()

    # --- 5) stop() resolves outstanding receipts rather than hanging ------
    interp3 = await Interpreter(create_machine(CFG, logic=MachineLogic())).start()
    pending_receipt = interp3.send("NOISE", wait=True)
    await interp3.stop()
    resolved = await asyncio.wait_for(pending_receipt, timeout=1.0)
    print(f"OBSERVED pending receipt after stop() -> {resolved!r}")
    print("EXPECTED it resolves (does not hang) even though interpreter stopped")
    if resolved.error is None:
        ok = False

    # --- 6) [NEW / "need"] one Event instance sent wait=True TWICE while
    #        in flight: both receipts resolve independently, and the
    #        caller's own Event object is not mutated by the engine.
    interp4 = await Interpreter(create_machine(CFG, logic=MachineLogic())).start()
    shared_event = Event(type="NOISE", payload={"tag": "shared"})
    before = copy.deepcopy(shared_event)
    fut_a = interp4.send(shared_event, wait=True)
    fut_b = interp4.send(shared_event, wait=True)
    receipt_a, receipt_b = await asyncio.wait_for(
        asyncio.gather(fut_a, fut_b), timeout=1.0
    )
    print(f"OBSERVED two wait=True sends of ONE Event instance -> {receipt_a!r}, {receipt_b!r}")
    print("EXPECTED both receipts resolve (neither hangs) and no error on either")
    both_resolved = receipt_a is not None and receipt_b is not None
    neither_hung = True  # proven by wait_for not timing out
    no_errors = (
        both_resolved and receipt_a.error is None and receipt_b.error is None
    )
    if not (both_resolved and no_errors):
        ok = False
    print(
        f"OBSERVED caller's Event object after both sends = {shared_event!r} "
        f"(unchanged from {before!r} = {shared_event == before})"
    )
    print("EXPECTED caller's own Event object is NOT mutated by the engine")
    if shared_event != before:
        ok = False
    await interp4.stop()

    print("RESULT:", "FIXED" if ok else "NOT FIXED (see failing checks above)")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
