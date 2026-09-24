# -----------------------------------------------------------------------------
# bench_g_semantics.py — (g) failure, cancellation, thread-safety, re-entrancy
# -----------------------------------------------------------------------------
"""Behavioural probes. These are correctness questions, not speed questions,
but they decide whether CandleViewer can put this library on the order path.

Probes:
  g1  action raises                      -> is the event lost? machine wedged?
  g2  guard raises                       -> transition taken or skipped?
  g3  entry action raises during start   -> does start() fail cleanly?
  g4  invoked service raises             -> onError reached?
  g5  invoked service cancelled (stop)   -> is CancelledError swallowed?
  g6  send() from another THREAD         -> asyncio-safe or corruption?
  g7  send() from another asyncio TASK   -> ordering preserved?
  g8  re-entrancy: send() inside action  -> deadlock? ordering?
  g9  event ordering under concurrency   -> strict FIFO?
  g10 unhandled event in final state     -> silently dropped?
  g11 sync engine: action raises         -> propagates to caller?
"""

from __future__ import annotations

import asyncio
import threading
import time
import traceback
from typing import Any, Dict, List

import common
from xstate_statemachine import (
    Interpreter,
    MachineLogic,
    SyncInterpreter,
    create_machine,
)


def toggle_cfg(name: str = "m") -> Dict[str, Any]:
    return {
        "id": name,
        "initial": "a",
        "context": {"n": 0, "seq": []},
        "states": {
            "a": {"on": {"GO": {"target": "b", "actions": ["act"]}}},
            "b": {"on": {"GO": {"target": "a", "actions": ["act"]}}},
        },
    }


# --- g1: action raises --------------------------------------------------------
async def g1_action_raises() -> Dict[str, Any]:
    calls = {"n": 0}

    def act(i, ctx, e, a):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("boom in action")
        ctx["n"] += 1

    m = create_machine(toggle_cfg(), logic=MachineLogic(actions={"act": act}))
    interp = await Interpreter(m).start()
    for _ in range(4):
        await interp.send("GO")
    await asyncio.sleep(0.2)
    res = {
        "action_invocations": calls["n"],
        "context_n_after_4_events": interp.context["n"],
        "status": interp.status,
        "states": sorted(interp.current_state_ids),
        "still_running": interp.is_running,
    }
    # can it still process events afterwards?
    before = interp.context["n"]
    await interp.send("GO")
    await asyncio.sleep(0.1)
    res["accepts_events_after_raise"] = interp.context["n"] != before or (
        sorted(interp.current_state_ids) != res["states"]
    )
    await interp.stop()
    return res


# --- g2: guard raises ---------------------------------------------------------
async def g2_guard_raises() -> Dict[str, Any]:
    cfg = toggle_cfg("g2")
    cfg["states"]["a"]["on"]["GO"]["cond"] = "bad_guard"

    def bad_guard(ctx, e):
        raise ValueError("guard exploded")

    def act(i, ctx, e, a):
        ctx["n"] += 1

    m = create_machine(
        cfg,
        logic=MachineLogic(
            actions={"act": act}, guards={"bad_guard": bad_guard}
        ),
    )
    try:
        interp = await Interpreter(m).start()
    except Exception as exc:
        return {"start_raised": f"{type(exc).__name__}: {exc}"}
    await interp.send("GO")
    await asyncio.sleep(0.2)
    out = {
        "states": sorted(interp.current_state_ids),
        "status": interp.status,
        "transition_taken": "g2.b" in interp.current_state_ids,
        "still_running": interp.is_running,
    }
    await interp.stop()
    return out


# --- g3: entry action raises at start -----------------------------------------
async def g3_entry_raises() -> Dict[str, Any]:
    cfg = toggle_cfg("g3")
    cfg["states"]["a"]["entry"] = ["bad"]

    def bad(i, ctx, e, a):
        raise RuntimeError("entry boom")

    m = create_machine(cfg, logic=MachineLogic(actions={"bad": bad, "act": bad}))
    interp = Interpreter(m)
    try:
        await interp.start()
        return {
            "start_raised": False,
            "status": interp.status,
            "states": sorted(interp.current_state_ids),
        }
    except Exception as exc:
        return {
            "start_raised": True,
            "exc": f"{type(exc).__name__}: {exc}",
            "status_after": interp.status,
        }


