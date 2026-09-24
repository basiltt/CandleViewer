---
r4: R4-30
title: "Semantics: a deferred event's replay folds into the triggering event's own Receipt"
labels: [bug, severity/medium, area/events, area/interpreter]
severity: Medium
repro_script: repro/R4-30_deferred_replay_folds_receipt.py
commit: 5e07ba8
python: 3.13.7
verified: true
---

## Summary

When `onUnhandled: "defer"` holds an event back and a later transition
changes the configuration, `_process_event_and_transient_transitions`
(`interpreter.py:1323-1361`) replays every deferred event *inside the same
run-loop iteration* as the event that triggered the configuration change —
before that triggering event's own `Receipt` is resolved
(`_resolve_receipt` runs only after this whole method returns,
`interpreter.py:1271-1280`). The result: `send("ARM", wait=True)`'s
`Receipt` reports the state reached *after* replaying an earlier-deferred
event, not the state ARM's own transition produced. Two distinct events'
effects are collapsed into one receipt, so a receipt-derived audit trail
cannot attribute a state change to the event that actually caused it.

## Environment

- Commit: `5e07ba8` (post-0.8.0, pre-0.8.1 tag; `__version__` reports `0.8.0`)
- Python: 3.13.7
- Install: editable (`pip install -e .`) against
  `C:/Users/basil/Desktop/Projects/FullStackProjects/_ref/xstate-statemachine`

## Minimal reproduction

```python
"""R4-30: a deferred event's replay folds into the triggering event's own
Receipt. The replay loop (interpreter.py `_process_event_and_transient_
transitions`, "3. Replay deferred events...") runs inside the same run-loop
iteration as the triggering event, before that event's own receipt is
resolved (`_resolve_receipt` runs after `_process_event_and_transient_
transitions` returns, interpreter.py ~1271-1280).

EXPECTED: send("ARM", wait=True) should return a Receipt describing ARM's
OWN transition (a -> b), not the state reached after a deferred event
replayed on top of it.
OBSERVED: the Receipt for "ARM" reports the post-replay state (b -> c, from
replaying the earlier-deferred "LATE"), not ARM's own transition (a -> b).

Exits 1 while the defect is present, 0 once fixed.
"""
from __future__ import annotations

from xstate_statemachine import MachineLogic, SyncInterpreter, create_machine

CFG = {
    "id": "m_defer_replay",
    "initial": "a",
    "onUnhandled": "defer",
    "states": {
        "a": {"on": {"ARM": "b"}},
        "b": {"on": {"LATE": "c"}},
        "c": {},
    },
}

machine = create_machine(CFG, logic=MachineLogic())
interp = SyncInterpreter(machine).start()

r_late_initial = interp.send("LATE", wait=True)  # deferred while in "a"
r_arm = interp.send("ARM", wait=True)  # a->b, triggers replay of LATE: b->c

print(f"receipt for deferred LATE (queued): {r_late_initial}")
print(f"receipt for ARM                   : {r_arm}")
print(f"final state                       : {sorted(interp.current_state_ids)}")

arm_state_ids = set(r_arm.state_ids)
final_state_ids = set(interp.current_state_ids)
# ARM's own transition takes the machine to "b"; if the LATE replay folded
# into ARM's receipt, r_arm.state_ids will already report "c".
c_in_arm_receipt = any(sid.endswith(".c") or sid == "c" for sid in arm_state_ids)

print(f"\nARM receipt reports final state 'c' (post-replay): {c_in_arm_receipt}")

defect_present = c_in_arm_receipt
print(
    "OBSERVED:",
    "ARM's Receipt reflects the post-replay state, folding LATE's effect "
    "into ARM's own receipt"
    if defect_present
    else "ARM's Receipt reflects only its own transition",
)
print(
    "EXPECTED: ARM's Receipt reports only ARM's own transition (state 'b'); "
    "the replayed LATE event's effect should be separately attributable"
)
print("RESULT:", "FAIL - defect present" if defect_present else "PASS")

raise SystemExit(1 if defect_present else 0)
```

## Observed behaviour

```
receipt for deferred LATE (queued): Receipt(state_ids=frozenset({'m_defer_replay.a'}), changed=False, error=None, deferred=True)
receipt for ARM                   : Receipt(state_ids=frozenset({'m_defer_replay.c'}), changed=True, error=None, deferred=False)
final state                       : ['m_defer_replay.c']

ARM receipt reports final state 'c' (post-replay): True
OBSERVED: ARM's Receipt reflects the post-replay state, folding LATE's effect into ARM's own receipt
EXPECTED: ARM's Receipt reports only ARM's own transition (state 'b'); the replayed LATE event's effect should be separately attributable
RESULT: FAIL - defect present
```

(exit code 1)

## Expected behaviour

A `Receipt`'s own docstring (`events.py:342-355`) defines it per-event:

> `changed`: `True` if a transition was taken (configuration or context
> changed) for THIS event.

