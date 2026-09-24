---
r5: R5-10
title: "Semantics: `guardErrorPolicy: \"raise\"` cancels the remaining candidates in a transition array, so an unguarded fallback on an `invoke.onDone` is never taken and the completion is dropped"
labels: [bug, severity/low, area/semantics]
severity: Low
repro_script: repro/R5-10_guard-raise-cancels-fallback-candidate.py
commit: 3ed3099
python: 3.13.7
verified: true
---

## Summary

`docs/_guide/guards.md` §"Error Handling in Guards" opens by stating that
when a guard raises, "the interpreter substitutes a result and **moves on to
the next candidate**", and then lists three policies under that sentence.
That is true for `"false"` and `"true"` but not for `"raise"`: the exception
propagates out of the selection pass, so every **lower-priority candidate in
the same transition array is cancelled** — an unguarded fallback branch that
exists precisely to catch a failing check is not evaluated. On a
caller-driven `send()` the raise at least reaches the caller; on an
**engine-driven** transition (`invoke.onDone`/`onError`) there is no caller,
the completion event is consumed with no retry, and the region stays in the
invoking state.

This was filed at High on the claim that the region is *silently stranded*.
Our own adversarial re-run refutes that half: the machine remains fully
responsive to external events, and the failure is reported on four
surfaces — `on_guard_error`, `last_transition_ok=False`, `last_error`, and
`has_dormant_invocations=True` (the signal `docs/_guide/snapshots.md` §145
designates for exactly this check, in preference to `status`). What survives
is a real but observable and documentable semantic gap, filed here at **Low**.

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
"""R5-10 repro: under `guardErrorPolicy: "raise"`, a guard that raises on an
ENGINE-DRIVEN transition (`invoke.onDone`) also cancels every LOWER-PRIORITY
candidate in the same array, so an unguarded fallback is never taken and the
completion event is dropped with no retry. Control: the identical machine
under the default `"false"` takes the fallback. The region is NOT wedged and
the failure IS observable; the defect is the lost fallback branch, which
`docs/_guide/guards.md` does not document.

Exits 1 while present, 0 once fixed. Stdlib + xstate_statemachine only.
"""

import asyncio
import logging
import sys

from xstate_statemachine import Interpreter, MachineLogic, create_machine


def gboom(c, e):
    raise RuntimeError("guardboom")


async def svc(i, c, e):
    return {"ok": True}


def cfg(policy: str):
    return {
        "id": "ld", "initial": "verifying",
        # mandatory config block
        "actionErrorPolicy": "rollback", "guardErrorPolicy": policy,
        "onUnhandled": "ignore", "strictTargets": True, "strict": False,
        "spawnBlockingTimeout": 5.0,
        "states": {
            "verifying": {"invoke": {"id": "ver", "src": "svc", "onDone": [
                {"target": "accepted", "guard": "risk_ok"},
                {"target": "rejected"},  # unguarded fallback
            ]}},
            "accepted": {}, "rejected": {},
        },
    }


async def run(policy: str):
    i = Interpreter(
        create_machine(
            cfg(policy),
            logic=MachineLogic(services={"svc": svc}, guards={"risk_ok": gboom}),
        )
    )
    await i.start()
    await asyncio.sleep(0.3)
    out = (sorted(i.current_state_ids), i.status, i.last_transition_ok,
           i.has_dormant_invocations)
    await i.stop()
    return out


async def main() -> int:
    r_ids, r_status, r_ok, r_dormant = await run("raise")
    f_ids, _, f_ok, f_dormant = await run("false")

    print("OBSERVED:")
    print('  guardErrorPolicy="raise"  ids=%s status=%s last_ok=%s dormant=%s'
          % (r_ids, r_status, r_ok, r_dormant))
    print('  guardErrorPolicy="false"  ids=%s last_ok=%s dormant=%s  (control)'
          % (f_ids, f_ok, f_dormant))
    print("EXPECTED:")
    print("  a raising guard makes ITS candidate unselectable; the next")
    print("  candidate is still evaluated, so both policies reach")
    print("  ['ld.rejected'] (or `raise`'s cancellation of the remaining")
    print("  candidates is documented in guards.md).")

    if r_ids == ["ld.verifying"] and f_ids == ["ld.rejected"]:
        print("RESULT: FAIL - `raise` cancelled the unguarded fallback "
              "candidate and dropped the completion event")
        return 1
    print("RESULT: PASS")
    return 0


if __name__ == "__main__":
    logging.disable(logging.CRITICAL)
    sys.exit(asyncio.run(main()))
