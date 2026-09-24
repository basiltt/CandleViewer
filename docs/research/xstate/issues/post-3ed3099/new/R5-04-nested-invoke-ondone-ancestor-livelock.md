---
r5: R5-04
title: "Bug: nested invokes whose `onDone` targets their common compound ancestor livelock `SyncInterpreter.start()`; no budget bounds it"
labels: [bug, severity/blocker, area/sync-interpreter]
severity: Blocker
repro_script: repro/R5-04_nested-invoke-ondone-ancestor-livelock.py
commit: 3ed3099
python: 3.13.7
verified: true
---

## Summary

`SyncInterpreter.start()` never returns for a machine where a compound state
and its initial child each `invoke` a service whose `onDone` targets their
common compound ancestor. Re-entering the ancestor re-arms both invokes, both
sync services complete inside the same drain, and their `done.invoke` events
re-enter the ancestor again — forever. This is a *different* budget from the
one #103 repaired: #103 made the **settle** budget per-drain and terminal, but
this cycle contains no `always` transition at all, so
`_process_transient_transitions` returns at its first line and the only budget
in play is the **event-chain** budget, which `sync_interpreter.py:802-807`
explicitly resets on every macrostep that does not grow the queues. This cycle
consumes exactly what it produces, so the queues never grow and the budget is
re-armed in lockstep with the loop. #103 closed its own reproducer; the
invariant behind it — *`start()` terminates* — is still unenforced.

## Environment

- Commit: `3ed3099096d15544e96c9d9458c21c2a30ef48e3` (`main`,
  `[Unreleased] — targeting 0.8.1`; `__version__` still reports `0.8.0`, so
  this build is identified by commit).
- Python: CPython 3.13.7
- OS: Windows 11 Pro 10.0.26200
- Editable install of the repo into a local venv; no library source modified.

## Minimal reproduction

```python
"""R5-04 repro: nested invokes whose `onDone` targets their common compound
ancestor livelock `SyncInterpreter.start()`; `maxIterations` does not bound it.

Exits 1 while the defect is present (start() has not returned inside the
watchdog budget, at any `maxIterations`), 0 once fixed (start() returns, or
raises a typed error, in bounded time).

Stdlib + xstate_statemachine only.
"""

import copy
import logging
import sys
import threading

from xstate_statemachine import MachineLogic, SyncInterpreter, create_machine

logging.disable(logging.CRITICAL)

WATCHDOG_S = 8.0

# `m.a` invokes `i1`; its child `m.a.a` invokes `i2`.  Both services succeed
# immediately and both `onDone` transitions target `#m.a` -- the common
# compound ancestor.  Re-entering `m.a` re-arms `i1` AND (via the initial
# child) `i2`, so the cycle consumes exactly as many events as it produces.
CFG = {
    "id": "m",
    "initial": "a",
    "states": {
        "a": {
            "initial": "a",
            "invoke": {"id": "i1", "src": "svc", "onDone": {"target": "#m.a"}},
            "states": {
                "a": {
                    "invoke": {
                        "id": "i2",
                        "src": "svc",
                        "onDone": {"target": "#m.a"},
                    }
                }
            },
        }
    },
}


def svc(interpreter, ctx, event):  # noqa: ANN001, D103
    return {"ok": 1}


def probe(max_iterations):
    """Start a SyncInterpreter on a watchdog thread; report whether it returns."""
    cfg = copy.deepcopy(CFG)
    if max_iterations is not None:
        cfg["maxIterations"] = max_iterations
    machine = create_machine(cfg, logic=MachineLogic(services={"svc": svc}))
    interp = SyncInterpreter(machine)
    out = {}

    def run():
        try:
            interp.start()
            out["returned"] = sorted(interp.current_state_ids)
            out["ok"] = getattr(interp, "last_transition_ok", None)
            out["last_error"] = repr(getattr(interp, "last_error", None))
        except BaseException as exc:  # noqa: BLE001
            out["raised"] = f"{type(exc).__name__}: {exc}"

    th = threading.Thread(target=run, daemon=True)
    th.start()
    th.join(WATCHDOG_S)
    alive = th.is_alive()
    print(
        f"  maxIterations={max_iterations!r:>6}  after {WATCHDOG_S}s: "
        f"start_alive={alive}  {out}"
    )
    return alive


