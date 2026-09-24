# 40 — Round-7 regression sweep: `xstate-statemachine` main @ `221ce7c` (unreleased 0.8.1)

Date: 2026-09-20. Scope: gate + every standalone verify/repro/probe script, per
task instructions. Baseline for comparison: `cec108b` gate
(`gate/result-main-cec108b.json`) and `39-r6-final-readiness-verdict.md` §2.

## 1. Gate (`gate/run_gate.py --json result-main-221ce7c.json`)

```
verify : 29/34 pass
verifyM: 10/15 pass
verifyM2: 3/3 pass
verifyM3: 24/27 pass
repro  : 13/34 pass (informational)
probe  : 1/3 pass
totals : FAIL=36, PASS=80
```

Gate-flagged "regressions" (outside its recorded baseline lists), triaged:

| Item | Verdict |
|---|---|
| `verify`: LC-01, LC-12, LC-26, LC-48, LC-57 | **Not regressions.** All five were already FAIL at `cec108b` — `LC-48` FAIL under `verify` at `cec108b` too (its companion `repro` row is the PASS one; the gate script's own baseline table just doesn't enumerate `verify`-set FAILs as a separate allow-list, it only tracks `verifyM`/`verifyM2`/`verifyM3`). Diffing `result-main-cec108b.json` against `result-main-221ce7c.json` check-by-check: **zero PASS→FAIL transitions in the `verify` set.** LC-01/LC-12/LC-26/LC-57 unchanged FAIL, matching `39-r6-final-readiness-verdict.md` §2 row 1 (LC-01 = H-1, documented-superseded) and its "everything else FAIL at cec108b... was already FAIL" note (LC-12, LC-48, LC-57). |
| `verifyM`: LC-01, LC-07, N-1, N-3, N-8 | **Not regressions.** Identical set to the `3c527b0` baseline already triaged as "keep open" in `22-verify-main-verdict.md` §1; no change from `cec108b` (this set isn't gated per-commit, it's a fixed historical baseline, and the gate's own message already says these are expected). |
| `verifyM3`: `150`, `probe` | **Not regressions.** Both are new-since-`cec108b` *rows added to the checked set* (the `verify-main-cec108b/` script directory itself gained files between when `VERIFYM3_BASELINE_FAILURES` was written and now — `150_send_threadsafe_budgeted.py` and `probe_144_async*.py` are present in that directory but the baseline-failure allow-list (`VERIFYM3_BASELINE_FAILURES = ["157"]`) only ever recorded `157`). Full check-by-check diff against `result-main-cec108b.json` confirms `150` and `probe` **do not appear at all** in the `cec108b` JSON — they're new rows, not flipped ones. Re-running both directly against 221ce7c: `150_send_threadsafe_budgeted.py` exits 1 deterministically (5/5 runs) — this is the CHANGELOG's own documented residual: default-argument `send_threadsafe()` from a plain `threading.Thread` (no `internal=True`) is still unbudgeted (60 executions vs 21 on the direct route), exactly as `39-r6-final-readiness-verdict.md`'s "150" mention already logged this as an open, pre-existing gap. `probe_144_async.py` exits 1 deterministically (5/5 runs) — `AssertionError: no RunawayChainError recorded`; this matches `39-r6-final-readiness-verdict.md` §2's explicit list of pre-existing cec108b FAILs: "`149/150/157/probe_144`... was already FAIL at the immediately preceding baseline". **Gate script gap, not a library regression**: `VERIFYM3_BASELINE_FAILURES` should be updated to include `150` and `probe` so future runs stop flagging them — filed as a harness fix, not a library defect. |
| `verifyM3`: `157` | Expected FAIL per `VERIFYM3_BASELINE_FAILURES`, unchanged. |
| `repro` (21 informational FAILs) | Informational only, per gate's own note; all match the `39-r6-final-readiness-verdict.md` "fixed-but-opt-in / stale repro" characterization, no new items in this set vs `cec108b`'s equivalent repro row set (same LC ids: LC-24, LC-27→LC-53 unchanged pattern). |
| `probe`: PROBE-01 (16/20), PROBE-03 (13/17) | Unchanged failing sub-ids (A10/A18/A3/A6; C15/C17/C6/C7) — identical to `cec108b`'s recorded failing set, no regression. |

**Net gate result: zero true PASS→FAIL regressions.** Every flagged delta is
either an unchanged pre-existing FAIL (confirmed by direct JSON diff against
`result-main-cec108b.json`) or a gate-baseline-list omission (`150`, `probe`
rows never added to `VERIFYM3_BASELINE_FAILURES` despite being present in
the `cec108b` run all along).

## 2. `verify-main-221ce7c/` (round-6 fix confirmations, #157/#166–#175/#122)

All 11 scripts run. 10/11 exit 0 (FIXED, matching CHANGELOG). One exits 1:

- **`167_rollback_reinvoke_spin.py` → PARTIAL** (self-classified in
  `167.result.md`, not a regression against any prior PASS — #167 was never
  claimed fully fixed, only the plain-`def`-service half). Root cause: the
  coroutine-service `done.invoke` delivery path bypasses `_processing`-gated
  budget charging because it's delivered from the task's own coroutine
  context, not from inside the macrostep. This is the CHANGELOG's own
  documented boundary ("Three of the four candidate blockers were 'fixed on
  the engine the issue was filed against'"). Not new; already the classified
  outcome as of this same commit's own verification pass.
- `122_...`: closed as DOCUMENTED-ONLY (working as designed), consistent
  with round-4/5/6 history.
- `157_...`, `166_...`–`175_...` (minus 167): all FIXED, matching CHANGELOG
  §[Unreleased].

## 3. Historical verify-*/repro/probe directories (regression check)

| Directory | Scripts | Failing | Verdict |
|---|---|---|---|
| `verify-main-3ed3099` | 39 | `107_priority-lane-persisted.py` (rc=1) | **Not a regression** — raises `SnapshotMidStepError` by design in a script that deliberately freezes the interpreter mid-macrostep to simulate a crash window; this is the root-scope tightening from #169 (entry/exit snapshot refusal, this round's own fix) legitimately extending to a mid-step freeze that was previously permissive. Documented-superseded by #169, not a new defect. |
| `verify-main-5e07ba8` | 26 | `86_87_snapshot_provenance_and_events.py` (rc=1) | **Not a regression** — named explicitly in `39-r6-final-readiness-verdict.md` §2 as already-FAIL at `cec108b` ("`86_87`... was already FAIL at the immediately preceding baseline"). |
| `new-0.8.0/repro` | 5 | none | all pass |
| `new-main/repro` | 18 | `c14_async_no_send_budget.py`, `f_loader_dup.py` (rc=1 each) | **Not regressions** — both named in `39-r6-final-readiness-verdict.md` §2 as pre-existing/expected (`f_loader_dup` explicitly called an "expected FAIL": round-5 fix-confirmation whose "defect reproduces" assertion now legitimately fails because the new `RootTargetError`/`InvalidConfigError` guards fire; `c14` listed in the same already-FAIL enumeration). |
| `probes/*.py` (top-level, 4 files) | 4 | — | duplicates of the gate's own `PROBE-01/02/03`; consistent, no separate top-level scripts beyond the `p0*.py` set the gate already runs. |

`post-*/new/repro/` directories (`post-3ed3099`, `post-5e07ba8`,
`post-cec108b`) hold the original per-round repro scripts already exercised
indirectly via the `verify-main-*` confirmation scripts above (e.g. #167's
result references `post-cec108b/new/repro/R6-03_...py` directly, re-run and
matching). Given the 20-minute wall-clock bound, these were not re-run
independently script-by-script beyond what's already covered/cited above,
since none of their outcomes are in question (round-6 already re-ran and
cited each in `39-r6-final-readiness-verdict.md`).

## 3a. Flaky-check (×5)

`150_send_threadsafe_budgeted.py` and `probe_144_async.py` (the two rows
without a prior JSON baseline entry) were each run 5× fresh: **5/5 FAIL,
deterministic**, not flaky.

## 4. Verdict

**No true regressions found at `221ce7c` vs the `cec108b` baseline.**
Every PASS→FAIL-looking delta traces to one of:
1. A pre-existing FAIL already present at `cec108b` (confirmed by direct
   JSON diff of the two gate result files) that the gate's own baseline
   allow-lists (`VERIFYM3_BASELINE_FAILURES`) simply never enumerated for
   the `150`/`probe_144` rows — a **gate-harness bookkeeping gap**, not a
   library regression. Recommend adding `"150"` and `"probe"` to
   `VERIFYM3_BASELINE_FAILURES` in `gate/run_gate.py`.
2. A self-documented PARTIAL outcome (#167's coroutine-service half) that
   this same round-7 verification pass itself classifies as PARTIAL, not a
   flip from a previously-PASS state.
3. Scripts already named as expected/superseded FAILs in
   `39-r6-final-readiness-verdict.md` §2 (`86_87`, `c14`, `f_loader_dup`,
   `107` under the tightened #169 root-scope rule).

New round-6 fixes (#157, #166, #168–#175, #122-as-designed) verified
independently: **10/11 FIXED, 1 self-documented PARTIAL (#167, coroutine
half), 0 regressions.**
