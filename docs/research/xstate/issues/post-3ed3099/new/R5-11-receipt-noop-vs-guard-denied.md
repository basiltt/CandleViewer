---
r5: R5-11
title: "Enhancement: A guard-denied event and an event the state never declared are indistinguishable — identical receipt, status, `last_transition_ok` and `on_unhandled_event` disposition"
labels: [enhancement, severity/low, area/observability]
severity: Low
repro_script: repro/R5-11_receipt-noop-vs-guard-denied.py
commit: 3ed3099
python: 3.13.7
verified: true
---

## Summary

`send(..., wait=True)` returns `Receipt(changed=False, error=None,
deferred=False)` both when the current state declares no handler for the
event and when it declares one whose only guard returned `False`. Under a
given `onUnhandled` policy every other surface agrees too: same `status`,
same `last_transition_ok`, and the same `on_unhandled_event` disposition
(`"ignored"`). A caller cannot tell "this event does not apply in this
state" from "a business rule refused it".

This was filed at High on three claims — that the outcome is silent at the
call site, surfaces one event late, and absorbs guard *errors*. Our own
adversarial re-run refutes all three: `onUnhandled: "error"` flips `status`
to `"error"` inside the same macrostep, so the discriminator is present at
the instant the receipt is read; `Receipt.deferred` separates the defer case
(#84); and a guard that *raises* under `guardErrorPolicy: "raise"` does put
the exception on the receipt. What remains is a genuine two-way ambiguity
that is also upstream-aligned, filed here at **Low** as an enhancement.

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
"""R5-11 repro: a real no-op and a guard-DENIED event are indistinguishable.

Under one `onUnhandled` policy, `send(..., wait=True)` returns a byte-identical
`Receipt(changed=False, error=None, deferred=False)` for (a) an event the state
does not declare and (b) an event it DOES declare whose only guard returned
False -- with identical `status`, `last_transition_ok`, and
`on_unhandled_event` disposition. Two other cases ARE separable and are printed
as controls: `onUnhandled:"error"` flips `status`, `"defer"` sets
`Receipt.deferred`.

Exits 1 while present, 0 once fixed. Stdlib + xstate_statemachine only.
"""

import asyncio
import logging
import sys

from xstate_statemachine import Interpreter, MachineLogic, create_machine


class Hook:
    """Records on_unhandled_event without depending on hook arity."""

    def __init__(self):
        self.seen = []

    def __getattr__(self, name):
        def f(*a, **k):
            if name == "on_unhandled_event":
                self.seen.append(a[-1] if len(a) > 2 else None)
        return f


def cfg(policy, guarded):
    on = {"GO": ({"target": "b", "guard": "deny"} if guarded else "b")}
    return {
        "id": "m", "initial": "a",
        "actionErrorPolicy": "rollback", "guardErrorPolicy": "raise",
        "onUnhandled": policy, "strictTargets": True, "strict": False,
        "spawnBlockingTimeout": 5.0,
        "states": {"a": {"on": on}, "b": {}},
    }

async def probe(policy, guarded, event):
    m = create_machine(cfg(policy, guarded),
                       logic=MachineLogic(guards={"deny": lambda c, e: False}))
    i = Interpreter(m)
    h = Hook()
    i.use(h)
    await i.start()
    r = await i.send(event, wait=True)
    # The hook's event TYPE is deliberately excluded -- the caller already
    # knows which event it sent. Only the DISPOSITION is a signal.
    out = (r.changed, repr(r.error), r.deferred, i.status,
           i.last_transition_ok, h.seen)
    await i.stop()
    return out


async def main() -> int:
    noop = await probe("ignore", False, "NOPE")
    denied = await probe("ignore", True, "GO")
    errored = await probe("error", False, "NOPE")
    deferred = await probe("defer", False, "NOPE")

    def show(label, t):
        print("  %-22s changed=%s error=%s deferred=%s status=%s last_ok=%s "
              "hook=%s" % (label, t[0], t[1], t[2], t[3], t[4], t[5]))

    print("OBSERVED:")
    show("real no-op", noop)
    show("guard-denied", denied)
    show("unhandled (control)", errored)
    show("deferred (control)", deferred)
    print("EXPECTED:")
    print("  a guard-denied event is distinguishable from an event the state")
    print("  never declared -- via the receipt, `last_transition_ok`, or an")
    print("  `on_unhandled_event` disposition such as 'guard_denied'.")
    if noop == denied:
        print("RESULT: FAIL - no-op and guard-denied are identical on every "
              "surface")
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
  real no-op             changed=False error=None deferred=False status=running last_ok=True hook=['ignored']
  guard-denied           changed=False error=None deferred=False status=running last_ok=True hook=['ignored']
  unhandled (control)    changed=False error=None deferred=False status=error last_ok=True hook=['errored']
  deferred (control)     changed=False error=None deferred=True status=running last_ok=True hook=['deferred']
EXPECTED:
  a guard-denied event is distinguishable from an event the state
  never declared -- via the receipt, `last_transition_ok`, or an
  `on_unhandled_event` disposition such as 'guard_denied'.
RESULT: FAIL - no-op and guard-denied are identical on every surface
```

Exit status `1`.

The two control rows are the part that works and is worth keeping in the
test: `status` separates the `"error"` policy *inside the same expression*
as the receipt read, and `Receipt.deferred` (#84) separates the `"defer"`
policy. The first two rows are identical in all six fields.

## Expected behaviour

The library ships `on_unhandled_event(interpreter, event, active_state_ids,
disposition)` specifically as the out-of-band channel for "this event did not
cause a transition, and here is why". `docs/api/index.md:1865` enumerates the
vocabulary:

> `disposition` is `"ignored"`, `"deferred"`, `"errored"`, or `"dropped"`.

and `docs/_guide/plugins.md:319-321`:

> Fires when an event matches no transition in any active state, regardless
> of `onUnhandled` policy.

The vocabulary encodes the *policy applied*, not the *reason no transition
was selected*. Those are different questions, and the second one is the one a
caller cannot answer today. A guard that returns `False` is a decision made
by user logic that the engine observed directly — the engine knows a
candidate was found and evaluated, and that information is discarded before
anything a caller can read.

XState v5 has the same coarse behaviour, and that is the reason this is Low
rather than Medium: there, a transition whose guard is false is by definition
unselected, and the event is unhandled with no upstream discriminator. So
this is an enhancement over the reference implementation, not a divergence
from it. It is worth doing here because this library already went beyond
XState by adding `onUnhandled` policies, `Receipt.deferred` and the
`disposition` argument — the surface exists and is one value short.

Concretely, expected: something distinguishes the two cases without the
caller having to re-derive the machine's structure. Either a new disposition
(`"guard_denied"`), or a receipt field, or both.

## Root cause analysis

The information is available and is dropped at a well-defined point.

`_select_transitions` (`base_interpreter.py:4083`) calls
`_collect_eligible_transitions` per leaf, whose local `_passes()`
(`:3985-4004`) evaluates each candidate's guard and keeps only the satisfied
ones. A candidate that was *found for this event but failed its guard* is
simply not appended to `eligible`. By the time the method returns, a
guard-denied event and an undeclared event are represented identically: an
empty list.

`_process_event` (`base_interpreter.py:2013-2026`) then cannot tell them
apart either:

```python
transitions = self._select_transitions(event)
if not transitions:
    self._handle_unhandled_event(event)
    return
```

`_handle_unhandled_event` (`:3608-3660`) branches purely on
`self.machine.on_unhandled` and reports the *policy* it applied:

```python
if policy == "error":
    err = UnhandledEventError(event.type, active)
    self._notify_unhandled(event, active, "errored")
    self._fail(err)
    return

if policy == "defer":
    ...
    self._notify_unhandled(event, active, disposition)   # "deferred"
    return

logger.debug("🍃 No transition found for event '%s'.", event.type)
self._notify_unhandled(event, active, "ignored")
```

The receipt is resolved from the macrostep's outcome (`changed` is derived
from whether the configuration moved), so it inherits the same blindness.
`last_transition_ok` stays `True` in both cases, correctly — nothing failed;
its docstring scopes it to per-step failures reportable without a receipt,
and neither of these is a failure.

So the fix point is narrow: `_collect_eligible_transitions` is the only place
that knows a candidate existed and was denied, and nothing carries that fact
forward.

## Impact

**General users.** A caller that wants to react differently to "not
applicable here" and "refused by a rule" — a UI disabling a button versus
showing a reason, an API returning 404 versus 409, a retry loop deciding
whether to back off — must re-derive the machine's structure at the call
site, or add a side-channel action on the guarded transition, or change the
guard into an `always` on the target. All three duplicate logic the engine
already has. The impact is bounded because the caller does know which event
it sent, so in a machine where a given event type is guarded in exactly one
state the ambiguity is resolvable by hand; it stops being resolvable when the
same event is handled in several states with different guards, or when the
caller is generic (a replay driver, a gateway).

**Order-management scenario (our adoption audit, #26).** Our order gateway
forwards operator commands to the order's machine and reports the outcome.
`CANCEL` on an order in `filled` is *not applicable*; `CANCEL` on an order in
`submitting` whose `cancellable` guard denies (exchange cancel window
closed) is *refused*. Both come back as `Receipt(changed=False, error=None)`,
so the operator sees the same "no effect" either way — and the correct
follow-up differs (nothing to do, versus escalate to a manual exchange-side
cancel). Our catalogue rule CV-C06 already forbids gating on
`changed=False, error=None` and requires an explicit acknowledgement event
per outcome, so no shipped machine depends on the distinction; that
workaround is the reason this is Low for us, and it costs an extra state and
an extra event per decision point.

## Proposed fix

**Add a `"guard_denied"` disposition, and carry the reason from selection to
reporting.**

1. Have `_collect_eligible_transitions` (`base_interpreter.py:3959`) record
   that at least one candidate matched the event type and was rejected by its
   guard — a boolean out-parameter, or a small result object alongside the
   eligible list. `_passes()` (`:3985`) already computes exactly this; it
   just needs to report it. Keep the `guard_cache` memoisation semantics
   unchanged so per-region evaluation counts do not move.
2. Thread that flag through `_select_transitions` (`:4083`) to
   `_process_event` (`:2013`) and into `_handle_unhandled_event`.
3. In `_handle_unhandled_event`, report `"guard_denied"` instead of
   `"ignored"` when the flag is set and the policy is `"ignore"`. For the
   other policies the *policy* value remains primary (`"errored"`,
   `"deferred"`), since those describe what was done with the event; consider
   passing the reason as an additional keyword so both are available.
4. Optionally surface it on the receipt as well — e.g. a
   `Receipt.disposition` field mirroring the hook's value. This is the part
   that actually helps a `wait=True` caller, since the hook is out of band.
   It also subsumes `Receipt.deferred` (#84), which could become a property
   over `disposition` for compatibility.

**Documentation regardless of the code change.** `docs/api/index.md:1865`
and `docs/_guide/plugins.md:319` should state explicitly that `"ignored"`
covers both "no candidate matched the event type" and "a candidate matched
but its guard returned `False`", so a reader is not misled into thinking the
vocabulary is finer-grained than it is. If (4) is not taken, the receipt
documentation should say the same about `changed=False, error=None`.

**Compatibility.** Adding a disposition value is a widening of a documented
enum — a plugin that switches on it and has no `else` would newly miss the
`"guard_denied"` case, so it belongs in a minor release with a changelog
note; gating it behind a machine-config or interpreter flag for one release
is an option if that is a concern. Adding `Receipt.disposition` is additive.
Nothing about the existing `"ignored"` path changes for callers that do not
look at the new value.

## Acceptance criteria

- [ ] `repro/R5-11_receipt-noop-vs-guard-denied.py` exits `0`.
- [ ] `tests/test_round5_findings.py::test_guard_denied_is_distinguishable_from_undeclared_event`
      — the two cases differ on at least one caller-visible surface.
- [ ] `tests/test_round5_findings.py::test_unhandled_dispositions_matrix`
      — a four-way table (real no-op / guard-denied / unhandled under
      `"error"` / deferred under `"defer"`) asserting all four are
      pairwise distinguishable from `(receipt, status, disposition)`.
- [ ] `tests/test_round5_findings.py::test_guard_denied_with_multiple_candidates_reports_denied_only_when_all_denied`
      — a guarded candidate plus an unguarded fallback transitions
      normally and reports no unhandled disposition at all.
- [ ] `tests/test_round5_findings.py::test_receipt_deferred_still_true_for_defer_policy`
      — pins #84 if `Receipt.deferred` becomes a property over
      `disposition`.
- [ ] Parity: the same table runs green on `SyncInterpreter`.
- [ ] `docs/api/index.md` and `docs/_guide/plugins.md` document the new
      disposition value, or — if the code change is declined — document
      that `"ignored"` conflates the two causes.

## Related

- **Round-4 issues:** #84 (`Receipt.deferred`, which separates the defer
  case and is the precedent for putting a disposition on the receipt),
  #79 (provenance-based exemption in `_handle_unhandled_event`, the method
  this touches), #35 (`guardErrorPolicy` / `on_guard_error` — the analogous
  problem for a guard that *raises*, which was solved by adding a dedicated
  hook; the same shape of fix applies here for a guard that *denies*).
- **R5-10** (Low) — the other surviving observability residue this round:
  under `guardErrorPolicy: "raise"`, an engine-driven transition's remaining
  candidates are cancelled and the event never reaches
  `_handle_unhandled_event` at all. Fixing R5-10's item 3 (route
  engine-driven guard failures through the unhandled policy) and this
  issue's item 3 touch the same method and should be done together.
- **Register source ids:** R5-11 ← `LIB-01`, `L-02`, `C-03b` (library half),
  `D-observability-2`.
- **Evidence:** `triage-r5/t3_receipts.py`, `triage-r5/t3c_four.py` (as
  filed); `35-r5-11-refutation.md` (the adversarial re-run that downgraded
  this from High to Low and refuted the silence/one-event-late/guard-error
  claims); `33-r5-findings-register.md` §2/§3 R5-11.

## Verification

- Date: 2026-09-19
- Python: CPython 3.13.7
- Commit: `3ed3099`
- Re-ran `repro/R5-11_receipt-noop-vs-guard-denied.py` fresh: exit `1`,
  output unchanged — real no-op and guard-denied rows identical on all six
  fields; the `"error"`/`"defer"` controls remain distinguishable as
  described.
- Root-cause citations checked against source: `_handle_unhandled_event`
  (`base_interpreter.py:3608`) branches only on `self.machine.on_unhandled`
  and reports the applied policy (`"errored"`, `"deferred"`, `"ignored"`) via
  `_notify_unhandled`, with no path carrying forward "a candidate existed but
  its guard denied it" — matches the finding.
- Duplicate check: `gh issue list --search "guard_denied unhandled"` and
  related terms return no matching issue; #35 (guard raise visibility, a
  different failure mode, already cited under Related) is the nearest
  neighbor. No duplicate found.
- Self-contained, no project-name/label leak: confirmed.