print("OBSERVED:")
hung = [probe(mi) for mi in (None, 10, 1000)]

print("\nEXPECTED: start() returns (or raises a typed RunawayChainError) in")
print("          bounded time for every maxIterations -> start_alive=False.")
if any(hung):
    print("RESULT: FAIL -- SyncInterpreter.start() livelocked (watchdog fired).")
    sys.exit(1)
print("RESULT: PASS")
sys.exit(0)
```

## Observed behaviour

```
OBSERVED:
  maxIterations=  None  after 8.0s: start_alive=True  {}
  maxIterations=    10  after 8.0s: start_alive=True  {}
  maxIterations=  1000  after 8.0s: start_alive=True  {}

EXPECTED: start() returns (or raises a typed RunawayChainError) in
          bounded time for every maxIterations -> start_alive=False.
RESULT: FAIL -- SyncInterpreter.start() livelocked (watchdog fired).
```

Exit code `1`. The watchdog thread is still inside `start()` at every
`maxIterations` setting, including the smallest (`10`). The original track
evidence (`battle-3ed3099/fuzz/n1_repro.py`, re-run under a 40 s cap) adds
two further facts: RSS stays flat at 43 MB across the whole run — this is a
true **livelock**, not a leak, so no `MemoryError` will ever end it — and the
**async** engine's `start()` *returns* with `status="running"` and
`interpreter.error is None` while its event loop burns ~100 % CPU
indefinitely. The async engine therefore hands back a machine that looks
healthy by every public predicate and is permanently consuming a core.

## Expected behaviour

SCXML §3.13 ("Selecting and executing transitions") specifies the macrostep
as a loop that runs *until the machine is in a stable configuration* — a
microstep sequence is required to terminate before control returns to the
caller. A configuration that can never become stable is not a legal
computation and must be reported, not run forever.

XState v5 makes this explicit and is the precedent the library's own comment
already cites: `xstate@5.31.0` added the `maxIterations` machine option "to
configure the maximum number of microsteps allowed before throwing an
infinite loop error", and
[stately.ai/docs/eventless-transitions](https://stately.ai/docs/eventless-transitions)
documents the engine as guarding "against most infinite loop scenarios". The
guard is expected to *throw*, terminally.

The library's own contract says the same. `sync_interpreter.py:625-631`:

> 🛟 Bound the macrostep. The `raise` built-in re-enters this queue, so an
> action that raises its own trigger event feeds itself forever.
> `max_iterations` previously guarded only the eventless (`always`) path,
> leaving this loop unbounded: `send()` never returned, with no timeout and
> no way to interrupt it. **The same ceiling now applies to both paths.**

It does not. `start()` must return in bounded time for every machine, or
raise `RunawayChainError` with `last_transition_ok is False` — the contract
the chain budget already meets on the shapes it does catch
(`sync_interpreter.py:756-766`).

## Root cause analysis

**1. The cycle contains no `always` transition, so the #103 budget is not
even reached.**

`_process_transient_transitions` (`sync_interpreter.py:827`) begins:

```python
if not self.machine.has_always_transitions:
    return  # ⚡ nothing to settle; see MachineNode.has_always_transitions
```

The repro's machine has zero `always` transitions. The instance-scoped,
per-drain settle counter that #103 introduced (`self._settle_iterations`,
reset at `sync_interpreter.py:623-625`, tripped at `:851-868`) is never
incremented. #103's fix is correct for the shape it targeted and is simply
out of the path here — the cycle closes entirely through
`invoke` → `done.invoke` → `onDone` → re-entry.

**2. The event-chain budget self-resets, so it cannot bound a
conservative cycle.**

The only remaining guard is the chain budget in `_process_event_queue`
(`generated` / `tripped` / `limit`, `sync_interpreter.py:657-666`). It is
reset by `sync_interpreter.py:802-807`:

```python
if (
    len(self._internal_queue) + len(self._event_queue)
    <= queued_before
):
    generated = 0
    tripped = False