# --- g4 / g5: services ---------------------------------------------------------
def svc_cfg(name: str) -> Dict[str, Any]:
    return {
        "id": name,
        "initial": "loading",
        "context": {"err": None, "done": None},
        "states": {
            "loading": {
                "invoke": {
                    "src": "work",
                    "onDone": {"target": "ok", "actions": ["mark_done"]},
                    "onError": {"target": "bad", "actions": ["mark_err"]},
                }
            },
            "ok": {"type": "final"},
            "bad": {"type": "final"},
        },
    }


async def g4_service_raises() -> Dict[str, Any]:
    async def work(i, ctx, e):
        await asyncio.sleep(0.01)
        raise RuntimeError("service failed")

    def mark_err(i, ctx, e, a):
        ctx["err"] = str(getattr(e, "data", None) or getattr(e, "payload", None))

    def mark_done(i, ctx, e, a):
        ctx["done"] = True

    m = create_machine(
        svc_cfg("g4"),
        logic=MachineLogic(
            services={"work": work},
            actions={"mark_err": mark_err, "mark_done": mark_done},
        ),
    )
    interp = await Interpreter(m).start()
    await asyncio.sleep(0.4)
    out = {
        "states": sorted(interp.current_state_ids),
        "onError_reached": "g4.bad" in interp.current_state_ids,
        "error_payload_captured": interp.context["err"],
        "status": interp.status,
    }
    await interp.stop()
    return out


async def g5_service_cancelled() -> Dict[str, Any]:
    state = {"started": False, "cancelled": False, "finally_ran": False}

    async def work(i, ctx, e):
        state["started"] = True
        try:
            await asyncio.sleep(10)
            return "never"
        except asyncio.CancelledError:
            state["cancelled"] = True
            raise
        finally:
            state["finally_ran"] = True

    m = create_machine(
        svc_cfg("g5"),
        logic=MachineLogic(
            services={"work": work},
            actions={
                "mark_err": lambda i, c, e, a: c.__setitem__("err", "E"),
                "mark_done": lambda i, c, e, a: c.__setitem__("done", True),
            },
        ),
    )
    interp = await Interpreter(m).start()
    await asyncio.sleep(0.1)
    t0 = time.perf_counter()
    await interp.stop()
    stop_s = time.perf_counter() - t0
    return {
        "service_started": state["started"],
        "cancellation_delivered_to_service": state["cancelled"],
        "finally_block_ran": state["finally_ran"],
        "stop_blocked_seconds": stop_s,
        "stop_waited_for_service": stop_s > 1.0,
        "status": interp.status,
        "onError_fired_on_cancel": interp.context.get("err") is not None,
    }


# --- g6: send from another OS thread -------------------------------------------
async def g6_send_from_thread() -> Dict[str, Any]:
    def act(i, ctx, e, a):
        ctx["n"] += 1

    m = create_machine(toggle_cfg("g6"), logic=MachineLogic(actions={"act": act}))
    interp = await Interpreter(m).start()
    loop = asyncio.get_running_loop()
    N = 500
    errors: List[str] = []

    # 6a: naive — call send() from a thread without the loop
    def naive():
        try:
            coro = interp.send("GO")
            # a coroutine object created but never awaited on this thread
            coro.close()
            errors.append("no_exception_but_event_never_delivered")
        except Exception as exc:
            errors.append(f"{type(exc).__name__}: {exc}")

    t = threading.Thread(target=naive)
    t.start()
    t.join()
    await asyncio.sleep(0.1)
    naive_delivered = interp.context["n"]

    # 6b: correct — run_coroutine_threadsafe
    def proper():
        for _ in range(N):
            fut = asyncio.run_coroutine_threadsafe(interp.send("GO"), loop)
            fut.result(timeout=5)

    t0 = time.perf_counter()
    th = threading.Thread(target=proper)
    th.start()
    while th.is_alive():
        await asyncio.sleep(0.001)
    th.join()
    deadline = time.perf_counter() + 30
    while interp.context["n"] < N and time.perf_counter() < deadline:
        await asyncio.sleep(0.001)
    dt = time.perf_counter() - t0
    out = {
        "naive_thread_send_result": errors,
        "naive_thread_events_delivered": naive_delivered,
        "threadsafe_sent": N,
        "threadsafe_delivered": interp.context["n"],
        "threadsafe_all_delivered": interp.context["n"] == N,
        "threadsafe_total_s": dt,
        "threadsafe_us_per_event": dt / N * 1e6,
        "status": interp.status,
    }
    await interp.stop()
    return out