```

## Observed behaviour

```
OBSERVED:
  guardErrorPolicy="raise"  ids=['ld.verifying'] status=running last_ok=False dormant=True
  guardErrorPolicy="false"  ids=['ld.rejected'] last_ok=True dormant=False  (control)
EXPECTED:
  a raising guard makes ITS candidate unselectable; the next
  candidate is still evaluated, so both policies reach
  ['ld.rejected'] (or `raise`'s cancellation of the remaining
  candidates is documented in guards.md).
RESULT: FAIL - `raise` cancelled the unguarded fallback candidate and dropped the completion event
```

Exit status `1`.

Two observations that bound the severity, from an expanded run of the same
machine (`issues/post-3ed3099/new/repro/_scratch_r5_10.py`, cases A–C):

- **The region is not wedged.** With an `ANY` transition declared on
  `verifying`, `await i.send("ANY", wait=True)` returns `changed=True` and the
  machine moves to `elsewhere`. The interpreter is fully responsive; only the
  completion event was lost.
- **The failure is reported on four surfaces.** Hooks fired:
  `on_guard_error` (plus the usual lifecycle hooks);
  `last_transition_ok=False`; `last_error=RuntimeError('guardboom')`;
  `has_dormant_invocations=True` with
  `pending_invocations() == [PendingInvocation(state_id='ld.verifying',
  invoke_id='ver', src='svc')]`. `logger.exception` also fires at
  `base_interpreter.py:4496`. `interpreter.error` is `None` and `status` is
  `"running"`, which is correct and documented — `interpreters.md:223` and
  `snapshots.md:149` both state that `status` is *not* a liveness signal and
  that `has_dormant_invocations` is the one to use.

## Expected behaviour

The library's own documented contract, `docs/_guide/guards.md:586`:

> If a guard raises an exception, the interpreter substitutes a result and
> **moves on to the next candidate**. What it substitutes is controlled by
> the machine-config key **`guardErrorPolicy`**:

with the `"raise"` row at `:592`:

> The exception propagates. In `SyncInterpreter` it reaches the `send()`
> caller; in the async `Interpreter` the run loop contains it and stays
> alive. Either way the machine is left in its pre-event state and remains
> usable.

The observed outcome matches the `"raise"` row. It does **not** match the
lead sentence that governs all three rows, and the lead sentence is the one
that tells a reader what happens to the rest of the candidate array. The
source makes the same promise, `base_interpreter.py:4472-4479`:

> a guard is a *predicate supplied by the user*, so a raised exception is a
> defect in that predicate rather than a machine-level failure. Per the
> documented contract it evaluates to `False`, blocking this transition while
> leaving the machine responsive and **allowing any lower-priority transition
> (e.g. an unguarded fallback in the same `on` array) to be considered**.

That comment sits directly above the `except` block that, under `"raise"`,
re-raises and prevents exactly the behaviour it describes.

XState v5 resolves a transition array by evaluating candidates in order and
taking the first whose guard passes; a guard that throws is a defect in user
code, and the actor is not expected to abandon the remaining candidates.
W3C SCXML §3.13 selects, per the document order of the transition list, the
first transition whose condition evaluates true — and §5.9 specifies that an
error in evaluating a condition is treated as the condition evaluating to
false, precisely so that evaluation of the list continues.

Either behaviour is defensible for the caller-driven case (a caller can catch
the exception and retry). Two things are needed:

1. **Decide and document what `"raise"` does to the rest of the candidate
   array**, since the guide currently promises the opposite of what happens.
2. **Engine-driven transitions have no caller to catch the raise.** For
   `invoke.onDone`/`onError`, an `after` deadline, or an `always`, the
   propagated exception has nowhere to go and the triggering event is
   consumed. These need a defined disposition, not just containment.

## Root cause analysis

The guard is evaluated in `BaseInterpreter._is_guard_satisfied`
(`base_interpreter.py:~4455`). The policy is applied in its `except`
handler at `:4485-4510`:

```python
except Exception as exc:
    policy = self.machine.guard_error_policy
    logger.exception(...)
    for plugin in self._plugins:
        plugin.on_guard_error(self, guard.type, event, exc)
    if policy == "raise":
        raise
    result = policy == "true"