```

The comment above it (`:798-801`) states the intent: "A step that produced
nothing ends the current chain (parity with the async `_raise_depth` reset).
`tripped` is cleared here too: the runaway is over once it stops
regenerating."

The condition is `<=`, i.e. *did not grow* — not *produced nothing*. This
cycle is exactly **conservative**: each macrostep dequeues one `done.invoke`
and, by re-entering `m.a`, re-arms the two invokes which enqueue the same
number back. `len(queues) == queued_before` on every single pass, so
`generated` is zeroed before it can ever reach `limit`. With `maxIterations:
10` the counter never gets past 1. That is why tightening the budget has no
effect at all — the observed table is flat across `None`, `10` and `1000`.

**3. `#94`'s completion-sparing makes it worse, by design.**

`sync_interpreter.py:688-699` documents that engine completions
(`done.invoke`, `error.platform`, due `after`) are **never dropped**, because
dropping one strands the machine in the invoking state. The comment
anticipates precisely this shape — "a rollback that re-arms an invoke whose
`onDone` fails again is a genuine self-feeding cycle made entirely of
completions, and the count is the only thing that breaks it" — and relies on
the count. The count is the thing the reset at `:802-807` destroys. The two
mechanisms are individually reasonable and jointly vacuous.

**4. Build-time validation is structurally blind.**

`validation.py:132-151`:

```python
def _is_dead_always_loop(
    label: str, t: "TransitionDefinition", target: "StateNode"
) -> bool:
    return (
        label == "always"
        and target is t.source
        and not t.reenter
        and not t.actions
    )
```

Two independent reasons this cannot fire: `label == "always"` (the repro's
transitions are labelled `onDone`), and `target is t.source` (the target is
the ancestor `m.a`, the source is `m.a` for `i1` — but the `i2` transition's
source is `m.a.a`, a *different* node). The validator detects a self-loop on
the eventless graph; it does not detect a *cycle*, and it does not consider
the `invoke`/`onDone` edges that close this one.

**Regression provenance.** This is not a regression of #103 — #103's change
is sound and its reproducer stays fixed. It is the residue of the same
underlying gap #103 was one instance of: *no budget in the sync engine is
terminal for the whole `start()`/`send()` call*. The `<=`-reset was
introduced as part of the #88 per-chain semantics (the comment at `:788-797`
names the 3,000-independent-raises batch case it was added for); #88 needed
`generated` to reset for *independent* user events, and reused a queue-length
proxy that a conservative cycle satisfies trivially.

## Impact

**General.** `SyncInterpreter.start()` is the constructor-time entry point.
A machine with this shape hangs the calling thread at startup with no
timeout, no exception, no log line after the first, and no way to interrupt
it — the thread is inside a tight `while` loop in library code and does not
poll for cancellation. On the async engine the failure is quieter and worse:
`start()` returns a machine reporting `status="running"` with `error is
None`, so health checks pass while one core is pinned at 100 % forever. Any
`asyncio` service that constructs this machine degrades the whole loop; every
other task on it is starved.

The shape is not exotic. "A compound state supervises a step; its child runs
a sub-step; when either finishes, go back to the top of the supervisor" is
the ordinary way to express a retry/polling supervisor, and `onDone`
targeting the compound ancestor is how you write it.

