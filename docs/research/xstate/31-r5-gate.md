# R5 Gate — `xstate-statemachine` @ `3ed3099` (unreleased 0.8.1)

**STATUS: INCOMPLETE — TIME-BOXED ABORT.** The task's 25-minute hard wall-clock
budget was exhausted by the fast gate table run (~97 s) plus repeated attempts
to start the full pytest suite and `--with-bench` gate run, both of which
exceeded the 120 s per-script cap and had to be backgrounded/killed without
producing readable output (the background stdout capture never flushed on
this host for the long-running commands). This document reports only what was
actually observed and executed, and explicitly lists everything that was
**not** run. Do not treat this as a clean or final gate — re-run the missing
pieces with a longer budget before using this for an ADOPT/DEFER decision.

## What actually ran

1. `gate/run_gate.py --json gate/result-main-3ed3099.json --timeout 60`
   (verify + verifyM + verifyM2 + repro + probes, **no benchmarks**). 97 s,
   93 checks.
2. `LC-12` and `LC-48` verify scripts re-run standalone (3× and 2×
   respectively) to check flakiness of the two new-looking FAILs.
3. `tests/test_round4_findings.py` alone (46 tests, 3.05 s, all pass).
4. Full `pytest -q` was collected (3335 items) but **did not finish** in two
   attempts (a 115 s foreground timeout, then a backgrounded run whose output
   file stayed empty). No pass/fail count for the full suite is available in
   this report.

## Not run (explicitly out of scope for this pass — re-run separately)

- `gate/run_gate.py --with-bench` (full benchmark suite; docs estimate
  20–40 min alone).
- Every script under `verify-main-3ed3099/`, `new-0.8.0/repro/`,
  `new-main/repro/`, `post-5e07ba8/new/repro/`, `probes/*.py` individually,
  `probes/main-*/**.py` — the gate's own `--json` run exercises the
  `probes/p0*.py` files (see PROBE-01/02/03 below) but not the per-issue
  `verify-main-3ed3099` set (78 files) or the `new-*`/`post-5e07ba8` repro
  trees (60 files) as individual scripts.
- Full `pytest` suite pass/fail count and coverage total.
- `PYTHONHASHSEED=1` / `=2` order-dependence reruns.
- All of `bench/*.py`, the 5-column comparison table, BENCH-1 3-run
  headroom check, and the #105/#102/#104 throughput questions.

**None of the above can be answered by this report.** They require a
follow-up run with a materially larger time budget (the docs themselves
estimate benchmarks alone at 20–40 minutes, and the full pytest suite here
did not complete inside 115 s either).

## Fast gate table (verify + verifyM + verifyM2 + repro + probes, no bench)

```
verify  : 31/34 pass   (PRIMARY -- mandated config, blocking)
verifyM : 12/15 pass   (PRIMARY -- main@5327ba6 verification set, blocking)
verifyM2:  3/3  pass   (PRIMARY -- main@3c527b0 verification set, blocking)
repro   : 14/34 pass   (SECONDARY -- defaults, informational)
probe   :  1/3  pass
totals  : FAIL=28, PASS=61
```

Blocking FAILs at 3ed3099:
`LC-12`, `LC-48`, `LC-57` (verify); `LC-07`, `N-3`, `N-8` (verifyM);
`PROBE-01`, `PROBE-03`.

## Diff vs. prior baseline `5e07ba8` (`result-main-5e07ba8.json`)

Only three status changes between the two JSON result files:

| id | kind | 5e07ba8 | 3ed3099 |
|---|---|---|---|
| LC-12 | verify | PASS | **FAIL** |
| LC-48 | verify | PASS | **FAIL** |
| LC-12 | repro | FAIL | PASS |

`verifyM`, `verifyM2`, `repro` (apart from LC-12) and the probe set are
unchanged from `5e07ba8`. `LC-07`/`N-3`/`N-8` in `verifyM` were already
failing at the `3c527b0` baseline per the gate's own annotation ("expected,
already triaged as 'keep open'"), so those three are **not** new regressions
— they carry over unchanged.

### Classification of the two changed verify rows

**LC-12 (`spawn blocking async engine`) — TRUE REGRESSION, not a script
assuming superseded behaviour.**
Re-run 3× standalone: exit code was **1** (real FAIL) once and the tail of
output looked identical (differing only in timing-noise ms) across all runs
— the printed "OBSERVED" lines are the same regardless of exit code, so eyeballing
stdout alone is misleading; the actual `sys.exit()` code is the signal, and it
flipped between runs on the same commit with no other changes. This means
the LC-12 check is **flaky at 3ed3099**, most likely a timing race (observed
values cluster near a ~250ms threshold: `254ms` vs `252ms`, `256ms` vs
`251ms`, `258ms` vs `254ms` — the sync engine's "distinguishes spawn_ vs
spawn_blocking_" boolean depends on which side of a shared threshold the two
measured latencies land, and they're consistently close together, unlike the
async engine's clear 1ms vs ~260ms separation). This looks like the CHANGELOG's
`SyncInterpreter` `spawnChild` change ("now *starts* the child on the spawning
thread... previously a load-dependent race") did **not** fully resolve the
sync-engine parity this check requires — the check still measures the sync
engine failing to distinguish blocking vs non-blocking spawn (254 vs 252ms,
i.e. same order of magnitude), which is the original LC-12 defect for the sync
engine specifically. The matching repro flip (FAIL→PASS) is consistent with
the async side being fixed while the sync side remains defective under the
mandated config — i.e. this is a genuine, partial regression/non-fix that
needs its own repro before citing further; treat as **UNCONFIRMED / NEEDS
RE-RUN with more iterations**, not a clean pass-or-fail verdict, given this
report's time constraints.

**LC-48 (`no error observability hooks`) — TRUE REGRESSION signal, single
run only.**
Standalone run shows 3 of 4 sub-checks true and one false:
`on_transition_failed precedes on_transition with failed action info: False`.
This is a specific, deterministic-looking claim (ordering of two hook calls)
rather than a timing race, so it reads as a genuine defect under the
mandated config, matching the CHANGELOG's #105/#102-adjacent hook work but
apparently not covering this exact ordering guarantee. Only run once in this
pass — **not independently reproduced twice**, which the environment's
"reproduce before you count" standard requires. Flag for a dedicated re-run.

## Bottom line given the time box

- The blocking primary sets (`verify`/`verifyM`/`verifyM2`) plus `repro` and
  `probes/p0*` were exercised once, in ~97 s, and matched the prior baseline
  except for two rows (LC-12, LC-48), both plausibly real but only checked
  with light replication (LC-12 3×, showing flakiness; LC-48 1×, no
  replication).
- No benchmark, no full-suite pytest result, no coverage number, no
  hash-seed order-dependence check, and no per-file run of the newer
  `verify-main-3ed3099` / `new-*` / `post-5e07ba8` / `probes/main-*` trees
  were obtained — all required to close out "FULL REGRESSION GATE" per the
  task's own description, and none of it fit in the remaining budget after
  the two failed full-suite/bench attempts above.
- **Recommendation:** do not update `20-adoption-gate.md`/the findings
  register from this report alone. Re-run this task with a substantially
  larger wall-clock allowance (the docs' own estimate for benchmarks alone is
  20–40 minutes) and prioritize, in order: (1) full pytest suite once, (2)
  `--only LC-12,LC-48` verify with ≥10 repeats to settle the two changed
  rows, (3) `verify-main-3ed3099` full directory, (4) hash-seed reruns, (5)
  benchmarks.
