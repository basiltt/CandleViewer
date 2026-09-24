"""(c) stop() / stop(drain=True) racing with in-flight work: task leaks.

1,000 cycles of: build -> start -> start in-flight work -> stop, with the
stop racing against sends, an invoked service, an `after` timer and a
spawned child actor. After each batch:

    len(asyncio.all_tasks()) - baseline  MUST be 0

and the whole run is executed under `-W error` (see run_c1.cmd / the
report's exact command) so that
  * "coroutine ... was never awaited"  (RuntimeWarning)
  * "Task was destroyed but it is pending"  (logged, not a warning --
    captured separately via a custom asyncio exception handler + log
    capture)
are failures rather than noise.

Variants, each 1,000 cycles unless noted:
  V1  stop() with N sends in flight
  V2  stop(drain=True) with N sends in flight
  V3  stop() while an invoked async service is mid-await
  V4  stop() while an `after` timer is armed but not yet due
  V5  stop() while a spawned child actor is running
  V6  stop() racing itself (two concurrent stop() calls)
"""

from __future__ import annotations

import asyncio
import gc
import logging
import sys
import warnings

from common import counter_machine, emit
from xstate_statemachine import Interpreter, MachineLogic, create_machine

CYCLES = int(sys.argv[1]) if len(sys.argv) > 1 else 1000


# --------------------------------------------------------------------------
# Capture "Task was destroyed but it is pending" + loop exception handler
# --------------------------------------------------------------------------
class _Capture(logging.Handler):
    def __init__(self):
        super().__init__(level=logging.DEBUG)
        self.records: list[str] = []

    def emit(self, record):  # noqa: A003
        msg = record.getMessage()
        if "Task was destroyed but it is pending" in msg:
            self.records.append(msg[:200])


# --------------------------------------------------------------------------
# Machines
# --------------------------------------------------------------------------
SERVICE_CFG = {
    "id": "svc",
    "initial": "loading",
    "context": {},
    "states": {
        "loading": {
            "invoke": {
                "src": "slow",
                "onDone": {"target": "ok"},
                "onError": {"target": "bad"},
            }
        },
        "ok": {"type": "final"},
        "bad": {"type": "final"},
    },
}

AFTER_CFG = {
    "id": "aft",
    "initial": "waiting",
    "context": {},
    "states": {
        "waiting": {"after": {50000: {"target": "late"}}},
        "late": {"type": "final"},
    },
}

CHILD_CFG = {
    "id": "child",
    "initial": "busy",
    "context": {},
    "states": {"busy": {"after": {60000: {"target": "fin"}}}, "fin": {"type": "final"}},
}

PARENT_CFG = {
    "id": "parent",
    "initial": "running",
    "context": {},
    "states": {
        "running": {
            "entry": ["spawn_kid"],
            "on": {"PING": {"actions": []}},
        }
    },
}


async def slow(interpreter, ctx, event):  # noqa: ANN001
    await asyncio.sleep(3600)
    return "never"


def make_service_machine():
    return create_machine(SERVICE_CFG, logic=MachineLogic(services={"slow": slow}))


def make_after_machine():
    return create_machine(AFTER_CFG, logic=MachineLogic())


def make_parent_machine():
    child = create_machine(CHILD_CFG, logic=MachineLogic())
    return create_machine(
        PARENT_CFG, logic=MachineLogic(services={"kid": child})
    )


# --------------------------------------------------------------------------
# Cycles
# --------------------------------------------------------------------------
async def cycle_sends(drain: bool, n_sends: int = 5):
    i = Interpreter(counter_machine())
    await i.start()
    for _ in range(n_sends):
        await i.send("PING")
    await i.stop(drain=drain)


async def cycle_service():
    i = Interpreter(make_service_machine())
    await i.start()
    await asyncio.sleep(0)  # let the invoke task start
    await i.stop()


