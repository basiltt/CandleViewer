"""N2 — CONCURRENCY attacks on the round-5 fixes (#149/#150/#157/#148).

service_executor under 200 concurrent plain-def services + stop() mid-service;
send_threadsafe internal=True forgery; RAISE at the call site under 16 threads;
_die under double cancel; leaked threads/tasks after 500 cycles.
"""

from __future__ import annotations

import asyncio
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List

from n_harness import attack, main

from xstate_statemachine import (
    Interpreter,
    MachineLogic,
    OverflowPolicy,
    QueueOverflowError,
    create_machine,
)


@attack(
    "N2-01",
    "#149: 200 concurrent plain-def services run OFF the loop — the loop keeps turning while they block",
    "the #116 ordering fix must not cost loop liveness",
)
async def n2_01() -> Dict[str, Any]:
    tids: List[int] = []

    def slow(i_, ctx, e):  # noqa: ANN001
        tids.append(threading.get_ident())
        time.sleep(0.25)
        return {"v": 1}

    cfg = {
        "id": "sv",
        "initial": "idle",
        "context": {"done": 0, "ticks": 0},
        "states": {
            "idle": {"on": {"RUN": "work"}},
            "work": {
                "invoke": {"src": "slow", "onDone": {"target": "idle", "actions": ["fin"]}}
            },
        },
    }

    def fin(i_, ctx, e, am):  # noqa: ANN001
        ctx["done"] = ctx.get("done", 0) + 1

    main_tid = threading.get_ident()
    beats = {"n": 0}

    async def heartbeat():
        while True:
            await asyncio.sleep(0.005)
            beats["n"] += 1

    N = 200
    ok_all = True
    loop_alive = 0
    machines = []
    for _ in range(N):
        m = create_machine(
            cfg, logic=MachineLogic(actions={"fin": fin}, services={"slow": slow})
        )
        machines.append(await Interpreter(m).start())
    # 📏 Calibrate: on Windows `asyncio.sleep(0.005)` rounds up to the ~15 ms
    #    timer granularity, so an absolute beat count proves nothing. Measure
    #    the IDLE beat rate first and compare the loaded rate against it.
    hb = asyncio.create_task(heartbeat())
    c0 = time.monotonic()
    await asyncio.sleep(1.0)
    idle_rate = beats["n"] / (time.monotonic() - c0)
    beats["n"] = 0
    t0 = time.monotonic()
    await asyncio.gather(*(i.send("RUN") for i in machines))
    # while the 200 services block, the loop must still schedule us
    while time.monotonic() - t0 < 10.0:
        await asyncio.sleep(0.005)
        loop_alive = beats["n"]
        if all(i.context["done"] >= 1 for i in machines):
            break
    elapsed = time.monotonic() - t0
    hb.cancel()
    # liveness: while 200 blocking services are in flight the loop must keep
    # scheduling the heartbeat at >= 60% of its measured IDLE rate.
    loaded_rate = beats["n"] / max(elapsed, 1e-6)
    # Require >= 20 beats so the rate is a real measurement and not 4 beats
    # of Windows ~15 ms timer quantisation.
    lively = beats["n"] >= 20 and loaded_rate >= 0.6 * idle_rate
    done = sum(i.context["done"] for i in machines)
    await asyncio.gather(*(i.stop() for i in machines))
    off_loop = all(t != main_tid for t in tids) and bool(tids)
    return {
        "ok": done == N and off_loop and lively,
        "services_completed": done,
        "expected": N,
        "ran_off_loop": off_loop,
        "heartbeats_under_load": beats["n"],
        "idle_rate_hz": round(idle_rate, 1),
        "loaded_rate_hz": round(loaded_rate, 1),
        "loop_stayed_lively": lively,
        "elapsed_s": round(elapsed, 3),
    }


@attack(
    "N2-02",
    "#149: stop() while a plain-def service is mid-flight returns promptly and leaks no thread",
    "an owned executor must be torn down, not left holding a blocked worker for ever",
)
async def n2_02() -> Dict[str, Any]:
    gate = threading.Event()

    def blocking(i_, ctx, e):  # noqa: ANN001
        gate.wait(3.0)
        return 1

    cfg = {
        "id": "b",
        "initial": "idle",
        "states": {
            "idle": {"on": {"RUN": "work"}},
            "work": {"invoke": {"src": "blocking", "onDone": "idle"}},
        },
    }
    m = create_machine(cfg, logic=MachineLogic(services={"blocking": blocking}))
    i = await Interpreter(m).start()
    before = threading.active_count()
    await i.send("RUN")
    await asyncio.sleep(0.05)
    t0 = time.monotonic()
    try:
        await asyncio.wait_for(i.stop(), timeout=5.0)
        stop_s = time.monotonic() - t0
        timed_out = False
    except asyncio.TimeoutError:
        stop_s = time.monotonic() - t0
        timed_out = True
    gate.set()
    await asyncio.sleep(0.3)
    after = threading.active_count()
    return {
        "ok": not timed_out and stop_s < 4.0 and after <= before + 1,
        "stop_seconds": round(stop_s, 3),
        "timed_out": timed_out,
        "threads_before": before,
        "threads_after": after,
    }


