"""(a) Bounded inbox under fan-in: no event both accepted and lost.

2,000 interpreters, 500 events each, pushed by 16 producer tasks, with a
bounded inbox under each of RAISE / BLOCK / DROP_NEWEST.

Invariant per interpreter and per policy:

    sends_attempted == accepted + refused_at_call_site
    accepted        == processed + dropped_via_hook + still_queued_at_stop

`refused_at_call_site` is a QueueOverflowError raised by send() (RAISE).
`dropped_via_hook` is PluginBase.on_event_dropped(reason="queue_full")
(DROP_NEWEST). Anything else is an event that was both accepted and lost.

Usage:  python a1_bounded_fanin.py <policy> [n_interp] [n_events] [n_prod] [cap]
"""

from __future__ import annotations

import asyncio
import sys
import time

from common import Accountant, counter_machine, emit
from xstate_statemachine import Interpreter, QueueOverflowError
from xstate_statemachine.models import OverflowPolicy

POLICIES = {
    "raise": OverflowPolicy.RAISE,
    "block": OverflowPolicy.BLOCK,
    "drop_newest": OverflowPolicy.DROP_NEWEST,
}


async def run(policy_name: str, n_interp: int, n_events: int, n_prod: int, cap: int):
    policy = POLICIES[policy_name]
    machine = counter_machine()  # one machine node, many interpreters
    interps = []
    accs = []
    for _ in range(n_interp):
        acc = Accountant()
        i = Interpreter(machine, max_queue_size=cap, overflow_policy=policy)
        i.use(acc)
        interps.append(i)
        accs.append(acc)
    await asyncio.gather(*(i.start() for i in interps))

    attempted = 0
    accepted = 0
    refused = 0
    other_errors: list[str] = []
    lock = asyncio.Lock()

    # Work list: (interp_index,) repeated n_events, sharded over producers.
    total = n_interp * n_events

    async def producer(pid: int):
        nonlocal attempted, accepted, refused
        a = acc_ = r = 0
        k = pid
        while k < total:
            idx = k % n_interp
            k += n_prod
            a += 1
            try:
                await interps[idx].send("PING")
            except QueueOverflowError:
                r += 1
            except Exception as exc:  # noqa: BLE001
                other_errors.append(f"{type(exc).__name__}: {exc}")
                r += 1
            else:
                acc_ += 1
        async with lock:
            attempted += a
            accepted += acc_
            refused += r

    t0 = time.perf_counter()
    try:
        await asyncio.wait_for(
            asyncio.gather(*(producer(p) for p in range(n_prod))),
            timeout=600,
        )
        deadlocked = False
    except asyncio.TimeoutError:
        deadlocked = True
    produce_s = time.perf_counter() - t0

    depth_before_stop = sum(i.queue_depth for i in interps)

    # Let the consumers finish, then drain-stop.
    t1 = time.perf_counter()
    for i in interps:
        await i.stop(drain=True, timeout=120)
    drain_s = time.perf_counter() - t1

    processed = sum(len(a.received) for a in accs)
    dropped_full = sum(
        1 for a in accs for (_t, reason) in a.dropped if reason == "queue_full"
    )
    dropped_other = [
        reason for a in accs for (_t, reason) in a.dropped if reason != "queue_full"
    ]
    still_queued = sum(i.queue_depth for i in interps)
    ctx_total = sum(i.context["n"] for i in interps)

    emit(
        f"a1_{policy_name}",
        {
            "policy": policy_name,
            "n_interp": n_interp,
            "n_events_each": n_events,
            "n_producers": n_prod,
            "inbox_cap": cap,
            "attempted": attempted,
            "accepted": accepted,
            "refused_queue_overflow": refused,
            "processed": processed,
            "context_n_total": ctx_total,
            "dropped_hook_queue_full": dropped_full,
            "dropped_hook_other_reasons": sorted(set(dropped_other)),
            "still_queued_at_stop": still_queued,
            "queue_depth_before_stop": depth_before_stop,
            "unaccounted_accepted_but_lost": accepted
            - processed
            - dropped_full
            - still_queued,
            "attempt_balance_ok": attempted == accepted + refused,
            "other_errors_sample": other_errors[:5],
            "deadlocked": deadlocked,
            "produce_s": round(produce_s, 3),
            "drain_s": round(drain_s, 3),
            "ev_per_s": round(total / produce_s, 1) if produce_s else None,
        },
    )


if __name__ == "__main__":
    pol = sys.argv[1] if len(sys.argv) > 1 else "raise"
    n_i = int(sys.argv[2]) if len(sys.argv) > 2 else 2000
    n_e = int(sys.argv[3]) if len(sys.argv) > 3 else 500
    n_p = int(sys.argv[4]) if len(sys.argv) > 4 else 16
    cap = int(sys.argv[5]) if len(sys.argv) > 5 else 64
    asyncio.run(run(pol, n_i, n_e, n_p, cap))
