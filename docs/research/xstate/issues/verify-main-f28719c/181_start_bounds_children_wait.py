# -*- coding: utf-8 -*-
"""Verify #181 on f28719c: start() bounds the wait for invoked children.
Standalone (stdlib + xstate_statemachine only). Matrix: {def, async def}
entry action x per-child timeout observability, watchdog-protected.
Exit 0 iff every cell passes.
"""
import asyncio
import logging
import sys
import time

from xstate_statemachine import Interpreter, MachineLogic, create_machine

WATCHDOG_S = 30.0


def build(kind: str, delay: float):
    if kind == "async def":
        async def entry_action(i, c, e, a):
            await asyncio.sleep(delay)
    else:
        def entry_action(i, c, e, a):
            time.sleep(delay)

    cfg = {
        "id": "m181",
        "initial": "parent",
        "states": {
            "parent": {
                "invoke": {"id": "child", "src": "child_machine"},
            }
        },
    }
    child_cfg = {
        "id": "child",
        "initial": "busy",
        "states": {"busy": {"entry": ["slow"]}},
    }
    from xstate_statemachine import create_machine as cm

    child_machine = cm(
        child_cfg, logic=MachineLogic(actions={"slow": entry_action})
    )
    machine = create_machine(
        cfg, logic=MachineLogic(services={"child_machine": child_machine})
    )
    return machine


async def run_cell(kind: str) -> dict:
    machine = build(kind, delay=1.0)
    warnings = []

    class Handler(logging.Handler):
        def emit(self, record):
            if "children_timeout" in record.getMessage():
                warnings.append(record.getMessage())

    logger = logging.getLogger("xstate_statemachine.interpreter")
    h = Handler()
    logger.addHandler(h)
    it = Interpreter(machine)
    t0 = time.monotonic()
    await asyncio.wait_for(it.start(children_timeout=0.1), timeout=5.0)
    elapsed = time.monotonic() - t0
    status_during = it.status
    await asyncio.sleep(1.2)  # let the slow child finish
    logger.removeHandler(h)
    await asyncio.wait_for(it.stop(), timeout=5.0)
    # A `def` entry action holds the event-loop thread until it returns and
    # CANNOT be pre-empted (documented, #181/#194): its bound is honest only
    # in that the overrun is reported, not in wall-clock duration. `async def`
    # IS bounded in wall-clock terms since it yields at await points.
    bounded_ok = elapsed < 0.9 if kind == "async def" else True
    return {
        "kind": kind,
        "start_elapsed": elapsed,
        "bounded": bounded_ok,
        "status_during": status_during,
        "warned": bool(warnings),
    }


async def main() -> int:
    results = []
    for kind in ("def", "async def"):
        r = await asyncio.wait_for(run_cell(kind), timeout=WATCHDOG_S)
        results.append(r)
        print(r)
    ok = all(r["bounded"] and r["status_during"] == "running" and r["warned"] for r in results)
    print("VERDICT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
