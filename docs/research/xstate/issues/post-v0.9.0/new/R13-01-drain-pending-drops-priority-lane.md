# Bug: `Interpreter.drain_pending()` silently discards the entire priority queue, and `stop()` then destroys it

**NOT POSTED. Draft.**

**Severity (ours): High** - data loss on the documented durable-shutdown path.
**Version:** `0.9.0` (tag `v0.9.0` = `91bd979`; also present on `main` @ `e3a1f22`).
**Affects:** the async `Interpreter`.

## Summary

`Interpreter.drain_pending()` (`interpreter.py:1715`) is documented as removing and returning

> "**every** accepted-but-unprocessed event ... intended for shutdown paths that must persist accepted work durably before the process exits."

Its body reads `self._event_queue` only. The async engine has **two** queues, and `_priority_queue` (`interpreter.py:374`) is never touched. Everything in the priority lane - fired `after` timers, invoke completions, and anything submitted through the public `send_priority()` (`interpreter.py:1051`) - is omitted from the result **and left in the queue**, where `_teardown()` then calls `_priority_queue.clear()` (`interpreter.py:1635`).

So the documented shutdown recipe

```python
pending = await interpreter.drain_pending()
persist(pending)
await interpreter.stop()
```

**permanently loses** every priority-lane event that was accepted before shutdown.

The sibling view disagrees. `_snapshot_pending_events()` (`interpreter.py:1675`) returns `[ev for ev, _ in self._priority_queue] + inbox` - it deliberately includes the lane (that was #107), and it is what the public `pending_events` property exposes. The interpreter therefore offers two durability views of the same state that return different sets, and the one whose docstring promises completeness is the lossy one.

## Reproduction

Standalone - stdlib plus `xstate_statemachine` only, every helper inlined, no files read, runs from any working directory. A slow action parks the run loop so both lanes stay populated; everything else is public API.

```python
"""drain_pending() omits the priority lane; stop() then destroys it."""
import asyncio

from xstate_statemachine import create_machine, MachineLogic, Interpreter

CFG = {
    "id": "m",
    "initial": "a",
    "states": {
        "a": {
            "on": {
                "GO": {"target": "b", "actions": ["slow"]},
                "P1": "a", "P2": "a", "I1": "a", "I2": "a",
            }
        },
        "b": {"on": {"P1": "b", "P2": "b", "I1": "b", "I2": "b"}},
    },
}


async def slow(interpreter, ctx, event, action):
    await asyncio.sleep(1.0)


def types(events):
    return [getattr(e, "type", e) for e in events]


async def main():
    machine = create_machine(CFG, logic=MachineLogic(actions={"slow": slow}))
    i = Interpreter(machine)
    await i.start()

    await i.send("GO")
    await asyncio.sleep(0.2)          # run loop is parked inside `slow`

    await i.send("I1", wait=False)    # inbox
    i.send_priority("P1", wait=False)  # priority lane
    await i.send("I2", wait=False)    # inbox
    i.send_priority("P2", wait=False)  # priority lane
    await asyncio.sleep(0.05)

    view = types(i.pending_events)
    drained = types(await i.drain_pending())
    print("pending_events      :", view)
    print("await drain_pending :", drained)
    print("LOST                :", [t for t in view if t not in drained])
    print("still queued after  :", types(i.pending_events))

    # The omitted events are not merely absent from the return value:
    # stop() clears the lane, so they are gone for good.
    print("priority lane before stop:", [getattr(e, "type", e) for e, _ in i._priority_queue])
    await i.stop()
    print("priority lane after  stop:", [getattr(e, "type", e) for e, _ in i._priority_queue])


asyncio.run(asyncio.wait_for(main(), 25))
```

Output on `v0.9.0` (exit 0):

```
pending_events      : ['P1', 'P2', 'I1', 'I2']
await drain_pending : ['I1', 'I2']
LOST                : ['P1', 'P2']
still queued after  : ['P1', 'P2']
priority lane before stop: ['P1', 'P2']
priority lane after  stop: []
```

## Expected

`drain_pending()` returns every accepted-but-unprocessed event, priority lane first - the order `_snapshot_pending_events()` already uses.

## Why we do not think this is documented behaviour

We checked before filing. The docstring plus `docs/api/index.md:717`, `docs/_guide/interpreters.md:212`, `docs/_guide/snapshots.md:299` and `README.md:1632` all describe the return as *every* pending event. None mentions a lane exclusion, and `pending_events` on the very same object disagrees with it.

We also considered and rejected three readings:

- *"Harmless - they stay queued."* They stay queued only until `stop()`, which is the next line of the documented recipe. The final two lines of the repro show the lane empty afterwards.
- *"Duplicate of #107 / #214 / #233."* Those are restore paths and are fixed. This reproduces on a **live** interpreter with no snapshot involved.
- *"Trust boundary."* Nothing here crosses one; it is all public API on an interpreter the caller owns.

There is no XState v5 or SCXML analogue that would excuse it - neither spec has this API.

## Impact

The priority lane is where engine-minted, chain-charged events land (`_deliver_priority`, `interpreter.py:2498`) - a fired deadline, a completed fill-poll - and `send_priority()` is public. These are precisely the events an operator would least like to lose at shutdown. In an order-management context, a `drain_pending()` -> persist -> exit path silently discards a deadline that fired microseconds before the process went down, with no error and no log.

We rated it High rather than Critical only because the alternative is correct and already documented: `get_persisted_snapshot()` then `stop()` (snapshots.md, Option B) captures the lane. Our own shutdown wrapper now uses that exclusively and treats any `drain_pending()` result as a lower bound.

## Suggested fix

In `Interpreter.drain_pending()`, drain `_priority_queue` first, then `_event_queue`, matching `_snapshot_pending_events()`. A regression test asserting that a `send_priority()` event issued immediately before shutdown survives `drain_pending()` would pin it.

*(Note on scope: `SyncInterpreter` exposes no `send_priority()` and keeps a single queue, so its `drain_pending()` is not affected by this. The divergence is between the async engine's two views of itself, not between the engines' public APIs.)*