async def cycle_after():
    i = Interpreter(make_after_machine())
    await i.start()
    await asyncio.sleep(0)
    await i.stop()


async def cycle_child():
    i = Interpreter(make_parent_machine())
    await i.start()
    await asyncio.sleep(0)
    await i.send("PING")
    await i.stop()


async def cycle_double_stop():
    i = Interpreter(counter_machine())
    await i.start()
    await i.send("PING")
    await asyncio.gather(i.stop(), i.stop(), return_exceptions=True)


async def cycle_true_race(jitter: list[int] = [0]):  # noqa: B006
    """stop() scheduled CONCURRENTLY with producers, at a varying loop phase.

    The other cycles stop after the in-flight work is set up; this one lets
    stop() and the producers interleave at a rotating number of loop turns,
    so the teardown lands in a different place each cycle.
    """
    i = Interpreter(make_service_machine())
    await i.start()

    async def producer():
        for _ in range(10):
            await i.send("PING")
            await asyncio.sleep(0)

    async def stopper():
        for _ in range(jitter[0] % 7):
            await asyncio.sleep(0)
        await i.stop(drain=(jitter[0] % 2 == 0))

    jitter[0] += 1
    await asyncio.gather(producer(), stopper(), return_exceptions=True)


async def measure(name: str, coro_factory, cycles: int, cap: _Capture):
    # settle
    for _ in range(3):
        await asyncio.sleep(0)
    gc.collect()
    await asyncio.sleep(0.05)
    baseline = len(asyncio.all_tasks())

    loop_exceptions: list[str] = []
    old_handler = asyncio.get_running_loop().get_exception_handler()

    def handler(loop, ctx):
        loop_exceptions.append(str(ctx.get("message"))[:200])

    asyncio.get_running_loop().set_exception_handler(handler)
    before_records = len(cap.records)

    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        for _ in range(cycles):
            await coro_factory()
        # let deferred teardown tasks finish
        for _ in range(20):
            await asyncio.sleep(0)
        await asyncio.sleep(0.2)
        gc.collect()
        await asyncio.sleep(0.05)
        wmsgs = [str(x.message) for x in w]

    after = len(asyncio.all_tasks())
    asyncio.get_running_loop().set_exception_handler(old_handler)
    return {
        "cycles": cycles,
        "tasks_baseline": baseline,
        "tasks_after": after,
        "task_delta": after - baseline,
        "runtime_warnings": sorted(set(wmsgs))[:10],
        "runtime_warning_count": len(wmsgs),
        "task_destroyed_pending": len(cap.records) - before_records,
        "loop_exception_messages": sorted(set(loop_exceptions))[:10],
    }


async def main():
    cap = _Capture()
    logging.getLogger("asyncio").addHandler(cap)
    logging.getLogger("asyncio").setLevel(logging.DEBUG)
    # Silence the library's own chatter so the capture is readable.
    logging.getLogger("xstate_statemachine").setLevel(logging.CRITICAL)

    res = {}
    res["v1_stop_with_sends"] = await measure(
        "v1", lambda: cycle_sends(False), CYCLES, cap
    )
    res["v2_stop_drain_with_sends"] = await measure(
        "v2", lambda: cycle_sends(True), CYCLES, cap
    )
    res["v3_stop_during_invoke"] = await measure(
        "v3", cycle_service, CYCLES, cap
    )
    res["v4_stop_with_armed_after"] = await measure(
        "v4", cycle_after, CYCLES, cap
    )
    res["v5_stop_with_child_actor"] = await measure(
        "v5", cycle_child, CYCLES, cap
    )
    res["v6_concurrent_double_stop"] = await measure(
        "v6", cycle_double_stop, CYCLES, cap
    )
    res["v7_stop_racing_producers_at_rotating_phase"] = await measure(
        "v7", cycle_true_race, CYCLES, cap
    )
    emit("c1_stop_leaks", res)


if __name__ == "__main__":
    asyncio.run(main())