**Concrete order-management scenario.** An order-submission supervisor
`submitting` invokes `reserve_margin`; its initial child `placing` invokes
`place_with_venue`. Both `onDone` handlers target `#oms.submitting` so the
supervisor re-evaluates whether more legs remain. On the day both services
return synchronously from a warm cache — the fast path, under load — the
order manager's `SyncInterpreter.start()` never returns. The process appears
to be up; its health endpoint (if async) reports `running`; orders queue
behind a thread that will never come back, and there is no timeout anywhere
in the library to break it. Recovery requires killing the process, and the
in-flight order state was never persisted because `start()` never returned to
hand back an interpreter to snapshot.

## Proposed fix

**1. Make the chain reset mean what its comment says.** Replace the
queue-length proxy at `sync_interpreter.py:802-807` with the actual
predicate — *this macrostep generated nothing*:

```python
if not step_generated:      # tracked: did this step append to either queue?
    generated = 0
    tripped = False
```

Record `queued_before` and compare against appends made during
`self._drive(self._process_event(current_event))` (a counter incremented in
`_deliver_completion` / the internal-raise path is the least invasive form).
A conservative cycle then accumulates `generated` monotonically and trips at
`limit`, while #88's 3,000 independent one-deep raises still reset correctly
because each of those steps genuinely produces nothing after its own child
is drained.

**2. Add a terminal per-call ceiling.** Independently of chain accounting,
cap the *total* macrosteps executed inside one `_process_event_queue` drain
at a generous multiple of `max_iterations` (say `10 * limit`, or a separate
`maxMacrosteps` option defaulting to that). On breach: trip exactly as the
chain budget does — `last_transition_ok = False`,
`_last_action_error = RunawayChainError(self.id, limit, dropped_total)`,
`on_event_dropped` per victim, `_repair_configuration()`, and return. This is
the defence in depth that makes "`start()` terminates" an invariant rather
than a property of whichever budget happens to be in the path, and it closes
the whole family of which #103 and this issue are two members.

**3. Apply the same ceiling to the async engine.** `Interpreter`'s
`_raise_depth` has the same per-macrostep reset. A cycle made entirely of
completions burns the loop without ever tripping it; the breach must set
`status="error"` with a `RunawayChainError` so a returned-but-spinning
interpreter is observable.

**4. Widen validation to a genuine cycle check.** Generalise
`_is_dead_always_loop` into a reachability check over the *zero-input* edge
set — `always` transitions **plus** `invoke.onDone`/`onError` edges whose
service is synchronously resolvable — and reject a cycle in that graph whose
transitions carry no actions and no guards (the existing exemption: an action
can mutate context and flip a guard). This also subsumes the
ancestor-targeting case.

**Compatibility.** (1) and (2) only affect machines that currently hang or
spin, which have no working behaviour to preserve. (4) is a new build-time
rejection and should ship behind the same escape hatch as the existing
validator findings, with the message naming the cycle's node ids.

## Acceptance criteria

- [ ] `repro/R5-04_nested-invoke-ondone-ancestor-livelock.py` exits `0`.
- [ ] `tests/test_sync_interpreter.py::test_nested_invoke_ondone_to_common_ancestor_terminates`
      — `start()` returns (or raises `RunawayChainError`) within 5 s for the
      repro's machine at `maxIterations` of `None`, `10` and `1000`.
- [ ] `tests/test_sync_interpreter.py::test_conservative_cycle_does_not_reset_chain_budget`
      — a macrostep that dequeues one event and enqueues one event does
      **not** zero `generated`; asserted directly on the counter or via the
      trip occurring within `limit` steps.
- [ ] `tests/test_sync_interpreter.py::test_independent_raises_still_reset_chain_budget`
      — the #88 case (3,000 independent one-deep raises in one
      `send_events()` batch) is still processed in full, guarding the fix in
      (1) against regressing what the `<=` reset was added for.
- [ ] `tests/test_sync_interpreter.py::test_completion_only_cycle_trip_is_observable`
      — after the trip, `last_transition_ok is False`, `last_error` is a
      `RunawayChainError`, `status` is not corrupted, and every active node's
      parent is also active (no torn configuration), matching #112's
      contract.
