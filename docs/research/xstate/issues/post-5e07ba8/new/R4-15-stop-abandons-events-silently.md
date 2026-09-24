---
r4: R4-15
title: "Bug: events abandoned by `stop()` are lost with no `on_event_dropped` hook and no log"
labels: [bug, severity/low, area/interpreter]
severity: Low
repro_script: repro/R4-15_stop_abandons_events_silently.py
commit: 5e07ba8
python: 3.13.7
verified: true
---

## Summary

Every other event-loss path in the engine calls `plugin.on_event_dropped(...)`:
inbox-full under `DROP_NEWEST`, send-to-a-stopped-machine, and runaway-chain
budget exhaustion. `stop()` is the exception. Two distinct ways it abandons
events both skip the hook: (1) a fire-and-forget `await interp.send(...)`
parked in `_enqueue_blocking`'s spin loop when the inbox is full under
`OverflowPolicy.BLOCK`, and (2) events merely queued (not yet dequeued) when
`stop()` is called with the default `drain=False`. In both cases the producer
coroutine returns normally -- indistinguishable from a successful send -- and
no plugin, log line, or counter records that the event never reached the
machine. Merges `D-concurrency-2` and `D-observability-8`, one root cause:
shutdown is the only event-loss family in the library with no drop signal.

## Environment