"THIS event" is ARM; ARM's own transition takes the machine from `a` to
`b`. The replay of `LATE` (deferred since before ARM was sent) is a
*consequence* of ARM's transition, triggered by the same macrostep, but it
is a distinct event with its own effect (`b` -> `c`). XState v5's actor
model treats each processed event as producing its own snapshot/transition
record (https://stately.ai/docs/transitions); collapsing two events'
effects into one `Receipt` breaks that same-granularity expectation and
makes a receipt-derived audit trail unable to say which event caused which
state change.

## Root cause analysis

- `interpreter.py:1343-1361`, inside `_process_event_and_transient_
  transitions`:
  ```python
  # 3️⃣ Replay deferred events now that the configuration changed.
  if before != frozenset(self._active_state_nodes):
      ...
      while self._deferred_events and rounds < limit:
          ...
          for deferred in self._take_deferred_for_replay():
              await self._process_event(deferred)
              await self._settle_transient_transitions()
          ...
  ```
  This whole method is invoked once per dequeued event from
  `_run_event_loop` (`interpreter.py:1242`), and `_resolve_receipt` for the
  *triggering* event is only called after this method returns
  (`interpreter.py:1271-1280`, comparing `config_before`/`context_before`
  captured before the call against the state *after* everything —
  including replay — has run). There is no separate receipt resolution
  point for the replay step itself; its effect is invisible except as
  folded into whichever event's `config_before`/`config_after` snapshot
  happens to bracket it.
- Documented replay design rationale (`interpreter.py:1345-1350`): replay
  runs "HERE, inside the same run-loop iteration, rather than re-queued"
  specifically to preserve ordering ahead of live traffic — a reasonable
  design goal that this issue does not ask to change. The gap is narrower:
  the *triggering* event's receipt should be resolved before the replay
  loop runs, not folded together with it.
- Register notes a documented hook-pairing workaround exists (observing
  `on_transition` calls per replayed event), but that is an
  observability-hook substitute for a receipt, not a fix to the receipt
  itself.

## Impact

**General users:** anyone using `onUnhandled: "defer"` together with
`wait=True` receipts for auditing gets receipts that misattribute state
changes whenever a deferred event happens to replay in the same step as
another event.

**Order-management scenario:** an order state machine defers an
out-of-order `SHIP` event (received before `CONFIRM`) under `onUnhandled:
"defer"`. When `CONFIRM` arrives and transitions the order out of
`pending`, `SHIP` replays in the same step and moves it to `shipped`. A
caller doing `receipt = await interp.send("CONFIRM", wait=True)` for its
audit log records the order as having gone straight to `shipped` "because
of CONFIRM" — an incorrect causal record for compliance/audit purposes,
since `SHIP`'s own receipt (`interp.send("SHIP", wait=True)`, awaited much
earlier) already reported `deferred=True` with no state change, so the
`SHIP`-caused transition is never attributed to `SHIP` anywhere.

## Proposed fix

Two options, either acceptable:

1. **Resolve the triggering event's receipt before running the replay
   loop.** Split `_resolve_receipt`'s inputs (`config_before`/
   `context_before` captured before `_process_event_and_transient_
   transitions`, current state captured immediately after step 1+2 but
   before step 3's replay) so ARM's own receipt reflects only `a -> b`,
   then let the replay loop run afterward and resolve `LATE`'s *own*
   receipt (it already has one pending from the earlier deferred `send`)
   against the state at the start of replay.
2. **Add a `replayed` list to `Receipt`** enumerating which deferred events
   were replayed as a side effect of this step, so callers can separate
   "ARM's own effect" from "what else fired as a consequence" without
   changing when receipts resolve.

Either requires touching `interpreter.py:1271-1280` (receipt resolution)
and `interpreter.py:1343-1361` (replay loop) together, since they currently
share one `config_before`/`context_before` snapshot per dequeued event.

Compatibility: option 1 changes existing `Receipt.state_ids`/`changed`
values for the triggering event in the defer+replay case (a bug fix, but a
behavior change for the fixed case specifically); option 2 is purely
additive.

## Acceptance criteria

- [ ] `repro/R4-30_deferred_replay_folds_receipt.py` exits 0
- [ ] New test `tests/test_interpreter.py::test_deferred_replay_receipt_attribution`
      (or under whichever test module covers defer/replay) asserts ARM's
      receipt reflects only ARM's transition (or, if option 2 is chosen,
      that `replayed` lists `LATE`)
- [ ] `docs/_guide/testing-and-pure-api.md` updated if it documents
      `Receipt` semantics for the defer/replay interaction

## Related

- Register source id: `battle-5e07ba8/observability/probe_matrix.py`
  (`probe_deferred_replay`)
- Register notes a documented hook-pairing workaround exists

## Verification

- Date: 2026-09-19
- Python: 3.13.7 (venv: `xstate-statemachine/.venv-main`)
- Commit: `5e07ba8`
- Ran `repro/R4-30_deferred_replay_folds_receipt.py` in a fresh process
  (60 s cap): output matched the Observed block verbatim (ARM's receipt
  reports `m_defer_replay.c`, not `.b`); exit code `1`.
- Confirmed root cause at `src/xstate_statemachine/interpreter.py:1323-1361`
  (`_process_event_and_transient_transitions`: steps 1-2 process the
  triggering event and settle transient transitions, step 3's replay loop
  runs deferred events in the same call before returning) and
  `:1271-1280` (`_resolve_receipt` for the triggering event is called only
  after `_process_event_and_transient_transitions` returns, i.e. after
  replay) — line ranges and code exactly as cited.
- Confirmed `Receipt`'s docstring at `src/xstate_statemachine/events.py:344-345`
  ("`changed`: `True` if a transition was taken ... for THIS event") — as
  quoted.
- Fetched `https://stately.ai/docs/transitions`: confirmed XState v5 models
  each sent event as producing its own transition/state update, supporting
  the "distinct events should have distinct, separately-attributable
  effects" claim.
- Searched `gh issue list -R basiltt/xstate-statemachine --state all --limit
  120 --search "deferred replay receipt"`: no exact match; issue #84
  (`Receipt.deferred` change=False semantics) is related but distinct (that
  issue is about the deferred event's own receipt, not about a later
  triggering event's receipt folding in the replay) — already cross-linked
  in this file's "Related" section via the `deferred=True` mechanism, no
  duplicate found.
- No project name/label leakage found in the file.
