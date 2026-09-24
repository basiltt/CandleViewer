"""(d) Cancel the task awaiting `send(wait=True)` mid-transition.

The question is whether cancelling the AWAITER corrupts the machine. In
this engine the awaiter and the transition run on different tasks: the
producer awaits a `Future` in `_receipts`, while `_run_event_loop` executes
the macrostep. Cancelling the producer must therefore:

  * not cancel or damage the transition (it is already committed / in
    flight; the machine is not the awaiter's to abort),
  * not leave an orphaned entry in `_receipts`,
  * leave `context`, configuration and `status` consistent,
  * leave the machine able to process the NEXT event normally.

Variants (each repeated many times, cancelling at a rotating loop phase so
the cancellation lands in different places in the macrostep):

  V1  cancel while the action list is mid-await (a long async action)
  V2  cancel at a rotating number of loop turns after send() was issued
  V3  cancel every awaiter of a batch, then verify the machine still works
  V4  `_receipts` map growth across 2,000 cancelled awaiters (leak check)
  V5  cancel an awaiter whose event is still QUEUED behind a slow one
"""

from __future__ import annotations

import asyncio
import gc

from common import Accountant, emit
from xstate_statemachine import Interpreter, MachineLogic, create_machine

CFG = {
    "id": "cx",
    "initial": "a",
    "context": {"n": 0, "half": 0},
    "states": {
        "a": {
            "on": {
                "SLOW": {"target": "b", "actions": ["slow_bump"]},
                "FAST": {"actions": ["bump"]},
            }
        },
        "b": {"on": {"BACK": {"target": "a"}, "FAST": {"actions": ["bump"]}}},
    },
}

GATE: dict = {}


async def slow_bump(interpreter, ctx, event, action_def):  # noqa: ANN001
    ctx["half"] += 1  # observable mid-action marker
    ev = GATE.get("ev")
    if ev is not None:
        GATE["entered"].set()
        await ev.wait()
    else:
        await asyncio.sleep(0.01)
    ctx["n"] += 1  # completes only if the action was not torn apart


def bump(interpreter, ctx, event, action_def):  # noqa: ANN001
    ctx["n"] += 1


def machine():
    return create_machine(
        CFG, logic=MachineLogic(actions={"slow_bump": slow_bump, "bump": bump})
    )


def receipts(i):
    return len(i._receipts)


def awaiter(i, ev_type: str):
    """A TASK that awaits `send(..., wait=True)`, as an application writes it.

    Note `send(wait=True)` returns the receipt `Future` itself, not a
    coroutine, so `asyncio.create_task(i.send(...))` is a TypeError. The
    realistic shape is a coroutine that awaits it -- and cancelling THAT
    task propagates the cancellation into the receipt future, because
    awaiting a future is what delivers the cancellation.
    """

    async def _run():
        return await i.send(ev_type, wait=True)

    return asyncio.create_task(_run())


async def v1_cancel_mid_action():
    GATE["ev"] = asyncio.Event()
    GATE["entered"] = asyncio.Event()
    i = Interpreter(machine())
    acc = Accountant()
    i.use(acc)
    await i.start()

    t = awaiter(i, "SLOW")
    await asyncio.wait_for(GATE["entered"].wait(), 5)  # inside the action
    t.cancel()
    try:
        await t
    except asyncio.CancelledError:
        pass
    mid = {
        "states_during": sorted(i.current_state_ids),
        "n_during": i.context["n"],
        "half_during": i.context["half"],
        "receipts_after_cancel": receipts(i),
    }
    GATE["ev"].set()  # let the action finish
    await asyncio.sleep(0.05)

    # The machine must still work.
    r = await asyncio.wait_for(i.send("FAST", wait=True), 5)
    out = {
        **mid,
        "action_completed_n": i.context["n"],
        "half_total": i.context["half"],
        "states_after": sorted(i.current_state_ids),
        "next_event_receipt_changed": r.changed,
        "next_event_receipt_error": repr(r.error),
        "status": i.status,
        "receipts_at_end": receipts(i),
        "last_transition_ok": i.last_transition_ok,
    }
    await i.stop()
    GATE.clear()
    return out


