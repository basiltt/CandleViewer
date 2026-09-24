---
r5: R5-12
title: "Bug: `actionErrorPolicy: \"fail\"` leaves the configuration on the SOURCE state, bricks the interpreter, and persists the bricked state without complaint"
labels: [bug, severity/blocker, area/interpreter]
severity: Blocker
repro_script: repro/R5-12_action-error-policy-fail-persists-source-state.py
commit: 3ed3099
python: 3.13.7
verified: true
---

## Summary

Under `actionErrorPolicy: "fail"`, an action that raises during the target's
`entry` list rolls the configuration back to the **source** state and then
calls `_fail()`, so the machine sits at `status="error"` while
`current_state_ids` reports the pre-transition leaf. The machine is bricked —
every subsequent `send()` returns `changed=False` and the status never leaves
`"error"` — yet `get_persisted_snapshot()` accepts it and returns
`{"status": "error", "state_ids": ["f.a"]}`, a structurally legal blob that
restores into a permanently dead machine reporting a state it had already
left. #102 closed the *no-leaf* snapshot window (`state_ids: []` is now
refused with `SnapshotMidStepError`); this is the **legal-but-wrong-leaf**
window under the same policy, and it is uncovered by that guard and by
`persistence.check_shape()`, whose only configuration predicate is
`status == "running" and configuration is empty`. The documented contract
says `"fail"` "also **stops** with `TransitionFailedError`"; the machine is
not stopped, it is stranded.

## Environment

- Commit: `3ed3099096d15544e96c9d9458c21c2a30ef48e3` (`main`,
  `[Unreleased] — targeting 0.8.1`; `__version__` still reports `0.8.0`, so
  this build is identified by commit).
- Python: CPython 3.13.7
- OS: Windows 11 Pro 10.0.26200
- Editable install of the repo into a local venv; no library source modified.

## Minimal reproduction

```python
"""R5-12 repro: `actionErrorPolicy: "fail"` leaves the configuration on the
SOURCE state, bricks the interpreter, and `get_persisted_snapshot()` happily
persists that bricked state.

The documented contract (README "Failure modes" table) is that `"fail"`
"also stops with `TransitionFailedError`". Observed instead: `status` becomes
`"error"`, the configuration is the *source* leaf, an earlier action in the
same entry list has already applied its outward effect, every subsequent send
is inert, and a snapshot taken now is accepted and reports
`{"status": "error", "state_ids": ["f.a"]}`.

Exits 1 while the defect is present, 0 once fixed.
Stdlib + xstate_statemachine only.
"""

import asyncio
import json
import logging
import sys

from xstate_statemachine import Interpreter, MachineLogic, create_machine

logging.disable(logging.CRITICAL)

CFG = {
    "id": "f",
    "initial": "a",
    "actionErrorPolicy": "fail",
    # `ok1` succeeds (its effect escapes), then `boom` raises.
    "states": {"a": {"on": {"GO": "b"}}, "b": {"entry": ["ok1", "boom"]}, "c": {}},
}

ran = []


def ok1(interp, ctx, evt, action_def=None):  # noqa: ANN001, D103
    ran.append("ok1")


def boom(interp, ctx, evt, action_def=None):  # noqa: ANN001, D103
    raise RuntimeError("boom")


async def main():
    logic = MachineLogic(actions={"ok1": ok1, "boom": boom})
    interp = await Interpreter(create_machine(CFG, logic=logic)).start()

    receipt = await interp.send("GO", wait=True)
    obs = {
        "receipt_changed": receipt.changed,
        "receipt_error": repr(receipt.error),
        "ids_after": sorted(interp.current_state_ids),
        "status": interp.status,
        "interpreter_error": type(interp.error).__name__ if interp.error else None,
        "ran": list(ran),
    }

    # The machine is now inert: further events change nothing.
    r2 = await interp.send("GO", wait=True)
    obs["second_send_changed"] = r2.changed
    obs["status_after_second_send"] = interp.status

    # ...and the bricked configuration is happily persisted.
    try:
        snap = interp.get_persisted_snapshot()
        obs["snapshot"] = {"status": snap["status"], "state_ids": snap["state_ids"]}
    except Exception as exc:  # noqa: BLE001
        obs["snapshot"] = "REFUSED: " + type(exc).__name__

    print("OBSERVED:")
    print(json.dumps(obs, indent=2))
    print(
        "\nEXPECTED: the configuration is NOT the source leaf ['f.a'] while "
        "status=='error',\n          and get_persisted_snapshot() REFUSES a "
        "bricked machine (or the\n          machine is stopped with "
        "TransitionFailedError per the documented contract)."
    )
    bad = (
        obs["ids_after"] == ["f.a"]
        and obs["status"] == "error"
        and isinstance(obs["snapshot"], dict)
    )
    if bad:
        print(
            "RESULT: FAIL -- source-state configuration under status='error', "
            "persisted without complaint."
        )
        return 1
    print("RESULT: PASS")
    return 0


sys.exit(asyncio.run(main()))
```

