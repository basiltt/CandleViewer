"""E7-redo: SyncInterpreter `after` timers when constructed inside a
running asyncio event loop.

`RealClock.set_timeout` branches on `asyncio.get_running_loop()`:

    loop = asyncio.get_running_loop()  (or None)
    if loop is not None: return loop.call_later(...)
    return self._heap.push(...)

The branch is on the CALLER'S context at schedule time, not on which
engine owns the clock. A `SyncInterpreter` started from inside a running
loop -- e.g. a sync sub-machine driven from an async service, a sync
machine built in an async test, or an async app that keeps one sync
machine for a hot path -- therefore parks its `after` deadlines on the
asyncio loop. `clock.pump()` then finds an EMPTY heap, so `tick()` and
the pump at the top of `send()` never fire the timer.

E7a  control: outside a loop, tick() fires the timer
E7b  inside a running loop, tick() fires the timer
E7c  inside a loop, does the timer arrive by any other route (loop turn)?
E7d  same question for a SyncInterpreter nested under an async parent
"""

from __future__ import annotations

import asyncio
import os
import sys
import threading
import time
import warnings

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _harness import Probe  # noqa: E402

from xstate_statemachine import (  # noqa: E402
    MachineLogic,
    SyncInterpreter,
    create_machine,
)

warnings.simplefilter("ignore", DeprecationWarning)
P = Probe("E7-redo — sync timers inside a running asyncio loop")

CFG = {
    "id": "sy",
    "initial": "a",
    "context": {"log": []},
    "states": {
        "a": {"after": {40: {"target": "b", "actions": ["note"]}}},
        "b": {},
    },
}


def _note(i, c, e, a):
    c["log"].append("fired")


def boot():
    m = create_machine(CFG, logic=MachineLogic(actions={"note": _note}))
    return SyncInterpreter(m).start()


def e7a():
    """True control: no asyncio loop anywhere on this thread."""
    out = {}

    def body():
        i = boot()
        out["pending_at_start"] = getattr(i.clock, "pending", "n/a")
        time.sleep(0.08)
        i.tick()
        out["states"] = set(i.current_state_ids)
        i.stop()

    t = threading.Thread(target=body)
    t.start()
    t.join()
    return (
        out["states"] == {"sy.b"},
        f"off-loop thread: clock.pending={out['pending_at_start']} "
        f"states_after_tick={out['states']}",
    )


async def e7b():
    i = boot()
    heap_pending = getattr(i.clock, "pending", "n/a")
    time.sleep(0.08)  # blocking on purpose: tick() must not need the loop
    i.tick()
    st = set(i.current_state_ids)
    i.stop()
    return (
        st == {"sy.b"},
        f"inside a loop: clock.pending={heap_pending} states_after_tick={st} "
        f"(pending==0 means the deadline went to loop.call_later, not the heap)",
    )


async def e7c():
    i = boot()
    await asyncio.sleep(0.15)  # give the asyncio loop plenty of turns
    st_loop = set(i.current_state_ids)
    i.tick()
    st_tick = set(i.current_state_ids)
    queued = len(i._event_queue)
    i.stop()
    return (
        st_tick == {"sy.b"},
        f"after 150ms of loop turns states={st_loop}; after tick()={st_tick}; "
        f"queue_depth={queued}",
    )


async def e7d():
    """A sync child driven from inside an async service -- the real shape."""
    results = {}

    async def driver():
        i = boot()
        await asyncio.sleep(0.12)
        i.tick()
        results["states"] = set(i.current_state_ids)
        results["pending"] = getattr(i.clock, "pending", "n/a")
        i.stop()

    await driver()
    return (
        results["states"] == {"sy.b"},
        f"sync machine driven from an async coroutine: states={results['states']} "
        f"clock.pending={results['pending']}",
    )


async def main():
    ok, d = e7a()
    P.check("E7a", "control: outside any loop", ok, d)
    for pid, title, fn in [
        ("E7b", "inside a loop, tick() fires", e7b),
        ("E7c", "inside a loop, any other route", e7c),
        ("E7d", "sync child under async parent", e7d),
    ]:
        try:
            ok, d = await fn()
            P.check(pid, title, ok, d)
        except Exception as exc:  # noqa: BLE001
            P.record_exc(pid, title, exc)
    P.report()


if __name__ == "__main__":
    asyncio.run(main())
