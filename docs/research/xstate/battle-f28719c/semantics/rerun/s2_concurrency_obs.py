"""S2 - CONCURRENCY + OBSERVABILITY: round-7 attacks on the #166/#172/#173/#157
fixes: per-macrostep chain budget under external load, service_pool_size,
done-callback balance, loop-side RAISE refusal hooks.
"""

from __future__ import annotations

import asyncio
import threading
import time
from typing import Any, Dict, List

from n_harness import attack, main

from xstate_statemachine import (
    Interpreter,
    MachineLogic,
    OverflowPolicy,
    PluginBase,
    SyncInterpreter,
    create_machine,
    raise_,
)


class DropSpy(PluginBase):
    def __init__(self) -> None:
        self.drops: List[str] = []
        self.lock = threading.Lock()

    def on_event_dropped(self, interp, event, reason):  # noqa: ANN001
        with self.lock:
            self.drops.append(reason)


# ----------------------------------------------------------- S2-01 budget --
CHAIN = {
    "id": "ch",
    "initial": "idle",
    "context": {"n": 0},
    "states": {
        "idle": {"on": {"GO": "spin", "PING": {"actions": ["noop"]}}},
        "spin": {"entry": ["tick", raise_({"type": "MORE"})], "on": {"MORE": "spin2"}},
        "spin2": {"entry": ["tick", raise_({"type": "MORE"})], "on": {"MORE": "spin"}},
    },
}


def _chain_logic() -> MachineLogic:
    def tick(i_, ctx, e, am):  # noqa: ANN001
        ctx["n"] = ctx.get("n", 0) + 1

    def noop(i_, ctx, e, am):  # noqa: ANN001
        pass

    return MachineLogic(actions={"tick": tick, "noop": noop})


@attack(
    "S2-01",
    "#166: 16 concurrent EXTERNAL senders during a self-generated chain do "
    "NOT reset the per-macrostep budget - the chain still trips",
    "the budget is on the instance now, reset only when an external event "
    "BEGINS its step; concurrent traffic must not hand the runaway a refill",
)
async def s2_01() -> Dict[str, Any]:
    spy = DropSpy()
    m = create_machine(CHAIN, logic=_chain_logic())
    i = await Interpreter(m).use(spy).start()
    stop = threading.Event()

    def flood() -> None:
        while not stop.is_set():
            try:
                i.send_threadsafe("PING")
            except Exception:  # noqa: BLE001
                pass
            time.sleep(0.001)

    threads = [threading.Thread(target=flood, daemon=True) for _ in range(16)]
    for t in threads:
        t.start()
    await i.send("GO")
    await asyncio.sleep(3.0)
    stop.set()
    for t in threads:
        t.join(timeout=1)
    tripped = "chain_budget" in spy.drops
    # NOTE (D7-semantics-2): `last_error` is a LATCH cleared by the next
    # successful transition, so under concurrent external traffic it reads
    # None moments after the trip. The hook is the reliable channel.
    err = type(i.last_error).__name__ if i.last_error else None
    ticks = i.context.get("n", 0)
    await i.stop()
    return {
        "ok": tripped,  # hook-observable trip is the contract
        "chain_budget_drops": spy.drops.count("chain_budget"),
        "last_error": err,
        "ticks": ticks,
        "tripped": tripped,
    }


# ------------------------------------------------------ S2-02 pool size=1 --
POOL = {
    "id": "pl",
    "initial": "idle",
    "states": {
        "idle": {"on": {"RUN": "work"}},
        "work": {"invoke": {"src": "slow", "onDone": "idle"}},
    },
}