## Observed behaviour

```
OBSERVED:
{
  "receipt_changed": false,
  "receipt_error": "RuntimeError('boom')",
  "ids_after": [
    "f.a"
  ],
  "status": "error",
  "interpreter_error": "TransitionFailedError",
  "ran": [
    "ok1"
  ],
  "second_send_changed": false,
  "status_after_second_send": "error",
  "snapshot": {
    "status": "error",
    "state_ids": [
      "f.a"
    ]
  }
}

EXPECTED: the configuration is NOT the source leaf ['f.a'] while status=='error',
          and get_persisted_snapshot() REFUSES a bricked machine (or the
          machine is stopped with TransitionFailedError per the documented contract).
RESULT: FAIL -- source-state configuration under status='error', persisted without complaint.
```

Exit code `1`. Four distinct facts, each independently a problem:

1. **`ids_after == ["f.a"]`** — the source. Not the target `f.b`, not a
   dedicated fault state. Anything reading `current_state_ids`, `value` or
   state tags sees the machine as still sitting in `a`, as though `GO` had
   never been accepted.
2. **`ran == ["ok1"]`** — `ok1` executed and its outward effect has left the
   machine. A "rollback" restored configuration and context but cannot undo
   an effect, so the reported state and the world disagree.
3. **`second_send_changed == false`, `status` still `"error"`** — permanently
   inert. One raise disables the machine for the rest of the process.
4. **`snapshot` accepted** — `{"status": "error", "state_ids": ["f.a"]}` is
   returned without complaint and passes `persistence.check_shape()` on the
   way back in.

The **sync** engine agrees: `battle-3ed3099/triage-r5/t2_engine.py` shows the
same source-state configuration and `status="error"`.

## Expected behaviour

**The library's own documented contract.** `README.md:1437`, the "failure
modes" table:

> | An **action** raises (entry, exit, or transition) | Contained; the
> transition still commits | `actionErrorPolicy`: `"rollback"` restores
> configuration *and* context · `"fail"` **also stops with
> `TransitionFailedError`** | `on_action_error`, `on_transition_failed`,
> `interpreter.last_transition_ok` |

"Stops" is a specific, observable outcome in this library: `status ==
"stopped"`, children reaped, timers cancelled, and — critically —
`get_persisted_snapshot()` describing a machine a consumer knows not to
resume as though it were live. What actually happens is `status == "error"`
with a *running-shaped* configuration, which is a different thing: `"error"`
is the status `_fail()` uses for an invoked service that died
(`base_interpreter.py:3826-3851`), where the configuration legitimately still
names where the failure happened.

`TransitionFailedError`'s own docstring (`exceptions.py:249-266`) states it
the same way:

> Raised when ``actionErrorPolicy`` is ``"fail"`` and an action raised. […]
> "the transition was rolled back and the machine **stopped**
> (actionErrorPolicy='fail')."

**Configuration legality.** SCXML §3.13 and the XState v5 snapshot model both
treat a persisted snapshot as a resumable description of a live machine. A
snapshot whose `state_ids` name a leaf the machine has provably left, and
into which no event can ever be delivered, is not a resumable description of
anything — it is indistinguishable, to every consumer-side predicate, from a
healthy machine parked in `a`. XState's error snapshots carry the error as
the snapshot's defining feature and are not fed back through
`createActor(..., { snapshot })` as though live; this library's
`from_snapshot` restores `status` verbatim (`base_interpreter.py:1423-1428`,
"#135: `status` is restored as persisted") and then rebuilds the
configuration from `configuration or state_ids` (`:1441-1442`), producing a
dead machine wearing a live machine's clothes.

Concretely, one of these must hold:

- `"fail"` genuinely stops: `status == "stopped"`, per the README and the
  exception's own message; **or**
- the configuration under `status == "error"` is not silently the source leaf
  — the failure is represented, not hidden; **and in either case**
- `get_persisted_snapshot()` refuses, or `check_shape()` rejects on restore,
  a snapshot that cannot be resumed — the same protection #102 established
  for the no-leaf window, applied to this one.