- [ ] `tests/test_interpreter.py::test_async_completion_cycle_fails_observably`
      — the async engine's `start()` does not return a spinning
      `status="running"` machine; the breach sets `status="error"` with a
      `RunawayChainError`.
- [ ] `tests/test_validation.py::test_invoke_ondone_cycle_to_ancestor_is_rejected_at_build_time`
      — `create_machine` on the repro's config fails with a message naming
      `m.a` and `m.a.a`.
- [ ] `tests/test_validation.py::test_existing_dead_always_loop_still_detected`
      — the #29 self-loop case is unchanged.
- [ ] `tests/test_validation.py::test_ondone_cycle_with_actions_or_guards_is_not_rejected`
      — a cycle whose transitions carry actions or guards stays legal,
      preserving the current exemption.
- [ ] #103's own regression test still passes unchanged.

## Related

- **#103** (`SyncInterpreter.start()` hangs forever on a cross-region
  `always` transition re-entering an invoking state) — verified **FIXED** at
  `3ed3099`; this issue is the same invariant violated through a path #103's
  per-drain settle counter does not sit on. Filed as R4-04 in the previous
  round.
- **#112** (settle-budget trip leaves an orphaned leaf / non-reproducible
  round-trip) — supplies the observability + `_repair_configuration()`
  contract that the new terminal ceiling in step (2) must meet.
- **#88** (per-chain `tripped` semantics in `_process_event_queue`) — the
  change that introduced the `<=` queue-length reset; step (1) refines it
  without regressing its motivating case.
- **#94** (engine completions are never dropped) — interacts directly: the
  sparing rule is what leaves the count as the only brake.
- **#29** (dead `always` loop detection) — the validator step (4) widens.
- **#116** (sync/async invoke timing parity) — the plain-sync service
  completing inside the entering macrostep is what makes this cycle close on
  the sync engine at all.
- **Register source ids:** R5-04, `D5-fuzz-1`.
- **Evidence:** `battle-3ed3099/fuzz/n1_repro.py` (40 s cap, RSS table,
  async arm), `battle-3ed3099/fuzz/n9_livelock_scope.py`,
  `battle-3ed3099/fuzz/shrink_hang.py` / `min_hang.json` (the shrink that
  produced this configuration).
- Raised by our adoption audit (#26).

## Verification

- Date: 2026-09-19
- Python: CPython 3.13.7 (`.venv-main`)
- Commit: `3ed3099096d15544e96c9d9458c21c2a30ef48e3` (confirmed via
  `git rev-parse HEAD` in the library clone; `main`,
  `[Unreleased] — targeting 0.8.1`)
- Re-ran `repro/R5-04_nested-invoke-ondone-ancestor-livelock.py` fresh with
  a 30 s cap per the livelock class: it did not terminate within the
  script's own 8 s watchdog at any `maxIterations` (`None`, `10`, `1000`)
  and exited `1`, matching the documented "Observed behaviour" exactly.
  Non-termination is the expected observed result for this repro.
- Root-cause citations checked against source at this commit:
  `sync_interpreter.py:657/707/806` (`generated = 0` / `tripped = False`
  resets, `<=`-queue-length condition at `:802-807`), `validation.py:131-150`
  (`_is_dead_always_loop`, `label == "always"` / `target is t.source` gate).
  Line numbers and quoted code match.
- README/contract citations: none claimed beyond source comments, which
  match verbatim.
- Duplicate check: `gh issue list -R basiltt/xstate-statemachine --state all
  --limit 150` (search flag unreliable in this environment; checked full
  title list instead) — no open or closed issue covers a nested-invoke
  `onDone`-to-ancestor cycle or a terminal ceiling on the sync event-chain
  budget. #103 (closed, `always`-loop settle-budget) and #94/#88 (closed,
  completion-sparing / `<=` reset) are related but do not cover this cycle
  shape; both are cited in Related with their closed status noted.
- Result: exit `1`, confirms defect as described. `verified: true`.
