"""LC-24 verification on xstate-statemachine 0.8.0.

Fix shipped (#47): `pending_events` property, `drain_pending()`, and
`stop(drain=True)` on both engines. Snapshots carry `pending_events` and
`from_snapshot` re-enqueues them, recursively for child actors. Default
`stop()` (drain=False) keeps 0.7.x semantics but now WARNS when discarding
a non-empty queue.

We test:
  1. `pending_events` reports accepted-but-unprocessed events in FIFO order.
  2. `drain_pending()` empties the queue without processing them.
  3. Snapshot round-trip: pending events survive get_snapshot -> from_snapshot.
  4. `stop(drain=True)` processes the queue to empty before teardown.
  5. Default `stop()` still discards silently but logs a warning (documented
     default behaviour, not a bug under the new API).

Exit 0 if all hold, 1 otherwise.
"""

from __future__ import annotations

import asyncio
import logging

from xstate_statemachine import Interpreter, MachineLogic, create_machine

logging.disable(logging.CRITICAL)

CFG = {
    "id": "counter",
    "initial": "s",
    "context": {"n": 0},
    "states": {"s": {"on": {"BUMP": {"actions": ["bump"]}}}},
}


def bump(i, c, e, a):  # noqa: ANN001
    c["n"] += 1


async def main() -> int:
    ok = True

    # 1) pending_events + drain_pending, with the run loop paused so events
    #    pile up in the inbox before being processed.
    m = create_machine(CFG, logic=MachineLogic(actions={"bump": bump}))
    interp = Interpreter(m)
    await interp.start()
    # Freeze processing by cancelling the run loop task's ability to run:
    # instead, send a burst faster than it can drain by sending many at once
    # via send_events (batch) then immediately inspecting before awaiting.
    for _ in range(50):
        interp._event_queue.put_nowait(  # simulate pre-drain burst directly
            __import__("xstate_statemachine").events.Event(type="BUMP", payload={})
        )
    pending = interp.pending_events
    print(f"OBSERVED len(pending_events) after burst  = {len(pending)}")
    print("EXPECTED len(pending_events) after burst  = 50 (>0)")
    if len(pending) == 0:
        ok = False

    drained = await interp.drain_pending()
    print(f"OBSERVED len(drained)                     = {len(drained)}")
    print(f"OBSERVED pending_events after drain        = {len(interp.pending_events)}")
    print("EXPECTED pending_events after drain        = 0")
    if len(interp.pending_events) != 0:
        ok = False
    if interp.context["n"] != 0:
        print(f"OBSERVED context['n'] after drain (should be unprocessed) = {interp.context['n']}")
        ok = False
    await interp.stop()

    # 2) Snapshot round trip.
    m2 = create_machine(CFG, logic=MachineLogic(actions={"bump": bump}))
    interp2 = Interpreter(m2)
    await interp2.start()
    from xstate_statemachine.events import Event as EvtType
    for _ in range(5):
        interp2._event_queue.put_nowait(EvtType(type="BUMP", payload={}))
    snap = interp2.get_snapshot()
    import json
    snap_pending = json.loads(snap).get("pending_events")
    print(f"OBSERVED snapshot has pending_events key   = {snap_pending is not None}")
    print(f"OBSERVED len(snapshot pending_events)      = {len(snap_pending or [])}")
    if not snap_pending or len(snap_pending) != 5:
        ok = False
    await interp2.stop()

    m3 = create_machine(CFG, logic=MachineLogic(actions={"bump": bump}))
    restored = Interpreter.from_snapshot(snap, m3)
    print(f"OBSERVED restored pending_events count     = {len(restored.pending_events)}")
    print("EXPECTED restored pending_events count     = 5")
    if len(restored.pending_events) != 5:
        ok = False

    # 3) stop(drain=True) processes queue to empty before teardown.
    m4 = create_machine(CFG, logic=MachineLogic(actions={"bump": bump}))
    interp4 = Interpreter(m4)
    await interp4.start()
    for _ in range(10):
        interp4._event_queue.put_nowait(EvtType(type="BUMP", payload={}))
    await interp4.stop(drain=True, timeout=5.0)
    print(f"OBSERVED context['n'] after stop(drain=True) = {interp4.context['n']}")
    print("EXPECTED context['n'] after stop(drain=True) = 10")
    if interp4.context["n"] != 10:
        ok = False

    # 4) Default stop() logs a warning when discarding a non-empty queue.
    m5 = create_machine(CFG, logic=MachineLogic(actions={"bump": bump}))
    interp5 = Interpreter(m5)
    await interp5.start()
    for _ in range(3):
        interp5._event_queue.put_nowait(EvtType(type="BUMP", payload={}))

    warned = []

    class Handler(logging.Handler):
        def emit(self, record):
            if "pending event" in record.getMessage():
                warned.append(record.getMessage())

    logging.disable(logging.NOTSET)
    lg = logging.getLogger("xstate_statemachine")
    lg.setLevel(logging.WARNING)
    h = Handler()
    lg.addHandler(h)
    await interp5.stop()
    lg.removeHandler(h)
    logging.disable(logging.CRITICAL)
    print(f"OBSERVED default stop() warns on non-empty queue = {len(warned) > 0}")
    print("EXPECTED default stop() warns on non-empty queue = True (0.7.x DISCARD behaviour kept, now logged)")
    if not warned:
        ok = False
    if interp5.context["n"] != 0:
        ok = False  # default stop() must still NOT process them

    print("RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
