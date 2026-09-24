---
r5: R5-09
title: "Bug: The transient settle budget is reset per drain, not per macrostep, so one event's legitimate settle starves the next event in the same `send_events()` batch"
labels: [bug, severity/high, area/sync-interpreter]
severity: High
repro_script: repro/R5-09_settle-budget-per-drain.py
commit: 3ed3099
python: 3.13.7
verified: true
---

## Summary

#103 moved the `always`-settling counter from a per-call local onto the
instance and reset it once, at the start of each *drain*, to stop `start()`
hanging when a settle pass re-armed an invoke. The reset granularity is now
too coarse: `maxIterations` is documented and used as a *per-macrostep*
ceiling, but every event in a single `send_events([...])` batch shares one
allowance. Two independent events that each settle in 40 hops under a limit
of 50 both complete when sent one at a time, and the second one trips
`RunawayChainError` when the same two are batched. The effective budget is
`maxIterations / len(batch)` — a silent, load-dependent cliff for anyone
replaying a batch.

## Environment

- Commit: `3ed3099` (`main`, merge of #139 `fix/0.8.1-round4`; unreleased
  0.8.1 — `__version__` still reports `0.8.0`, so this build is identified
  by commit).
- Python: CPython 3.13.7
- OS: Windows 11 Pro 10.0.26200
- Editable install of the repo into a local venv; no library source
  modified.

## Minimal reproduction

```python
"""R5-09 repro: the settle budget is reset per DRAIN, not per macrostep.

`SyncInterpreter._process_event_queue` zeroes `_settle_iterations` once, at
the start of the drain (`sync_interpreter.py:622-625`). Two independent
events delivered in one `send_events([...])` batch therefore share a single
`maxIterations` allowance: the second event inherits the first's spend and
trips `RunawayChainError` even though each, alone, settles well within
budget.

Control: the SAME two events sent one at a time both complete.

Exits 1 while the defect is present, 0 once fixed.
Stdlib + xstate_statemachine only.
"""

import logging
import sys

from xstate_statemachine import SyncInterpreter, create_machine

N = 40  # hops per chain; each event needs 40 of a 50 budget
LIMIT = 50


def cfg():
    states = {"idle": {"on": {"GO": "s0", "GO2": "u0"}}}
    for k in range(N):
        states[f"s{k}"] = {"always": f"s{k + 1}"}
    states[f"s{N}"] = {"on": {"GO2": "u0"}}
    for k in range(N):
        states[f"u{k}"] = {"always": f"u{k + 1}"}
    states[f"u{N}"] = {}
    return {
        "id": "L",
        "initial": "idle",
        "maxIterations": LIMIT,
        "states": states,
    }


def drive(batched: bool):
    i = SyncInterpreter(create_machine(cfg())).start()
    if batched:
        i.send_events(["GO", "GO2"])
    else:
        i.send("GO")
        i.send("GO2")
    out = (
        i.value,
        i.last_transition_ok,
        type(i.last_error).__name__ if i.last_error else None,
    )
    i.stop()
    return out


def main() -> int:
    seq_value, seq_ok, seq_err = drive(batched=False)
    bat_value, bat_ok, bat_err = drive(batched=True)

    print("OBSERVED:")
    print("  maxIterations                :", LIMIT, "| hops per event:", N)
    print("  sequential send(GO); send(GO2):")
    print("     value                     :", seq_value)
    print("     last_transition_ok        :", seq_ok, "| last_error:", seq_err)
    print("  batched send_events([GO,GO2]):")
    print("     value                     :", bat_value)
    print("     last_transition_ok        :", bat_ok, "| last_error:", bat_err)
    print("EXPECTED:")
    print("  the settle budget is per macrostep, so both routes reach")
    print("  'u%d' with last_transition_ok=True and last_error=None" % N)

    broken = bat_value != seq_value or not bat_ok or bat_err is not None
    if broken:
        print(
            "RESULT: FAIL - the second event in the batch inherited the "
            "first event's settle spend"
        )
        return 1
    print("RESULT: PASS")
    return 0


if __name__ == "__main__":
    logging.disable(logging.CRITICAL)
    sys.exit(main())
```

## Observed behaviour

```
OBSERVED:
  maxIterations                : 50 | hops per event: 40
  sequential send(GO); send(GO2):
     value                     : u40
     last_transition_ok        : True | last_error: None
  batched send_events([GO,GO2]):
     value                     : u9
     last_transition_ok        : False | last_error: RunawayChainError
EXPECTED:
  the settle budget is per macrostep, so both routes reach
  'u40' with last_transition_ok=True and last_error=None
RESULT: FAIL - the second event in the batch inherited the first event's settle spend
```

Exit status `1`.

`u9` is exactly the arithmetic: the first event spent 40 of the 50, leaving
10 for the second, which therefore stops nine hops in. The corroborating
probe in our audit (`probes/main-3ed3099/p2_gate_and_inline.py`, cases J-6
and J-6b) shows the same pair: a single 40-hop chain under
`maxIterations: 50` completes on both `start()` and `GO`
(`j6_start_ok`/`j6_go_ok: true`), while the two-event batch gives
`j6b_value: "u9"`, `j6b_ok: false`, `j6b_err: "RunawayChainError"`.