- Commit: `5e07ba8` (`main`, unreleased 0.8.1; `__version__` reports `0.8.0`)
- Python: 3.13.7 (CPython, 64-bit)
- OS: Windows 11 Pro (10.0.26200)
- Install: editable (`pip install -e .`) into a project venv
- Found by our adoption audit (#26), round 4.

## Minimal reproduction

```python
# -*- coding: utf-8 -*-
"""R4-15: events abandoned by `stop()` are lost with no `on_event_dropped`
and no log -- both a fire-and-forget send parked on a full BLOCK inbox, and
events merely queued under the default `drain=False`.

Standalone: no harness import.
"""
from __future__ import annotations

import asyncio

from xstate_statemachine import Interpreter, MachineLogic, PluginBase, create_machine
from xstate_statemachine.models import OverflowPolicy

CONFIG = {
    "id": "counter",
    "initial": "idle",
    "context": {"n": 0},
    "strict": True,
    "guardErrorPolicy": "raise",
    "strictTargets": True,
    "states": {
        "idle": {"on": {"PING": {"actions": ["bump"]}, "STOPME": {"target": "over"}}},
        "over": {"type": "final"},
    },
}


def bump(interpreter, ctx, event, action_def):  # noqa: ANN001
    ctx["n"] = ctx.get("n", 0) + 1


def counter_machine():
    return create_machine(CONFIG, logic=MachineLogic(actions={"bump": bump}))


class Accountant(PluginBase):
    def __init__(self) -> None:
        self.dropped = []

    def on_event_dropped(self, interpreter, event, reason):  # noqa: ANN001
        self.dropped.append((event.type, reason))


CAP = 4
N_BLOCKED = 5


async def scenario_block_stop() -> int:
    """A full BLOCK inbox: 5 fire-and-forget sends parked, then stop()."""
    acc = Accountant()
    interp = Interpreter(
        counter_machine(), max_queue_size=CAP, overflow_policy=OverflowPolicy.BLOCK
    )
    interp.use(acc)
    await interp.start()

    for _ in range(CAP):
        await interp.send("PING")
    assert interp.queue_depth == CAP, interp.queue_depth

    outcomes = []

    async def blocked_producer(k: int) -> None:
        try:
            await interp.send("PING")
            outcomes.append(f"{k}: send() returned normally")
        except Exception as exc:  # noqa: BLE001
            outcomes.append(f"{k}: {type(exc).__name__}: {exc}")

    tasks = [asyncio.create_task(blocked_producer(k)) for k in range(N_BLOCKED)]
    await asyncio.sleep(0)  # let each reach the spin in _enqueue_blocking

    await interp.stop()  # no drain
    await asyncio.gather(*tasks, return_exceptions=True)

    silent = N_BLOCKED - len(acc.dropped)
    print(f"[BLOCK]   producers parked={N_BLOCKED} on_event_dropped={acc.dropped}")
    for o in outcomes:
        print("   ", o)
    print(f"[BLOCK]   silent losses: {silent}/{N_BLOCKED}")
    return silent


async def scenario_default_drain_false() -> int:
    """Default drain=False: events queued but never processed by stop()."""
    acc = Accountant()
    cfg2 = {"id": "m_stop_pending", "initial": "a", "states": {"a": {"on": {"X": "a"}}}}
    machine = create_machine(cfg2, logic=MachineLogic())
    interp = Interpreter(machine)
    interp.use(acc)
    await interp.start()
    for i in range(5):
        interp.send(f"X{i}", wait=False)
    pending_before = len(interp.pending_events)
    await interp.stop()
    silent = pending_before - len(acc.dropped)
    print(f"[DRAIN=F] pending_events before stop={pending_before} on_event_dropped={acc.dropped}")
    print(f"[DRAIN=F] silent losses: {silent}/{pending_before}")
    return silent


async def main() -> int:
    s1 = await scenario_block_stop()
    s2 = await scenario_default_drain_false()
    print("EXPECTED: both scenarios fire on_event_dropped for every abandoned event (silent losses = 0).")
    ok = s1 == 0 and s2 == 0
    print("RESULT:", "PASS" if ok else "FAIL (stop() abandons events with no drop hook)")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
```

## Observed behaviour

```
[BLOCK]   producers parked=5 on_event_dropped=[]
    0: send() returned normally
    1: send() returned normally
    2: send() returned normally
    3: send() returned normally
    4: send() returned normally
[BLOCK]   silent losses: 5/5
[DRAIN=F] pending_events before stop=5 on_event_dropped=[]
[DRAIN=F] silent losses: 5/5
EXPECTED: both scenarios fire on_event_dropped for every abandoned event (silent losses = 0).
RESULT: FAIL (stop() abandons events with no drop hook)
```

All 5 fire-and-forget sends parked on the full BLOCK inbox report
`send() returned normally` even though none of them were ever enqueued;
`on_event_dropped` fires zero times. Separately, 5 events queued with
`send(..., wait=False)` under the default `drain=False` are abandoned when
`stop()` flips `status` to `"stopped"`, again with zero `on_event_dropped`
calls.

## Expected behaviour

The library's own drop contract, exercised at every other loss site
(`interpreter.py`'s `DROP_NEWEST` branch, "not_running" refusal, and the
runaway-chain budget path), is: whenever an event that was accepted by the
public `send`/`send_priority` API does not reach the machine, every
registered `PluginBase.on_event_dropped(self, event, reason)` is called with
a reason string. `stop()` -- itself a fully expected, common shutdown path,
not a crash -- is the one place an event can vanish while that contract is
silently not honored.

## Root cause analysis

`src/xstate_statemachine/interpreter.py:819-833`, `_enqueue_blocking`:

```python
async def _enqueue_blocking(
    self, event_obj: Any, receipt: "Optional[asyncio.Future[Receipt]]"
) -> Optional[Receipt]:
    """`OverflowPolicy.BLOCK`: suspend the producer until there is room."""
    if self._refuse_if_not_running(event_obj):
        return await receipt if receipt is not None else None
    while self._inbox_is_full():
        if self.status != "running":
            self._fail_receipt(
                event_obj, "stopped while blocked on a full inbox"
            )
            return await receipt if receipt is not None else None
        await asyncio.sleep(0)
    self._put_inbox(event_obj)
    return await receipt if receipt is not None else None
```

The `status != "running"` branch calls only `self._fail_receipt(...)`. With
`wait=True` a caller sees the failure via the receipt future; with the
ordinary fire-and-forget `await interp.send(...)` (`receipt is None`),
`_fail_receipt` on a `None` receipt is a no-op and the coroutine simply
returns `None` -- there is no `for plugin in self._plugins:
plugin.on_event_dropped(...)` call anywhere in this branch, unlike the
sibling `DROP_NEWEST` branch in `_enqueue()` a few lines below
(`interpreter.py:849-863`), which does call it.

Separately, `stop()`'s default `drain=False` path (no drain loop is run
before `status` is set to `"stopped"`) abandons whatever is still sitting in
`_event_queue` / `_priority_queue` with no equivalent hook call for those
events either -- the same missing-signal defect, different entry point.

## Impact

**General users.** `on_event_dropped` is the library's one documented
mechanism for an operator to observe "this event never reached the machine";
a monitoring/alerting integration built on it will report a perfectly clean
zero-drop run while `stop()` is silently discarding fire-and-forget sends and
whatever is left in the inbox. `await send()` returning normally is, in this
one situation, not evidence the event was accepted at all.

