"""R4-27: SyncInterpreter.tick() delivers only ONE due `after` deadline per
call when deadlines chain (a->b->c->d, each `after: 0`/short). Its while-loop
pumps timers only while the internal queues are non-empty and exits as soon
as the queue drains for that step, so a newly-armed already-due timer from
the just-completed transition is never observed before tick() returns. The
async engine's settle loop keeps draining until quiescent, so it walks the
whole chain in one wall-clock settle.

Realistic shape: an ack-timeout -> retry -> escalate ladder, all already due
after a stall. A caller ticking once per poll lands one rung below where
wall-clock says it should be.

Exits 1 while a single tick() after all deadlines are already due leaves the
sync engine short of the terminal state that the async engine reaches in one
settle.
"""
from __future__ import annotations
import sys as _xs_sys  # noqa: E402
from pathlib import Path as _XsPath  # noqa: E402
_xs_sys.path.insert(0, str(_XsPath(__file__).resolve().parents[4] / "gate"))
from _paths import REPO_ROOT as _REPO, XSTATE_SRC as _XS, upstream_main_python as _xs_main_py  # noqa: E402,F401

import asyncio
import logging
import sys
import time

sys.path.insert(
    0, str(_XS / 'src')
)
logging.disable(logging.CRITICAL)

from xstate_statemachine import (  # noqa: E402
    Interpreter,
    MachineLogic,
    SyncInterpreter,
    create_machine,
)

CFG = {
    "id": "order",
    "initial": "submitted",
    "states": {
        "submitted": {"after": {50: "ack_timeout"}},
        "ack_timeout": {"after": {50: "retry"}},
        "retry": {"after": {50: "escalated"}},
        "escalated": {},
    },
}


def sync_run():
    s = SyncInterpreter(create_machine(CFG, logic=MachineLogic())).start()
    time.sleep(0.25)  # all three deadlines are now due
    s.tick()  # a single tick, as a poll-based caller would do
    result = sorted(s.current_state_ids)
    s.stop()
    return result


async def async_run():
    i = await Interpreter(create_machine(CFG, logic=MachineLogic())).start()
    await asyncio.sleep(0.25)
    result = sorted(i.current_state_ids)
    await i.stop()
    return result


if __name__ == "__main__":
    sync_result = sync_run()
    async_result = asyncio.run(async_run())
    print(f"OBSERVED: sync (1 tick after 0.25s)={sync_result}  async (0.25s settle)={async_result}")
    print("EXPECTED: sync == ['order.escalated'] == async; every due deadline drains in one tick()")
    if sync_result == async_result:
        print("PASS")
        sys.exit(0)
    print("FAIL: sync tick() lags behind the fully-settled async state")
    sys.exit(1)