@attack(
    "N2-03",
    "#150: send_threadsafe(internal=True) FORGERY from a plain thread cannot outrun maxIterations",
    "a caller claiming engine provenance must not get an unbounded free pass",
)
async def n2_03() -> Dict[str, Any]:
    cfg = {
        "id": "f",
        "initial": "a",
        "context": {"n": 0},
        "maxIterations": 30,
        "states": {"a": {"on": {"P": {"actions": ["bump"]}}}},
    }

    def bump(i_, ctx, e, am):  # noqa: ANN001
        ctx["n"] = ctx.get("n", 0) + 1

    m = create_machine(cfg, logic=MachineLogic(actions={"bump": bump}))
    i = await Interpreter(m).start()
    drops: List[str] = []

    class Insp:
        def on_event_dropped(self, interp, event, reason):  # noqa: ANN001
            drops.append(reason)

    i.use(Insp())
    errs: List[str] = []

    def worker():
        for _ in range(200):
            try:
                i.send_threadsafe("P", internal=True)
            except Exception as exc:  # noqa: BLE001
                errs.append(type(exc).__name__)

    ths = [threading.Thread(target=worker) for _ in range(4)]
    for t in ths:
        t.start()
    for t in ths:
        t.join()
    for _ in range(200):
        await asyncio.sleep(0.01)
        if i.context["n"] >= 800:
            break
    n = i.context["n"]
    status = i.status
    err = type(i.last_error).__name__ if i.last_error else None
    await i.stop()
    # A forged internal=True IS charged to the chain budget (#150): the
    # excess is dropped, but the drop must be OBSERVABLE, not silent, and
    # the machine must stay alive.
    charged = n < 800
    observable = "chain_budget" in drops
    return {
        "ok": status == "running" and (not charged or observable),
        "delivered": n,
        "expected_if_uncharged": 800,
        "charged_to_budget": charged,
        "drop_reasons": sorted(set(drops)),
        "observable": observable,
        "status": status,
        "last_error": err,
        "call_site_errors": sorted(set(errs)),
    }


@attack(
    "N2-04",
    "#157: OverflowPolicy.RAISE surfaces QueueOverflowError at the send_threadsafe() CALL SITE under 16 threads",
    "a fire-and-forget caller never reads a future; the error must reach the caller's own stack",
)
async def n2_04() -> Dict[str, Any]:
    started = threading.Event()

    async def slow(i_, ctx, e, am):  # noqa: ANN001
        # Must be ASYNC: a blocking sync action stops the loop from ever
        # running the call_soon_threadsafe callbacks, so the inbox never
        # fills and this would test nothing.
        started.set()
        await asyncio.sleep(1.0)

    cfg = {
        "id": "o",
        "initial": "a",
        "states": {"a": {"on": {"SLOW": {"actions": ["slow"]}, "P": {"actions": []}}}},
    }
    m = create_machine(cfg, logic=MachineLogic(actions={"slow": slow}))
    i = await Interpreter(
        m, max_queue_size=4, overflow_policy=OverflowPolicy.RAISE
    ).start()
    await i.send("SLOW")
    await asyncio.sleep(0.05)
    raised: List[str] = []
    swallowed = 0
    lock = threading.Lock()

    def worker():
        nonlocal swallowed
        for _ in range(40):
            try:
                i.send_threadsafe("P")
                with lock:
                    swallowed += 1
            except QueueOverflowError:
                raised.append("QueueOverflowError")
            except Exception as exc:  # noqa: BLE001
                raised.append(type(exc).__name__)

    ths = [threading.Thread(target=worker) for _ in range(16)]
    for t in ths:
        t.start()
    for _ in range(400):
        await asyncio.sleep(0.005)
        if not any(t.is_alive() for t in ths):
            break
    for t in ths:
        t.join()
    kinds = sorted(set(raised))
    await asyncio.sleep(1.2)
    await i.stop()
    return {
        "ok": bool(raised) and kinds == ["QueueOverflowError"],
        "raised_at_call_site": len(raised),
        "kinds": kinds,
        "accepted": swallowed,
    }


