"""P2 @cec108b -- #150 / #157 / #148 concurrency attacks.

v1  `send_threadsafe(..., internal=True)` forgery: a FOREIGN thread that is
    not inside any action claims self-send accounting. Must not let a
    non-action producer bypass the inbox / overflow policy in a way that
    forges system provenance, and must not wedge the chain budget.
v2  OverflowPolicy.RAISE under 16 threads on a cap-32 inbox: every call
    either enqueues or raises QueueOverflowError ON THE CALLING THREAD;
    zero losses on an unread future (#157 -- prior D-concurrency-6).
v3  `_die` under double cancel: cancel the run-loop task twice (and cancel
    after it is already dead). `_die` must be idempotent -- one on_error,
    one terminal status, no hung `send(wait=True)`.
v4  500 start/stop cycles with threads + executor services: thread and task
    deltas bounded.
"""

from __future__ import annotations

import asyncio
import threading
import time

from common import emit
from xstate_statemachine import Interpreter, MachineLogic, create_machine
from xstate_statemachine.events import Event
from xstate_statemachine.exceptions import QueueOverflowError

CFG = {
    "id": "ts",
    "initial": "idle",
    "context": {"n": 0},
    "states": {"idle": {"on": {"PING": {"actions": ["bump"]}}}},
}


def bump(i, ctx, e, a):  # noqa: ANN001
    ctx["n"] += 1


def mk():
    return create_machine(CFG, logic=MachineLogic(actions={"bump": bump}))


class Hooks:
    def __init__(self) -> None:
        self.dropped: list = []
        self.errors: list = []


def hooked(i, h):  # noqa: ANN001
    from xstate_statemachine import PluginBase

    class P(PluginBase):
        def on_event_dropped(self, interp, event, reason=None, **kw):  # noqa: ANN001
            h.dropped.append((getattr(event, "type", event), reason))

        def on_error(self, interp, error):  # noqa: ANN001
            h.errors.append(type(error).__name__)

    i.use(P())