## Root cause analysis

**1. `"fail"` reuses `"rollback"`'s restore, then bolts `_fail()` on the
end.**

`_apply_action_error_policy` (`base_interpreter.py:3687`) treats the two
non-`continue` policies identically — `:3732-3734`:

```python
if self.machine.action_error_policy != "continue":
    action_def, exc = failed_actions[0]
    raise _RollbackRequested(action_def, exc)
```

The caller's atomic block (`:2683-2742`) catches it, restores
`_active_state_nodes` from `snapshot_before` (`:2701-2702`), re-arms the
exited states' timers and invokes (`:2707-2712`), unwinds any `spawn_*`, and
hands off to `_finish_rollback`. Everything up to here is `"rollback"`
behaviour and is correct for `"rollback"`.

`_finish_rollback` (`:3771`) then adds the only `"fail"`-specific step,
`:3798-3806`:

```python
if not isinstance(cause, _RollbackRequested):
    return False
if self.machine.action_error_policy == "fail":
    err = TransitionFailedError(
        cause.action_def.type, transition.source.id
    )
    err.__cause__ = cause.original
    self._fail(err)
return True
```

So `"fail"` is defined as *`"rollback"` plus `_fail()`*. But `_fail()`
(`:3826`) sets `status = "error"` and runs `_on_terminal("error")` — it does
**not** stop the machine, and by then the configuration has already been
restored to the source. The two halves were designed against different mental
models: the restore assumes the machine carries on from `a`, `_fail()`
assumes the machine is finished. The result is a machine that is finished
*and* claims to be in `a`.

**2. The snapshot guard's predicate is emptiness, not resumability.**

`get_persisted_snapshot` (`base_interpreter.py:1121`) refuses exactly one
condition, `:1156-1160`:

```python
if self._step_in_flight() and not self._active_leaf_present():
    if _seen is None:
        raise SnapshotMidStepError(self.id)
```

That is #102's guard: *mid-step **and** no leaf*. Here the step has
completed and a leaf is present (`f.a`), so both conjuncts are false and the
snapshot proceeds. The read side is no stricter —
`persistence.check_shape()` (`persistence.py:186-189`) has exactly one
configuration predicate:

```python
if status == "running" and not (
    snapshot.get("configuration") or snapshot["state_ids"]
):
    fail("status is 'running' but the configuration is empty")
```

`status` is `"error"`, and the configuration is non-empty, so neither clause
engages. Nothing anywhere asks whether an `"error"` snapshot's configuration
is *meaningful*.

**3. The receipt cannot warn the caller either.**

`receipt.changed` is `False` and `receipt.error` is the bare
`RuntimeError('boom')` — the *original* exception, not the
`TransitionFailedError` the policy constructed. A caller checking
`receipt.error is None` learns something happened, but a caller checking
`changed` learns only "no transition", which is also what a guard denial
returns. This is the same collapse R5-11 reports from the other side.

**Provenance.** The `"fail"` branch has had this shape since the policy was
introduced; the `_fail()` call in `_finish_rollback` is what #39/#27 added to
make the failure carryable on a receipt. It made the failure *observable* on
a `wait=True` caller without making the resulting configuration *honest*, and
#102's later snapshot guard was scoped to the torn-midstep window, so it does
not reach this one.

## Impact