# --- g7 / g9: concurrent tasks and ordering ------------------------------------
async def g7_concurrent_tasks() -> Dict[str, Any]:
    cfg = {
        "id": "g7",
        "initial": "s",
        "context": {"seq": []},
        "states": {
            "s": {"on": {"E": {"target": "s", "actions": ["rec"]}}}
        },
    }

    def rec(i, ctx, e, a):
        ctx["seq"].append(e.payload.get("k"))

    m = create_machine(cfg, logic=MachineLogic(actions={"rec": rec}))
    interp = await Interpreter(m).start()

    # a single producer must observe FIFO
    for k in range(500):
        await interp.send("E", k=k)
    deadline = time.perf_counter() + 30
    while len(interp.context["seq"]) < 500 and time.perf_counter() < deadline:
        await asyncio.sleep(0.001)
    single_fifo = interp.context["seq"] == list(range(500))

    # many concurrent producers: per-producer order must hold
    interp.context["seq"].clear()
    P, M = 10, 50

    async def producer(pid: int):
        for j in range(M):
            await interp.send("E", k=(pid, j))

    await asyncio.gather(*(producer(p) for p in range(P)))
    deadline = time.perf_counter() + 30
    while len(interp.context["seq"]) < P * M and time.perf_counter() < deadline:
        await asyncio.sleep(0.001)
    seq = list(interp.context["seq"])
    per_producer_ok = all(
        [j for (p, j) in seq if p == pid] == list(range(M))
        for pid in range(P)
    )
    await interp.stop()
    return {
        "single_producer_strict_fifo": single_fifo,
        "events_received": len(seq),
        "no_events_lost": len(seq) == P * M,
        "per_producer_order_preserved": per_producer_ok,
    }


# --- g8: re-entrancy — send() inside an action ---------------------------------
async def g8_reentrancy() -> Dict[str, Any]:
    cfg = {
        "id": "g8",
        "initial": "a",
        "context": {"seq": [], "depth": 0},
        "states": {
            "a": {"on": {"OUTER": {"target": "b", "actions": ["reenter"]}}},
            "b": {"on": {"INNER": {"target": "a", "actions": ["rec_inner"]}}},
        },
    }
    holder: Dict[str, Any] = {}

    def reenter(i, ctx, e, a):
        ctx["seq"].append("outer")
        # 🔁 fire an event from *inside* an action. `send` is a coroutine on
        #    the async engine, so this must be scheduled, not awaited.
        holder["task"] = asyncio.create_task(i.send("INNER"))

    def rec_inner(i, ctx, e, a):
        ctx["seq"].append("inner")

    m = create_machine(
        cfg,
        logic=MachineLogic(actions={"reenter": reenter, "rec_inner": rec_inner}),
    )
    interp = await Interpreter(m).start()
    try:
        await asyncio.wait_for(interp.send("OUTER"), timeout=5)
        deadline = time.perf_counter() + 5
        while (
            "inner" not in interp.context["seq"]
            and time.perf_counter() < deadline
        ):
            await asyncio.sleep(0.005)
        out = {
            "deadlocked": "inner" not in interp.context["seq"],
            "sequence": list(interp.context["seq"]),
            "final_states": sorted(interp.current_state_ids),
            "status": interp.status,
        }
    except asyncio.TimeoutError:
        out = {"deadlocked": True, "note": "send() inside action timed out"}
    await interp.stop()
    return out


