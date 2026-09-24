# 14 — Re-evaluating semantics probes on xstate-statemachine 0.8.0

Source of truth: `_ref/xstate-statemachine` CHANGELOG.md `[0.8.0] - 2026-09-17
— Fortify` section, and a fresh run of `probes/p01_core_transitions.py`,
`probes/p02_invoke_timers_history.py`, `probes/p03_context_snapshot_determinism.py`
against the 0.8.0 install (commit 9bf6065).

## Trigger

`gate/run_gate.py` flagged probe **A18** (`01_core_transitions`) as a
regression: it passed on the recorded 0.7.0 baseline and now fails on 0.8.0.
The same run showed **C10** and **C16** (`03_context_snapshot_determinism`)
newly passing, which is only a baseline update, not a concern.

## Verdict on A18 (the regression alarm)

**Not a true regression — the probe encoded the OLD (silently-wrong) 0.7.x
behaviour, and 0.8.0's default configuration correctly rejects it at build
time.**

A18 config:

```python
cfg = {
    "id": "m",
    "initial": "A",
    "states": {
        "A": {
            "initial": "A1",
            "on": {"GO": {"target": ".does_not_exist"}},
            "states": {"A1": {}, "A2": {}},
        }
    },
}
```

`.does_not_exist` is a relative `.child` target that does not exist anywhere
in the tree. The probe's recorded expectation was that this is **silently
ignored**: no error, no transition, machine stays in `m.A.A1`.