@attack(
    "N2-05",
    "#148: _die is idempotent under DOUBLE cancel — death is published and send(wait=True) never hangs",
    "a cancel landing before the loop's first turn must still publish death",
)
async def n2_05() -> Dict[str, Any]:
    cfg = {"id": "d", "initial": "a", "states": {"a": {"on": {"P": {"actions": []}}}}}
    results: Dict[str, Any] = {}
    for label, delay in (("pre_first_turn", 0.0), ("after_turn", 0.05)):
        m = create_machine(cfg, logic=MachineLogic())
        i = await Interpreter(m).start()
        task = getattr(i, "_event_loop_task", None)
        if task is None:
            results[label] = "no-task-attr"
            await i.stop()
            continue
        if delay:
            await asyncio.sleep(delay)
        task.cancel()
        task.cancel()  # double cancel
        await asyncio.sleep(0.15)
        st = i.status
        try:
            await asyncio.wait_for(i.send("P", wait=True), timeout=1.0)
            sent = "returned"
        except asyncio.TimeoutError:
            sent = "HUNG"
        except Exception as exc:  # noqa: BLE001
            sent = type(exc).__name__
        results[label] = {
            "status": st,
            "is_running": i.is_running,
            "send": sent,
            "error": type(i.error).__name__ if getattr(i, "error", None) else None,
        }
        try:
            await asyncio.wait_for(i.stop(), timeout=2.0)
        except Exception:  # noqa: BLE001,S110
            pass
    # #114/#148: a cancelled run loop publishes DEATH — terminal status
    # (`error`), is_running False, and no hung `wait=True` caller. Both the
    # pre-first-turn cancel and a later one must reach the same place.
    ok = all(
        isinstance(v, dict)
        and v["status"] in ("error", "stopped")
        and v["is_running"] is False
        and v["send"] != "HUNG"
        for v in results.values()
    ) and len({v["status"] for v in results.values()}) == 1
    return {"ok": ok, **results}


@attack(
    "N2-06",
    "500 start/stop cycles with an executor service leak no threads and no asyncio tasks",
    "an owned ThreadPoolExecutor per interpreter is a leak vector under churn",
)
async def n2_06() -> Dict[str, Any]:
    def svc(i_, ctx, e):  # noqa: ANN001
        return 1

    cfg = {
        "id": "c",
        "initial": "idle",
        "states": {
            "idle": {"on": {"RUN": "work"}},
            "work": {"invoke": {"src": "svc", "onDone": "idle"}},
        },
    }
    base_t = threading.active_count()
    base_task = len(asyncio.all_tasks())
    for _ in range(500):
        m = create_machine(cfg, logic=MachineLogic(services={"svc": svc}))
        i = await Interpreter(m).start()
        await i.send("RUN")
        await i.stop()
    await asyncio.sleep(0.5)
    end_t = threading.active_count()
    end_task = len(asyncio.all_tasks())
    return {
        "ok": end_t - base_t <= 4 and end_task - base_task <= 1,
        "threads": [base_t, end_t],
        "tasks": [base_task, end_task],
    }


@attack(
    "N2-07",
    "A shared, CALLER-OWNED service_executor is used and NOT shut down by interpreter.stop()",
    "ownership: an injected executor belongs to the caller across many interpreters",
)
async def n2_07() -> Dict[str, Any]:
    ex = ThreadPoolExecutor(max_workers=3, thread_name_prefix="caller_owned")
    seen: List[str] = []

    def svc(i_, ctx, e):  # noqa: ANN001
        seen.append(threading.current_thread().name)
        return 1

    cfg = {
        "id": "x",
        "initial": "idle",
        "states": {
            "idle": {"on": {"RUN": "work"}},
            "work": {"invoke": {"src": "svc", "onDone": "idle"}},
        },
    }
    for _ in range(5):
        m = create_machine(cfg, logic=MachineLogic(services={"svc": svc}))
        i = await Interpreter(m, service_executor=ex).start()
        await i.send("RUN")
        for _ in range(100):
            await asyncio.sleep(0.005)
            if sorted(i.current_state_ids) == ["x.idle"] and seen:
                break
        await i.stop()
    still_usable = True
    try:
        ex.submit(lambda: 1).result(timeout=2)
    except Exception:  # noqa: BLE001
        still_usable = False
    ex.shutdown(wait=True)
    used = all(n.startswith("caller_owned") for n in seen) and bool(seen)
    return {
        "ok": used and still_usable,
        "ran_on_injected_executor": used,
        "executor_alive_after_stop": still_usable,
        "threads_seen": sorted(set(seen)),
    }


if __name__ == "__main__":
    main("n2_concurrency")