Note that the failure is **not** silent — `last_transition_ok` and
`last_error` are correctly set by #112. But `send_events()` itself returns
`None` and raises nothing, so a caller that batches gets a truncated
configuration unless it inspects those two fields after every batch.

## Expected behaviour

The library documents `maxIterations` as the bound on a **single macrostep**.
`sync_interpreter.py:838-841` states the intent:

> Bound the microstep loop. A pair of `always` transitions that target each
> other spins forever; XState added the same guard in v5.31.0.
> `max_iterations` is configurable on the machine.

XState v5's equivalent guard is per-microstep-sequence: the limit exists to
terminate a *cycle*, and is re-evaluated for each macrostep, so the number of
events you deliver in one call cannot change whether a given machine settles.
W3C SCXML §3.13 makes the same structural claim — the macrostep for an
external event is a complete, self-contained sequence of microsteps run to
quiescence; the next external event begins a new one. A budget that spans
several external events is measuring the wrong unit.

Concretely: for any machine and any two events `A` and `B`,
`send_events([A, B])` must reach the same configuration as
`send(A); send(B)`.

## Root cause analysis

`SyncInterpreter._process_event_queue` (`sync_interpreter.py:612`) resets the
counter exactly once, before the drain loop begins
(`sync_interpreter.py:621-625`):

```python
self._is_processing = True
# 🔁 #103: one settle budget per drain (see
#    `_process_transient_transitions`).
self._settle_iterations = 0
self._settle_tripped = False
```

`_process_transient_transitions` (`sync_interpreter.py:826`) then only ever
*increments* it (`:850`) and checks it against the limit (`:851`), and says so
explicitly at `:843-847`:

> #103: the counter lives on the INSTANCE and is reset by
> `_process_event_queue` at the start of each drain, not here. A settle pass
> that re-arms an `invoke` whose sync completion lands on the queue returns
> to the drain, which calls back in; a per-call counter restarted at 0 every
> time, so the budget tripped repeatedly and terminated never — `start()`
> hung.

That reasoning is sound and the fix it motivates is correct: the counter must
*not* be reset on every call into `_process_transient_transitions`, because
one macrostep can re-enter it several times. But "not per call" was
implemented as "per drain", and a drain is not a macrostep — it is the whole
`send_events()` batch. `send_events` (`:596-610`) appends every event and
calls `_process_event_queue` once:

```python
for event_or_type in events:
    event_obj = self._prepare_event(event_or_type)
    self._event_queue.append(event_obj)

self._process_event_queue()
```

so each event in the list is a separate macrostep inside one drain, sharing
one allowance. The drain loop already has the hook needed to fix this: it
takes `current_event` off the queue and calls
`self._drive(self._process_event(current_event))` followed by
`self._process_transient_transitions()` (`:784-785`) — the boundary between
macrosteps is that exact point.

Note the contrast with the *chain* budget in the same loop, which the round-4
work did get per-event right: at `:803-808` `generated`/`tripped` are reset
when a macrostep leaves the queues no longer than it found them — an explicit
"this chain is over, the next event starts fresh" rule. The settle budget has
no equivalent.

The async engine is not affected in the same way (it has no `send_events`
batch API and drives one external event per loop turn), which is why this
shows up as an engine divergence.

## Impact

**General users.** Anyone who uses `send_events()` — the documented way to
feed a machine a batch — gets a `maxIterations` that silently shrinks with
batch size. The failure is load-dependent and shape-dependent: the same code
that passes a unit test sending events one at a time truncates in production
where events arrive in batches, and the truncation leaves the machine in a
legal-looking intermediate state (`u9` above) with no exception at the call
site. Replay and catch-up paths, which are exactly the ones that batch, are
the most exposed. The workaround — never batch, or set `maxIterations` to
`limit * max_batch_size` — requires knowing about this bug and makes the
ceiling useless as a runaway guard.

