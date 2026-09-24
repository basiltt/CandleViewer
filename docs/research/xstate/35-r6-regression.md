# Round-6 Regression Sweep — main@cec108b

**Scope:** gate script (`gate/run_gate.py`) + all standalone regression/repro scripts under
`issues/verify-0.8.0/`, `issues/verify-main-5327ba6/`, `issues/verify-main-3c527b0/`,
`issues/verify-main-5e07ba8/`, `issues/verify-main-3ed3099/`, `issues/verify-main-cec108b/`,
`issues/new-0.8.0/repro/`, `issues/new-main/repro/`, `issues/post-5e07ba8/new/repro/`,
`issues/post-3ed3099/new/repro/`, and `probes/*.py` + `probes/main-*/*.py`
(excluding `refute/`, `__pycache__`). 238 standalone scripts + gate's 89 checks.

**Commit under test:** `cec108b` (unreleased 0.8.1; `__version__` still reports `0.8.0`).
**Comparison baselines:** prior gate snapshot `gate/result-main-5e07ba8.json` (last full green-ish
snapshot before this round) and `gate/result-main-3ed3099.json` (immediately preceding commit in
this chain, closer baseline — used to separate *new* regressions from *already-reopened* items).

## 1. Gate script result

```
verify : 29/34 pass   (PRIMARY, blocking)
verifyM: 10/15 pass   (PRIMARY, blocking)
verifyM2: 3/3 pass    (PRIMARY, blocking)
repro  : 13/34 pass   (SECONDARY, informational)
probe  : 1/3 pass
totals : FAIL=33 PASS=56
```
Raw output: `gate/result-main-cec108b.json`.

## 2. Delta vs prior gate snapshot (5e07ba8) — PASS→FAIL

| kind | id | 5e07ba8 | cec108b | 3ed3099 (closer baseline) | Classification |
|---|---|---|---|---|---|
| verify | LC-01 | PASS | FAIL | PASS | **TRUE REGRESSION** |
| verify | LC-12 | PASS | FAIL | FAIL | already reopened at 3ed3099 — not new this round |
| verify | LC-26 | PASS | FAIL | PASS | **TRUE REGRESSION** |
| verify | LC-48 | PASS | FAIL | FAIL | already reopened at 3ed3099 — not new this round |
| verifyM | LC-01 | PASS | FAIL | PASS | **TRUE REGRESSION** |
| verifyM | N-1 | PASS | FAIL | PASS | **TRUE REGRESSION** |
| repro | LC-26 | PASS | FAIL | (n/a, repro not compared) | superseded-behaviour, secondary/informational only |

verify LC-57 and probes PROBE-01/PROBE-03 are FAIL at both 5e07ba8 and cec108b (and 3ed3099) —
unchanged, not regressions this round.

## 3. Repro replication (5x each) — the 4 true regressions

All reran 5/5 identical (deterministic, not flaky):

| id | outcome | detail |
|---|---|---|
| LC-01 (verify + verifyM) | FAIL 5/5 | CHANGELOG's "`fail` policy → status `stopped`, config cleared" claim is not what's observed: action raises `RuntimeError` under `fail` policy, transition rolls back correctly (state, trace, `last_transition_ok=False` all match expected), **but** the interpreter ends `status='stopped'` with `error=TransitionFailedError(cause=RuntimeError)` instead of the CHANGELOG-documented `status='error'`. Same root cause surfaces in both the 0.8.0-era and 5327ba6-era scripts (`3-fail-stops-with-retrievable-error` sub-case), so this is one defect counted once. |
| LC-26 | FAIL 5/5 | `AfterEvent` now carries `scheduled_for`/`fired_at`/`lateness_ms` (that part is fixed), but under a 100-iteration busy loop lateness is 88–92 ms against a 50 ms budget — the settle/priority-lane budget introduced this round does not bound lateness under load as the CHANGELOG's "per-macrostep settle budget" implies it should. |
| N-1 | FAIL 5/5 | Cases A/B/C (fresh + reused-instance concurrent `send()`/`send_threadsafe`) all now resolve correctly — the original collision bug is fixed. Case D regresses: `stop()` no longer resolves every outstanding duplicate-instance receipt with `InterpreterStoppedError`; instead some receipts land as ordinary `Receipt(changed=True, ...)` for events that raced the stop. |

## 4. Verdict

4 TRUE REGRESSIONS vs the last full baseline (`5e07ba8`), all reproduced 5/5:

1. **LC-01** — `fail` action-error policy: interpreter stops with `status='stopped'` + `TransitionFailedError`, not the CHANGELOG-promised `status='error'`. (Round-5 CHANGELOG item: `"fail" → status stopped + config cleared` — the *status stopped* half now regresses relative to the documented contract of a distinguishable `error` status; config-clearing itself was not the axis under test here.)
2. **LC-26** — `after`-timer lateness under the new per-macrostep settle budget exceeds the expected bound (88–92 ms vs 50 ms) under load, though the timestamp fields themselves are correctly populated.
3. **N-1 case D** — `stop()` does not resolve *every* outstanding duplicate-`Event`-instance receipt with `InterpreterStoppedError`; some in-flight duplicates settle as ordinary success receipts instead.
4. **repro/LC-26** (secondary, informational) — same lateness defect as #2, seen at library defaults; not independently counted as a regression, folded into item 2.

Everything else that shows FAIL at `cec108b` (LC-12, LC-48, LC-57, PROBE-01, PROBE-03, all of
`149/150/157/probe_144`, the `R4-*`/`R5-*` post-3ed3099 and post-5e07ba8 repros, `c14`, `f_loader_dup`,
`86_87`, `fv1_blockers_highs`, `r4merge/m5`) was **already FAIL/reopened at the immediately preceding
baseline (`3ed3099`) or is a previously-confirmed R4/R5 register finding (✅ in
`33-r5-findings-register.md` / `30-r4-findings-register.md`)** — superseded-behaviour, not a new
regression introduced by `cec108b`. `f_loader_dup` and `fv1_blockers_highs` are in fact **expected
FAILs**: they are round-5 fix-confirmation scripts whose assertions now correctly raise the new
`InvalidConfigError`/`RootTargetError` guards (i.e. the script's old "defect reproduces" assertion
now fails because the defect is fixed) — worth flagging for a repro-script refresh, not a code defect.

Full raw per-script results: `gate/tmp_regrun/results.json` (238 scripts, 37 non-PASS, itemized above).
Gate raw output: `gate/result-main-cec108b.json`.