async def v2_rotating_phase(trials: int = 200):
    bad = []
    for k in range(trials):
        i = Interpreter(machine())
        await i.start()
        t = awaiter(i, "SLOW")
        for _ in range(k % 9):
            await asyncio.sleep(0)
        t.cancel()
        try:
            await t
        except asyncio.CancelledError:
            pass
        await asyncio.sleep(0.03)  # let the transition finish either way
        r = await asyncio.wait_for(i.send("FAST", wait=True), 5)
        st = sorted(i.current_state_ids)
        # Invariants: exactly one leaf active; context n consistent with the
        # number of completed bumps; the follow-up event worked.
        ok = (
            len(st) == 1
            and i.status == "running"
            and r.error is None
            and receipts(i) == 0
            and i.context["half"] in (0, 1)
            and i.context["n"] == i.context["half"] + 1
        )
        if not ok:
            bad.append(
                {
                    "trial": k,
                    "phase": k % 9,
                    "states": st,
                    "ctx": dict(i.context),
                    "status": i.status,
                    "receipts": receipts(i),
                    "err": repr(r.error),
                }
            )
        await i.stop()
    return {"trials": trials, "violations": len(bad), "sample": bad[:5]}


async def v3_cancel_whole_batch():
    i = Interpreter(machine())
    acc = Accountant()
    i.use(acc)
    await i.start()
    tasks = [awaiter(i, "FAST") for _ in range(50)]
    await asyncio.sleep(0)
    for t in tasks:
        t.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    await asyncio.sleep(0.1)
    r = await asyncio.wait_for(i.send("FAST", wait=True), 5)
    out = {
        "processed": len(acc.received),
        "context_n": i.context["n"],
        "receipts_left": receipts(i),
        "follow_up_ok": r.error is None and r.changed,
        "status": i.status,
        "note": "50 FAST events were accepted; all 50 awaiters were cancelled.",
    }
    await i.stop()
    return out


async def v4_receipt_leak(n: int = 2000):
    i = Interpreter(machine())
    await i.start()
    gc.collect()
    for _ in range(n):
        t = awaiter(i, "FAST")
        await asyncio.sleep(0)
        t.cancel()
        try:
            await t
        except asyncio.CancelledError:
            pass
    # drain
    deadline = 500
    while i.queue_depth and deadline:
        await asyncio.sleep(0.001)
        deadline -= 1
    await asyncio.sleep(0.1)
    out = {
        "cancelled_awaiters": n,
        "receipts_map_size_after": receipts(i),
        "context_n": i.context["n"],
        "status": i.status,
    }
    await i.stop()
    return out


async def v5_cancel_queued_behind_slow():
    GATE["ev"] = asyncio.Event()
    GATE["entered"] = asyncio.Event()
    i = Interpreter(machine())
    acc = Accountant()
    i.use(acc)
    await i.start()
    slow_t = awaiter(i, "SLOW")
    await asyncio.wait_for(GATE["entered"].wait(), 5)
    queued = [awaiter(i, "FAST") for _ in range(5)]
    await asyncio.sleep(0)
    for t in queued:
        t.cancel()
    await asyncio.gather(*queued, return_exceptions=True)
    GATE["ev"].set()
    r = await asyncio.wait_for(slow_t, 5)
    await asyncio.sleep(0.1)
    out = {
        "slow_receipt_changed": r.changed,
        "slow_receipt_error": repr(r.error),
        "processed": len(acc.received),
        "context_n": i.context["n"],
        "receipts_left": receipts(i),
        "states": sorted(i.current_state_ids),
        "status": i.status,
    }
    await i.stop()
    GATE.clear()
    return out


async def main():
    emit(
        "probe_d_cancel",
        {
            "v1_cancel_mid_action": await v1_cancel_mid_action(),
            "v2_rotating_phase": await v2_rotating_phase(),
            "v3_cancel_whole_batch": await v3_cancel_whole_batch(),
            "v4_receipt_leak": await v4_receipt_leak(),
            "v5_cancel_queued_behind_slow": await v5_cancel_queued_behind_slow(),
        },
    )


if __name__ == "__main__":
    asyncio.run(main())
