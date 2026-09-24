---
lc: LC-03
title: "Semantics: events with no handler in the current state are silently discarded"
labels: [bug, severity/blocker, area/interpreter, candleviewer]
severity: Blocker
blocks_adoption: true
repro_script: repro/LC-03_unhandled-events-discarded.py
library_version: 0.7.0 (commit 42612cf)
python: 3.13.7
verified: true
---

## Summary

If an event arrives while the machine is in a state that declares no handler for it, `_process_event` logs a debug line and returns. The event is destroyed. There is no buffering, no `defer`, no plugin hook, and no way for the sender to learn that the event it just sent had no effect — a legitimate event that arrived a few milliseconds early is indistinguishable from a typo'd event name. "Ignore" is the only available policy and it is the silent one.

This is the highest-consequence of the three Blockers because it is a **timing** bug: the same code passes every test where events arrive in the expected order, and loses data only under real-world interleaving.

## Environment

- Library: `xstate-statemachine` 0.7.0, commit `42612cf` (local clone, `pip install -e`)
- Python: 3.13.7 (CPython, venv)
- OS: Windows 11
- Install: editable install from source clone

## Minimal reproduction

```python
"""LC-03 repro: events that have no handler in the *current* state are silently
discarded. An OMS order machine sitting in `submitting` (awaiting an invoke) loses
every `PARTIAL`/`FILL` that arrives before the ack — no error, no hook, no warning
the caller can observe.

Exits 1 when the defect is present.
"""

from __future__ import annotations

import asyncio
import logging
import sys

from xstate_statemachine import Interpreter, MachineLogic, create_machine

logging.disable(logging.CRITICAL)

CONFIG = {
    "id": "oms",
    "initial": "idle",
    "context": {"filled": 0},
    "states": {
        "idle": {"on": {"NEW": "submitting"}},
        # `submitting` has NO handler for PARTIAL/FILL — it only waits for the ack.
        "submitting": {
            "invoke": {"src": "place", "onDone": {"target": "live"}},
        },
        "live": {
            "on": {
                "PARTIAL": {"actions": ["apply_fill"]},
                "FILL": {"target": "filled", "actions": ["apply_fill"]},
            }
        },
        "filled": {"type": "final"},
    },
}


async def main() -> int:
    def apply_fill(i, c, e, a):
        c["filled"] += e.payload["qty"]

    async def place(i, c, e):
        await asyncio.sleep(0.05)  # exchange ack latency
        return "ok"

    logic = MachineLogic(actions={"apply_fill": apply_fill}, services={"place": place})
    interp = Interpreter(create_machine(CONFIG, logic=logic))
    await interp.start()

    await interp.send("NEW")
    # Exchange pushes fills while we are still awaiting the ack.
    await interp.send({"type": "PARTIAL", "qty": 10})
    await interp.send({"type": "PARTIAL", "qty": 10})
    await interp.send({"type": "FILL", "qty": 10})
    await asyncio.sleep(0.3)

    states = sorted(interp.current_state_ids)
    filled = interp.context["filled"]
    status = interp.status
    await interp.stop()

    print(f"OBSERVED state  : {states}")
    print(f"OBSERVED filled : {filled}")
    print(f"OBSERVED status : {status}")
    print("EXPECTED state  : ['oms.filled'] (or an observable unhandled-event signal)")
    print("EXPECTED filled : 30")
    print("EXPECTED: the 3 events must not vanish without any programmatic trace.")

    bad = filled == 0 and states != ["oms.filled"]
    print("RESULT: DEFECT REPRODUCED" if bad else "RESULT: not reproduced")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
```

## Observed behaviour

```
OBSERVED state  : ['oms.live']
OBSERVED filled : 0
OBSERVED status : running
EXPECTED state  : ['oms.filled'] (or an observable unhandled-event signal)
EXPECTED filled : 30
EXPECTED: the 3 events must not vanish without any programmatic trace.
RESULT: DEFECT REPRODUCED
```

