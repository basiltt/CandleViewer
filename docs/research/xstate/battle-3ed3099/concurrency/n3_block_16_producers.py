"""N3 - #104: BLOCK must enqueue eagerly, and never lose an event, under
16 concurrent producers plus a concurrent stop().

v1  16 producers x 200 fire-and-forget `await send()` each, cap 32, BLOCK.
    Every attempted event must be processed or dropped-with-a-hook. Zero
    "returned normally but vanished".
v2  same, but a `stop(drain=True)` lands mid-flight: after the drain, the
    balance must still close.
v3  fire-and-forget on an EMPTY inbox (the literal #104 repro) x 500.
"""

from __future__ import annotations

import asyncio

from common import Accountant, counter_machine, emit
from xstate_statemachine import Interpreter
from xstate_statemachine.models import OverflowPolicy

PRODUCERS = 16
EACH = 200
CAP = 32


async def run(drain_mid: bool) -> dict:
    acc = Accountant()
    interp = Interpreter(
        counter_machine(), max_queue_size=CAP,
        overflow_policy=OverflowPolicy.BLOCK,
    )
    interp.use(acc)
    await interp.start()

    attempted = 0
    call_errors: list[str] = []

    async def producer(k: int) -> None:
        nonlocal attempted
        for _ in range(EACH):
            attempted += 1
            try:
                await interp.send("PING")
            except Exception as exc:  # noqa: BLE001
                call_errors.append(type(exc).__name__)

    tasks = [asyncio.create_task(producer(k)) for k in range(PRODUCERS)]
    if drain_mid:
        await asyncio.sleep(0.25)
        await interp.stop(drain=True)
    await asyncio.gather(*tasks, return_exceptions=True)
    if not drain_mid:
        # let the inbox drain fully
        for _ in range(200):
            if interp.queue_depth == 0:
                break
            await asyncio.sleep(0.01)
        await interp.stop(drain=True)

    processed = len(acc.received)
    dropped = len(acc.dropped)
    refused = len(call_errors)
    unaccounted = attempted - processed - dropped - refused - interp.queue_depth
    return {
        "attempted": attempted,
        "processed_hook": processed,
        "context_n": interp.context["n"],
        "dropped_hook": dropped,
        "drop_reasons": sorted({r for _, r in acc.dropped}),
        "refused_at_call_site": refused,
        "call_error_kinds": sorted(set(call_errors)),
        "queue_depth_at_end": interp.queue_depth,
        "unaccounted_lost": unaccounted,
        "hook_vs_context_agree": processed == interp.context["n"],
        "pass": unaccounted == 0 and processed == interp.context["n"],
    }


async def v3_empty_inbox() -> dict:
    acc = Accountant()
    interp = Interpreter(
        counter_machine(), max_queue_size=1024,
        overflow_policy=OverflowPolicy.BLOCK,
    )
    interp.use(acc)
    await interp.start()
    for _ in range(500):
        interp.send("PING")  # fire-and-forget, NOT awaited (the #104 shape)
    for _ in range(300):
        if interp.context["n"] >= 500:
            break
        await asyncio.sleep(0.01)
    out = {
        "sent_fire_and_forget": 500,
        "processed": len(acc.received),
        "context_n": interp.context["n"],
        "dropped": acc.dropped,
    }
    await interp.stop()
    out["pass"] = out["context_n"] == 500
    return out


async def main() -> int:
    res = {
        "v1_16_producers": await run(False),
        "v2_stop_drain_midflight": await run(True),
        "v3_empty_inbox_fire_and_forget": await v3_empty_inbox(),
    }
    ok = all(v["pass"] for v in res.values())
    emit("n3_block_16_producers", {**res, "result": "PASS" if ok else "FAIL"})
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
