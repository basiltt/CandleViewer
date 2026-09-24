"""P12 (STANDALONE): the #192 provenance tag does NOT survive a snapshot
round-trip, and neither does the priority LANE itself.

`_persisted_pending` flattens the lane to `[ev for ev, _ in queue]` and
`_enqueue_restored` puts every restored record into the INBOX. So after a
round-trip:

  * a pending engine completion is external inbox traffic -- uncharged by
    `maxIterations`, never shed by a chain trip, and it resets the settle
    budget rules differently from a lane item;
  * a caller's `send(priority=True)` loses its head-of-queue position
    relative to later inbox traffic only in so far as ordering is
    preserved, but a due `after` event that was in the lane now queues
    BEHIND any external backlog restored with it.

The probe persists a machine with one lane item and one inbox item and
shows both land in the inbox with the lane empty.

Exit 1 = provenance/lane lost.
"""
import asyncio, json, sys
from xstate_statemachine import create_machine, Interpreter, MachineLogic

CFG = {"id": "m", "initial": "a",
       "states": {"a": {"on": {"P": "b", "X": "b"}}, "b": {}}}


def build():
    return create_machine(json.loads(json.dumps(CFG)), logic=MachineLogic())


async def main():
    i = Interpreter(build())
    await i.start()
    # Stop the loop from draining: park items directly, as the engine does.
    i._priority_queue.append((_ev("LANE"), True))
    i._put_inbox(_ev("INBOX"))
    lane_before = [(e.type, tag) for e, tag in i._priority_queue]
    blob = json.loads(json.dumps(i.get_persisted_snapshot()))
    await i.stop()
    print("lane before:", lane_before)
    print("persisted pending:", [r["type"] for r in blob.get("pending_events", [])])

    j = Interpreter.from_snapshot(json.dumps(blob), build())
    lane_after = [(e.type, tag) for e, tag in j._priority_queue]
    q = j._event_queue
    items = list(getattr(q, "_queue", None) or getattr(q, "_items", []))
    names = [getattr(e, "type", e) for e in items]
    print("lane after restore:", lane_after)
    print("inbox after restore:", names)
    return lane_after, names


def _ev(t):
    from xstate_statemachine import Event
    return Event(type=t)


lane, inbox = asyncio.run(asyncio.wait_for(main(), 20.0))
bad = (not lane) and "LANE" in inbox
print("VERDICT:", "LANE + PROVENANCE LOST (bug)" if bad else "preserved (ok)")
sys.exit(1 if bad else 0)