@attack(
    "S2-02",
    "#173: service_pool_size=1 with 50 plain-def services serialises without "
    "deadlock, and stop() mid-service returns promptly leaking no threads",
    "a public pool size must not turn a saturated pool into a hang on stop()",
)
async def s2_02() -> Dict[str, Any]:
    def slow(i_, ctx, e):  # noqa: ANN001  plain def -> executor
        time.sleep(0.02)
        return 1

    before = threading.active_count()
    machines = []
    for _ in range(50):
        m = create_machine(POOL, logic=MachineLogic(services={"slow": slow}))
        machines.append(await Interpreter(m, service_pool_size=1).start())
    t0 = time.monotonic()
    await asyncio.gather(*[i.send("RUN") for i in machines])
    await asyncio.sleep(0.5)
    fired = time.monotonic() - t0

    # stop() MID-service on a fresh machine
    m2 = create_machine(POOL, logic=MachineLogic(services={"slow": slow}))
    i2 = await Interpreter(m2, service_pool_size=1).start()
    await i2.send("RUN")
    await asyncio.sleep(0.005)
    t1 = time.monotonic()
    try:
        await asyncio.wait_for(i2.stop(), timeout=10)
        stop_ok, stop_s = True, time.monotonic() - t1
    except asyncio.TimeoutError:
        stop_ok, stop_s = False, 10.0
    for i in machines:
        await i.stop()
    await asyncio.sleep(0.3)
    after = threading.active_count()
    idle = sum(1 for i in machines if "pl.idle" in i.current_state_ids)
    return {
        "ok": stop_ok and idle == 50 and (after - before) <= 2,
        "all_completed": idle,
        "dispatch_seconds": round(fired, 3),
        "stop_midservice_seconds": round(stop_s, 3),
        "threads_before": before,
        "threads_after": after,
    }


@attack(
    "S2-03",
    "#173: service_pool_size is validated (>=1) and DEFAULT_SERVICE_POOL_SIZE "
    "is exported; pool_size=8 beats pool_size=1 on 8 concurrent services",
    "a knob that does nothing is worse than no knob",
)
async def s2_03() -> Dict[str, Any]:
    import xstate_statemachine as _x
    from xstate_statemachine.interpreter import DEFAULT_SERVICE_POOL_SIZE

    exported = (
        hasattr(_x, "DEFAULT_SERVICE_POOL_SIZE")
        and "DEFAULT_SERVICE_POOL_SIZE" in getattr(_x, "__all__", ())
    )

    def slow(i_, ctx, e):  # noqa: ANN001
        time.sleep(0.15)
        return 1

    PAR = {
        "id": "pp", "type": "parallel",
        "states": {
            f"r{k}": {
                "initial": "idle",
                "states": {
                    "idle": {"on": {"RUN": "w"}},
                    "w": {"invoke": {"src": "slow", "onDone": "idle"}},
                },
            }
            for k in range(8)
        },
    }

    async def timed(n: int) -> float:
        m = create_machine(PAR, logic=MachineLogic(services={"slow": slow}))
        i = await Interpreter(m, service_pool_size=n).start()
        t0 = time.monotonic()
        await i.send("RUN", wait=True)
        el = time.monotonic() - t0
        await i.stop()
        return el

    t1 = await timed(1)
    t8 = await timed(8)
    bad = None
    try:
        Interpreter(create_machine(POOL, logic=MachineLogic(services={"slow": slow})), service_pool_size=0)
    except ValueError as exc:  # noqa: BLE001
        bad = "ValueError"
    return {
        "ok": (
            bad == "ValueError"
            and t8 < t1 * 0.6
            and DEFAULT_SERVICE_POOL_SIZE == 4
            and exported
        ),
        "default_pool": DEFAULT_SERVICE_POOL_SIZE,
        "exported_from_package_root": exported,
        "pool1_seconds": round(t1, 3),
        "pool8_seconds": round(t8, 3),
        "zero_rejected": bad,
    }


# ---------------------------------------- S2-04 loop-side RAISE refusal ----
FLAT = {"id": "f", "initial": "a", "states": {"a": {"on": {"E": {"actions": ["slow_act"]}}}}}