**Concrete order-management scenario.** A producer issues
`await interp.send("CANCEL", wait=False)` for an order-cancel command while
an unrelated coroutine calls `interp.stop()` for a graceful shutdown -- a
completely ordinary race in a service under load-shedding or rolling
restart. The cancel is silently dropped; the producer's log shows nothing
wrong; the order remains live at the venue. There is no drop counter to
catch this in production, and no way to distinguish "cancel delivered,
machine simply hadn't processed it yet" from "cancel discarded" after the
fact.

## Proposed fix

**Design.** Fire `on_event_dropped` for every event abandoned by `stop()`,
on both paths, matching the three loss paths that already do it.

1. In `_enqueue_blocking`'s `status != "running"` branch
   (`interpreter.py:823-828`), before/alongside `self._fail_receipt(...)`,
   call `for plugin in self._plugins: plugin.on_event_dropped(self,
   event_obj, "stopped_while_blocked")` and log at the same level as the
   `DROP_NEWEST` branch.
2. In `stop()`'s default (`drain=False`) path, before clearing
   `_event_queue` / `_priority_queue` / `_internal_queue`, snapshot their
   contents and call `on_event_dropped(self, event, "stopped_with_pending")`
   for each, then clear. This must not run when `drain=True` (those events
   are correctly drained, not dropped) and should be skippable via the
   existing drop-hook plugin machinery (no plugin registered -> negligible
   cost).
3. Both new reason strings should be documented alongside `"queue_full"`,
   `"not_running"`, and `"chain_budget"` wherever those are enumerated.

**Compatibility.** Additive: only adds hook invocations plugins can already
ignore; no signature or behavior change for the actual drop decision.

**Alternatives considered.**
1. *Only fix the BLOCK-stop path (`D-concurrency-2`) and leave the
   `drain=False` path as documented behavior.* Rejected: `drain=False` is
   the default, so this is the common case, and it has exactly the same
   "producer can't tell it was dropped" property as the BLOCK path.
2. *Raise from `send()` in these cases instead of using the hook.* Would
   change the return type / add new exceptions to a documented "returns
   None or an awaited receipt" contract for the fire-and-forget path;
   `on_event_dropped` is the existing convention for this class of loss and
   is additive.

## Acceptance criteria

- [ ] `_enqueue_blocking`'s stop-while-blocked branch calls
      `plugin.on_event_dropped(...)` for every producer it releases.
- [ ] `stop()` with the default `drain=False` fires `on_event_dropped` for
      every event still in the inbox/priority/internal lanes at the moment
      `status` flips to `"stopped"`.
- [ ] `stop(drain=True)` continues to process pending events normally and
      does **not** fire spurious drops for events it successfully drains.
- [ ] `repro/R4-15_stop_abandons_events_silently.py` exits `0`.
- [ ] `tests/test_shutdown_drops.py::test_block_stop_fires_on_event_dropped`
- [ ] `tests/test_shutdown_drops.py::test_default_stop_fires_on_event_dropped_for_pending`
- [ ] `tests/test_shutdown_drops.py::test_drain_stop_does_not_fire_drops`

## Related

- Register row `R4-15` (filed High, DOWNGRADE to Low). Merges source ids
  `D-concurrency-2` and `D-observability-8` -- one root cause, "shutdown is
  the only event-loss family with no drop hook."
- Evidence: `battle-5e07ba8/concurrency/d2_block_stop_silent_drop.py`,
  `battle-5e07ba8/observability/probe_matrix2.py`.
- Meta: our adoption audit **#26**.

## Verification

- Date: 2026-09-19
- Python: 3.13.7 (`.venv-main`)
- Commit: `5e07ba8`
- Ran `repro/R4-15_stop_abandons_events_silently.py` in a fresh process: exit
  code `1`, output matches the Observed section verbatim (5/5 silent losses
  in both the BLOCK-stop scenario and the default `drain=False` scenario;
  `on_event_dropped` fires zero times in either case).
- Root cause confirmed at `src/xstate_statemachine/interpreter.py`,
  `_enqueue_blocking`'s `status != "running"` branch (calls only
  `self._fail_receipt(...)`, no `on_event_dropped` loop), contrasted with the
  sibling `DROP_NEWEST` branch in `_enqueue()` which does call the hook.
- No duplicate found on `gh issue list -R basiltt/xstate-statemachine --state
  all --search "stop abandons"` (no results); the closed issue set has no
  entry for shutdown-path event drops.
- Self-contained; no project-name/label leak.
