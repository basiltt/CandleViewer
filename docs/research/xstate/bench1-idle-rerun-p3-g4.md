# BENCH-1 idle re-run (P3-G4, E50-T06)

Script: `docs/research/xstate/bench/_adhoc_bench1_rollback.py` (500 background order machines,
200 samples, `actionErrorPolicy: "rollback"` armed, xstate-statemachine 0.9.1, Python 3.13,
Windows 11 dev laptop), run 2026-10-04.

| Metric | Value |
|---|---:|
| p50 submit->open | 219.7 ms |
| p95 submit->open | 313.2 ms |
| p99 | 558.1 ms |
| Headroom (300 ms / p95) | 0.96x (bar: >= 3.0x, CV-C13) |

## Verdict: NOT CLOSED - inconclusive, not a pass

P3-G4 asks for an **idle** host. This run was on a shared workstation where several other
agents were running builds/tests concurrently (Sprint 01 multi-agent operation), so the host
was demonstrably not idle; the earlier 0.8.0 figure (94.6 ms p95, 3.17x) and ADR-0016
Amendment note (~2.46x with rollback) were taken on a quieter host. The result is a loaded-host
upper bound and cannot be used to claim or refute the 3.0x bar.

Required to close P3-G4: re-run on the target hardware with no other load
(`python bench/_adhoc_bench1_rollback.py`), report both shared-loop and dedicated-order-loop
numbers (ADR-0016 Amendment: report both ways), and append the figures here. The order lane
stays on a dedicated loop regardless (CV-C13).

## Suite budget (the other half of E50-T06)

`tools/statechart/suite_budget.py` (run by the `xstate-contract` job) fails when the contract
suite exceeds 60 s or any machine runs below 3 generated cases/s. Measured locally: 1488 cases,
~41-49 s on the same loaded host; slowest machine 33 cases/s.
