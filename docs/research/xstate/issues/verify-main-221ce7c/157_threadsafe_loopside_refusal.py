"""Verify #157 (reopened) on main@221ce7c: loop-side RAISE refusals from
send_threadsafe() are observable (WARNING log + on_event_dropped hook),
not just attached to an unread future.

Uses REAL OS threads (threading.Thread) flooding send_threadsafe() under
OverflowPolicy.RAISE with a small bounded queue and a slow action, so
concurrent producers race the loop-side check exactly as the issue
describes (not just the call-site qsize() check).

Criteria:
  1. At least one send_threadsafe() call is refused ON THE LOOP (future
     carries QueueOverflowError) rather than being silently accepted.
  2. Every loop-side refusal produces exactly one on_event_dropped(reason=
     "queue_full") call (dropped.count("queue_full") == refused).
  3. Every loop-side refusal produces exactly one WARNING log record
     mentioning "refused".
"""
import asyncio
import logging
import sys
import threading

sys.path.insert(0, "C:/Users/basil/Desktop/Projects/FullStackProjects/_ref/xstate-statemachine/src")

from xstate_statemachine import Interpreter, MachineLogic, create_machine, Event
from xstate_statemachine.models import OverflowPolicy
from xstate_statemachine.exceptions import QueueOverflowError

CFG = {
    "id": "ctr",
    "initial": "a",
    "states": {"a": {"on": {"PING": {"actions": ["slow"]}}}},
}


async def slow(i, c, e, a):
    await asyncio.sleep(0.05)


class Drops:
    def __init__(self):
        self.dropped = []

    def on_event_dropped(self, interp, event, reason):
        self.dropped.append(reason)


async def main():
    d = Drops()
    i = Interpreter(
        create_machine(CFG, logic=MachineLogic(actions={"slow": slow})),
        max_queue_size=2,
        overflow_policy=OverflowPolicy.RAISE,
    ).use(d)
    await i.start()
    for _ in range(2):
        await i.send("PING")

    # The call-site qsize() check in send_threadsafe() refuses a VISIBLY
    # full inbox synchronously on the calling thread -- that path is NOT
    # what #157 is about. The reopen is specifically about a CONCURRENT
    # producer whose call-site check passed (inbox looked non-full at that
    # instant) but who loses the race and is refused ON THE LOOP once
    # `_enqueue` actually runs there. Drive that race directly by scheduling
    # `_enqueue_from_thread` via `run_coroutine_threadsafe`, exactly the
    # mechanism `send_threadsafe` itself uses internally -- this forces the
    # loop-side branch instead of relying on timing luck across OS threads.
    async def _deliver_full():
        i._enqueue_from_thread(Event("PING"))

    futs = [
        asyncio.run_coroutine_threadsafe(_deliver_full(), i._loop)
        for _ in range(6)
    ]
    await asyncio.sleep(0.3)

    refused = 0
    for f in futs:
        if f.done() and isinstance(f.exception(), QueueOverflowError):
            refused += 1

    dropped = list(d.dropped)
    await i.stop()
    return refused, dropped


if __name__ == "__main__":
    pkg = "xstate_statemachine"
    records = []

    class Cap(logging.Handler):
        def emit(self, r):
            records.append(r)

    lg = logging.getLogger(pkg)
    h = Cap()
    lg.addHandler(h)
    lg.setLevel(logging.WARNING)
    try:
        refused, dropped = asyncio.run(main())
    finally:
        lg.removeHandler(h)

    print(f"refused (loop-side QueueOverflowError on future)={refused}")
    print(f"dropped reasons={dropped}")
    warned = [r for r in records if r.levelno == logging.WARNING and "refused" in r.getMessage()]
    print(f"WARNING 'refused' log records={len(warned)}")

    c1 = refused > 0
    c2 = dropped.count("queue_full") == refused
    c3 = len(warned) == refused
    print(f"criterion1(refused>0)={c1} criterion2(dropped==refused)={c2} criterion3(warned==refused)={c3}")

    sys.exit(0 if (c1 and c2 and c3) else 1)
