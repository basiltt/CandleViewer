---
r4: R4-04
title: "Bug: SyncInterpreter.start() never terminates for a cross-region `always` transition that re-enters an invoking state"
labels: [bug, severity/blocker, area/sync-interpreter]
severity: Blocker
repro_script: repro/R4-04_sync-start-nonterminating.py
commit: 5e07ba8
python: 3.13.7
verified: true
---

## Summary

`SyncInterpreter.start()` hangs forever on a parallel machine where one
region has an `always` transition targeting an invoking state in *another*
region. The microstep budget in `_process_transient_transitions` bounds a
single settling pass, not the settle loop: every pass that re-arms the
`invoke` returns control to `_process_event_queue`, which calls back in
with `iterations` reset to `0`. The budget therefore trips repeatedly and
terminally never — the "Exceeded 1000 microsteps … Aborting" message is
logged hundreds of times while the machine keeps spinning, growing the
inbox without bound. Build-time validation does not catch the shape either,
because `_is_dead_always_loop` only fires when `target is t.source`. For a
long-running stateful service this is an unbounded hang at *construction*
time on the synchronous engine, with no timeout, no exception, and no way
to interrupt the calling thread.

## Environment

- Commit: `5e07ba8842345a73ef8f830f0281de16370a7c74` (`main`,
  `[Unreleased] — targeting 0.8.1`; `__version__` still reports `0.8.0`,
  so this build is identified by commit).
- Python: CPython 3.13.7
- OS: Windows 11 Pro 10.0.26200
- Editable install of the repo into a local venv; no library source
  modified.

## Minimal reproduction

```python
"""R4-04 repro: SyncInterpreter.start() never terminates for a cross-region
`always` transition that re-enters an invoking state.

Exits 1 while the defect is present (start() has not returned inside the
budget), 0 once fixed (start() returns, or raises a typed error).
Stdlib + xstate_statemachine only.
"""

import logging
import sys
import threading
import time

from xstate_statemachine import MachineLogic, SyncInterpreter, create_machine

# The library logs "Exceeded 1000 microsteps ... Aborting" once per settling
# pass -- tens of thousands of times here, which is itself evidence that the
# budget is re-armed rather than terminal.  Counted, not printed.
BUDGET_S = 20.0


class _Counter(logging.Handler):
    count = 0

    def emit(self, record):
        _Counter.count += 1


logging.getLogger("xstate_statemachine").handlers[:] = [_Counter()]
logging.getLogger("xstate_statemachine").propagate = False

# `B.b1` has an eventless transition into the *other* region's invoking state
# `A.a1`.  Re-entering `A.a1` re-arms `invoke: svc`, whose `onDone` targets
# `a1` again -> the settling loop is re-entered from a fresh macrostep with
# `iterations` reset to 0 every time, so the microstep budget never bites.
CFG = {
    "id": "m",
    "type": "parallel",
    "maxIterations": 1000,  # library default, stated explicitly
    "states": {
        "A": {
            "initial": "a1",
            "states": {
                "a1": {"invoke": {"id": "s", "src": "svc", "onDone": "a1"}},
                "a2": {},
            },
        },
        "B": {
            "initial": "b1",
            "states": {"b1": {"always": {"target": "#m.A.a1"}}},
        },
    },
}


def svc(interpreter, ctx, event):
    return 1


result = {}


def run():
    t0 = time.time()
    interp = SyncInterpreter(
        create_machine(CFG, logic=MachineLogic(services={"svc": svc}))
    )
    try:
        interp.start()
    except Exception as exc:  # a typed RunawayChainError would be acceptable
        result["error"] = repr(exc)
    result["elapsed"] = time.time() - t0
    result["state_ids"] = sorted(interp.current_state_ids)
    result["status"] = interp.status
    result["last_transition_ok"] = interp.last_transition_ok
    result["last_error"] = interp.last_error
    result["queue_depth"] = interp.queue_depth


thread = threading.Thread(target=run, daemon=True)
thread.start()
thread.join(BUDGET_S)

print("OBSERVED:")
print("  'Exceeded 1000 microsteps ... Aborting' logged %d times" % _Counter.count)
if thread.is_alive():
    print("  SyncInterpreter.start() has NOT returned after %.0f s" % BUDGET_S)
    print("  no timeout, no exception, no way to interrupt the calling thread")
else:
    print("  start() returned in %.3f s" % result["elapsed"])
    print("  result:", result)

print("EXPECTED:")
print("  start() terminates: the iteration budget (maxIterations=1000) bounds")
print("  the whole settling loop and a typed RunawayChainError is raised, or")
print("  build-time validation rejects the cyclic `always` graph.")

if thread.is_alive():
    print("RESULT: FAIL - non-terminating start() on the sync engine")
    sys.exit(1)
print("RESULT: PASS")
sys.exit(0)
```