0.8.0 adds **build-time target validation** (CHANGELOG `Added`, #29/#30):

> `create_machine()` now walks the finished tree and rejects, in one
> message, every transition target that does not resolve... `strict_targets`
> defaults to `True`.

This is one of the two behaviours explicitly called out under `### Changed`
as a **deliberate exception** to "every new behaviour preserves 0.7.x
semantics by default" — the changelog intro says so directly: "Every new
behaviour is a per-machine policy or an additive API whose default preserves
0.7.x semantics, **with two deliberate exceptions called out under
Changed**." Unresolvable transition targets are exactly the class of defect
`strict_targets` was built to catch (tracking issue: silent failure by
default), and A18's config is a textbook unresolvable target — it's the
*mechanism* strict-targets validation exists to close, not a corner case that
slipped through.

Running with the escape hatch confirms the diagnosis restores the exact 0.7.x
observed behavior:

```python
create_machine(cfg, logic=MachineLogic(), strict_targets=False)
```

reproduces the 0.7.x silent-ignore behavior (with a one-shot
`DeprecationWarning`), while the default (`strict_targets` unset / `True`)
now raises `InvalidConfigError` at `create_machine()` time, before an
interpreter is ever constructed — hence the probe's `boot()` call raises
before `i.send("GO")` is reached.

**Action:** A18 moves from "passing baseline" to "expected new failure" in
`PROBE_BASELINE_FAILURES`. This is a fixed defect surfaced by the probe
harness testing the *old* semantics, not new library breakage.

## Full per-probe reconciliation

### `01_core_transitions`

| id | 0.7.0 | 0.8.0 | verdict | explanation |
|----|-------|-------|---------|-------------|
| A1 | PASS | PASS | unchanged | — |
| A2 | PASS | PASS | unchanged | — |
| A3 | FAIL | FAIL | unchanged, open defect | Self-transition with explicit target and no `reenter` still treated as internal (no exit/entry). Not touched by 0.8.0. |
| A4 | PASS | PASS | unchanged | — |
| A5 | FAIL (0.7.0 baseline) | **PASS** | **fixed** | `.child` relative target now resolves into the source's own descendants (matching XState v5), per CHANGELOG `Fixed`: "`.child` targets resolve into the **source's** descendants... 0.7.x sibling reading kept as fallback (#31)." Baseline updated: A5 removed from failure list. |
| A6 | FAIL | FAIL | unchanged, open defect | Guard side-effect leakage (later guards still evaluated after a match) not addressed in 0.8.0. |
| A7 | PASS | PASS | unchanged | — |
| A8 | PASS | PASS | unchanged | — |
| A9 | PASS | PASS | unchanged | — |
| A10 | ERROR (baseline failure) | ERROR | unchanged, open item — now caught earlier | Non-progressing `always` self-target now raises `InvalidConfigError` at `create_machine()` (build-time validation, #29/#30) instead of behaving badly at runtime. Still counted as a baseline failure (probe expects the loop-until-guard-flips runtime behavior, which the library no longer permits by default); the *nature* of the failure changed from a runtime issue to a fail-fast build-time rejection, which is the intended improvement, but the probe's literal expectation is still unmet so it stays in the baseline. |
| A11–A14 | PASS | PASS | unchanged | — |
| A15 | PASS | PASS | unchanged | — |
| A16 | PASS | PASS | unchanged | — |
| A17 | PASS | PASS | unchanged | — |
| A18 | PASS (0.7.0 baseline, i.e. not in failure list) | **ERROR** | **deliberate behaviour change, not a regression** | See analysis above: `strict_targets` (default `True`) now rejects the unresolvable `.child` target at build time. Probe encoded 0.7.x silent-ignore semantics. Added to 0.8.0 baseline. |
| A19 | PASS | PASS | unchanged | — |
| A20 | PASS | PASS | unchanged | — |

0.8.0 result: **16/20 PASS** (A3, A6, A10, A18 fail/error).

### `02_invoke_timers_history`

| id | 0.7.0 | 0.8.0 | verdict |
|----|-------|-------|---------|
| B1–B14 | all PASS | all PASS | unchanged |

0.8.0 result: **14/14 PASS**. No baseline changes.

### `03_context_snapshot_determinism`

| id | 0.7.0 | 0.8.0 | verdict | explanation |
|----|-------|-------|---------|-------------|
| C1–C5 | PASS | PASS | unchanged | — |
| C6 | FAIL (baseline) | FAIL | unchanged, open defect | Restoring a snapshot taken mid-`after` still does not resume the delayed transition (`fired: false`). Not in scope of 0.8.0's `restart_services=True` (that path is for `invoke`, not `after` timers). |
| C7 | FAIL (baseline) | FAIL | unchanged, open defect (opt-in fix exists) | Restoring a snapshot taken mid-invoke still does not re-run the service by *default* (`calls: 0`). 0.8.0 adds `from_snapshot(restart_services=True)` and `pending_invocations()` (#44) as an **opt-in** API — CHANGELOG: "restoring a snapshot is still a static rebuild that starts nothing by default." The probe exercises the default, so it correctly still fails; this is "fixed but opt-in," matching the task's framing, not a defect regression. Stays in baseline. |
| C8, C9 | PASS | PASS | unchanged | — |
| C10 | FAIL (baseline) | **PASS** | **fixed** | The SCXML-correct internal event queue (#36, CHANGELOG `Added`/wave 3) makes a zero-delay `raise` to self drain via a dedicated internal queue before the next external event, giving trace order `['entry', 'RAISED', 'EXTERNAL']` — exactly what C10 expects. Baseline updated: C10 removed. |
| C11, C12, C13, C14 | PASS | PASS | unchanged | — |
| C15 | FAIL (baseline) | FAIL | unchanged, open item — now fails earlier/louder | Unknown target state name (`"nowhere_at_all"`, not a relative `.child` target) is now rejected at `create_machine()` via the general unresolvable-target validator (same `strict_targets` mechanism as A18), rather than failing at `send()` time or silently. The probe expects the string `"raised-at-some-point"` (any raise, create-time or send-time, would satisfy it) but the harness compares the *returned label* which is `create_machine:InvalidConfigError`, not the literal string `"raised-at-some-point"` — so the exact-match harness still records FAIL even though the underlying behavior ("fails loud") is exactly what the probe title asks for. This is arguably a probe-expectation format issue (the probe should accept any `"<phase>:<ExceptionName>"` string), not a library defect. Kept as an open baseline failure since the probe's strict-equality expectation is unmet, but noted here as effectively resolved in substance. |
| C16 | FAIL (baseline) | **PASS** | **fixed** | `sendTo` can now address an invoke by explicit `id` and by `systemId` (#40, CHANGELOG `Added`). Baseline updated: C16 removed. |
| C17 | FAIL (baseline) | FAIL | unchanged, open defect (opt-in fix exists) | Events arriving during a transient/invoking state are still dropped by default. 0.8.0's bounded inbox / `onUnhandled: "defer"` / internal queue changes are all opt-in policies; `onUnhandled` defaults to `"ignore"` (CHANGELOG: "default (`ignore`) ... " preserves 0.7.x). The probe exercises defaults, so it still observes the drop. Fixed but opt-in — stays in baseline. |

0.8.0 result: **13/17 PASS** (C6, C7, C15, C17 fail).

## Summary of `PROBE_BASELINE_FAILURES` changes (0.7.0 → 0.8.0)

```
01_core_transitions:              ["A3","A5","A6","A10"]  -> ["A3","A6","A10","A18"]
02_invoke_timers_history:         []                        -> [] (unchanged)
03_context_snapshot_determinism:  ["C6","C7","C10","C15","C16","C17"]
                                                             -> ["C6","C7","C15","C17"]
```

- **Removed** (legitimate fixes, verified against CHANGELOG + source
  behaviour): `A5` (#31 `.child`-target fix), `C10` (#36 internal event
  queue), `C16` (#40 `sendTo` by id/systemId).
- **Added**: `A18` — deliberate `strict_targets` default-on behaviour change
  (CHANGELOG `Changed`/build-time validation), not a regression; the probe
  encoded pre-0.8.0 silent-ignore semantics that the library no longer
  permits by default.
- **Unchanged, still open**: `A3`, `A6`, `A10`, `C6`, `C7`, `C15`, `C17` — all
  still fail on 0.8.0 for the same underlying reasons as 0.7.0 (`C7`/`C17`
  have opt-in fixes available — `restart_services=True` and a non-default
  `onUnhandled`/inbox policy respectively — but the probes intentionally
  exercise defaults).

`run_gate.py` `PROBE_BASELINE_FAILURES` has been updated to the 0.8.0
baseline above; the original 0.7.0 baseline is preserved as
`PROBE_BASELINE_FAILURES_0_7_0` for historical reference / re-runs against a
0.7.0 install.