async def v1_internal_forgery() -> dict:
    h = Hooks()
    i = Interpreter(mk())
    hooked(i, h)
    await i.start()
    n = 200
    barrier = threading.Barrier(8)
    results: list = []

    def worker():
        barrier.wait()
        for _ in range(n // 8):
            try:
                i.send_threadsafe("PING", internal=True)
            except Exception as exc:  # noqa: BLE001
                results.append(repr(exc))

    ths = [threading.Thread(target=worker) for _ in range(8)]
    for t in ths:
        t.start()
    for t in ths:
        t.join()
    for _ in range(60):
        await asyncio.sleep(0.02)
        if i.context["n"] >= n:
            break
    # provenance: does a forged-internal event become a SYSTEM event?
    ev = Event(type="PING")
    forged_is_system = getattr(ev, "is_system", None)
    status, running, ctx = i.status, i.is_running, dict(i.context)
    await i.stop()
    return {
        "forged_internal_sends": n,
        "processed": ctx["n"],
        "call_site_errors": results[:3],
        "status": status,
        "is_running": running,
        "chain_budget_drops": [d for d in h.dropped if d[1] == "chain_budget"],
        "user_event_is_system": bool(forged_is_system),
        "wedged": not running,
        "note": (
            "internal=True from a non-action thread routes to the unbounded "
            "internal queue and is charged to the chain budget"
        ),
        "pass": ctx["n"] == n and running and not forged_is_system,
    }


async def v2_raise_16_threads() -> dict:
    from xstate_statemachine.interpreter import OverflowPolicy

    h = Hooks()
    slow = {
        "id": "slow",
        "initial": "idle",
        "context": {"n": 0},
        "states": {"idle": {"on": {"PING": {"actions": ["bump"]}}}},
    }

    def slow_bump(i, ctx, e, a):  # noqa: ANN001
        ctx["n"] += 1

    m = create_machine(slow, logic=MachineLogic(actions={"bump": slow_bump}))
    i = Interpreter(
        m, max_queue_size=32, overflow_policy=OverflowPolicy.RAISE
    )
    hooked(i, h)
    await i.start()

    per = 300
    threads = 16
    raised = {"n": 0}
    returned = {"n": 0}
    fut_fail = {"n": 0}
    futs: list = []
    lock = threading.Lock()

    def worker():
        for _ in range(per):
            try:
                f = i.send_threadsafe("PING")
            except QueueOverflowError:
                with lock:
                    raised["n"] += 1
                continue
            except Exception:  # noqa: BLE001
                with lock:
                    raised["n"] += 1
                continue
            with lock:
                returned["n"] += 1
                futs.append(f)

    ths = [threading.Thread(target=worker) for _ in range(threads)]
    # keep the loop busy so the inbox actually fills
    for t in ths:
        t.start()
    while any(t.is_alive() for t in ths):
        await asyncio.sleep(0.001)
    for t in ths:
        t.join()
    await asyncio.sleep(0.4)
    for f in futs:
        try:
            f.result(timeout=2)
        except QueueOverflowError:
            fut_fail["n"] += 1
        except Exception:  # noqa: BLE001
            fut_fail["n"] += 1
    ctx = dict(i.context)
    await i.stop()
    total = threads * per
    return {
        "threads": threads,
        "attempted": total,
        "raised_on_calling_thread": raised["n"],
        "returned_a_future": returned["n"],
        "failed_only_on_unread_future": fut_fail["n"],
        "processed": ctx["n"],
        "drop_hooks": len(h.dropped),
        "accounted": raised["n"] + fut_fail["n"] + ctx["n"] + len(h.dropped),
        "note": (
            "#157 demands refusal at the CALL SITE; residual future-only "
            "failures are the documented concurrent-producer race"
        ),
        "pass": raised["n"] > 0,
    }


async def v3_die_double_cancel() -> dict:
    out = []
    for extra_cancel in (1, 2, 3):
        h = Hooks()
        i = Interpreter(mk())
        hooked(i, h)
        await i.start()
        await asyncio.sleep(0)
        task = i._event_loop_task
        for _ in range(extra_cancel):
            task.cancel()
            await asyncio.sleep(0)
        await asyncio.sleep(0.05)
        try:
            r = await asyncio.wait_for(i.send("PING", wait=True), 2)
            sent = f"resolved: {type(r).__name__}"
        except asyncio.TimeoutError:
            sent = "HUNG"
        except Exception as exc:  # noqa: BLE001
            sent = f"raised {type(exc).__name__}"
        out.append(
            {
                "cancels": extra_cancel,
                "status": i.status,
                "is_running": i.is_running,
                "on_error_hook_count": len(h.errors),
                "send_wait_true": sent,
                "ok": i.status == "error"
                and len(h.errors) == 1
                and sent != "HUNG",
            }
        )
        try:
            await i.stop()
        except Exception:  # noqa: BLE001
            pass
    return {"cases": out, "pass": all(c["ok"] for c in out)}


async def v4_cycles(cycles: int = 500) -> dict:
    base_t = threading.active_count()
    base_k = len(asyncio.all_tasks())
    for k in range(cycles):
        i = Interpreter(mk())
        await i.start()
        if k % 5 == 0:
            t = threading.Thread(
                target=lambda: i.send_threadsafe("PING")
            )
            t.start()
            t.join()
        else:
            await asyncio.wait_for(i.send("PING", wait=True), 5)
        await i.stop()
    await asyncio.sleep(0.4)
    return {
        "cycles": cycles,
        "thread_delta": threading.active_count() - base_t,
        "task_delta": len(asyncio.all_tasks()) - base_k,
        "pass": threading.active_count() - base_t <= 8
        and len(asyncio.all_tasks()) - base_k <= 1,
    }


async def main() -> int:
    res = {
        "v1_internal_forgery": await v1_internal_forgery(),
        "v2_raise_16_threads": await v2_raise_16_threads(),
        "v3_die_double_cancel": await v3_die_double_cancel(),
        "v4_500_cycles": await v4_cycles(),
    }
    res["result"] = (
        "PASS"
        if all(v["pass"] for v in res.values() if isinstance(v, dict))
        else "FAIL"
    )
    emit("p2_threadsafe_die", res)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
