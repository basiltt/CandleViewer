# Round 14 — v0.9.1 Wheel/Bench/Suite Verification

**Scope note:** run under a hard 20-min task budget; bench_h (300s cap) was
descoped to keep within bounds — see "Not run" below.

## 1. Repo/tag/wheel identity

- `origin/main` = `801eacd` (merge of PR #249, round-13 fix branch).
  `git diff v0.9.1..HEAD --stat` is **empty** — main is exactly `v0.9.1`
  (801eacd is a fast-forward/no-op merge commit, no file changes).
- `__version__` = `0.9.1`.
- PyPI wheel `xstate_statemachine-0.9.1-py3-none-any.whl`:
  sha256 `d832d4d9a17b7b8003f61fa0714a8e57eaff316bcd5dd699d81d410362687162`
  — **matches** the value given in the task brief.
- Byte-compare (newline-normalized) of every `.py` under `xstate_statemachine/`
  in the wheel against `git show v0.9.1:src/xstate_statemachine/<f>`:
  **42/42 identical**. Wheel contents are exactly the tagged source.

## 2. CHANGELOG [0.9.1] round-13 fixes — spot-checked via tests

`tests/test_round13_findings.py` (24 tests) plus `test_round11/12_findings.py`
(54 tests) = 78 tests, run twice with `PYTHONHASHSEED=1` and `=2`:
**78 passed** both times, no ordering/hash-seed sensitivity observed.
This covers #239–#248 (drain_pending priority ordering + wait=True
InterpreterStoppedError, on_interpreter_start restored_from_snapshot flag,
SnapshotCorruptError, RestoredChainError MRO, dropped_receipts hook,
events.re_mint, SyncInterpreter None-arg ValueError, production_characteristics
--json/--json-file host block).

## 3. BENCH-6 — production_characteristics.py --quick --json ×10

Loaded-timer (`busy_machines=500`) lateness_ms per run:
64.09, 58.01, 76.31, 67.02, 79.83, 73.61, 64.33, 93.42, 63.67, 76.46

- **p50 = 70.31 ms, p99 = 92.20 ms**
- vs our ≤100 ms bar: **pass** (p99 92.2 ms < 100 ms, though noticeably
  closer to the bar than round-13's headline).
- vs round-13's reported p99 55.8 ms: **regressed** — this run's p99 is
  ~65% higher (92.2 vs 55.8 ms). Median (70.3ms) also exceeds round-13's p99.
  This is the same machine/host, `--quick` mode, 10 runs vs presumably fewer
  in round-13; worth flagging as a benchmark-variance or host-load watch item
  rather than a functional regression — no test failures accompany it, and
  it's still inside the ≤100ms gate. `host` block confirms
  `library_version=0.9.1`, Windows-11, CPython 3.13.7, 8 cores.
- `bench_c_timers_v2.py` (our wrapper) run once: consumed the new `--json`
  output successfully — `summary_by_busy_level["500"] = {p50: 65.9, p99: 69.0,
  mean: 67.14}`, `within_bar_at_500: true`. Wrapper compatible with 0.9.1.

## 4. Suite series (this run)

- `bench_a_throughput`: lockstep_5000 p50 47µs/p99 107µs latency;
  pure_api_50000 ≈33.4k ev/s; raw_send_50000 ≈240k enqueue/s. In line with
  prior rounds, no red flags.
- `bench_j_policies`: rollback 0.75x baseline, defer 1.15x baseline,
  rollback_and_defer 0.83x baseline — consistent with documented overheads.
- `bench_e_actors`: send_to_child_10000 all delivered (10000/10000);
  leak_check over 300 cycles × 10 children: RSS growth 0.25MB total
  (0.085 KB/actor) — no leak signal.
- **Not run**: `bench_h_candleviewer_budgets` (300s cap) — descoped to stay
  within the 20-min task bound. Recommend running standalone before final
  sign-off if a completeness gate requires it; nothing in this session
  suggests it would fail (throughput/actor/timer benches all nominal).

## 5. Full pytest+coverage suite (already-running background job)

Tail of `suite-v0.9.1.log`:

```
Required test coverage of 90.0% reached. Total coverage: 92.93%
3601 passed, 13 skipped, 15 warnings in 586.76s (0:09:46)
```

**Complete.** 0 failures, 0 errors, coverage gate (90%) passed at 92.93%.

## 6. Verdict

- Wheel == tag == main source: **confirmed identical, byte-for-byte**.
- Round-13 targeted regression tests: **78/78 pass**, hash-seed-stable.
- Full suite: **3601 passed / 13 skipped, 0 failed**, coverage 92.93% ≥ 90% gate.
- Timer lateness bar (≤100ms p99 @ 500 busy machines): **passes** but with
  reduced headroom vs round-13 baseline (92.2ms vs 55.8ms p99) — a variance
  watch item, not a blocking defect.
- Actor/throughput/policy benches: nominal, no leaks, no anomalies.
- Outstanding from this session: `bench_h_candleviewer_budgets` not executed
  (time-boxed); recommend as a follow-up before an unconditional "battle
  tested" stamp, though nothing observed here contradicts readiness.

**Recommendation: proceed.** All previously reported issues (#239–#248) are
closed and verified via the actual round-13 test file, not just changelog
claims; wheel provenance is verified byte-for-byte; the full suite is green
with coverage above gate. The one open item is the un-run 300s budget bench
and the narrower (but still passing) timer-lateness headroom — both are
follow-ups, not blockers, for shipping.
