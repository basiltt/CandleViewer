# 75 — Round-14 regression sweep: v0.9.1

**Subject.** Library `origin/main` = `801eacd`; tag `v0.9.1` = `45bb7f3`.
`git diff v0.9.1..HEAD --stat` is **empty**: the extra merge commit changes no files.
`__version__ == "0.9.1"`, imported from `src/` in `.venv-main`. The PyPI wheel
`xstate_statemachine-0.9.1-py3-none-any.whl` has sha256
`d832d4d9a17b7b8003f61fa0714a8e57eaff316bcd5dd699d81d410362687162`, which **matches**.

## 0. Answer

**No true regressions.** Every PASS→FAIL movement was reproduced, re-run ×5 and
triaged:

- One was a timing flake in our own script.
- One comes from a version number hard-coded in our script.
- One is an argv-only probe that was never baselined.
- One was a gate failure caused by CPU load while the sweep ran concurrently.
  The issue stays fixed ×13 under forced load.

All 9 round-13 verify scripts (#239–#248) pass ×5. The library suite result is
**3601 passed, 13 skipped, 15 warnings, 586.76 s, coverage 92.93 %** (bar 90 %).
This is from the tail of `suite-v0.9.1.log`. Round 13 had 3577 passed; the extra
24 are `test_round13_findings.py`.

None of the three SUPERSEDED-BY categories (#239 / #240 / #243) was needed. No
historical script depended on the old behaviour those fixes changed.

## 1. Adoption gate — `gate/result-v0.9.1.json`

| | v0.9.0 (`result-v0.9.0.json`) | v0.9.1 (this run) |
|---|---|---|
| Totals | 94 PASS / 31 FAIL | 98 PASS / 33 FAIL |
| Movements | — | **1 PASS→FAIL (167)**, 1 FAIL→PASS (LC-45), 7 new ids |

- **167 `rollback_reinvoke_spin` (verifyM4 + verifyM5) — NOT a regression (load flake).**
  The gate ran at the same time as the 6-worker script sweep, and both 167 rows
  failed at about 5.6 s. Re-run results:
  - `run_gate.py --only 167` ×3: **all PASS**.
  - The script ×5 in each of its two directories (the gate's cwd): **10/10 rc=0**.
  - The script ×5 **with 6 busy-loop CPU hogs**: **5/5 rc=0**.
  - In every run, `def` and `async def` × Interpreter/SyncInterpreter are bounded
    at 1003 calls with a `chain_budget` drop and a settled state. The original
    repro exits 0.
  - Constraint: run the gate on an idle host. The script's settle windows are
    wall-clock based.
- **New ids 225-228 / 233: FAIL, and both are harness artefacts.** Details in §2
  (`228.repo_path_provided` needs `XSM_REPO`; 233 pins `"0.9.0"`).
- **229–232: PASS.** **LC-45: FAIL→PASS.**
- rc=1 comes from the baseline FAIL set the gate already tracks. There are 0 ERROR
  rows.

## 2. Historical script sweep — `gate/r14_regression_raw.json`

- 553 scripts (`gate/r14_scriptlist.txt`). This is the r12/r13 set plus
  `verify-v0.9.1/` and `probes/v0.9.0/`. `refute*/` and `__pycache__` are excluded.
- Driver: `gate/run_r14_regression.py`, 6 workers, 120 s cap each, cwd `<home>`.
- Result: **468 PASS / 85 FAIL / 0 TIMEOUT**, 212 s. r13 had 452 / 82 / 0 of 534.
- Compared with r12 raw: **10 FAIL→PASS**. Of the 85 FAILs, 81 match the r13 sweep's
  known-FAIL set. These are old-version repros that correctly report "defect
  present" semantics, or tagged fixed-but-opt-in cases. See §2 of `74-…`.

Movements compared with `sweep-r13.json`:

| Script | r13 | r14 | Triage |
|---|---|---|---|
| `verify-main-3ed3099/105_external-send-not-charged-to-chain-budget.py` | PASS | FAIL (once) | **Script flake, not a regression.** Burst 3000 read `applied=2942` with `chain_budget_drops=0`. The script reads the count after a fixed `sleep(0.5)` and does not poll to convergence. Re-runs: ×5 serial 5/5 PASS, ×8 parallel 8/8 PASS. A new standalone convergence repro, `verify-v0.9.1/r14/105_converge.py`, **12/12 parallel reached 3000/3000**. No events are lost. |
| `verify-v0.9.0/233_235_verify.py` | PASS* | FAIL | **Script-pinned.** It asserts `__version__ == "0.9.0"`. Every behavioural sub-check passes: 233 order `['B','A']`; 235 deprecation warned; `DoneEvent` demotion. The version is now correctly 0.9.1. |
| `probes/v0.9.0/p3_warn_finaliser.py` | — | FAIL | **Unbaselined argv probe.** It needs `sys.argv[1]` and hits `IndexError` when called without one. `on`/`off` both exit 0, with the #232 warning emitted once each. |
| `verify-v0.9.0/225-228_matrix.py` | FAIL | FAIL | Only `228.repo_path_provided` fails. With `XSM_REPO=<lib>` it prints **ALL PASS**. |
| `verify-main-cec108b/150_send_threadsafe_budgeted.py` | FAIL | FAIL (×5) | Unchanged from r13. Documented default: `internal=` opt-in. Tracked in 74. |
| `post-de2da4e/new/repro/DE-L4-repro.py` | FAIL | FAIL | Unchanged (REPRODUCED). Already dispositioned in 74. |

\* 233 is listed as PASS in `sweep-r13.json` because r13 ran against 0.9.0.

## 3. Round-13 fixes — `issues/verify-v0.9.1/`, flaky ×5

| Script | ×5 |
|---|---|
| 239_drain_pending (both lanes, priority-first; `wait=True` → `InterpreterStoppedError`) | 0 0 0 0 0 |
| 240_on_interpreter_start (fires on restore, `restored_from_snapshot`) | 0 0 0 0 0 |
| 241_snapshot_corrupt (malformed chain fields → `SnapshotCorruptError`) | 0 0 0 0 0 |
| 243_restored_chain_error (IS-A `RunawayChainError` and `RestoredError`) | 0 0 0 0 0 |
| 244_dropped_receipts (+ `on_receipt_dropped`) | 0 0 0 0 0 |
| 245_sync_interpreter_kwargs (`ValueError` if non-None) | 0 0 0 0 0 |
| 247_pep740_attestation | 0 0 0 0 0 |
| 248_remint_gating (`events.re_mint()`) | 0 0 0 0 0 |
| repro_243_246 | 0 0 0 0 0 |

#242 (`--json` / `--json-file` host block) and #246 are covered in the
`*-recheck.md` notes and `repro_243_246.py`.

## 4. Livelock / hang repros

- 190 swept scripts mention livelock, spin, hang or deadlock. All of them ran
  under the 120 s watchdog, with **0 TIMEOUT**.
- 167 (rollback re-invoke spin) and the 166 always-invoke livelock also pass inside
  the gate.
- 167 was additionally stressed ×5 under 6 CPU hogs with a 30 s watchdog: 5/5
  bounded.

## 5. Reductions (stated honestly)

- The gate's first attempt inside a 120 s cap timed out; the full gate takes 368 s.
  It was re-run in the background with a 900 s cap.
- The gate and the sweep ran at the same time, which caused the 167 load flake
  described above.
- I did not re-run the contract corpus, the B11/B12 invariants or BENCH-6 this
  round. The v0.9.0→v0.9.1 `src/` diff is 8 files, +257/−11, and does not change
  the scheduler or clock modules. It does touch `drain_pending` handling of fired
  timer items (#239) in `interpreter.py`, which is on the send path. The row-6
  BENCH-6 numbers in 74 are therefore carried forward, **not re-measured**.
  Re-measure before sign-off if timer lateness matters.

## 6. Verdict impact

No change to `74-r13-final-readiness-verdict.md` §6 from a regression standpoint.
Nothing regressed, and the #239–#248 fixes hold on both `def` and `async def`
paths. Suggested hygiene, all in **our** scripts: poll-to-convergence in 105;
un-pin the version in 233; give p3 a default argv; set `XSM_REPO` in the gate.
