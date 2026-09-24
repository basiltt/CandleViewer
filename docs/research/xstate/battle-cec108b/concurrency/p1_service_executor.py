"""P1 @cec108b -- #149 `service_executor` for plain-def services.

v1  200 concurrent plain-def services across 200 interpreters: every one must
    complete, the loop must keep turning (a heartbeat task must tick), and
    #116's ordering (done.invoke ahead of an already-queued event) must hold.
v2  stop() while a plain-def service is still running on the executor: no
    hang, no "Task destroyed", no thread leak, status stopped.
v3  a caller-supplied executor is NOT shut down by the interpreter; an owned
    one IS.
v4  thread-count delta after 200 interpreter lifecycles.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import threading
import time

from common import emit
from xstate_statemachine import Interpreter, MachineLogic, create_machine

CFG = {
    "id": "svc",
    "initial": "run",
    "context": {"out": None, "seen": []},
    "states": {
        "run": {
            "invoke": {
                "id": "job",
                "src": "plain",
                "onDone": {"target": "ok", "actions": ["keep"]},
                "onError": {"target": "bad"},
            },
            "on": {"RACE": {"actions": ["mark"]}},
        },
        "ok": {"type": "final"},
        "bad": {"type": "final"},
    },
}


def keep(i, ctx, e, a):  # noqa: ANN001
    ctx["out"] = e.data
    ctx["seen"].append("done")


def mark(i, ctx, e, a):  # noqa: ANN001
    ctx["seen"].append("race")


def mk(sleep_s: float = 0.0):
    def plain(i, ctx, e):  # noqa: ANN001 -- plain def, not a coroutine
        if sleep_s:
            time.sleep(sleep_s)
        return {"tid": threading.get_ident()}

    return create_machine(
        CFG,
        logic=MachineLogic(
            actions={"keep": keep, "mark": mark}, services={"plain": plain}
        ),
    )


async def v1_two_hundred(n: int = 200) -> dict:
    ticks = {"n": 0}
    stop = asyncio.Event()

    async def heart():
        while not stop.is_set():
            ticks["n"] += 1
            await asyncio.sleep(0.002)

    h = asyncio.create_task(heart())
    interps = [Interpreter(mk(0.02)) for _ in range(n)]
    t0 = time.perf_counter()
    await asyncio.gather(*(i.start() for i in interps))
    # #116 ordering probe: queue RACE before the service settles.
    for i in interps:
        i.send("RACE")
    await asyncio.gather(*(i.wait_done() for i in interps))
    dt = time.perf_counter() - t0
    stop.set()
    await h
    tids = set()
    ordering_ok = 0
    completed = 0
    for i in interps:
        if i.context["out"] is not None:
            completed += 1
            tids.add(i.context["out"]["tid"])
        if i.context["seen"][:1] == ["done"]:
            ordering_ok += 1
    await asyncio.gather(*(i.stop() for i in interps))
    return {
        "interpreters": n,
        "completed": completed,
        "distinct_service_threads": len(tids),
        "ran_off_loop_thread": threading.get_ident() not in tids,
        "done_before_queued_RACE": ordering_ok,
        "heartbeat_ticks_during": ticks["n"],
        "wall_s": round(dt, 3),
        "pass": completed == n
        and ordering_ok == n
        and ticks["n"] > 5
        and threading.get_ident() not in tids,
    }


async def v2_stop_mid_service() -> dict:
    i = Interpreter(mk(0.6))
    await i.start()
    await asyncio.sleep(0.05)  # service is on the executor now
    t0 = time.perf_counter()
    try:
        await asyncio.wait_for(i.stop(), 5)
        stop_err = None
    except Exception as exc:  # noqa: BLE001
        stop_err = repr(exc)
    dt = time.perf_counter() - t0
    await asyncio.sleep(0.8)  # let the abandoned service finish
    return {
        "stop_s": round(dt, 3),
        "stop_error": stop_err,
        "status": i.status,
        "is_running": i.is_running,
        "hung": dt > 3,
        "pass": stop_err is None and dt < 3 and not i.is_running,
    }


async def v3_executor_ownership() -> dict:
    ex = concurrent.futures.ThreadPoolExecutor(max_workers=2)
    i = Interpreter(mk(0.0), service_executor=ex)
    await i.start()
    await asyncio.wait_for(i.wait_done(), 5)
    await i.stop()
    caller_alive = True
    try:
        ex.submit(lambda: 1).result(timeout=2)
    except Exception:  # noqa: BLE001
        caller_alive = False
    ex.shutdown()

    j = Interpreter(mk(0.0))
    await j.start()
    await asyncio.wait_for(j.wait_done(), 5)
    owned = j._service_executor
    await j.stop()
    owned_released = j._service_executor is None
    return {
        "caller_executor_still_usable": caller_alive,
        "owned_executor_released_on_stop": owned_released,
        "owned_was_created": owned is not None,
        "pass": caller_alive and owned_released,
    }


async def v4_thread_leak(cycles: int = 200) -> dict:
    base = threading.active_count()
    for _ in range(cycles):
        i = Interpreter(mk(0.0))
        await i.start()
        await asyncio.wait_for(i.wait_done(), 5)
        await i.stop()
    await asyncio.sleep(0.5)
    after = threading.active_count()
    return {
        "cycles": cycles,
        "threads_baseline": base,
        "threads_after": after,
        "delta": after - base,
        "pass": after - base <= 8,
    }


async def main() -> int:
    res = {
        "v1_200_concurrent": await v1_two_hundred(),
        "v2_stop_mid_service": await v2_stop_mid_service(),
        "v3_executor_ownership": await v3_executor_ownership(),
        "v4_thread_leak": await v4_thread_leak(),
    }
    res["result"] = (
        "PASS" if all(v["pass"] for v in res.values() if isinstance(v, dict)) else "FAIL"
    )
    emit("p1_service_executor", res)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
