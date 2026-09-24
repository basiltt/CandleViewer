# R6-10 adversarial refutation — `Receipt.denied` conflation + defer shadowing

**Verdict: DOWNGRADE High → Medium.** Both halves reproduce at `cec108b`, but
neither loses information: the discriminating data is present on the same
`Receipt`. What is actually broken is documentation precision and the
single-valued plugin disposition, not the caller's ability to tell the cases
apart.

## Repro (re-run, usage corrected)

Original `f5b` had two harness bugs of my own making: `logic_modules=[<class>]`
(must be a module path/object — corrected to `logic=MachineLogic(guards=...)`)
and a sync `send()` without `wait=True` (the sync engine returns `None` unless
`wait=True`, so `denied` read as `None`). Corrected and re-run.

Isolated 2-state machine, single `E` candidate, `guardErrorPolicy:"raise"`
(`repro/f5b_sync_parity.py`, `repro/f5c_async_disposition.py`):

| guard | receipt.denied | receipt.error | disposition hook |
|---|---|---|---|
| returns `False` | `True` | `None` | `"guard_denied"` |
| **raises** | `True` | `RuntimeError` | *(none — pass aborts)* |
| undeclared event | `False` | `None` | `"ignored"` |

Identical on `Interpreter` and `SyncInterpreter`. Catalogue B8 confirms the
same (`f5_denied_conflation.json`); B8 declares exactly one `TIGHTEN_SL`
candidate, so the `denied=True` in the raising row cannot be a sibling
candidate legitimately returning `False` — it is the crashed guard.

## Why this is not High

**1. The two cases #153 exists to separate are NOT re-merged.** #153's stated
contract is *declared-but-refused* vs *undeclared*. That separation is intact:
undeclared still yields `denied=False`. The crash is a **third** case that
#153 never enumerated, mislabelled into the denial bucket.

**2. The information is not lost.** `Receipt.error` is a first-class,
documented field that carries exactly this exception, on the same object, in
the same read. `(denied, error is None)` is a total discriminator over all
three cases. The claim concedes this ("works but is undocumented"). A caller
reaching a wrong conclusion must read `denied` *while ignoring a non-`None`
`error`* — and the docs already instruct precedence-checking of the companion
flags (`deferred`: "Check this before reading `changed`").

**3. The plugin channel is clean.** A crashed guard under `raise` fires **no**
`on_unhandled_event` at all — the selection pass re-raises before
`_handle_unhandled_event` runs. So `disposition == "guard_denied"` is a sound,
un-conflated signal. Only the `Receipt` boolean is imprecise.

**4. Real defect, but it is a doc/wording deviation.** `docs/api/index.md:1222`
and `interpreters.md:510` say denial means every guard *"returned `False`"*;
the code sets the flag from `_guard_denied_this_step`, which
`_is_guard_satisfied` also reaches via the `policy == "raise"` path
(`base_interpreter.py:4834` returns `False`). Fix is one condition or one
sentence.

## The defer half is weaker still

`f7_disposition_precedence.json`: under `onUnhandled:"defer"` the disposition
is `"deferred"`, but the **receipt still reports `denied=True` alongside
`deferred=True`**. The denial is *not* shadowed where the caller reads it; only
the single-valued plugin string picks one label, as it must.

`f6_denied_defer_buffer.json` reproduces the replay (3 denials → `deferred_count=3`
→ guard flips → `set_trading_stop` 0 → 3). But this is `defer` doing its
documented job: `onUnhandled` is defined over "an event selects no transition",
which a guard-denied event does, and defer is documented as holding an event
"until the machine can handle it". Selecting `"defer"` machine-wide on a chart
whose guards refuse for *business* reasons is a configuration choice with a
documented consequence — a guard denial is not a deferrable "not yet", and the
catalogue should scope `defer` to the order path rather than the root. That is
our config to fix, not a library defect.

**XState v5 is silent here** — it has no `Receipt` and no `onUnhandled`, so it
grants no authority to either reading.

## Residual (the Medium)

1. `denied` should be `False` when the candidate's guard raised; or the two doc
   sites should state that `denied` covers "no candidate passed" and that
   `error is not None` distinguishes a crash.
2. `defer` + guard denial deserves an explicit warning in
   `interpreters.md` §Unhandled Events: denied events enter the buffer and are
   re-evaluated later against a different world.

Neither blocks adoption: `(denied, error is None)` is available today, and the
defer interaction is avoidable in our own chart configuration.