**General.** Any process that persists machine state — the whole point of
`get_persisted_snapshot`/`from_snapshot` — can write a blob that looks
perfectly healthy by every available predicate, restore it, and get a machine
that accepts events and does nothing, forever, from a state it had already
left. Because `status` round-trips as `"error"` (#135) the blob is at least
*labelled*, but the label is shared with the recoverable
invoked-service-failure case, and the configuration under it is actively
misleading rather than merely uninformative. Monitoring built on
`current_state_ids` or state tags — the normal way to build a dashboard on
this library — shows the pre-transition state and no alert.

The exposure is widened by R5-14: under `strict=True`, an action name with a
`spawn_` prefix is hijacked by the built-in router and raises
`ActorSpawningError`, which lands in exactly this path. A user who never
wrote a raising action can still arrive here.

**Concrete order-management scenario.** An order manager sets
`actionErrorPolicy: "fail"` precisely because a half-applied order transition
must halt rather than continue — that is the whole reason to choose `"fail"`
over `"continue"`. The transition `submitted -> live` has
`entry: ["record_fill", "notify_risk"]`. `record_fill` writes the fill to the
ledger and returns; `notify_risk` raises because the risk service is
momentarily down. The machine rolls back to `submitted`, `_fail()`s, and the
process's periodic checkpoint writes `{"status": "error", "state_ids":
["oms.order.submitted"]}`.

The fill is in the ledger. The state machine says the order is still
*submitted*. Every subsequent `CANCEL`, `FILL` or `EXPIRE` is silently
accepted and discarded — `changed=False`, no exception, no hook. On restart
the snapshot restores cleanly and the order resumes as "submitted", so
reconciliation will attempt to submit it again against a venue that has
already filled it. `"fail"` was chosen to make this impossible and instead
produced the quietest possible version of it.

## Proposed fix

**1. Make `"fail"` mean what the README and `TransitionFailedError` say:
stop.** In `_finish_rollback` (`base_interpreter.py:3798-3806`), replace the
`_fail(err)` call for the `"fail"` policy with a genuine terminal stop that
records the error — e.g. set `self.error = err`, then drive the normal
`stop()` teardown path so `status` becomes `"stopped"`, children are reaped,
and timers are cancelled. A stopped machine's configuration is understood to
be historical, so the source-state leaf stops being a lie. This is one
behaviour change and it aligns the code with two pieces of existing
documentation rather than inventing a third semantics.

**2. If `"error"` is kept instead of `"stopped"`, do not restore the source
configuration under it.** The alternative design is to keep `_fail()` and
make the `"fail"` path *skip* the configuration restore — leave the machine
where the failure happened (the partially-entered target), matching the
`"error"` status's existing meaning for invoked-service failures. Whichever
is chosen, `"fail"` must stop sharing `"rollback"`'s restore unconditionally:
split the branch in `_apply_action_error_policy` (`:3732-3734`) so the policy
is decided before the restore, not after it.

**3. Enforce one snapshot invariant on both sides.** The read side already
has the right idea and applies it to one status. Generalise it:

- *Write side* — in `get_persisted_snapshot` (`:1156`), add a guard beside
  #102's: refuse to persist a machine that is not resumable. The precise
  predicate is *"`status` names a terminal-by-policy outcome while the
  configuration describes a live-looking leaf"*; the simplest robust form is
  to record, on `_fail()` via a policy-driven `TransitionFailedError`, a flag
  such as `self._configuration_is_historical = True`, and raise a typed
  `SnapshotBrickedError` (sibling of `SnapshotMidStepError`) when it is set.
  If fix (1) is taken, this collapses to the existing, already-correct
  handling of `"stopped"`.
- *Read side* — extend `persistence.check_shape()` (`persistence.py:186`)
  beyond the `running`-and-empty clause: an `"error"` snapshot whose
  `state_ids` are non-empty must also carry a non-`None` `"error"` string,
  and `from_snapshot` must not silently produce a machine that reports a leaf
  it can never transition out of. Symmetry with the write side is the point —
  the same predicate, enforced in both directions, is what R5-01/R5-02 ask
  for in the general case.

**Compatibility.** (1) changes an observable status for a policy that is
opt-in and, today, produces a state no correct program can be relying on
(every send is inert). Note it in the changelog under `actionErrorPolicy`
and in the README table, which already describes the new behaviour. (3)'s
write-side refusal is a new exception on a call that currently returns a
useless blob; scope it to the bricked condition only so healthy `"error"`
snapshots (invoked-service failure) keep working exactly as they do now.

## Acceptance criteria

- [ ] `repro/R5-12_action-error-policy-fail-persists-source-state.py` exits
      `0`.
- [ ] `tests/test_interpreter.py::test_action_error_policy_fail_stops_the_machine`
      — after an entry-action raise under `"fail"`, `status == "stopped"`
      (or, if design (2) is chosen, the configuration is not the source leaf)
      and `interpreter.error` is a `TransitionFailedError` whose `__cause__`
      is the original exception.
- [ ] `tests/test_interpreter.py::test_action_error_policy_fail_configuration_is_not_the_source_leaf`
      — `current_state_ids` does not silently report the pre-transition leaf
      while the machine is dead.
- [ ] `tests/test_interpreter.py::test_action_error_policy_rollback_is_unchanged`
      — the `"rollback"` path still restores configuration *and* context and
      leaves `status == "running"`; guards the split in fix (2) against
      regressing the sibling policy.
- [ ] `tests/test_persistence.py::test_bricked_machine_snapshot_is_refused`
      — `get_persisted_snapshot()` on the repro's post-failure interpreter
      raises a typed error (or returns a `"stopped"` snapshot under fix (1)),
      never `{"status": "error", "state_ids": ["f.a"]}`.
- [ ] `tests/test_persistence.py::test_error_snapshot_from_failed_service_still_persists`
      — the legitimate `"error"` case (invoked service died, no `onError`)
      is unaffected and still round-trips, so the new guard is not a blanket
      ban on `"error"` snapshots.
- [ ] `tests/test_persistence.py::test_check_shape_rejects_error_snapshot_without_error_string`
      — the read-side half of the invariant.
- [ ] `tests/test_sync_interpreter.py::test_action_error_policy_fail_parity`
      — `SyncInterpreter` reaches the identical outcome, since
      `_apply_action_error_policy` is the shared single point both engines
      call.
- [ ] #102's mid-step refusal test still passes unchanged.

## Related

- **#102** (mid-macrostep snapshot not refused; `state_ids: []` restores as a
  permanently inert but healthy-looking machine) — verified **FIXED** at
  `3ed3099`. Its guard covers the *no-leaf* window; this issue is the
  *legal-but-wrong-leaf* window, reached after the step has completed, and
  the same "a snapshot must be resumable" invariant motivates both. Filed as
  R4-01 in the previous round.
- **#110** (snapshot shape validation) — `check_shape()` is the read-side
  half fix (3) extends.
- **#135** (`from_snapshot` restores `status` as persisted) — why the bad
  blob survives a round trip instead of being normalised away.
- **#39 / #27** (`Receipt.error` carries the action failure;
  `actionErrorPolicy` default-flip warning) — introduced the `_fail()` call
  in `_finish_rollback` that this issue isolates.
- **R5-11** (High, the receipt cannot distinguish outcomes) — the reason a
  caller cannot compensate at the call site: `changed=False, error=<original
  exception>` is not distinguishable from a guard denial by shape.
- **R5-14** (Medium, `spawn_*` hijacks user action names) — a second,
  non-obvious way to enter this path without writing a raising action.
- **Register source ids:** R5-12, `L-01`, `C-03` (library half).
- **Evidence:** `triage-r5/t3_receipts.py::L01` (async, `wait=True`),
  `triage-r5/t2_engine.py` (sync-engine parity).
- Raised by our adoption audit (#26).

## Verification

- Date: 2026-09-19
- Python: CPython 3.13.7 (`.venv-main`)
- Commit: `3ed3099096d15544e96c9d9458c21c2a30ef48e3` (confirmed via
  `git rev-parse HEAD` in the library clone; `main`,
  `[Unreleased] — targeting 0.8.1`)
- Re-ran `repro/R5-12_action-error-policy-fail-persists-source-state.py`
  fresh: exited `1`, output matches the documented "Observed behaviour"
  exactly — `receipt_changed=False`, `ids_after=["f.a"]`,
  `status="error"`, `interpreter_error="TransitionFailedError"`,
  `ran=["ok1"]`, second send inert, and
  `get_persisted_snapshot()` returns `{"status": "error",
  "state_ids": ["f.a"]}` without complaint.
- Root-cause citations checked against source at this commit:
  `base_interpreter.py:3732-3734` (`_apply_action_error_policy` raising
  `_RollbackRequested` for any non-`"continue"` policy),
  `base_interpreter.py:3798-3806` (`_finish_rollback`'s `"fail"`-specific
  `_fail()` call after the configuration has already been restored to the
  source), `base_interpreter.py:1156-1158` (`get_persisted_snapshot`'s
  guard is `_step_in_flight() and not _active_leaf_present()`, both false
  post-step), `persistence.py:186-189` (`check_shape()`'s only
  configuration predicate is `status == "running"` and empty). Line
  numbers and quoted code match.
- README/contract citation: line 1437 of `README.md` documents
  `actionErrorPolicy: "fail"` as "also stops with `TransitionFailedError`"
  — confirmed present verbatim; the observed behaviour (configuration
  frozen at the source leaf, machine bricked but not stopped) contradicts
  this documented contract as claimed.
- Duplicate check: `gh issue list -R basiltt/xstate-statemachine --state
  all --limit 150` (search flag unreliable in this environment; checked
  full title list instead) — no open or closed issue covers the
  legal-but-wrong-leaf snapshot window under `actionErrorPolicy: "fail"`.
  #102 (closed, mid-step no-leaf snapshot refusal) is the nearest relative
  and is correctly distinguished in Related/Summary as covering a
  different window; #39/#27 (closed) introduced the `_fail()` call this
  issue isolates and are cited accordingly.
- Result: exit `1`, confirms defect as described. `verified: true`.
