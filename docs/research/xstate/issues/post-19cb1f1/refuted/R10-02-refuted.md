# R10-02 — "Self-targeting `onDone` never re-arms the invoke" — **REFUTED**

Commit 19cb1f1. Severity as filed: High. **Verdict: REFUTED (API misuse; documented, XState-v5-aligned semantics).** Residual: an Info-level diagnostic gap, filed separately below.

## Reproduction (the behaviour is real)
`battle-19cb1f1/concurrency/t4_self_target_ondone_never_rearms.py` re-runs FAIL at 19cb1f1:
`SELF` (async/def, async/async def, sync/def) → `entries=1, submits=1, state=[m.work], dormant=True, last_error=None, hook_stranded=[]`, while `HOP` → `entries=submits=11`, `RunawayChainError`.

## Why it is not a defect
1. **`onDone: {target: "work"}` from inside `work` is an *internal* transition by contract**, not an external one. `base_interpreter.py:3021-3028`: `if target_state == transition.source and not transition.reenter: → _execute_internal_transition()` — no exit, no re-entry, therefore (correctly) no new `statesToInvoke` record and nothing for `_arm_pending_invokes` to arm. The report's SCXML §3.12 premise ("a targeted transition exits and re-enters its source") describes SCXML's *external* transition; SCXML equally defines `type="internal"`, and **XState v5 makes internal the default for a self-transition** — `reenter: true` is the opt-in to external. This library follows XState v5, not raw SCXML defaults, and says so.
2. **It is documented, three times.** `docs/_guide/pythonic-api.md` L576-599 ("By default, a self-transition (same source and target) is treated as internal — no exit/entry actions fire. Use `reenter=True`…"); `docs/api/index.md` L260; `docs/_guide/troubleshooting.md` L284-289 names this exact wedge shape and its three fixes. CHANGELOG 0.4.2 (L1913-1921) is the behaviour-change entry.
3. **Correct usage behaves exactly as the report demands.** `C:/Users/basil/r10_02/t4r_reenter_refutation.py` (standalone, neutral cwd `C:/Users/basil`, both service kinds, both engines, polled to convergence — stable submit count over 6×0.1 s reads, converging at 0.7 s, not sampled): with `"reenter": True` all live lanes give `entries=submits=22 == maxIterations+2`, `last_error=RunawayChainError`, `on_invocation_stranded` fired `[["m.work","spin"]]` — identical to `HOP` plus the #207 stranding report. Without `reenter`, all lanes give exactly `submits=1`. Zero violations. (sync + `async def` = documented `NotSupportedError`.)

## The "silent / indistinguishable" half also fails
`has_dormant_invocations == True` in the plain-`SELF` rows — that *is* the documented liveness answer (`base_interpreter.py:1641-1643`: "`True` exactly while work the configuration relies on is parked"), and `pending_invocations()` names the invoke. Nothing was cut, so `on_invocation_stranded` / `RunawayChainError.stranded` correctly stay silent: no chain budget tripped, so there is no cut to report. Absence of `last_error` is right — no error occurred.
Note the probe's own oracle is miscalibrated: it treats `dormant and not hook_stranded` as a violation, but #207 scopes the hook to budget-cut stranding by design (`_stranded_by_cut`, :1921), which the report itself quotes.

## Residual (new, Info) — validator asymmetry
`validation.py:205` warns on an `always` self-target that cannot progress, but no equivalent warning exists for an `onDone`/`on` self-target whose intent is plainly a restart loop. A build-time hint would have converted this whole report into a one-line warning. Non-blocking; no constraint needed beyond the existing usage rule.

## Adoption impact
No change to the 54-… verdict. Fold into usage guidance, not constraints: **any self-targeting transition intended to restart a state's `invoke`/`entry` must carry `"reenter": true`.**