The repro runs `start()` on a daemon thread purely so the script can
*observe* the hang and exit; on the main thread it simply never returns.

## Observed behaviour

```
OBSERVED:
  'Exceeded 1000 microsteps ... Aborting' logged 396 times
  SyncInterpreter.start() has NOT returned after 20 s
  no timeout, no exception, no way to interrupt the calling thread
EXPECTED:
  start() terminates: the iteration budget (maxIterations=1000) bounds
  the whole settling loop and a typed RunawayChainError is raised, or
  build-time validation rejects the cyclic `always` graph.
RESULT: FAIL - non-terminating start() on the sync engine
```

Exit status `1`.

The 396 log lines are the key evidence: the guard *is* firing, ~20 times a
second, and each firing aborts only the current pass. Memory grows with it
— a longer run of the same shape measured the inbox at **125,249 events and
climbing after 6 s**.

Lowering `maxIterations` makes the loop terminate, and the settling time
scales roughly as `2^(N/2)` in the budget — i.e. the work per pass is
exponential in the limit, and the default of 1000 is far past any tractable
value:

| `maxIterations` | `start()` outcome |
|---|---|
| 18 | settles in 0.62 s |
| 24 | settles in 1.92 s |
| 28 | settles in 3.17 s |
| **1000 (default)** | **still running when the 20 s budget expired** |

The settled runs are themselves wrong in a second way: they report
`status='running'`, `last_transition_ok=True`, `last_error=None` after the
budget was breached hundreds of times — the settling break is entirely
unobservable to the caller. (That reporting gap is tracked separately; see
Related.)

## Expected behaviour

W3C SCXML §3.13 requires the eventless-transition settling loop to run
"until no more transitions match" as part of reaching a stable
configuration, and an implementation is expected to terminate; SCXML
explicitly notes that a specification of eventless transitions that never
stabilises is an author error to be detected, not an implementation
behaviour to be exhibited.

