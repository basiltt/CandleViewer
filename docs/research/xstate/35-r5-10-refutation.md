# R5-10 adversarial refutation — DOWNGRADE High → Low

Library: `_ref/xstate-statemachine` @ `3ed3099` (unreleased 0.8.1). Repro: `triage-r5/t4_final.py::LD01`.
Corrected repro: `/tmp/ld01_fixed.py` (A–D below), run on the same commit.

## 1. The filed repro reproduces verbatim

`ids=['ld.v']`, `status='running'`, `interpreter.error=None`, `last_transition_ok=False`,
`last_error=RuntimeError('guardboom')`, `pending_invocations()=[PendingInvocation('ld.v','ver','svc')]`,
hooks fired: `on_guard_error` only. Confirmed.

## 2. Usage defects in the filed repro

- **Mandatory config block absent.** The repro sets only `guardErrorPolicy`; the five other
  normative keys (`actionErrorPolicy`, `onUnhandled`, `strictTargets`, `strict`,
  `spawnBlockingTimeout`) are missing (`28-statechart-catalogue.md` §1.3b).
- **The "further send returns changed=False" evidence is an artefact of the repro.** `'ANY'` is
  not declared anywhere in that machine, so `changed=False` proves nothing about stranding.
  With the full block and `ANY` declared (**A**), `send('ANY', wait=True)` returns
  `changed=True` and the machine moves `ld.v → ld.done`. **The region is not wedged; the
  interpreter is fully responsive.** That half of the claim is refuted.
- **The health check used `status`.** `docs/_guide/snapshots.md` §"status is not a liveness
  signal" and `interpreters.md` L223 both state explicitly that `status` is *not* a liveness
  signal and that `has_dormant_invocations` (0.8.1) is the signal to use. In (**A**)
  `has_dormant_invocations is True`. **"Reports healthy" is false against the documented
  health signal.**

## 3. Documented behaviour

`docs/_guide/guards.md` §"Error Handling in Guards" documents `guardErrorPolicy: "raise"` as:
*"the exception propagates … in the async `Interpreter` the run loop contains it and stays
alive. Either way the machine is left in its pre-event state and remains usable."* That is
exactly the observed outcome, including `interpreter.error is None` (a contained run-loop
exception is not a machine-level failure). The same section and `plugins.md` L312 document
`on_guard_error` as firing under **every** policy, *precisely because* a raising guard was
otherwise indistinguishable from `False` (CHANGELOG #35). `last_transition_ok`/`last_error`
are documented (`json-config.md` L110, `testing-and-pure-api.md` L187) as the
**fire-and-forget** surface for callers that have no receipt. So the claim "no receipt and no
error surface" is wrong on its second half: the engine-driven path lands on exactly the surface
the library designates for callerless failures — plus `logger.exception`.

## 4. `pending_invocations()` — claim is inverted

(**D**) A genuinely live 5 s service reports `pending_invocations() == []`,
`has_dormant_invocations == False`. The dead strand reports non-empty. So the signal **does**
separate live from strand, in the direction that matters for an OMS (strand → non-empty →
alarm). The documented contract (`api/index.md` L714) is "invokes in the active configuration
with NO live service" — after the service completed and its `onDone` was refused, that is
literally true. The residual complaint is only that it does not *label* the two dormant causes
(restored vs guard-crashed) and carries no timestamp — an ergonomics gap, not a false health
report. The former LD-02 does not survive as a High.

## 5. What does survive

(**B**) Under `guardErrorPolicy: "raise"`, a raising guard on an `invoke.onDone` **also
suppresses lower-priority candidates in the same array** — an unguarded fallback branch is not
taken and the completion event is consumed with no retry (`ids=['ld2.v']`).
(**C**) The same machine under the default `"false"` takes the fallback (`ids=['ld3.fallback']`).
This is the implicit consequence of "the exception propagates", and is unsurprising, but the
guards doc never spells out that `raise` also cancels the rest of the candidate list, and the
engine-driven case has no retry. Real, reproducible, **Low**: fully observable
(`on_guard_error` + `last_error` + `has_dormant_invocations` + log), non-wedging, and avoidable
by CandleViewer rule — an `invoke.onDone/onError` branch must not carry a fallible guard; put
the check in an `always` on the committed state.

## Verdict

**DOWNGRADE to Low.** "Silently" and "reporting healthy" are both refuted by documented,
implemented signals the repro did not query; the region is not stranded to events. Residue is
the undocumented candidate-list cancellation under `raise` on engine-driven transitions, plus
the unlabelled/untimestamped `PendingInvocation`.