async def g8b_sync_reentrancy() -> Dict[str, Any]:
    """The sync engine processes inside send() — re-entrant send is the real
    hazard there (recursion or a queue?)."""
    cfg = {
        "id": "g8b",
        "initial": "a",
        "context": {"seq": []},
        "states": {
            "a": {"on": {"OUTER": {"target": "b", "actions": ["reenter"]}}},
            "b": {"on": {"INNER": {"target": "a", "actions": ["rec"]}}},
        },
    }

    def reenter(i, ctx, e, a):
        ctx["seq"].append("outer_start")
        i.send("INNER")
        ctx["seq"].append("outer_end")

    def rec(i, ctx, e, a):
        ctx["seq"].append("inner")

    m = create_machine(
        cfg, logic=MachineLogic(actions={"reenter": reenter, "rec": rec})
    )
    try:
        interp = SyncInterpreter(m).start()
        interp.send("OUTER")
        out = {
            "sequence": list(interp.context["seq"]),
            "final_states": sorted(interp.current_state_ids),
            "note": "outer_end before inner => queued; inner between => recursive",
        }
        interp.stop()
        return out
    except RecursionError as exc:
        return {"RecursionError": str(exc)[:200]}
    except Exception as exc:
        return {"exception": f"{type(exc).__name__}: {exc}"}


# --- g10: event to a stopped / final machine -----------------------------------
async def g10_dropped_events() -> Dict[str, Any]:
    m = create_machine(
        toggle_cfg("g10"),
        logic=MachineLogic(actions={"act": lambda i, c, e, a: None}),
    )
    interp = await Interpreter(m).start()
    await interp.stop()
    out: Dict[str, Any] = {"status_after_stop": interp.status}
    try:
        await interp.send("GO")
        out["send_after_stop"] = "silently dropped (no exception)"
    except Exception as exc:
        out["send_after_stop"] = f"{type(exc).__name__}: {exc}"
    try:
        await interp.start()
        out["restart_after_stop"] = "allowed"
    except Exception as exc:
        out["restart_after_stop"] = f"{type(exc).__name__}: {exc}"

    # unknown event on a live machine
    i2 = await Interpreter(
        create_machine(
            toggle_cfg("g10b"),
            logic=MachineLogic(actions={"act": lambda i, c, e, a: None}),
        )
    ).start()
    before = sorted(i2.current_state_ids)
    await i2.send("NOT_A_REAL_EVENT")
    await asyncio.sleep(0.05)
    out["unknown_event_ignored"] = sorted(i2.current_state_ids) == before
    await i2.stop()
    return out


# --- g11: sync engine, action raises -------------------------------------------
def g11_sync_action_raises() -> Dict[str, Any]:
    def act(i, ctx, e, a):
        raise RuntimeError("sync boom")

    m = create_machine(toggle_cfg("g11"), logic=MachineLogic(actions={"act": act}))
    interp = SyncInterpreter(m).start()
    out: Dict[str, Any] = {}
    try:
        interp.send("GO")
        out["propagates_to_caller"] = False
    except Exception as exc:
        out["propagates_to_caller"] = True
        out["exc"] = f"{type(exc).__name__}: {exc}"
    out["states_after"] = sorted(interp.current_state_ids)
    out["status_after"] = interp.status
    return out


async def main() -> None:
    common.report("machine_specs", common.machine_specs())
    probes = {
        "g1_action_raises": g1_action_raises,
        "g2_guard_raises": g2_guard_raises,
        "g3_entry_action_raises_at_start": g3_entry_raises,
        "g4_service_raises": g4_service_raises,
        "g5_service_cancelled_on_stop": g5_service_cancelled,
        "g6_send_from_other_thread": g6_send_from_thread,
        "g7_concurrent_producers_ordering": g7_concurrent_tasks,
        "g8_reentrancy_async": g8_reentrancy,
        "g10_stopped_and_unknown_events": g10_dropped_events,
    }
    out: Dict[str, Any] = {}
    for name, fn in probes.items():
        try:
            out[name] = await asyncio.wait_for(fn(), timeout=90)
        except asyncio.TimeoutError:
            out[name] = {"TIMEOUT": "probe hung >90s — likely deadlock"}
        except Exception:
            out[name] = {"PROBE_CRASHED": traceback.format_exc()[-800:]}

    for name, fn in (
        ("g8b_reentrancy_sync", g8b_sync_reentrancy),
        ("g11_sync_action_raises", g11_sync_action_raises),
    ):
        try:
            r = fn()
            out[name] = await r if asyncio.iscoroutine(r) else r
        except Exception:
            out[name] = {"PROBE_CRASHED": traceback.format_exc()[-800:]}

    common.report("g_semantics", out)


if __name__ == "__main__":
    asyncio.run(main())
