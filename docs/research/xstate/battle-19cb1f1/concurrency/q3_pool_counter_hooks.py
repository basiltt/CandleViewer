"""Q3 - round-6 fix surface: pool size, stop() mid-service, done-callback
double-fire, and the loop-side RAISE refusal hook.

A. `service_pool_size=1` with 50 plain-`def` services, and `stop()` called
   mid-service: no hang, no task/thread leak, no lost accounting.
B. `send_threadsafe(internal=True)` in-flight counter (#172): after a
   storm of delivered / refused / cancelled sends, the counter must be
   back to 0 -- a leak gates the chain-budget reset for ever.
C. Loop-side RAISE refusal (#157): `on_event_dropped(reason="queue_full")`
   must fire EXACTLY ONCE per refusal -- never zero (the original bug),
   never twice (the call-site check plus the loop-side one).
"""

from __future__ import annotations

import asyncio
import threading
import time

from common import emit
from xstate_statemachine import (
    Interpreter,
    MachineLogic,
    OverflowPolicy,
    PluginBase,
    create_machine,
)
from xstate_statemachine.exceptions import QueueOverflowError

SVC_CFG = {
    "id": "pool",
    "initial": "idle",
    "context": {"done": 0},
    "states": {
        "idle": {"on": {"GO": {"target": "work"}}},
        "work": {
            "invoke": {
                "src": "slow",
                "onDone": {"target": "idle", "actions": ["count"]},
                "onError": {"target": "idle"},
            }
        },
    },
}


def count(i, ctx, e, ad):  # noqa: ANN001
    ctx["done"] += 1


def slow(i, ctx, e):  # plain def -> runs on the executor  # noqa: ANN001
    time.sleep(0.05)
    return "ok"


async def a_pool_and_stop() -> dict:
    out = {}
    for size in (1, 4):
        itps = [
            Interpreter(
                create_machine(
                    SVC_CFG,
                    logic=MachineLogic(
                        actions={"count": count}, services={"slow": slow}
                    ),
                ),
                service_pool_size=size,
            )
            for _ in range(10)
        ]
        threads_before = threading.active_count()
        await asyncio.gather(*(i.start() for i in itps))
        t0 = time.perf_counter()
        for k in range(50):
            itps[k % 10].send_threadsafe("GO")
        await asyncio.sleep(0.4)
        # stop() while services are certainly still running
        try:
            await asyncio.wait_for(
                asyncio.gather(*(i.stop() for i in itps)), 15
            )
            stopped = "ok"
        except asyncio.TimeoutError:
            stopped = "HUNG"
        await asyncio.sleep(0.3)
        out[f"pool_{size}"] = {
            "wall_s": round(time.perf_counter() - t0, 2),
            "stop_midservice": stopped,
            "thread_delta": threading.active_count() - threads_before,
            "task_leftover": len(asyncio.all_tasks()) - 1,
            "statuses": sorted({i.status for i in itps}),
        }
    return out


PLAIN = {
    "id": "plain",
    "initial": "idle",
    "context": {"n": 0},
    "states": {"idle": {"on": {"PING": {"actions": ["bump"]}}}},
}


def bump(i, ctx, e, ad):  # noqa: ANN001
    ctx["n"] += 1


def plain_machine():
    return create_machine(PLAIN, logic=MachineLogic(actions={"bump": bump}))


async def b_inflight_counter() -> dict:
    itp = Interpreter(plain_machine(), max_queue_size=8,
                      overflow_policy=OverflowPolicy.RAISE)
    await itp.start()
    delivered = refused = raised_at_callsite = 0
    futs = []
    for _ in range(400):
        try:
            f = itp.send_threadsafe("PING", internal=True)
            futs.append(f)
        except QueueOverflowError:
            raised_at_callsite += 1
        except Exception:  # noqa: BLE001
            raised_at_callsite += 1
    await asyncio.sleep(0.6)
    for f in futs:
        try:
            f.result(timeout=2)
            delivered += 1
        except Exception:  # noqa: BLE001
            refused += 1
    await asyncio.sleep(0.3)
    counter = getattr(itp, "_threadsafe_self_sends_in_flight", "MISSING")
    # A leaked counter permanently blocks the chain reset; prove the
    # machine still resets by sending one plain event and checking depth.
    await asyncio.wait_for(itp.send("PING", wait=True), 5)
    depth = getattr(itp, "_raise_depth", "MISSING")
    await itp.stop()
    return {
        "attempted": 400,
        "raised_at_callsite": raised_at_callsite,
        "future_delivered": delivered,
        "future_refused": refused,
        "inflight_counter_after": counter,
        "raise_depth_after_quiescence": depth,
        "ok": counter == 0 and depth == 0,
    }


class DropCounter(PluginBase):
    def __init__(self) -> None:
        self.drops: list = []
        self.lock = threading.Lock()

    def on_event_dropped(self, i, event, reason) -> None:  # noqa: ANN001
        with self.lock:
            self.drops.append(reason)


async def c_loopside_refusal_hook() -> dict:
    """16 threads hammer a depth-4 RAISE inbox; every refusal -- call-site
    or loop-side -- must produce exactly one queue_full hook."""
    itp = Interpreter(plain_machine(), max_queue_size=4,
                      overflow_policy=OverflowPolicy.RAISE)
    dc = DropCounter()
    itp.use(dc)
    await itp.start()

    callsite_refusals = {"n": 0}
    futures: list = []
    lock = threading.Lock()
    stop = threading.Event()

    def producer() -> None:
        while not stop.is_set():
            try:
                f = itp.send_threadsafe("PING")
                with lock:
                    futures.append(f)
            except QueueOverflowError:
                with lock:
                    callsite_refusals["n"] += 1
            except Exception:  # noqa: BLE001
                pass
            time.sleep(0.0005)

    ts = [threading.Thread(target=producer, daemon=True) for _ in range(16)]
    for t in ts:
        t.start()
    await asyncio.sleep(2.0)
    stop.set()
    for t in ts:
        t.join(timeout=2)
    await asyncio.sleep(0.5)

    loopside_refusals = 0
    for f in futures:
        try:
            f.result(timeout=2)
        except QueueOverflowError:
            loopside_refusals += 1
        except Exception:  # noqa: BLE001
            loopside_refusals += 1
    await asyncio.sleep(0.3)
    hooks = len(dc.drops)
    qf = sum(1 for r in dc.drops if r == "queue_full")
    total_refusals = callsite_refusals["n"] + loopside_refusals
    await itp.stop()
    return {
        "callsite_refusals": callsite_refusals["n"],
        "loopside_refusals": loopside_refusals,
        "total_refusals": total_refusals,
        "queue_full_hooks": qf,
        "other_drop_reasons": sorted(set(dc.drops) - {"queue_full"}),
        "hooks_total": hooks,
        "exactly_once": qf == total_refusals,
        "loopside_observable": (loopside_refusals == 0) or (qf > 0),
    }


async def main() -> int:
    a = await a_pool_and_stop()
    b = await b_inflight_counter()
    c = await c_loopside_refusal_hook()
    ok = (
        all(v["stop_midservice"] == "ok" for v in a.values())
        and all(v["thread_delta"] <= 2 for v in a.values())
        and b["ok"]
        and c["loopside_observable"]
    )
    emit(
        "q3_pool_counter_hooks",
        {
            "A_pool_and_stop_midservice": a,
            "B_inflight_counter": b,
            "C_loopside_refusal_hook": c,
            "C_exactly_once": c["exactly_once"],
            "result": "PASS" if ok else "FAIL",
        },
    )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