XState v5 added exactly this guard in v5.31.0 and raises on an infinite
eventless loop rather than spinning
(<https://stately.ai/docs/eventless-transitions>), and the library's own
source cites that precedent as the reason the guard exists, at
`src/xstate_statemachine/sync_interpreter.py:810-813`:

> 🛟 Bound the microstep loop. A pair of `always` transitions that
> target each other spins forever; XState added the same guard in
> v5.31.0. `max_iterations` is configurable on the machine.

So the contract the library states for itself is that `max_iterations`
bounds the loop. Expected: `start()` returns in bounded time for every
machine, and when the bound is hit it is reported — as
`RunawayChainError`, exactly as the sibling event-chain budget already
does. Better still, the cyclic `always` graph is rejected at build time by
`validation.py`, where the other `always` validations already live.

## Root cause analysis

**1. The microstep budget is per-pass, not per-settle.**

`SyncInterpreter._process_transient_transitions`
(`sync_interpreter.py:797`) declares its counter as a local, initialised on
every call (`:809-812`):

```python
iterations = 0
limit = getattr(self.machine, "max_iterations", 1000)
while True:
    iterations += 1
    if iterations > limit:
        logger.error("🔁 Exceeded %d microsteps while settling transient ...")
        break
```

The `break` exits *this invocation*. Control returns to
`_process_event_queue` (`:586`), which — because the pass re-armed the
`invoke` on `A.a1` and thereby queued fresh events — calls
`_process_transient_transitions` again from a new macrostep, with
`iterations` freshly `0`. Nothing accumulates across calls, so the guard
can never be terminal. This is why the message appears 396 times instead
of once.

**2. The event-chain budget cannot backstop it either.**

`_process_event_queue` has its own budget (`:627-636`: `generated`,
`tripped`, `limit`), but it is explicitly reset whenever the queue length
decreases (`:776-777`):

```python
generated = 0
tripped = False
```

Each settling pass drains before re-arming, so the queue length dips on
every cycle and the chain budget is re-armed in lockstep with the microstep
budget. Neither counter ever reaches its limit in a terminal way.

**3. Build-time validation is blind to the shape.**

`validation.py:132-151`:

```python
def _is_dead_always_loop(label, t, target) -> bool:
    return (
        label == "always"
        and target is t.source
        and not t.reenter
        and not t.actions
    )
```

The check is *identity of target and source*. The repro's transition has
`source = m.B.b1` and `target = m.A.a1` — a different node, in a different
region — so `_is_dead_always_loop` returns `False` and the machine builds
clean. The validator detects a self-loop; it does not detect a *cycle*. The
cycle here is not even purely within the `always` graph: it closes through
`invoke`/`onDone` (`a1 --invoke.onDone--> a1`, re-armed by the cross-region
`always`), which is why a naive self-loop check has no chance.

**4. The break is silent.**

Contrast the two budgets in the same file. The event-chain budget at
`:716-737` does the full job on breach — logs once (`if not tripped`),
fires `on_event_dropped` for every victim, sets
`self.last_transition_ok = False`, and stores
`self._last_action_error = RunawayChainError(self.id, limit, dropped_total)`
so `Receipt.error` and `last_transition_ok` carry it, per the `#77`
criterion-6 comment. The transient budget at `:812-824` does none of that
— bare `logger.error` and `break`. Hence the `last_transition_ok=True,
last_error=None` seen in the bounded runs above.

**Regression provenance.** The per-pass guard is the original shape of the
`#29` mitigation (the `_is_dead_always_loop` docstring cites `#29`); it was
written for the mutually-targeting self-loop pair and has never been
widened to cover re-entry from a fresh macrostep. This is a
never-sufficient guard rather than a regression from a previously-correct
state.

## Impact

**General users.** Any `SyncInterpreter` construction is a potential
unbounded hang. The failure is at `start()`, so it occurs before the
application has any interpreter handle to inspect, cancel, or time out; on
the sync engine there is no equivalent of `asyncio.wait_for` to wrap it,
so the calling thread is simply lost and memory climbs until the process is
OOM-killed. The triggering shape — a parallel machine where one region
nudges another region back into a service-invoking state — is an ordinary
supervisor/worker pattern, not a contrived one, and neither build-time
validation nor any runtime signal warns about it. A user who hits this sees
a process that hangs on startup with no output beyond a repeating log line
that says it is aborting.

**Order-management scenario (our adoption audit, #26).** We pin
`SyncInterpreter` for anything on the order-decision path, because the
decision must complete synchronously before the order is released. A
catalogue change that introduces this shape — a risk region that sends the
order region back into its `invoke`-backed pricing call — turns order
placement into a hung thread at machine construction. There is no timeout
to trip, no exception to catch, no receipt to inspect: the order-placement
worker is gone, memory grows, and the service degrades until the process
dies. Orders in flight at that moment have no disposition recorded. That is
a direct money-loss path from a config-level mistake, which is why this is
a Blocker for us independently of the persistence findings.

## Proposed fix

**1. Make the settling budget bound the settle, not the pass.** Hoist the
counter out of `_process_transient_transitions` into per-macrostep state on
the interpreter — e.g. `self._transient_iterations`, reset in
`_process_event_queue` only when a genuine external event begins a new
macrostep, and incremented across every settling pass within that
macrostep. The existing `while True` body is unchanged; only the lifetime
of `iterations` moves.

**2. Make the breach observable and terminal.** On breach, mirror the
event-chain budget at `:716-737` exactly: set `last_transition_ok = False`,
set `_last_action_error = RunawayChainError(self.id, limit, ...)`, fire
`on_event_dropped` for the discarded tail, and *raise* the
`RunawayChainError` out of `start()` rather than returning a machine that
claims to be running. `RunawayChainError` already exists
(`exceptions.py:392`) and is already the vocabulary for "a budget stopped
runaway self-generated work", so no new exception type is needed and
callers already catching `XStateMachineError` are covered.

**3. Widen `_is_dead_always_loop` into a real cycle check.** Replace the
`target is t.source` test in `validation.py:132-151` with a cycle detection
over the eventless-transition graph: build the directed graph of
`always` edges (source state → resolved target state), plus the
`invoke.onDone`/`onError` edges that can re-arm a service, and report any
strongly-connected component containing an `always` edge whose members
carry no actions and no `reenter` (i.e. nothing in the cycle can mutate
context to flip a guard). The current self-loop case falls out as the
one-node SCC, so existing `#29` behaviour and its tests are preserved.

**Compatibility.** (1) is invisible to any machine that settles today —
only machines that currently hang or that currently breach the budget
repeatedly change behaviour. (2) converts a silent hang into a raised
typed error at `start()`; that is a breaking change only for code relying
on the current non-termination, i.e. nobody. (3) newly rejects at build
time some machines that today build and then hang; it should land behind
the same validation-strictness switch as the other `always` checks, and the
SCC report should name the participating state ids so the fix is obvious.

**Alternatives considered.** A wall-clock timeout on `start()` would bound
the symptom but not diagnose it, and picking a portable default duration is
not possible. Detecting "queue is growing monotonically across N macrosteps"
is a heuristic with false positives on legitimately busy machines. The
iteration budget is already the library's chosen mechanism and its own
documented contract — the fix is to make it actually bound the loop it
claims to bound.

## Acceptance criteria

- [ ] `repro/R4-04_sync-start-nonterminating.py` exits `0`.
- [ ] `tests/test_sync_interpreter.py::test_cross_region_always_into_invoking_state_raises_runaway_chain_error`
      — `start()` raises `RunawayChainError` in bounded time (assert under
      a few seconds), rather than hanging.
- [ ] `tests/test_sync_interpreter.py::test_transient_budget_is_per_macrostep_not_per_pass`
      — the "Exceeded N microsteps" log fires at most once per macrostep.
- [ ] `tests/test_sync_interpreter.py::test_transient_budget_breach_sets_last_transition_ok_false`
      — `last_transition_ok is False` and `last_error` is a
      `RunawayChainError`, matching the event-chain budget's contract.
- [ ] `tests/test_sync_interpreter.py::test_transient_budget_breach_fires_on_event_dropped`
- [ ] `tests/test_validation.py::test_cross_region_always_cycle_is_rejected_at_build_time`
      — the repro's config fails `create_machine` with a message naming
      `m.B.b1` and `m.A.a1`.
- [ ] `tests/test_validation.py::test_existing_self_targeting_always_loop_still_detected`
      — the `#29` self-loop case is unchanged.
- [ ] `tests/test_validation.py::test_always_cycle_with_actions_is_not_rejected`
      — a cycle whose transitions carry actions stays legal (an action can
      mutate context and flip the guard), preserving the current exemption.
- [ ] Equivalent async-engine coverage, or an explicit note that
      `Interpreter` is unaffected and why.

## Related

- **Register ids:** R4-04 (this issue). Source id `D-fuzz-1`.
- **R4-12** (High, an `always` transition targeting the machine root empties
  the configuration on both engines, leaving `status="running"`) — the same
  blind spot in `_is_dead_always_loop`, via a simpler single-region path.
  The cycle-detection fix proposed here (step 3) should be designed to
  cover both; R4-12's fix is the ancestor-targeting case of the same
  validator change.
- **`D-fuzz-9`** (High, orphaned non-tree configuration after the settling
  budget breaks) — the same per-pass budget break at
  `sync_interpreter.py:812-824`, reached with a tighter `maxIterations` so
  the loop does terminate; leaves `m.b.b.a` active without its ancestors and
  reports `last_transition_ok=True`. Step 2 above (observable breach) is the
  shared fix for its reporting half.
- **Evidence:** `battle-5e07ba8/fuzz/repros.py d1` (+ `min_hang.json`,
  `shrink_hang.py`); `probes/main-5e07ba8-final/v4_sync_hang.py` (the
  `maxIterations` scaling table).
- **Prior art in this repo:** #29 (dead `always` loop detection — the
  validator this widens), #77 (observable budget breaks — criterion 6, the
  contract the event-chain budget meets and this one does not), #88
  (per-chain `tripped` semantics in `_process_event_queue`).

