"""(a) BLOCK-policy edge cases: fire-and-forget, stop-while-blocked, self-send.

A1 shows the accounting is exact on the happy path. This probe attacks the
three BLOCK paths that are NOT structured like the other two policies,
because `send()` under BLOCK returns a coroutine that has not yet done any
work, while RAISE/DROP_NEWEST enqueue eagerly before returning.

V1  fire-and-forget: `interp.send("PING")` WITHOUT awaiting, under each
    policy. `send()`'s docstring: "ALL of the work ... happens eagerly,
    before anything is awaited ... a fire-and-forget `interp.send("GO")`
    from inside the loop is delivered rather than silently dropped."
    Run under -W error to catch "coroutine was never awaited".

V2  stop() while a producer is blocked on a full inbox: is the blocked
    event reported anywhere (hook / log / exception), or silently lost?

V3  BLOCK self-deadlock: an action on the machine itself doing
    `await interp.send(...)` on a full inbox. The code routes this to the
    internal queue when `_processing`; verify it cannot wedge the loop.

V4  BLOCK producer CPU: `_enqueue_blocking` spins on `asyncio.sleep(0)`
    rather than waiting on a slot-free signal. Measure loop turns burned
    by one blocked producer over a fixed wall-clock window.
"""

from __future__ import annotations

import asyncio
import gc
import time
import warnings

from common import Accountant, counter_machine, emit
from xstate_statemachine import Interpreter, MachineLogic, create_machine
from xstate_statemachine.models import OverflowPolicy

POLICIES = {
    "raise": OverflowPolicy.RAISE,
    "block": OverflowPolicy.BLOCK,
    "drop_newest": OverflowPolicy.DROP_NEWEST,
}


async def v1_fire_and_forget():
    """Send without awaiting the returned awaitable, under each policy."""
    out = {}
    for name, pol in POLICIES.items():
        acc = Accountant()
        i = Interpreter(counter_machine(), max_queue_size=1000, overflow_policy=pol)
        i.use(acc)
        await i.start()
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            for _ in range(10):
                i.send("PING")  # deliberately NOT awaited
            # let the loop run
            for _ in range(50):
                await asyncio.sleep(0)
            await asyncio.sleep(0.05)
            gc.collect()
            await asyncio.sleep(0)
            msgs = [str(x.message) for x in w]
        out[name] = {
            "processed": len(acc.received),
            "context_n": i.context["n"],
            "queue_depth": i.queue_depth,
            "warnings": msgs,
        }
        await i.stop()
    return out


async def v2_stop_while_blocked():
    """Fill the inbox, park producers on BLOCK, then stop()."""
    acc = Accountant()
    i = Interpreter(
        counter_machine(), max_queue_size=4, overflow_policy=OverflowPolicy.BLOCK
    )
    i.use(acc)
    await i.start()

    # Wedge the consumer so the inbox cannot drain: occupy the loop with a
    # task that never yields to the run loop is impossible; instead stop the
    # loop from draining by pausing the interpreter's consumption with a
    # long-running action. Simpler: pre-fill via the priority-free path while
    # the run loop has not been given a turn.
    for _ in range(4):
        await i.send("PING")  # fills to cap without the loop getting a turn

    blocked_results = []

    async def blocked_producer(k: int):
        try:
            r = await i.send("PING", wait=True)
            blocked_results.append(("receipt", k, r.changed, repr(r.error)))
        except Exception as exc:  # noqa: BLE001
            blocked_results.append(("exc", k, type(exc).__name__, str(exc)))

    tasks = [asyncio.create_task(blocked_producer(k)) for k in range(3)]
    await asyncio.sleep(0)  # let them reach the block

    # Fire-and-forget blocked producers (no receipt) -- the loss-visible case.
    # ADAPTED @cec108b: send() returns an already-resolved Future when the
    # eager enqueue succeeds (#37/#104 design); create_task() rejects a
    # Future. ensure_future() accepts both shapes.
    ff = [asyncio.ensure_future(i.send("PING")) for _ in range(3)]
    await asyncio.sleep(0)

    await i.stop()  # no drain
    await asyncio.gather(*tasks, *ff, return_exceptions=True)
    await asyncio.sleep(0.05)

    return {
        "processed": len(acc.received),
        "dropped_hook": acc.dropped,
        "blocked_with_receipt": blocked_results,
        "status": i.status,
        "queue_depth": i.queue_depth,
        "note": (
            "3 wait=True + 3 fire-and-forget producers were parked on a full "
            "inbox when stop() ran; count how many are reported anywhere."
        ),
    }


async def v3_block_self_send():
    """An action awaiting send() on its own interpreter, inbox full."""
    holder = {}

    async def selfsend(interpreter, ctx, event, action_def):  # noqa: ANN001
        if ctx.get("n", 0) < 3:
            ctx["n"] = ctx.get("n", 0) + 1
            await interpreter.send("PING")

    cfg = {
        "id": "ss",
        "initial": "idle",
        "context": {"n": 0},
        "states": {"idle": {"on": {"PING": {"actions": ["selfsend"]}}}},
    }
    m = create_machine(cfg, logic=MachineLogic(actions={"selfsend": selfsend}))
    i = Interpreter(m, max_queue_size=1, overflow_policy=OverflowPolicy.BLOCK)
    holder["i"] = i
    await i.start()
    try:
        await asyncio.wait_for(i.send("PING", wait=True), timeout=5)
        wedged = False
    except asyncio.TimeoutError:
        wedged = True
    res = {"wedged": wedged, "n": i.context["n"], "status": i.status}
    await i.stop()
    return res


async def v4_block_producer_spin():
    """How many loop turns does one blocked producer burn per second?"""
    i = Interpreter(
        counter_machine(), max_queue_size=2, overflow_policy=OverflowPolicy.BLOCK
    )
    await i.start()
    for _ in range(2):
        await i.send("PING")

    turns = 0
    stop_flag = {"v": False}

    async def observer():
        nonlocal turns
        while not stop_flag["v"]:
            turns += 1
            await asyncio.sleep(0)

    async def producer():
        # one blocked send; it will unblock as soon as the loop drains
        await i.send("PING")

    obs = asyncio.create_task(observer())
    t0 = time.perf_counter()
    await producer()
    unblock_s = time.perf_counter() - t0
    stop_flag["v"] = True
    await obs
    await i.stop()
    return {
        "unblock_s": round(unblock_s, 6),
        "observer_turns_during_block": turns,
        "impl": "interpreter.py:819 _enqueue_blocking spins on asyncio.sleep(0)",
    }


async def main():
    res = {
        "v1_fire_and_forget": await v1_fire_and_forget(),
        "v2_stop_while_blocked": await v2_stop_while_blocked(),
        "v3_block_self_send": await v3_block_self_send(),
        "v4_block_producer_spin": await v4_block_producer_spin(),
    }
    emit("a2_block_edges", res)


if __name__ == "__main__":
    asyncio.run(main())