Exit code `1`. The machine ends parked in `oms.live` with `filled == 0`: all three exchange events were destroyed. Deterministic across repeated runs.

## Expected behaviour

Two distinct expectations, and the library meets neither.

**1. XState v5 agrees on the *semantics* but not on the *observability*.** Dropping an unmatched event is correct behaviour and this issue does **not** ask for that default to change. The gap is that in XState the drop is still visible to tooling: the inspection API emits an `@xstate.event` inspection record for **every** event sent to an actor, matched or not. From https://stately.ai/docs/transitions (FAQ, "How can I listen for events sent to actors?"): *"You can use the inspection API to listen for all inspection events in an actor system. The `@xstate.event` inspection event contains information about events sent from one actor to another (or itself)."* And https://stately.ai/docs/inspection: the `@xstate.event` event *"is emitted when an event is sent to an actor"* — emission is tied to delivery, not to whether a transition was selected. Here the equivalent is a `logger.debug` line and nothing else: `PluginBase` (`plugins.py`) declares `on_event_received` but no hook that reports the *disposition* of the event, so a plugin can count arrivals but cannot distinguish handled from dropped.

**2. XState v5 removed `strict` mode, and that is the relevant precedent — in both directions.** XState v4 had `createMachine({ strict: true })`, which threw on an unhandled event; v5 removed it (https://stately.ai/docs/migration — listed under removed features). So "raise on unhandled" is *not* current XState behaviour and this issue proposes it only as an **opt-in** (`on_unhandled="error"`), most useful in test suites. The deferral policy proposed below likewise has no direct XState equivalent; it is proposed on its own merits for this library, not as XState parity.

Minimum acceptable, and the part that is a genuine parity gap: an `on_unhandled_event` plugin hook so the drop is at least countable, matching what XState's inspection API already gives you.

## Root cause analysis

`src/xstate_statemachine/base_interpreter.py:1263-1278`:

```python
    async def _process_event(
        self, event: Union[Event, DoneEvent, AfterEvent]
    ) -> None:
        # 1. Select every transition this event triggers (one per region).
        transitions = self._select_transitions(event)
        if not transitions:
            logger.debug("🍃 No transition found for event '%s'.", event.type)
            return
```

The `return` is the whole defect. Three consequences:

1. **No buffering.** The event object is dropped on the floor at this point; nothing retains it, so no later state can ever process it.
2. **No error channel.** `_process_event` returns `None` either way, so its caller (`interpreter.py`'s `_run_event_loop`) cannot distinguish "handled" from "dropped", and `send()` — which is fire-and-forget and returns before the event is even dequeued — certainly cannot.
3. **No observability.** `plugins.py` declares no unhandled-event hook (LC-48) — the nearest, `on_event_received` (`plugins.py:116`), fires on dequeue, *before* transition selection, so it reports arrival but never disposition. A plugin therefore cannot count drops. A typo'd event name and a legitimately-early exchange fill take the identical code path and produce the identical (invisible) result.

The same path handles a genuinely unknown event type, which is why the two are indistinguishable.

Note the *ordering* is not the problem: event delivery is strict FIFO and per-producer order is preserved. The events are delivered in order, to a state that has nothing to say about them, and are then destroyed.

## Impact

**General users:** any machine fed by an external, unsynchronised event source — websockets, message queues, UI input, sensor streams, webhooks — loses events whenever the producer is faster than a transient state (an `invoke` in flight, an `after` delay, a bootstrap state). The loss is silent and timing-dependent, so it passes CI and appears in production under load. Refactoring is equally hazardous: moving a handler from a parent to a child state silently starts dropping events that used to work, with no test failure and no warning.

**CandleViewer trading OMS:** this is a direct financial-loss path. The order machine sits in `submitting` for the exchange ack round-trip (single-digit milliseconds in local measurement; far longer under stress). Exchange fill pushes routinely beat the ack. Every `PARTIAL`/`FILL` arriving in that window is destroyed: the repro shows a fully-filled order — 30 units, a real position on the exchange — leaving the machine in `live` with `filled == 0`. The machine then believes it has an open order that in fact no longer exists, and a position it does not know it holds. Downstream: risk limits computed from `filled` are wrong, the reconciliation loop sees a phantom open order, and any hedge sized from machine state is mis-sized. This affects essentially every order-path scenario in that application.

The universal workaround (`"*"` catch-all that appends to a `_deferred` context list, drained in a later state's `entry`) is **not** sufficient here: **LC-17** shows the buffer is never drained after a crash mid-invoke (the drain lives in an `entry` reachable only via `done.invoke`, and invokes are not restarted on restore), and **LC-18** shows the drain destroys exchange event ordering because it re-`send`s behind live traffic.

## Proposed fix

**1. Machine-level `on_unhandled` policy.** `create_machine(config, logic=..., on_unhandled=...)`, also settable per-state:

| Value | Behaviour |
|---|---|
| `"ignore"` | Today's behaviour. Default in 0.7.x/0.8 for compatibility. |
| `"error"` | Raise `UnhandledEventError(event, current_state_ids)` — routed like any other interpreter error (see LC-01's `status="error"` path), not swallowed. |
| `"defer"` | Buffer the event in an interpreter-owned deferral queue; re-evaluate the queue after **every** state change, delivering matching events **in original order at the head of the queue**, ahead of live traffic. |

**2. `defer` must be library-owned, not a userland pattern** — this is what makes it correct where the workaround is not:

- the buffer is part of the snapshot (`to_snapshot`/`from_snapshot`), so it survives a crash;
- it is drained on `start()` **before** any invoke is re-driven, unconditionally, rather than from some state's `entry` (closes LC-17);
- re-injection is at the head of the internal queue in original order, not via `create_task(send)` (closes LC-18);
- bound it: `defer_max` (default e.g. 1000) with a documented overflow policy (`drop-oldest` + hook), so a permanently-unhandled event type cannot grow unbounded;
- expose `interpreter.deferred_count` for metrics/alerting.

**3. Observability regardless of policy.** Declare on `PluginBase` (no-op default):

```python
def on_unhandled_event(self, interpreter, event, active_state_ids, disposition): ...
    # disposition: "ignored" | "deferred" | "errored"
```

This alone makes the drop countable and is worth shipping even if `defer` slips. Pair it with the `on_transition_failed`/`on_guard_error` hooks from LC-01/LC-48.

**Sketch:** `base_interpreter.py:1274-1278` (branch on the policy instead of `return`), a `_deferred: deque[Event]` on the interpreter drained from the state-change path at the end of `_execute_transition` (`base_interpreter.py:1882-1890`), snapshot round-trip in the `to_snapshot`/`from_snapshot` pair, `factory.py::create_machine` for the config key and its validation, `plugins.py` for the hook, mirrored in `sync_interpreter.py`.

**Backwards compatibility:** default `"ignore"` preserves current behaviour exactly; the new hook has a no-op default; the snapshot gains an optional `_deferred` key that older readers can ignore. Recommend a `DeprecationWarning`-free but documented default flip to `"defer"` (or at least `"error"` in dev/test) in 1.0, and a `strict=True` convenience that turns on `"error"` for test suites.

## Acceptance criteria

- [ ] `on_unhandled` accepted by `create_machine()` and per-state, validated (`ValueError` on an unknown value); default `"ignore"` is byte-identical to 0.7.0.
- [ ] `"error"`: the repro's first `PARTIAL` raises `UnhandledEventError` naming the event type and the active state ids; the interpreter reaches `status == "error"` rather than silently continuing.
- [ ] `"defer"`: the repro ends in `['oms.filled']` with `filled == 30`.
- [ ] `"defer"`: deferred events are delivered **in original order** and **ahead of** events sent after the state change (closes LC-18).
- [ ] `"defer"`: an event still unhandled in the new state stays deferred; it is not re-dropped.
- [ ] `"defer"`: `_deferred` survives `to_snapshot`/`from_snapshot`, and `start()` drains it before re-driving invokes — a snapshot taken mid-`submitting` with 3 deferred fills reaches `filled == 3` after restore (closes LC-17).
- [ ] `defer_max` overflow is bounded and reported through `on_unhandled_event`; `interpreter.deferred_count` exposed.
- [ ] `PluginBase.on_unhandled_event` declared with a no-op default and fires under all three policies with the right `disposition`; a 0.7.0 plugin subclass still loads unchanged.
- [ ] `SyncInterpreter` honours all three policies identically.
- [ ] Tests added:
  - `tests/test_unhandled_events.py::test_ignore_is_default_and_unchanged`
  - `tests/test_unhandled_events.py::test_error_policy_raises_unhandled_event_error`
  - `tests/test_unhandled_events.py::test_defer_delivers_after_state_change`
  - `tests/test_unhandled_events.py::test_defer_preserves_original_order_ahead_of_live_traffic`
  - `tests/test_unhandled_events.py::test_defer_survives_snapshot_restore_and_drains_at_boot`
  - `tests/test_unhandled_events.py::test_defer_max_overflow_is_reported`
  - `tests/test_unhandled_events.py::test_sync_interpreter_parity`
  - `tests/test_plugins.py::test_on_unhandled_event_hook_fires`
- [ ] `repro/LC-03_unhandled-events-discarded.py` exits `0` under `on_unhandled="defer"`.

## Related

- **LC-17** — a persisted deferral buffer is never drained after a crash; the universal LC-03 workaround strands fills. Closed by library-owned `defer` with a boot-time drain. Grouped here.
- **LC-18** — the deferral workaround destroys exchange event ordering. Closed by head-of-queue re-injection. Grouped here.
- **LC-48** — no error-observability hooks; `on_unhandled_event` is one of the three requested there.
- **LC-01**, **LC-02**, **LC-07**, **LC-08**, **LC-36** — same "resolution and execution failures degrade to silent no-ops" design family.

## Verification

Independently verified on 2026-09-15.

- Library: `xstate-statemachine` 0.7.0, commit `42612cf` (`main`), editable install.
- Python: 3.13.7 (CPython), Windows 11.
- Repro run in a fresh process: output matches the **Observed behaviour** block verbatim; **exit code `1`**.
- Root cause re-checked against source: `base_interpreter.py:1263-1278` confirmed verbatim as quoted (`_process_event`, `if not transitions: logger.debug(...); return`). Confirmed by inspection that `plugins.py` declares no unhandled-event hook — the full hook list is `on_interpreter_start/stop`, `on_event_received`, `on_transition`, `on_action_execute`, `on_action_error`, `on_guard_evaluated`, `on_service_start/done/error`.
- XState citations corrected. The draft asserted "SCXML §4 defines `<cancel>`/deferral semantics in which an event that selects no transition … is removable but observable" — `<cancel>` is SCXML's element for cancelling a *delayed send*, not a deferral mechanism for unmatched events, and no such §4 rule exists; the claim was removed. The quote attributed to `/docs/transitions` ("If a state does not have a transition for an event…") is not present on that page and was replaced with the page's verbatim inspection-API FAQ text plus `/docs/inspection`. The claim that "XState v5 has first-class deferral for exactly this case" was not substantiated by any cited page and was withdrawn; the Expected section now states plainly that the `defer` policy is proposed on this library's own merits, and notes that v4's `strict` mode (the precedent for the `"error"` policy) was *removed* in v5 — so the only genuine XState parity gap is observability.
- Not a duplicate: the upstream tracker (`basiltt/xstate-statemachine`) has one issue, #17 (closed, camelCase→snake_case auto-discovery), unrelated.
