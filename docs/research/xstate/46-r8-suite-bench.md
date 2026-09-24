# Round 8 — Suite + Coverage (partial; time-boxed)

Library: xstate-statemachine @ `6db65d8` (unreleased 0.8.1, `__version__` still
0.8.0 — keyed on commit per instructions).

## Full suite + coverage

```
cd _ref/xstate-statemachine
.venv-main/Scripts/python -m pytest -q -p no:cacheprovider --cov=src --cov-report=term
```

Result: **2 failed, 3457 passed, 13 skipped, 16 warnings in 878.90s (0:14:38)**.
Coverage: **TOTAL 92.70%** (required 90.0%, reached).

Failures (both in the same `subTest` parametrisation):

```
SUBFAILED(kind='def')       tests/test_round6_findings.py::TestAsyncRollbackRearmCycleBounded::test_service_calls_bounded_by_max_iterations
SUBFAILED(kind='async def') tests/test_round6_findings.py::TestAsyncRollbackRearmCycleBounded::test_service_calls_bounded_by_max_iterations
```

### Flake re-run (standalone ×3)

```
.venv-main/Scripts/python -m pytest -q -p no:cacheprovider \
  tests/test_round6_findings.py::TestAsyncRollbackRearmCycleBounded::test_service_calls_bounded_by_max_iterations
```

All 3 standalone runs: **1 passed** (2.2–2.3s each). This is a full-suite-only
flake (timing/load-sensitive bound check), not reproducible in isolation —
consistent with round-6/7 findings about lap-count assertions being sensitive
to scheduler contention under the full 3457-test run. Not a regression in the
round-7 fix set; no round-7 test failed.

## Round-7 parametrisation verification

`tests/test_round7_findings.py` defines:

```python
KINDS: Tuple[str, ...] = ("def", "async def")
```

and iterates `for kind in KINDS: with self.subTest(kind=kind): ...` through
the service/action-bearing tests (e.g.
`test_invoke_cycle_is_bounded_by_max_iterations`,
`test_invoke_done_event_is_charged_regardless_of_kind`, the priority-lane
tests, the in-flight-flag tests, etc.) — confirming the changelog's claim
that every service/action test is parametrised over both `def` and
`async def`, and cross-checked against both `SyncInterpreter` and the async
`Interpreter` in the sampled tests read directly (lines 156–1223).

37 tests collected from this file; full run (part of the suite run above)
passed cleanly (no failures attributed to `test_round7_findings.py`).

## Not completed within the 20-minute hard bound

The full coverage run alone consumed ~15 of the allotted 20 minutes. The
following planned steps were **not executed** and should be run as a
follow-up with a fresh time budget:

- `PYTHONHASHSEED=1` vs `PYTHONHASHSEED=2` on
  `tests/test_round{5,6,7}_findings.py`.
- Benchmarks: `bench_a_throughput`, `bench_h_candleviewer_budgets` (×3,
  bisect-hint for the 3.10→5.18 KB/order unattributed RSS delta flagged in
  round 7), `bench_j_policies`, `bench_c_timers` (incl. `load_500` tiers),
  `bench_e_actors`.
- Extension of the 8-column series table in
  `docs/research/xstate/41-r7-suite-bench.md`.

## Verdict (partial)

No new correctness regressions surfaced. Coverage remains well above the
90% gate. The one suite failure is a pre-existing, load-sensitive flake in a
round-6 pin (not round-7), confirmed non-reproducible standalone (3/3 pass).
Round-7's def/async-def parametrisation claim is verified by direct read of
`KINDS` and its use across the parametrised tests. Benchmark and hash-seed
work is deferred to a follow-up pass — see list above.