@attack(
    "S2-04",
    "#157: every loop-side RAISE refusal under 16 flooding threads fires "
    "on_event_dropped(queue_full) EXACTLY once, and the count matches the "
    "refusals observed on the futures",
    "a hidden shed rate is load shedding you cannot reconcile against",
)
async def s2_04() -> Dict[str, Any]:
    spy = DropSpy()

    def slow_act(i_, ctx, e, am):  # noqa: ANN001
        time.sleep(0.002)

    m = create_machine(FLAT, logic=MachineLogic(actions={"slow_act": slow_act}))
    i = await Interpreter(
        m, max_queue_size=4, overflow_policy=OverflowPolicy.RAISE
    ).use(spy).start()

    call_site = {"n": 0}
    future_refusals = {"n": 0}
    futs: List[Any] = []
    lk = threading.Lock()

    def flood() -> None:
        for _ in range(60):
            try:
                f = i.send_threadsafe("E")
                with lk:
                    futs.append(f)
            except Exception:  # noqa: BLE001
                with lk:
                    call_site["n"] += 1

    threads = [threading.Thread(target=flood, daemon=True) for _ in range(16)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=20)
    await asyncio.sleep(1.5)
    for f in futs:
        try:
            f.result(timeout=2)
        except Exception as exc:  # noqa: BLE001
            if "Overflow" in type(exc).__name__:
                future_refusals["n"] += 1
    await i.stop()
    qf = spy.drops.count("queue_full")
    return {
        # the hook must fire once per LOOP-SIDE refusal (the futures' ones),
        # never for the call-site ones (those already reached the caller)
        "ok": qf == future_refusals["n"] and qf > 0,
        "hook_queue_full": qf,
        "loop_side_refusals_on_futures": future_refusals["n"],
        "call_site_raises": call_site["n"],
        "other_drop_reasons": sorted(set(spy.drops) - {"queue_full"}),
    }


# ------------------------------------- S2-05 done-callback balance (#172) --
@attack(
    "S2-05",
    "#172: the threadsafe in-flight counter returns to 0 after delivered, "
    "refused, cancelled and loop-stopped-before-run outcomes (no double-fire)",
    "a leaked count gates the chain-budget reset for the machine's whole life",
)
async def s2_05() -> Dict[str, Any]:
    out: Dict[str, Any] = {}

    # [1] delivered + refused mix under RAISE
    spy = DropSpy()
    m = create_machine(FLAT, logic=MachineLogic(actions={"slow_act": lambda *a: None}))
    i = await Interpreter(
        m, max_queue_size=4, overflow_policy=OverflowPolicy.RAISE
    ).use(spy).start()
    fs = []
    for _ in range(200):
        try:
            fs.append(i.send_threadsafe("E", internal=True))
        except Exception:  # noqa: BLE001
            pass
    await asyncio.sleep(1.0)
    for f in fs:
        try:
            f.result(timeout=2)
        except Exception:  # noqa: BLE001
            pass
    await asyncio.sleep(0.3)
    out["after_mixed"] = i._threadsafe_self_sends_in_flight
    await i.stop()

    # [2] cancelled futures
    m2 = create_machine(FLAT, logic=MachineLogic(actions={"slow_act": lambda *a: None}))
    i2 = await Interpreter(m2).start()
    fs2 = [i2.send_threadsafe("E", internal=True) for _ in range(50)]
    for f in fs2:
        f.cancel()
    await asyncio.sleep(0.5)
    out["after_cancelled"] = i2._threadsafe_self_sends_in_flight
    await i2.stop()

    # [3] loop stopped before the coroutine ran
    m3 = create_machine(FLAT, logic=MachineLogic(actions={"slow_act": lambda *a: None}))
    i3 = await Interpreter(m3).start()
    fs3 = []
    for _ in range(50):
        try:
            fs3.append(i3.send_threadsafe("E", internal=True))
        except Exception:  # noqa: BLE001
            pass
    await i3.stop()
    await asyncio.sleep(0.3)
    out["after_loop_stopped"] = i3._threadsafe_self_sends_in_flight

    out["ok"] = all(v == 0 for k, v in out.items() if k.startswith("after_"))
    return out


if __name__ == "__main__":
    main("s2_concurrency_obs")
