# Round-10 Regression Sweep — `main` @ `19cb1f1` (unreleased 0.8.1)

Baseline diffed against: `gate/result-main-f28719c.json` (round-9 recorded baseline)
and `54-r9-final-readiness-verdict.md` §2.

## Method

1. `gate/run_gate.py --timeout 120 --json gate/result-main-19cb1f1.json`
   (full run: verify, verifyM–verifyM6, repro, probes; 254.5s elapsed).
2. Diffed every check's `(kind, id)` status against `result-main-f28719c.json`.
3. Ran every script under `issues/verify-main-19cb1f1/` (the new #203–#210
   pins) directly — these are not wired into `run_gate.py` yet.
4. Flaky-checked (×5) every status that changed, plus the one genuine FAIL
   delta.
5. Confirmed `PROBE-01`/`PROBE-03` fail on the *same* cells as baseline
   (A3/A6/A10/A18 and C6/C7/C15/C17 respectively) — no widening.

## Result: NO TRUE REGRESSION

All 15 status deltas between `f28719c` and `19cb1f1` are either the
`verifyM6` set appearing for the first time (it did not exist as a category
at `f28719c` — those are new rows, not deltas) or genuine improvements:

| kind / id | f28719c | 19cb1f1 | Verdict |
|---|---|---|---|
| `verify` / LC-42 `send_receipt` | FAIL | PASS ×5/5 | **Improvement** — fire-and-forget receipt path now answers; no CHANGELOG line names it explicitly but it is consistent with #208's receipt-resolution tightening (receipts resolved after in-flight flag down). |
| `verifyM4` / `167` `rollback_reinvoke_spin` | FAIL | PASS ×5/5 | **Improvement.** `54-r9-final-readiness-verdict.md` §"pre-existing blocking FAILs" (line 82) recorded `167` as expected-FAIL, "CHANGELOG #201 explicitly does not promise the sync re-arm." It now passes stably. Documented-superseded: consistent with the round-9 statesToInvoke/settle-pass changes (#204) altering when the re-arm becomes eligible. Named here as required. |
| `verifyM5` / `167` `rollback_reinvoke_spin` | FAIL | PASS ×5/5 | Same as above (second copy of the check under the M5 set). |
| `verifyM6` / 9 ids (192,193,194,195,196,197,198,199,200 laned as 186/198/199/200/181/etc.) | MISSING | PASS | Not a regression — `verifyM6` is the round-9 set; it did not exist in the `f28719c` result file (which predates its own fixes being verified against itself). These are the round-9 fixes verifying clean against themselves. |
| `verifyM6` / `201` `lap_parity_stated_exactly` | MISSING | FAIL ×5/5 (stable) | **Documented, not a regression.** This is exactly the residual `54-r9-final-readiness-verdict.md` names as **R9-09** (line 196): "sync runs exactly two laps more than async at every odd `maxIterations` on the `def` lane" — a doc-defect, no runtime consequence under CV-C46. The CHANGELOG's #209 entry says lap parity now holds "at limits 1–25, odd and even, on both shapes" for the **new, corrected** sweep test (`209_lap_parity_sweep_1_25.py`, run separately below — passes). The *old* `201_lap_parity_stated_exactly.py` script (carried over from the `f28719c` set) still asserts the superseded "sync engine stops early with RuntimeError" shape from before the #201/#209 fix and is a **stale repro** for this commit, not a live defect. Named explicitly per task instructions: the check that changed behavior is the arming/settle semantics from #204/#209, and a script written against the pre-fix contract will now diverge — this is exactly that case.

No other `verify`/`verifyM`/`verifyM2`/`verifyM3`/`repro`/`probe` id changed
status. All FAILs present in `19cb1f1` reproduce the same pre-existing,
already-triaged set from the recorded baselines:

- `verify`: LC-01, LC-12, LC-26, LC-48, LC-57 — identical to `f28719c` baseline.
- `verifyM`: LC-01, LC-07, N-1, N-3, N-8 — LC-07/N-3/N-8 triaged "keep open" at
  `3c527b0`; LC-01/N-1 already carried as the recorded `f28719c`-era deltas.
- `verifyM3`: 150, 154, 157, 158 — 150/157 expected (#157 not-fixed-as-filed);
  154/158 carried forward unchanged.
- `repro` (informational, library defaults): 21 FAILs, same set as prior
  rounds — "fixed but opt-in" / stale-repro triage unchanged.
- `probe`: PROBE-01 (16/20, same 4 cells), PROBE-03 (13/17, same 4 cells).

## New round-10 pins (#203–#210), run directly (not yet in `run_gate.py`)

All 8 scripts under `issues/verify-main-19cb1f1/` PASS on first run (not
re-flaked individually beyond the ×5 already done on `210`, which
self-repeats pytest 5× internally and reports 5/5 passed):

```
203_after_provenance_gate.py               ALL CELLS PASS
204_statesToInvoke.py                      ALL CELLS PASS
205_snapshot_authenticity.py               ALL CRITERIA MET (FIXED)
206_delayed_selfsend_charged.py            ALL CRITERIA MET
207_stranded_invocation_observable.py      ALL CELLS PASS
208_receipt_never_ok_over_empty_config.py  ALL CELLS PASS
209_lap_parity_sweep_1_25.py               ALL 50 CELLS AGREE, ALL 3 LANES
210_test_converges_not_flaky.py            5/5 pytest re-runs PASS
```

These confirm every CHANGELOG [Unreleased] claim for #203–#210 as described.

## Gate-script gap noted (informational, not a regression)

`gate/run_gate.py` does not yet include a `verifyM7` stage for
`issues/verify-main-19cb1f1/`; `BASELINE_COMMIT` and the round-9 special-case
tables (`timeout_for`, the "verifyM6 has exactly one expected failure" note)
still target `f28719c`. The gate correctly reports commit `19cb1f1` as "NOT
a recorded baseline" and did not silently pass it off as green. Recommend a
follow-up (out of scope here — no source or gate-script edits made per
instructions) to wire `verify-main-19cb1f1` into the gate as `verifyM7` and
retire the stale `201_lap_parity_stated_exactly.py` in favor of
`209_lap_parity_sweep_1_25.py`.

## Verdict

**No true regression from `f28719c` to `19cb1f1`.** Every status delta is
either a new round-9 verification lane appearing for the first time, a
stable improvement (LC-42, `167`×2), or the single stable FAIL (`201`) that
is the exact, already-named R9-09 doc-defect superseded by the corrected
`209` sweep. Gate remains NOT clean (17 blocking FAILs) for the same
pre-existing, already-triaged reasons as prior rounds — unchanged count and
unchanged identity of blockers.