## Verification

- Date: 2026-09-19
- Python: CPython 3.13.7 (`.venv-main`)
- Commit: `5e07ba8842345a73ef8f830f0281de16370a7c74` (confirmed via
  `git log -1` in the library clone)
- `repro/R4-04_sync-start-nonterminating.py` run fresh, capped at 60 s (the
  script's own 20 s internal budget elapses well within that): output
  matches the Observed behaviour section — the "Exceeded 1000 microsteps
  ... Aborting" line was logged repeatedly (424 times this run vs. 396 in
  the filed issue; both demonstrate the same non-terminal, re-armed
  budget), `start()` had not returned after 20 s, `RESULT: FAIL`. Exit
  code `1`.
- Root-cause narrative confirmed against source:
  `_process_transient_transitions` (per-pass counter `iterations`, reset
  on every call) is at `sync_interpreter.py:797`, with the budget/`break`
  at `:809-824`; `_process_event_queue` is at `:586`, with the event-chain
  budget reset (`generated = 0; tripped = False`) at `:776-777`; the fully
  observable event-chain-budget breach handling (`on_event_dropped`,
  `last_transition_ok = False`, `RunawayChainError`) is at `:716-737` for
  comparison; `_is_dead_always_loop` (`target is t.source` identity check)
  is at `validation.py:132-151`.
- External claim checked: GitHub release notes for `xstate@5.31.0`
  (fetched 2026-09-19) confirm it added the `maxIterations` machine option
  "to configure the maximum number of microsteps allowed before throwing
  an infinite loop error," matching the issue's citation of that guard as
  precedent. The `stately.ai/docs/eventless-transitions` page also
  confirms XState is documented to "help guard against most infinite loop
  scenarios" for eventless transitions.
- Duplicate check: `gh issue list -R basiltt/xstate-statemachine --state
  all --limit 120 --search "always transition runaway"` returned no
  matches; a full listing of all 40+ issues in the repo shows #29 covers
  only the same-state self-loop case (`target is t.source`), not the
  cross-region cycle this issue reports. No duplicate found.
- No project-name/label leakage found in the issue body or repro script.