```

Under `"false"`/`"true"` the method *returns a bool*, so the caller —
`_passes()` inside `_collect_eligible_transitions`
(`base_interpreter.py:3985-4004`) — simply records that this candidate is
ineligible and the upward walk continues to the next one. Under `"raise"`
the `raise` unwinds out of `_passes`, out of
`_collect_eligible_transitions`, out of `_select_transitions`
(`:4083`), and out of `_process_event` (`:2013`) before line `:2023`
(`transitions = self._select_transitions(event)`) has returned. No candidate
list is ever produced, so:

- the remaining, possibly unguarded, candidates are never examined;
- `_handle_unhandled_event` at `:2024-2026` is never reached either, so
  the `onUnhandled` policy does not apply and no `on_unhandled_event` hook
  fires;
- the event is simply gone.

For a `send()` the exception surfaces on the caller (sync) or is contained by
the run loop (async, `interpreter.py` run-loop handler) and reported via
`last_transition_ok`/`last_error`. For an engine-driven event the run loop is
the only "caller" — hence containment plus the fire-and-forget surface, which
is the documented arrangement for callerless failures
(`json-config.md:110`, `testing-and-pure-api.md:187`), but with no retry and
no record of *which* event was lost.

A secondary, smaller gap: `on_guard_evaluated` fires for the control case
(policy `"false"`) but not under `"raise"`, because the `raise` at `:4500`
precedes the hook call at `:4519`. An observer counting guard evaluations
sees the raising evaluation only through `on_guard_error`.

## Impact

**General users.** The "guarded primary branch + unguarded fallback" shape is
the standard way to express "accept if the check passes, otherwise reject" on
an `invoke.onDone`. A user who sets `guardErrorPolicy: "raise"` — the setting
recommended for a control path precisely because it does not silently
substitute a result — loses the fallback, and the docs tell them the fallback
will be taken. The state machine then parks in the invoking state with the
service finished. Because the failure *is* reported (`on_guard_error`,
`last_error`, `has_dormant_invocations`), a user with a health check on the
documented signal will notice; a user who reads `status` will not, and the
guide does not warn them at this spot.

**Order-management scenario (our adoption audit, #26).** Our risk-check
shape is `invoke: risk_service` with
`onDone: [{target: accepted, guard: within_limits}, {target: rejected}]` —
the fallback is the fail-safe. Under `guardErrorPolicy: "raise"` (which our
mandatory config block specifies, so that a crashing risk check is never
mistaken for a passing one) a bug inside `within_limits` means the order
neither accepts nor rejects: it sits in `verifying` with the risk service
already returned. That is a stuck order rather than a wrong one, and our
supervisor catches it via `has_dormant_invocations` — which is why this is a
Low and not a Blocker. The residual cost is a manual intervention per
occurrence and an order that is neither placed nor cancelled until then.

## Proposed fix

Primarily a **specification and documentation** fix, with a small code change
to make the engine-driven case tractable.

**1. Correct `docs/_guide/guards.md`.** Amend the lead sentence so it does
not promise next-candidate evaluation for all three policies, and add to the
`"raise"` row that the exception aborts the entire selection pass for that
event: remaining candidates in the same array are not evaluated, and the
event is consumed. Add an explicit note for engine-driven transitions
(`invoke.onDone`/`onError`, `after`, `always`): there is no caller to receive
the exception, so the completion is lost and the region stays put; observe it
via `on_guard_error`, `last_transition_ok`/`last_error` and
`has_dormant_invocations`. Recommend putting a fallible check in an `always`
on the committed state rather than on an `onDone` branch.

**2. Make `"raise"` cancel only its own candidate (preferred).** Treat a
raising guard as an unsatisfied guard for *selection* purposes — matching
SCXML §5.9 and the intent already written at `base_interpreter.py:4472-4479`
— and deliver the exception *after* the pass, on the surface that
corresponds to the trigger:

- record the exception, mark the candidate ineligible, continue the walk;
- once selection completes, if the event was caller-driven, raise (sync) /
  fail the receipt (async) as today, so `"raise"`'s existing contract to the
  caller is preserved;
- if the event was engine-driven, keep the containment plus
  `last_transition_ok`/`last_error`, but now the fallback has already been
  taken, which is the behaviour the fallback exists for.

This keeps `"raise"`'s promise ("the exception propagates", "the machine
remains usable") while restoring the array semantics the guide documents.

**3. Route engine-driven guard failures through the unhandled-event
policy.** Whatever is decided for (2), an engine-driven event that ends up
selecting nothing because of a guard error should reach
`_handle_unhandled_event` (`base_interpreter.py:3608`) so the machine's
`onUnhandled` policy applies and `on_unhandled_event` fires with a
disposition — today it is bypassed entirely by the unwind. A new disposition
value (`"guard_errored"`) would make the loss auditable.

**4. Fire `on_guard_evaluated` under `"raise"` too**, before the re-raise,
so evaluation counts are policy-independent.

**5. Ergonomics on `PendingInvocation`** (folded in from the former LD-02):
the record correctly appears for this dead strand, but carries no indication
of *why* the invoke is dormant (restored vs guard-crashed vs never started)
and no timestamp. Adding a `reason` and a `since` would let a supervisor
distinguish "restored a moment ago, about to be restarted" from "crashed
twenty minutes ago". Minor, but it is what turns the existing signal into an
actionable alarm.

**Compatibility.** (2) changes behaviour for machines that set
`guardErrorPolicy: "raise"` *and* have multiple candidates on one event *and*
have a guard that raises — a combination that today produces a stuck region,
so the change is strictly an improvement, but it should be a changelog entry.
(1), (4) and (5) are non-breaking.

## Acceptance criteria

- [ ] `repro/R5-10_guard-raise-cancels-fallback-candidate.py` exits `0`.
- [ ] `tests/test_round5_findings.py::test_guard_raise_still_evaluates_lower_priority_candidates`
      — `onDone: [{guard: raises}, {unguarded fallback}]` under
      `guardErrorPolicy: "raise"` reaches the fallback, and
      `last_error` still carries the guard's exception.
- [ ] `tests/test_round5_findings.py::test_guard_raise_on_send_still_reaches_the_caller`
      — pins the existing `"raise"` contract: the sync `send()` caller and
      the async `wait=True` receipt still receive the exception.
- [ ] `tests/test_round5_findings.py::test_guard_raise_engine_driven_is_observable`
      — `on_guard_error` fires, `last_transition_ok is False`,
      `last_error` is set, and the interpreter stays responsive to a
      subsequent external event.
- [ ] `tests/test_round5_findings.py::test_guard_error_fires_on_guard_evaluated_under_raise`
- [ ] `tests/test_round5_findings.py::test_engine_driven_guard_error_reaches_unhandled_policy`
      — `on_unhandled_event` fires with a `"guard_errored"` disposition
      when no candidate is selected because of a guard error.
- [ ] Parity: the same table runs green on `SyncInterpreter`.
- [ ] `docs/_guide/guards.md` §"Error Handling in Guards" states what
      `"raise"` does to the remaining candidates and what happens on an
      engine-driven transition; `docs/api/index.md:714`
      `pending_invocations()` documents the dormancy reason if (5) is taken.

## Related

- **Round-4 issues:** #35 (the `guardErrorPolicy` key and the
  `on_guard_error` hook that make this observable at all — the hook is
  working exactly as designed here), #44 (`pending_invocations()` /
  `has_dormant_invocations`, the health signal that bounds this to Low),
  #135 (`status` is not a liveness signal — the documentation that refutes
  the original "reports healthy" framing).
- **R5-11** (Low) — the other observability-shaped residue from this round:
  a real no-op and a guard-denied event are indistinguishable on every
  surface. Both concern what a caller can learn about a transition that did
  not happen.
- **Register source ids:** R5-10 ← `LD-01`, `LD-02` (the latter folded in as
  proposed-fix item 5).
- **Evidence:** `triage-r5/t4_final.py::LD01` (as filed);
  `35-r5-10-refutation.md` (the adversarial re-run that downgraded this from
  High to Low, cases A–D); `issues/post-3ed3099/new/repro/_scratch_r5_10.py`
  (this round's expanded re-run); `33-r5-findings-register.md` §2/§3 R5-10.

## Verification

- Date: 2026-09-19
- Python: CPython 3.13.7
- Commit: `3ed3099`
- Re-ran `repro/R5-10_guard-raise-cancels-fallback-candidate.py` fresh: exit
  `1`, output unchanged (`raise` stuck at `ld.verifying`, dormant=True;
  `false` control reaches `ld.rejected`).
- Also re-ran `repro/_scratch_r5_10.py` (the expanded A–C cases cited for the
  severity downgrade): exit `0`, confirms the region is not wedged (a
  further `ANY` send moves it to `elsewhere`) and the failure is reported on
  `on_guard_error`/`last_transition_ok`/`last_error`/`has_dormant_invocations`.
- Root-cause citations checked against source: `base_interpreter.py`'s guard
  exception handler contains `if policy == "raise": raise` (line 4505,
  matching the cited `:4485-4510` region), and `_handle_unhandled_event`
  (`:3608`) with `_notify_unhandled(..., "ignored")` at `:3660` confirms the
  raise unwinds before this method is ever reached.
- Duplicate check: `gh issue list --search "guardErrorPolicy raise"` returns
  #35 (guard-raise swallowed as `False` — the predecessor this issue's guide
  contract derives from, already cited), #129, #26 — no duplicate for the
  candidate-array-cancellation defect.
- Self-contained, no project-name/label leak: confirmed.