**Order-management scenario (our adoption audit, #26).** On startup we replay
each order's buffered exchange events into its machine with a single
`send_events([...])`: a dozen `ACK`/`PARTIAL_FILL`/`FILL` events per order.
Several of our states settle through short `always` chains (fee
recomputation, exposure recalculation, OCO sibling checks). With a dozen
events in one batch the later ones settle against an exhausted budget and
stop mid-chain — so an order that has genuinely filled is left in an
intermediate accounting state, with `send_events()` returning normally. A
truncated replay is a mis-stated position, and it is worse than a crash
because the machine looks settled.

## Proposed fix

**Reset the settle budget at the macrostep boundary, keeping #103's
invariant.** The requirement #103 identified is "do not reset on re-entry
into `_process_transient_transitions` within one macrostep". The requirement
here is "do reset between macrosteps". Both are satisfied by resetting in the
drain loop, immediately before processing each dequeued event, rather than
once before the loop:

```python
# in _process_event_queue, inside the drain loop, per event:
self._settle_iterations = 0
self._settle_tripped = False
self._drive(self._process_event(current_event))
self._process_transient_transitions()
```

Re-entrant calls from within the macrostep (the `invoke`-completion case #103
describes) still accumulate, because they happen between these two resets.

A subtlety worth getting right: the deferred-replay path at `:809-818`
re-injects held events at the head of the queue. Those are separate
macrosteps and should each get a fresh budget under the same rule — which the
per-event reset gives for free.

**Alternatively — and preferably, as a second step — separate "is this one
macrostep cycling?" from "has this drain done too much work".** Keep a
per-macrostep settle counter for the cycle guard (the thing `maxIterations`
documents), and add a distinct, much larger per-drain work ceiling for
total-work protection if that is wanted. Conflating the two is what produced
this bug. If a drain ceiling is added it needs its own error type and its own
config key, not `maxIterations`.

**Also make the failure loud at the call site.** `send_events()` returns
`None`, so today the only signal is `last_transition_ok`/`last_error`. Having
it return a list of per-event receipts (or at minimum raise
`RunawayChainError` when a *batch member* trips) would mean a truncated
replay cannot be mistaken for a successful one. This is a separate API
question and need not block the fix above.

**Compatibility.** Machines that currently trip on a batch will now complete
— strictly more work done, no configuration that was reachable before becomes
unreachable. A machine with a genuine `always` cycle still trips, now once per
offending event instead of once per batch, which is the more useful signal.
A user who was (unknowingly) relying on the drain ceiling as a total-work
bound loses it; that should be called out in the changelog, with the
suggestion to bound batch size instead.

## Acceptance criteria

- [ ] `repro/R5-09_settle-budget-per-drain.py` exits `0`.
- [ ] `tests/test_round5_findings.py::test_send_events_batch_matches_sequential_sends`
      — for the 40-hop/limit-50 machine above, `send_events([A, B])` reaches
      the same `value` as `send(A); send(B)`, with
      `last_transition_ok is True` and `last_error is None`.
- [ ] `tests/test_round5_findings.py::test_settle_budget_is_per_macrostep_not_per_batch`
      — parameterised over batch sizes 1…10 of the same event: the final
      configuration is independent of batch size.
- [ ] `tests/test_round5_findings.py::test_settle_budget_still_bounds_a_genuine_always_cycle`
      — a mutually-targeting `always` pair still trips `RunawayChainError`
      and terminates, once per event, with `_repair_configuration` leaving a
      legal configuration (#112 unchanged).
- [ ] `tests/test_round5_findings.py::test_invoke_completion_reentry_does_not_reset_budget`
      — pins #103's original case: a settle pass that re-arms an `invoke`
      whose sync completion lands on the queue still terminates and
      `start()` does not hang.
- [ ] `tests/test_round5_findings.py::test_deferred_replay_gets_a_fresh_settle_budget`
      — an event replayed from the defer buffer is a new macrostep.
- [ ] Changelog entry noting the granularity change from per-drain to
      per-macrostep.

## Related

- **Round-4 issues:** #103 (the per-drain reset this narrows), #112 (the
  observable trip — `last_transition_ok`/`last_error`/`_repair_configuration`
  — which is what makes the failure detectable at all and is unchanged by
  this fix), #77 (the chain-budget accounting in the same drain loop that
  *is* correctly reset per macrostep at `sync_interpreter.py:803-808`).
- **R5-04** (Blocker) — the other end of the same budget: a nested-invoke
  `onDone` cycle whose chain accounting self-resets every iteration, so no
  `maxIterations` value bounds it. R5-09 is "the budget is charged too
  widely"; R5-04 is "the budget is never charged". A single review of the
  drain loop's accounting should cover both.
- **R5-08** (High) — `send_threadsafe` bypasses the self-send gate, so that
  budget is unenforceable on the async engine. Same theme, different path.
- **Register source ids:** R5-09 ← `J-5` (`32-r5-diff-review.md`).
- **Evidence:** `probes/main-3ed3099/p2_gate_and_inline.py` (cases J-6,
  J-6b); `33-r5-findings-register.md` §2/§3 R5-09.

## Verification

- Date: 2026-09-19
- Python: CPython 3.13.7
- Commit: `3ed3099`
- Re-ran `repro/R5-09_settle-budget-per-drain.py` fresh: exit `1`, output
  unchanged (`sequential -> u40, ok`; `batched -> u9, RunawayChainError`).
- Root-cause citations checked against source: `sync_interpreter.py`
  `_process_event_queue` resets `self._settle_iterations = 0` /
  `self._settle_tripped = False` once, before the drain loop (matches
  `:612-625` region cited); `_process_transient_transitions` only increments
  and checks the counter, with the `#103` comment quoted verbatim present
  above the loop; `send_events` appends all events then calls
  `_process_event_queue()` once, confirming one shared budget per batch.
- Duplicate check: `gh issue list --search "settle budget"` returns #112
  (orphaned leaf on trip — a different symptom of the same subsystem, already
  cited under Related), #103 (the predecessor this narrows, already cited),
  #115, #77, #110 — none report the per-drain-vs-per-macrostep granularity
  bug. No duplicate found.
- Self-contained, no project-name/label leak: confirmed.
